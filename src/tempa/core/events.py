from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AgentActivityEvent:
    agent: str
    action: str
    detail: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "action": self.action,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


class EventBus:
    """In-process pub/sub for agent activity WebSocket clients."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._history: deque[dict[str, Any]] = deque(maxlen=200)
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    async def publish(self, event: AgentActivityEvent | dict[str, Any]) -> None:
        payload = event.to_dict() if isinstance(event, AgentActivityEvent) else event
        self._history.append(payload)
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            await queue.put(payload)

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history)[-limit:]

    async def publish_json(self, agent: str, action: str, detail: str = "") -> None:
        await self.publish(AgentActivityEvent(agent=agent, action=action, detail=detail))


event_bus = EventBus()
