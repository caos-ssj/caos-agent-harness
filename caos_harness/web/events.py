"""A small in-memory event bus for the dashboard's live streams.

Each channel has a version counter. A writer calls `publish(channel)`; a reader asks `wait(channel, since, timeout)` and sleeps on a
condition variable until the version moves or the timeout (the heartbeat) ends: no polling loop, no busy waiting.
"""
from __future__ import annotations

import threading


class EventBus:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._versions: dict[str, int] = {}
        self._total = 0

    def publish(self, channel: str) -> None:
        with self._cond:
            self._versions[channel] = self._versions.get(channel, 0) + 1
            self._total += 1
            self._cond.notify_all()

    def version(self, channel: str) -> int:
        with self._cond:
            return self._versions.get(channel, 0)

    def total(self) -> int:
        with self._cond:
            return self._total

    def versions(self, *channels: str) -> dict[str, int]:
        with self._cond:
            return {c: self._versions.get(c, 0) for c in channels}

    def wait(self, channel: str, since: int, timeout: float) -> int:
        """Blocks until `channel` is past `since` or `timeout` passes; returns the version it ended on."""
        with self._cond:
            self._cond.wait_for(lambda: self._versions.get(channel, 0) != since, timeout)
            return self._versions.get(channel, 0)

    def wait_any(self, since_total: int, timeout: float) -> int:
        """Blocks until anything was published after `since_total` or `timeout` passes; returns the running total."""
        with self._cond:
            self._cond.wait_for(lambda: self._total != since_total, timeout)
            return self._total
