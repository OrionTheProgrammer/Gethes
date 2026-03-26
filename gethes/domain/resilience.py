from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DomainState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN = "open"


@dataclass(frozen=True)
class DomainPolicy:
    name: str
    max_consecutive_failures: int = 2
    cooldown_seconds: float = 12.0


@dataclass(frozen=True)
class DomainFailureEvent:
    domain: str
    action: str
    error_type: str
    error_message: str
    state: DomainState
    open_until: float
    failure_streak: int
    total_failures: int


@dataclass(frozen=True)
class DomainHealthSnapshot:
    domain: str
    state: DomainState
    success_count: int
    total_failures: int
    failure_streak: int
    skipped_calls: int
    last_error: str
    open_until: float
    last_failure_at: float
    last_success_at: float

