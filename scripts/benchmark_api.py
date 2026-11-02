"""Measure a running local API; reports actual timings, never assumed targets.
python scripts/benchmark_api.py --requests 20 --out docs/API_BENCHMARK.json
Start the API and select OCEAN_RUN first. First request may include loading.
"""
import argparse
import json
import math
import platform
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode, urlparse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--requests", type=int, default=20)
    p.add_argument("--out", default="docs/API_BENCHMARK.json")
    args = p.parse_args()
    if urlparse(args.base).hostname not in ("localhost", "127.0.0.1", "::1"):
        p.error("Use a local API address")
    if not 2 <= args.requests <= 200:
        p.error("requests must be between 2 and 200")

    def get(path, params=None):
        started = time.perf_counter()
        with urlopen(args.base.rstrip("/") + path + "?" + urlencode(params or {}), timeout=120) as r:
            body = r.read()
            record = {"ms":round((time.perf_counter()-started)*1000, 3), "bytes":len(body), "cache":r.headers.get("X-Ocean-Cache", "BYPASS")}
        return json.loads(body), record

    meta, startup = get("/runs")
    b = meta["bounds"]
    cases = {"field": {"date":meta["dates"][0], "depth":meta["depths"][0]},
             "profile": {"date":meta["dates"][0], "lat":(b[1]+b[3])/2, "lon":(b[0]+b[2])/2}}
    results = {}
    for name, params in cases.items():
        _, first = get("/"+name, params)
        samples = [get("/"+name, params)[1] for _ in range(args.requests)]
        times = sorted(s["ms"] for s in samples)
        results[name] = {"first":first, "repeat_p50_ms":times[math.ceil(len(times)*.5)-1], "repeat_p95_ms":times[math.ceil(len(times)*.95)-1], "samples":samples}
    report = {"platform":platform.platform(), "source_mode":meta.get("source_mode"), "startup_runs":startup, "results":results,
              "scope":"Sequential localhost HTTP JSON downloads. Excludes browser drawing, GPU training, concurrent users, gzip, and cold operating-system disk caches. Center profile may be land. Restart API for a fresh process measurement."}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
