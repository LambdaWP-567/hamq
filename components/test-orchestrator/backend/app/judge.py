from __future__ import annotations


class Judge:
    def __init__(self, max_val: int = 10000) -> None:
        self.max_val = max_val
        self.received: set[int] = set()
        self.cycle: int = 0

    def reset(self) -> None:
        self.received = set()
        self.cycle = 0

    def record(self, counter: int) -> None:
        if counter == 1 and self.received:
            self.cycle += 1
            self.received = set()
        self.received.add(counter)

    def missing(self) -> list[int]:
        if not self.received:
            return []
        ceiling = max(self.received)
        return [i for i in range(1, ceiling + 1) if i not in self.received]

    def completion_pct(self) -> float:
        if not self.received:
            return 0.0
        ceiling = max(self.received)
        return len(self.received) / ceiling * 100.0

    def missing_count(self) -> int:
        return len(self.missing())
