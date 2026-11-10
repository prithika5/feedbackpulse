"""Small in-memory helpers that protect the free-tier Gemini quota."""

import time
from collections import OrderedDict, defaultdict, deque


class AnswerCache:
    """Replays the events for a repeated question without calling the model again."""

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self.entries: OrderedDict[tuple[str, str], list] = OrderedDict()

    @staticmethod
    def key(app_id: str, question: str) -> tuple[str, str]:
        return app_id, " ".join(question.lower().split())

    def get(self, app_id: str, question: str) -> list | None:
        key = self.key(app_id, question)
        if key in self.entries:
            self.entries.move_to_end(key)
            return self.entries[key]
        return None

    def put(self, app_id: str, question: str, events: list) -> None:
        self.entries[self.key(app_id, question)] = events
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)


class RateLimiter:
    """Allows a set number of requests per IP in a sliding window."""

    def __init__(self, max_requests: int, window_seconds: float, clock=time.monotonic):
        self.max_requests = max_requests
        self.window = window_seconds
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = self.clock()
        hits = self.hits[ip]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
