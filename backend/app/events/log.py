"""Ordered event log for a run. Every event is stored, then handed to live subscribers.

The CLI renders from these events today; the WebSocket (milestone 3) and Replay will too.
"""

import json
from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from app.db import Event

EventSink = Callable[[dict[str, Any]], None]


class EventLog:
    def __init__(self, session: Session, run_id: str):
        self.session = session
        self.run_id = run_id
        self.seq = 0
        self.sinks: list[EventSink] = []

    def subscribe(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    def emit(self, type_: str, **payload: Any) -> dict[str, Any]:
        self.seq += 1
        row = Event(
            run_id=self.run_id, seq=self.seq, type=type_, payload_json=json.dumps(payload)
        )
        self.session.add(row)
        self.session.commit()
        event = {"run_id": self.run_id, "seq": self.seq, "type": type_, "payload": payload}
        for sink in self.sinks:
            sink(event)
        return event
