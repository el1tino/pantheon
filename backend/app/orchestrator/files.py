"""Files written by seats during the build phase.

Putting whole HTML, CSS or JS files inside a JSON string breaks often (escaping, cut-off
replies), so a build reply is the usual JSON object first, followed by plain file blocks:

    {"stance": "report", "reply_to": null, "content": "Built the landing page."}
    === FILE: site/index.html ===
    <!doctype html>
    ...
    === END FILE ===

Every path is checked before anything is written: it must stay inside the run folder under an
allowed top-level folder, have an allowed text extension, and fit the size limit.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.orchestrator.protocol import AgentReply, ReplyError, parse_reply

ALLOWED_ROOTS = ("site", "docs")
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".md", ".json", ".svg", ".txt"}
IMAGE_EXTENSIONS = {".svg", ".png", ".webp", ".jpg"}
MAX_IMAGE_REQUESTS = 3
MAX_FILE_BYTES = 120_000
MAX_FILES_PER_REPLY = 8

FILE_START = "=== FILE: "
_BLOCK = re.compile(r"^=== FILE: (?P<path>[^\n]+?) ===[ \t]*\n(?P<body>.*?)\n?^=== END FILE ===[ \t]*$",
                    re.M | re.S)

FORMAT_HELP = """Reply with the JSON object first, then each file you write as a plain block:
=== FILE: site/index.html ===
...the complete file...
=== END FILE ===
Write complete files, never fragments or diffs. Do not put file contents inside the JSON."""


@dataclass
class FileBlock:
    path: str
    content: str


def clean_path(raw: str) -> str:
    """Normalise a seat-supplied path, or raise ReplyError if it isn't allowed."""
    path = raw.strip().strip("`'\"").replace("\\", "/")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ReplyError(f'"{raw}" is not allowed: use a relative path like site/index.html.')
    if p.parts[0] not in ALLOWED_ROOTS or len(p.parts) < 2:
        raise ReplyError(f'"{raw}" must live under {" or ".join(r + "/" for r in ALLOWED_ROOTS)}.')
    if p.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ReplyError(f'"{raw}" has a file type that is not allowed. Use one of: '
                         f'{", ".join(sorted(ALLOWED_EXTENSIONS))}.')
    if any(part.startswith(".") for part in p.parts):
        raise ReplyError(f'"{raw}": hidden files are not allowed.')
    return str(p)


def clean_image_path(raw: str) -> str:
    """Images are requested from a consultant, not written by seats, and live under site/."""
    path = raw.strip().strip("`'\"").replace("\\", "/")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or len(p.parts) < 2 or p.parts[0] != "site":
        raise ReplyError(f'Image path "{raw}" must be inside site/, like site/logo.svg.')
    if p.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ReplyError(f'Image path "{raw}" must end in one of: {", ".join(sorted(IMAGE_EXTENSIONS))}.')
    if any(part.startswith(".") for part in p.parts):
        raise ReplyError(f'"{raw}": hidden files are not allowed.')
    return str(p)


def parse_image_requests(raw) -> list[dict]:
    """Validate "proposal": {"images": [{"path", "prompt", "kind", "consultant"}]}."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_IMAGE_REQUESTS:
        raise ReplyError(f'"images" must be a list of at most {MAX_IMAGE_REQUESTS} requests.')
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ReplyError('Each image request needs "path", "prompt" and "kind" ("logo" or "image").')
        prompt = str(item.get("prompt", "")).strip()
        if not prompt or len(prompt) > 1000:
            raise ReplyError("Each image request needs a prompt of up to 1000 characters.")
        kind = str(item.get("kind", "image")).lower()
        out.append({"path": clean_image_path(str(item.get("path", ""))), "prompt": prompt,
                    "kind": "logo" if kind == "logo" else "image",
                    "consultant": str(item.get("consultant", "")).strip().lower() or None})
    return out


def parse_build_reply(text: str) -> tuple[AgentReply, list[FileBlock]]:
    head, sep, tail = text.partition(FILE_START)
    reply = parse_reply(head)
    files: list[FileBlock] = []
    if not sep:
        return reply, files
    tail = FILE_START + tail
    starts = len(re.findall(r"^=== FILE: ", tail, re.M))
    blocks = list(_BLOCK.finditer(tail))
    if len(blocks) != starts:
        raise ReplyError('A file block is missing its "=== END FILE ===" line (was the reply cut off?). '
                         "Send every file again, complete.")
    if len(blocks) > MAX_FILES_PER_REPLY:
        raise ReplyError(f"Write at most {MAX_FILES_PER_REPLY} files per reply.")
    seen = set()
    for m in blocks:
        path = clean_path(m.group("path"))
        if path in seen:
            raise ReplyError(f'"{path}" appears twice. Send each file once.')
        seen.add(path)
        body = m.group("body")
        if len(body.encode("utf-8")) > MAX_FILE_BYTES:
            raise ReplyError(f'"{path}" is too large (limit {MAX_FILE_BYTES // 1000} KB).')
        files.append(FileBlock(path, body.rstrip("\n") + "\n"))
    return reply, files
