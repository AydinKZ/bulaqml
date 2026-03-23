import time
from collections import OrderedDict

class TTLRUStore:
    def __init__(self, max_keys: int, ttl_sec: int):
        self.max_keys = max_keys
        self.ttl_sec = ttl_sec
        self._data = OrderedDict()
        self._last_seen = {}

    def get(self, key):
        v = self._data.get(key)
        if v:
            self._data.move_to_end(key)
        return v

    def set(self, key, value):
        self._data[key] = value
        self._data.move_to_end(key)
        self._last_seen[key] = time.time()
        self._evict()

    def touch(self, key):
        if key in self._data:
            self._data.move_to_end(key)
            self._last_seen[key] = time.time()

    def evict_ttl(self):
        now = time.time()
        dead = [k for k,t in self._last_seen.items() if (now-t) > self.ttl_sec]
        for k in dead:
            self._data.pop(k, None)
            self._last_seen.pop(k, None)

    def _evict(self):
        while len(self._data) > self.max_keys:
            k,_ = self._data.popitem(last=False)
            self._last_seen.pop(k, None)

    def __len__(self):
        return len(self._data)