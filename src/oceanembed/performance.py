"""Bounded, process-local acceleration; cached values retain original bytes."""
from collections import OrderedDict
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import RLock
from time import perf_counter


def fingerprint(path):
    p = Path(path).resolve()
    s = p.stat()
    return (str(p), s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)


@lru_cache(maxsize=4)
def _digest(identity):
    h = sha256()
    with open(identity[0], "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    if fingerprint(identity[0]) != identity:
        raise RuntimeError("Run changed during checksum; finish writing it and retry")
    return h.hexdigest()


_hash_lock = RLock()


def cached_sha256(path):
    # Serialize initial digest calculation so simultaneous validations don't hash twice.
    with _hash_lock:
        return _digest(fingerprint(path))


class ByteLRU:
    def __init__(self, max_bytes=32 * 1024 * 1024, max_entries=128):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.bytes = 0
        self.items = OrderedDict()
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            item = self.items.get(key)
            if item is not None:
                self.items.move_to_end(key)
                return item[0]

    def put(self, key, value, size):
        with self.lock:
            old = self.items.pop(key, None)
            if old is not None:
                self.bytes -= old[1]
            if size > self.max_bytes or self.max_entries < 1:
                return
            self.items[key] = (value, size)
            self.bytes += size
            while self.bytes > self.max_bytes or len(self.items) > self.max_entries:
                _, (_, count) = self.items.popitem(last=False)
                self.bytes -= count


class ResponseCache:
    """Cache only successful read-only JSON views, never validation or exports.

    Pure ASGI: does not consume streaming responses or hold exports in memory.
    File identity is checked before and after generation. Fingerprints are an
    invalidation mechanism, not a substitute for scientific provenance checks.
    """
    paths = frozenset(("/runs", "/field", "/profile", "/section", "/events"))

    def __init__(self, app, run_path, max_bytes=32 * 1024 * 1024):
        self.app, self.run_path = app, run_path
        self.cache = ByteLRU(max_bytes=max_bytes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "GET" or scope["path"] not in self.paths:
            return await self.app(scope, receive, send)
        start = perf_counter()
        try:
            identity = fingerprint(self.run_path())
        except OSError:
            return await self.app(scope, receive, send)
        key = (identity, scope["path"], scope.get("query_string", b""))
        hit = self.cache.get(key)
        if hit is not None:
            headers, body = hit
            await send({"type": "http.response.start", "status": 200,
                        "headers": headers + self.timing(start, "HIT")})
            return await send({"type": "http.response.body", "body": body})
        headers = None

        async def capture(message):
            nonlocal headers
            if message["type"] == "http.response.start":
                if message["status"] == 200:
                    headers = list(message.get("headers", []))
                message = {**message, "headers": list(message.get("headers", [])) + self.timing(start, "MISS")}
            elif message["type"] == "http.response.body" and headers is not None:
                body = message.get("body", b"")
                if not message.get("more_body", False):
                    try:
                        unchanged = fingerprint(self.run_path()) == identity
                    except OSError:
                        unchanged = False
                    if unchanged:
                        self.cache.put(key, (headers, body), len(body) + sum(len(k)+len(v) for k,v in headers))
                # Never cache a multi-chunk response, including its final chunk.
                headers = None
            await send(message)

        await self.app(scope, receive, capture)

    @staticmethod
    def timing(start, status):
        elapsed = (perf_counter() - start) * 1000
        return [(b"server-timing", f'app;dur={elapsed:.3f}'.encode()),
                (b"x-ocean-cache", status.encode()),
                (b"cache-control", b"no-store")]
