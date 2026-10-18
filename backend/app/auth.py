"""Accounts, invites and login sessions.

- The owner account comes from ADMIN_EMAIL / ADMIN_PASSWORD on first start.
- Nobody else can sign up without an invite code from the owner (single use, expires).
- Passwords are hashed with Argon2. Sessions are random tokens stored hashed, sent as an
  HttpOnly, SameSite=Lax cookie (Secure in production), never readable by page scripts.
- Failed logins are rate-limited per address and per email.
"""

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlmodel import Session, select

from app.config import APP_NAME, get_settings
from app.db import Invite, LoginSession, Run, User, get_session

COOKIE = f"{APP_NAME.lower()}_session"
MIN_PASSWORD = 10
_hasher = PasswordHasher()

LOGIN_WINDOW_S = 15 * 60
MAX_FAILS_PER_EMAIL = 5
MAX_FAILS_PER_ADDRESS = 20
_fails: dict[str, deque] = defaultdict(deque)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops the timezone


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Use at least {MIN_PASSWORD} characters.")


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise HTTPException(status_code=422, detail="That doesn't look like an email address.")
    return email


# ------------------------------------------------------------------ rate limiting


def _prune(key: str) -> deque:
    q = _fails[key]
    cutoff = time.monotonic() - LOGIN_WINDOW_S
    while q and q[0] < cutoff:
        q.popleft()
    return q


def check_rate(address: str, email: str) -> None:
    if len(_prune(f"email:{email}")) >= MAX_FAILS_PER_EMAIL or len(_prune(f"addr:{address}")) >= MAX_FAILS_PER_ADDRESS:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")


def record_fail(address: str, email: str) -> None:
    t = time.monotonic()
    _fails[f"email:{email}"].append(t)
    _fails[f"addr:{address}"].append(t)


def reset_rate_limits() -> None:
    _fails.clear()


# ------------------------------------------------------------------ sessions


def start_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=digest(token), user_id=user.id,
                        expires_at=now() + timedelta(days=get_settings().session_days)))
    db.commit()
    response.set_cookie(
        COOKIE, token, max_age=get_settings().session_days * 86400, httponly=True,
        secure=get_settings().cookie_secure, samesite="lax", path="/",
    )


def end_session(db: Session, token: str | None, response: Response) -> None:
    if token:
        row = db.get(LoginSession, digest(token))
        if row:
            db.delete(row)
            db.commit()
    response.delete_cookie(COOKIE, path="/", secure=get_settings().cookie_secure, httponly=True, samesite="lax")


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.get(LoginSession, digest(token))
    if not row:
        return None
    if _aware(row.expires_at) < now():
        db.delete(row)
        db.commit()
        return None
    return db.get(User, row.user_id)


def optional_user(request: Request, db: Session = Depends(get_session)) -> User | None:
    return user_from_token(db, request.cookies.get(COOKIE))


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Log in first.")
    return user


def owner_user(user: User = Depends(current_user)) -> User:
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="Only the owner can do that.")
    return user


# ------------------------------------------------------------------ run access


def can_read(user: User | None, run: Run) -> bool:
    if run.public:
        return True
    if user is None:
        return False
    return run.owner_id == user.id or (run.owner_id is None and user.is_owner)


def can_change(user: User | None, run: Run) -> bool:
    return user is not None and not run.public and (
        run.owner_id == user.id or (run.owner_id is None and user.is_owner))


# ------------------------------------------------------------------ owner and invites


def bootstrap_owner(db: Session) -> None:
    s = get_settings()
    if not (s.admin_email and s.admin_password):
        return
    if db.exec(select(User).where(User.is_owner == True)).first():  # noqa: E712
        return
    email = s.admin_email.strip().lower()
    existing = db.exec(select(User).where(User.email == email)).first()
    if existing:
        existing.is_owner = True
        db.add(existing)
    else:
        db.add(User(email=email, password_hash=hash_password(s.admin_password), is_owner=True))
    db.commit()


def new_invite(db: Session, owner: User) -> tuple[str, Invite]:
    code = secrets.token_urlsafe(16)
    invite = Invite(code_hash=digest(code), created_by=owner.id,
                    expires_at=now() + timedelta(days=get_settings().invite_days))
    db.add(invite)
    db.commit()
    return code, invite


def find_invite(db: Session, code: str) -> Invite | None:
    invite = db.exec(select(Invite).where(Invite.code_hash == digest(code))).first()
    if not invite or invite.used_by or _aware(invite.expires_at) < now():
        return None
    return invite
