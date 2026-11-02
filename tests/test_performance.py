"""Runnable without ML/web dependencies: python -m unittest discover -s tests -p test_performance.py."""
import asyncio
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from oceanembed.performance import ByteLRU, ResponseCache, cached_sha256


class CacheTests(unittest.TestCase):
    def test_eviction_is_bounded_and_recently_used_survives(self):
        cache = ByteLRU(max_bytes=6, max_entries=2)
        cache.put("a", b"aaa", 3)
        cache.put("b", b"bbb", 3)
        self.assertEqual(cache.get("a"), b"aaa")
        cache.put("c", b"ccc", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.bytes, 6)
        cache.put("a", b"huge payload", 12)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.bytes, 3)

    def test_hash_changes_after_same_size_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "run.nc"
            path.write_bytes(b"abc")
            self.assertEqual(cached_sha256(path), hashlib.sha256(b"abc").hexdigest())
            replacement = Path(d) / "replacement"
            replacement.write_bytes(b"xyz")
            replacement.replace(path)
            self.assertEqual(cached_sha256(path), hashlib.sha256(b"xyz").hexdigest())

    def test_response_identity_errors_streaming_and_invalidation(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "run.nc"
                path.write_bytes(b"initial")
                calls = []
                status, stream = 200, False
                # Exact output bytes, including float precision and nulls, must survive.
                payload = b'{"z":[[27.123456789,null]]}'

                async def endpoint(scope, receive, send):
                    calls.append(scope)
                    await send({"type":"http.response.start", "status":status, "headers":[(b"content-type",b"application/json")]})
                    if stream:
                        await send({"type":"http.response.body", "body":b"prefix", "more_body":True})
                    await send({"type":"http.response.body", "body":payload})

                middleware = ResponseCache(endpoint, lambda: path)

                async def request(route="/field", query=b"depth=100"):
                    result = []
                    async def send(message): result.append(message)
                    await middleware({"type":"http", "method":"GET", "path":route, "query_string":query}, None, send)
                    return result

                first, second = await request(), await request()
                self.assertEqual(len(calls), 1)
                self.assertEqual(first[-1]["body"], second[-1]["body"])
                self.assertIn((b"x-ocean-cache", b"HIT"), second[0]["headers"])
                await request(query=b"depth=200")
                self.assertEqual(len(calls), 2)
                path.write_bytes(b"different artifact")
                await request()
                self.assertEqual(len(calls), 3)
                await request("/validation")
                await request("/validation")
                self.assertEqual(len(calls), 5)
                status = 409
                await request(query=b"bad")
                await request(query=b"bad")
                self.assertEqual(len(calls), 7)
                status, stream = 200, True
                await request(query=b"stream")
                await request(query=b"stream")
                self.assertEqual(len(calls), 9)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
