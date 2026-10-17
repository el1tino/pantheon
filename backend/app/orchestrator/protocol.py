"""The agent reply format every seat must answer in (spec: "Agent reply format")."""

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class Stance(StrEnum):
    PROPOSE = "propose"
    CHALLENGE = "challenge"
    AGREE = "agree"
    VOTE = "vote"
    REPORT = "report"
    QUESTION = "question"


class VoteItem(BaseModel):
    target: str
    score: int = 1

    @field_validator("target", mode="before")
    @classmethod
    def _target_str(cls, v: Any) -> str:
        return str(v)


class AgentReply(BaseModel):
    stance: Stance
    reply_to: str | None = None
    content: str = Field(min_length=1)
    proposal: dict[str, Any] | None = None
    votes: list[VoteItem] | None = None

    @field_validator("stance", mode="before")
    @classmethod
    def _stance_lower(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("reply_to", mode="before")
    @classmethod
    def _reply_to_str(cls, v: Any) -> str | None:
        if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
            return None
        return str(v).strip()


class ReplyError(ValueError):
    """The model's text is not a valid AgentReply. The message is shown to the model on retry."""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ReplyError("No JSON object found. Reply with a single JSON object only.")
    return text[start : end + 1]


def parse_reply(text: str) -> AgentReply:
    try:
        data = json.loads(extract_json(text))
    except json.JSONDecodeError as exc:
        raise ReplyError(f"Invalid JSON: {exc}") from exc
    try:
        return AgentReply.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}" for e in exc.errors()
        )
        raise ReplyError(f"Reply does not match the format: {problems}") from exc


REPLY_FORMAT_HELP = """Reply with ONLY one JSON object, no other text:
{
  "stance": "propose | challenge | agree | vote | report | question",
  "reply_to": "message id like \\"m3\\", or null",
  "content": "what you say to the council (under 120 words)",
  "proposal": {"title": "short title", "summary": "one or two sentences"} or null,
  "votes": [{"target": "message id", "score": 1}] or null
}"""
