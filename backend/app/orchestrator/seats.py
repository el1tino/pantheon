"""Seat definitions loaded from config/seats.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel

from app.config import get_settings


class SeatConfig(BaseModel):
    letter: str
    name: str
    provider: str
    model_id: str
    colour: str
    logo: str = ""  # file name in frontend/public/logos/, without .svg
    voice_id: str = ""
    sensitive_ok: bool = False


def load_seats(path: Path | None = None) -> list[SeatConfig]:
    path = path or get_settings().seats_file
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [SeatConfig.model_validate(s) for s in data["seats"]]


def pick_seats(letters: list[str], path: Path | None = None) -> list[SeatConfig]:
    by_letter = {s.letter: s for s in load_seats(path)}
    unknown = [x for x in letters if x not in by_letter]
    if unknown:
        raise ValueError(f"Unknown seat letters: {', '.join(unknown)}")
    if len(set(letters)) != len(letters):
        raise ValueError("Each seat can only be picked once")
    return [by_letter[x] for x in letters]
