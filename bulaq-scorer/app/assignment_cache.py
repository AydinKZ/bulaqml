import threading
import time

import threading
import time


class AssignmentCache:
    def __init__(self, ttl_sec: int = 60):
        self.ttl_sec = ttl_sec
        self._data = {}
        self._lock = threading.Lock()

    def get(self, uuid: str):
        with self._lock:
            item = self._data.get(uuid)
            if not item:
                return None
            if item["exp"] < time.time():
                self._data.pop(uuid, None)
                return None
            return item["value"]

    def set(self, uuid: str, value: dict):
        with self._lock:
            self._data[uuid] = {
                "value": value,
                "exp": time.time() + self.ttl_sec,
            }

    def invalidate(self, uuid: str):
        with self._lock:
            self._data.pop(uuid, None)

    def clear(self):
        with self._lock:
            self._data.clear()