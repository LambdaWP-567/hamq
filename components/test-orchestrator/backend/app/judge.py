from __future__ import annotations

from datetime import datetime


class Judge:
    def __init__(self, max_val: int = 10000) -> None:
        self.max_val = max_val
        self.received: set[int] = set()
        self.cycle: int = 0
        self._first_missing_at: dict[int, str] = {}

    def reset(self) -> None:
        self.received = set()
        self.cycle = 0
        self._first_missing_at = {}

    def record(self, counter: int) -> None:
        if counter == 1 and self.received:
            self.cycle += 1
            self.received = set()
            self._first_missing_at = {}
        old_ceil = max(self.received) if self.received else 0
        self.received.add(counter)
        new_ceil = max(self.received)
        if new_ceil > old_ceil:
            now = datetime.now().strftime("%H:%M:%S")
            for i in range(old_ceil + 1, new_ceil + 1):
                if i not in self.received:
                    self._first_missing_at.setdefault(i, now)

    def missing(self) -> list[int]:
        if not self.received:
            return []
        ceiling = max(self.received)
        return [i for i in range(1, ceiling + 1) if i not in self.received]

    def missing_with_timestamps(self) -> list[tuple[int, str]]:
        return [(n, self._first_missing_at.get(n, "")) for n in self.missing()]

    def completion_pct(self) -> float:
        if not self.received:
            return 0.0
        ceiling = max(self.received)
        return len(self.received) / ceiling * 100.0

    def missing_count(self) -> int:
        return len(self.missing())
