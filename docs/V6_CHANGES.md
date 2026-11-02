# v6: responsiveness and verification

This release builds on v5. It changes serving and rendering, not model weights,
training losses, depth resolution, uncertainty calibration or validation rules.
It does not claim zero latency, production readiness or measured scientific skill.

## Changes

- Identical successful `/runs`, `/field`, `/profile`, `/section` and `/events`
  responses reuse the original JSON bytes in a process-local LRU cache. The
  default limits are 32 MiB of payload/header bytes and 128 entries; Python object
  overhead and the loaded dataset are additional memory. Large responses are not
  cached. Errors, validation and exports always bypass this cache.
- The cache key includes the run's resolved path, size, nanosecond modification
  and change times, and inode. Run replacement invalidates cached views and the
  loaded xarray dataset. Finish producing a run before serving it; prefer an
  atomic file replacement. Do not modify a live NetCDF file in place.
- Validation still checks schemas, source type, synthetic status and run
  provenance. Its SHA-256 is now calculated once per file identity rather than
  once per request. Replacing a same-sized file changes its identity and hash.
- Gzip level 3 compresses responses above 2 KiB for supporting clients, without
  rounding numbers or downsampling. `X-Ocean-Cache` reports HIT/MISS on cached
  routes. `Server-Timing` reports time to response headers, not full download or
  browser rendering time. HTTP browser caching is disabled on these views.
- Plotly is loaded as a separate local chunk when a chart mounts. The interface
  shell can load before the engine. Plotly's total size remains substantial;
  splitting does not make the first interactive chart instantaneous. No CDN or
  online map is required. Failed engine downloads have a retry button.
- Identical chart data no longer trigger Plotly updates for unrelated state
  changes. Resize requests are coalesced into animation frames, and chart cleanup
  uses the captured DOM node.
- A response from an old selection cannot be shown under the new selection's
  labels. Requests are cancelled on change and time out after 30 seconds.
- Explore playback waits for its field/profile requests to finish before
  scheduling the next date. It pauses on errors and outside Explore. This gates
  data availability, not completion of every browser paint.

## Your next stop

1. Extract into a fresh folder. Open `oceanembed-nio` in VS Code.
2. Follow `START_HERE.md` for the existing installation and demo commands.
3. Keep using Colab for training. This serving-only update does not require
   retraining existing v5 weights or recreating valid v5 calibration artifacts.
   If upgrading from v4, apply the migrations in `V5_CHANGES.md` first.
4. With all training/dev dependencies installed and `npm ci` completed, run:

   ```text
   python scripts/verify_release.py
   ```

5. With the API running, measure your actual machine:

   ```text
   python scripts/benchmark_api.py --requests 20 --out docs/API_BENCHMARK.json
   ```

   Restart the API before measuring a fresh process. The report separates the
   first request from repeated p50/p95 timings and records cache hits. It tests
   sequential field/profile downloads, not concurrent users or browser latency.
6. In browser developer tools, record a cold reload and a warm reload; then
   change depth/date, click profiles, play dates, open 3D, and export. Check that
   labels match the selected data, there are no console errors, the interface
   remains usable, and charts complete. Repeat on the laptop used for judging.

## Remaining limits

The full run still loads into RAM once per process. Large regional runs need
adequate RAM, and each extra Uvicorn worker duplicates the run and caches. Use
one worker on a laptop. Concurrent cache misses can repeat response computation;
validation hashing and dataset loading serialize their first computation. PNG
and NetCDF exports are generated on demand. Full-resolution 3D may be slow on
integrated graphics. Real-data accuracy, uncertainty coverage and latency must
be measured on the intended dataset and hardware. See `V6_VERIFICATION.json`
for what was actually checked in this environment.
