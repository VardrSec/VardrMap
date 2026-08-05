"""In-memory SSE broker — single instance only (Railway single-process deploy).
One asyncio.Queue per connected client, keyed by program_id."""
import asyncio
from collections import defaultdict

_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(program_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers[program_id].append(q)
    return q


def unsubscribe(program_id: str, q: asyncio.Queue) -> None:
    try:
        _subscribers[program_id].remove(q)
    except ValueError:
        pass


def notify(program_id: str, event: dict) -> None:
    """Push an event to all clients watching this engagement. Dead queues are pruned."""
    dead = []
    for q in list(_subscribers.get(program_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unsubscribe(program_id, q)
