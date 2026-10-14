"""Counts API transactions so a run can be capped."""

from __future__ import annotations

import threading


class BudgetExceeded(Exception):
    pass


class Budget:
    """Counts API transactions; ``limit`` of 0/None means unlimited."""

    def __init__(self, limit=None):
        self.limit = limit or None
        self.used = 0
        self._lock = threading.Lock()     # downloads can make several requests at once

    def spend(self, n=1):
        with self._lock:
            if self.limit is not None and self.used + n > self.limit:
                raise BudgetExceeded(f"Transaction limit for this download reached ({self.limit:,}).")
            self.used += n

    @property
    def remaining(self):
        return None if self.limit is None else self.limit - self.used
