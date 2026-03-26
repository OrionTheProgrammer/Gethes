from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, TypeVar

from gethes.domain.resilience import (
    DomainFailureEvent,
    DomainHealthSnapshot,
    DomainPolicy,
    DomainState,
)


T = TypeVar("T")


@dataclass
class _DomainHealth:
    success_count: int = 0
    total_failures: int = 0
    failure_streak: int = 0
    skipped_calls: int = 0
    last_error: str = ""
    open_until: float = 0.0
    last_failure_at: float = 0.0
    last_success_at: float = 0.0


class DomainSupervisor:
    """Application-layer fault boundary for domain operations.

    Each domain can open a short circuit after repeated failures. This keeps
    a failing subsystem from collapsing the whole runtime loop.
    """

    def __init__(
        self,
        policies: list[DomainPolicy] | tuple[DomainPolicy, ...],
        on_failure: Callable[[DomainFailureEvent], None] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._policies: dict[str, DomainPolicy] = {policy.name: policy for policy in policies}
        self._fallback_policy = DomainPolicy(name="default")
        self._health: dict[str, _DomainHealth] = {name: _DomainHealth() for name in self._policies}
        self._on_failure = on_failure
        self._now = now_fn or time.monotonic

    def call(
        self,
        domain: str,
        action: str,
        operation: Callable[[], T],
        *,
        fallback: T | None = None,
        critical: bool = False,
    ) -> T | None:
        token = domain.strip().lower() or "default"
        current_time = self._now()
        policy = self._policies.get(token, self._fallback_policy)
        health = self._health.setdefault(token, _DomainHealth())

        if health.open_until > current_time and not critical:
            health.skipped_calls += 1
            return fallback

        try:
            result = operation()
        except Exception as exc:
            health.total_failures += 1
            health.failure_streak += 1
            health.last_failure_at = current_time
            health.last_error = f"{type(exc).__name__}: {exc}"

            next_state = DomainState.DEGRADED
            if health.failure_streak >= max(1, policy.max_consecutive_failures):
                health.open_until = current_time + max(0.0, policy.cooldown_seconds)
                next_state = DomainState.OPEN
            else:
                health.open_until = 0.0

            if self._on_failure is not None:
                self._on_failure(
                    DomainFailureEvent(
                        domain=token,
                        action=action,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        state=next_state,
                        open_until=health.open_until,
                        failure_streak=health.failure_streak,
                        total_failures=health.total_failures,
                    )
                )

            if critical:
                raise
            return fallback

        health.success_count += 1
        health.failure_streak = 0
        health.open_until = 0.0
        health.last_success_at = current_time
        return result

    def reset_domain(self, domain: str) -> None:
        token = domain.strip().lower()
        if not token:
            return
        self._health[token] = _DomainHealth()

    def snapshots(self) -> list[DomainHealthSnapshot]:
        current_time = self._now()
        result: list[DomainHealthSnapshot] = []
        for domain, health in sorted(self._health.items()):
            if health.open_until > current_time:
                state = DomainState.OPEN
            elif health.failure_streak > 0:
                state = DomainState.DEGRADED
            else:
                state = DomainState.HEALTHY
            result.append(
                DomainHealthSnapshot(
                    domain=domain,
                    state=state,
                    success_count=health.success_count,
                    total_failures=health.total_failures,
                    failure_streak=health.failure_streak,
                    skipped_calls=health.skipped_calls,
                    last_error=health.last_error,
                    open_until=health.open_until,
                    last_failure_at=health.last_failure_at,
                    last_success_at=health.last_success_at,
                )
            )
        return result

