"""In-process pub/sub so WebSocket clients get a run's events the moment they are stored."""

import asyncio
from collections import defaultdict
from typing import Any

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


def subscribe(run_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers[run_id].add(q)
    return q


def unsubscribe(run_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(run_id)
    if subs is not None:
        subs.discard(q)
        if not subs:
            del _subscribers[run_id]


def publish(event: dict[str, Any]) -> None:
    for q in list(_subscribers.get(event["run_id"], ())):
        q.put_nowait(event)
