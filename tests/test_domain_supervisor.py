from __future__ import annotations

from gethes.application.domain_supervisor import DomainSupervisor
from gethes.domain.resilience import DomainPolicy, DomainState


def test_single_failure_degrades_without_opening_circuit() -> None:
    supervisor = DomainSupervisor(
        policies=[DomainPolicy(name="cloud", max_consecutive_failures=2, cooldown_seconds=10.0)]
    )

    result = supervisor.call("cloud", "sync", lambda: (_ for _ in ()).throw(RuntimeError("boom")), fallback="ok")
    assert result == "ok"

    snap = supervisor.snapshots()[0]
    assert snap.domain == "cloud"
    assert snap.state == DomainState.DEGRADED
    assert snap.failure_streak == 1
    assert snap.total_failures == 1


def test_repeated_failures_open_circuit_and_skip_calls() -> None:
    current_time = [100.0]

    def now_fn() -> float:
        return current_time[0]

    supervisor = DomainSupervisor(
        policies=[DomainPolicy(name="syster", max_consecutive_failures=2, cooldown_seconds=20.0)],
        now_fn=now_fn,
    )

    supervisor.call("syster", "reply", lambda: (_ for _ in ()).throw(ValueError("x")), fallback=None)
    supervisor.call("syster", "reply", lambda: (_ for _ in ()).throw(ValueError("x")), fallback=None)

    snap = supervisor.snapshots()[0]
    assert snap.state == DomainState.OPEN
    assert snap.failure_streak == 2

    executed = {"value": False}

    def should_not_run() -> str:
        executed["value"] = True
        return "run"

    result = supervisor.call("syster", "reply", should_not_run, fallback="fallback")
    assert result == "fallback"
    assert executed["value"] is False

    snap = supervisor.snapshots()[0]
    assert snap.skipped_calls == 1

    current_time[0] = 130.5
    result = supervisor.call("syster", "reply", lambda: "ok", fallback=None)
    assert result == "ok"
    snap = supervisor.snapshots()[0]
    assert snap.state == DomainState.HEALTHY
    assert snap.failure_streak == 0


def test_failure_callback_receives_open_event() -> None:
    received: list[DomainState] = []

    def on_failure(event) -> None:  # type: ignore[no-untyped-def]
        received.append(event.state)

    supervisor = DomainSupervisor(
        policies=[DomainPolicy(name="games", max_consecutive_failures=1, cooldown_seconds=5.0)],
        on_failure=on_failure,
    )
    supervisor.call("games", "snake_tick", lambda: (_ for _ in ()).throw(RuntimeError("oops")), fallback=None)
    assert received == [DomainState.OPEN]

