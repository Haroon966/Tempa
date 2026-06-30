from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str
    description: str
    body: str
    triggers: list[str] = field(default_factory=list)
    workers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    priority: int = 0
    path: str = ""
