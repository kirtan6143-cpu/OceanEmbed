# V15 — merge: mixed-layer generator fix + D26 palette split, on top of V14

Scope: two small, isolated changes merged into the V14 branch. Nothing in
V13/V14's own work (autoRange, bloom/vignette, at-a-glance panel, real-Argo-
only dots, Readiness tab, per-cell reliability reason) was touched or
reverted.

## 1. `scripts/create_visual_demo.py` — variable-depth mixed layer

V14's `autoRange()` auto-scales each map's legend to the run's real data,
but deliberately refuses to do so when the real span is under 2% of the
mode's physical domain (its own honest floor against fabricating contrast
out of near-noise) -- and falls back to the full fixed domain instead.
Checked against the V14 generator as shipped: MLD-T's real span was ~0.9 m
against a 150 m domain (2% floor = 3 m), so it was still falling back and
still rendering flat, not because of a frontend bug but because the
generator's single global exponential decay from z=0 barely moves over the
top ~20 m anywhere on the map -- every column crossed the MLD-T threshold
at ~11 m regardless of location.

Replaced with a two-layer profile: a near-constant mixed layer down to a
spatially- and seasonally-varying `mld` field (12-75 m), transitioning into
a thermocline decay toward a fixed deep temperature. This is the same fix
described in `DOMAIN_CALIBRATION.md` from the earlier (pre-V13) pass;
porting it here because V13/V14 rebuilt the frontend's handling of the
domain-mismatch symptom but inherited the unmodified generator, so the one
variable whose problem was in the *data*, not the *display*, was still
broken under the new build.

Verified (computed directly, all three now clear their own mode's autoRange
floor by a wide margin, sampled every 3rd day across the 45-day run):

| Field | Span needed to clear autoRange floor | Actual span after fix |
|---|---|---|
| D26 (2% of 250 m) | > 5.0 m | 52.0 m |
| TCHP (2% of 150 kJ/cm^2) | > 3.0 kJ/cm^2 | 92.7 kJ/cm^2 |
| MLD-T (2% of 150 m) | > 3.0 m | 40.2 m |

## 2. `frontend/src/OceanMap.tsx` — D26 no longer shares a palette with MLD-T

V14 gave TCHP its own purpose-built palette (`heatPotential`) but D26 and
MLD-T still both used `depthScale` -- same cream-teal-navy ramp, two
different physical quantities. Even with `autoRange` giving each its own
data-fit range, sharing one palette meant switching between those two tabs
could still read as "the same map." Added `isothermScale` (cream-to-coffee,
warm and monotone) for D26 only; MLD-T keeps `depthScale`. No other palette,
domain, or the `autoRange` logic itself was changed.

## 3. A periodic-pattern artifact in the anomaly texture, found by inspecting a live screenshot

Comparing a screenshot of the Heat events map on 2024-06-01 against the
reference imagery surfaced a visible diamond/argyle grid pattern covering
most of the Bay of Bengal — clearly not organic ocean structure. Traced to
the generator's `ripple` term: `0.22 * sin(x*0.8+y*0.5+day/10) * cos(y*0.8)`.
A raw sin*cos product is mathematically periodic, so it *always* renders as
a regular checkerboard when colour-mapped — this was invisible only on days
near the travelling warm-blob event's peak (day ~23), where that event's
signal (up to 1.7 degC) swamps it. On day 0 specifically (confirmed by
direct computation): the warm-blob term contributes 0.00044 degC while the
ripple term contributes up to 0.22 degC — on that date the ripple *is* the
entire visible anomaly field.

Replaced with Gaussian-smoothed noise (fixed seed 11, sigma 3.5), with a
slow amplitude "breathing" over time instead of a travelling phase.
Smoothing removes any single dominant wavelength, so the result cannot
produce a repeating geometric pattern at any date. Verified structurally,
not just visually: computed the spatial autocorrelation of the new anomaly
field at lags up to 28 cells (the old wave's period was ~7.85 cells) --
correlation decays smoothly and never bounces back toward +1 at the old
period or its harmonics, confirming no residual periodicity, unlike the
term it replaced.

## 4. Real contrast increase — not fabrication, a distinct thing

Following on from the discussion above about what does and doesn't cross
into fabricating data: added two changes that make the *same real values*
render more vividly, with nothing invented:

- **A monotonic S-curve on the colour mapping** (`fieldColor`'s new `GAMMA`
  step). This spends more of the palette's visual range on values further
  from the middle of the current range, instead of spacing colour linearly
  with value. Verified numerically before shipping: the exponent direction
  matters (`k<1` compresses toward the middle -- the opposite of the goal,
  caught this by computing sample outputs before committing to it); `k>1`
  (1.6 used here) correctly spreads values apart. Also verified strictly
  monotonic across the full [0,1] range, i.e. two real values' relative
  order and magnitude are always preserved -- this changes nothing about
  what the data says, only how visually distinct two different values look.
- **Bilinear upsampling of the real grid before colouring** (`bilinearUpsample`,
  4x). Every output pixel is a weighted average of the four real,
  actually-computed neighbouring grid values -- the same interpolation any
  smooth weather map does between station points, not new data. Replaces
  the one-pixel-per-cell blockiness with smooth gradients. Returns null
  (renders nothing) wherever any of the four real neighbours is null, so it
  never blurs a real value across a land boundary or a genuine data gap.

## 5. Pushing visual quality further toward the reference imagery

Two safe, purely-decorative tunings, done to close more of the remaining
gap without adding anything fabricated:

- Raster upsampling factor raised from 4x to 6x (still real interpolated
  values only, see `bilinearUpsample`'s own note) for smoother gradients.
- Ocean shimmer noise raised from 3 to 5 octaves, so it reads with the
  same multi-scale "painterly" texture as the reference imagery instead of
  one flat grain frequency. This is decorative surface texture layered over
  real data colours -- it never changes or replaces a value, only adds
  visual atmosphere on top, same as it did before at fewer octaves.

Not done, and the honest reason: a real photographic satellite/terrain
basemap (the single biggest remaining gap vs. the reference imagery) needs
sourcing an actual, correctly-licensed image covering this exact region --
a bundled-asset task, not a code tuning, and out of scope for this pass.

## 6. Real-photo basemap layer — code wired, image not bundled (network limit)

Added the code side of a real satellite-photo basemap: `useBasemapPhoto()`
probes for `/basemap-earth.jpg` (same "detect, don't assume" pattern as
`useCoastline`) and only renders it if it actually loads -- the map looks
and behaves exactly as before if the file is absent, so this ships safely
with no asset yet. When present, it's positioned via the existing X()/Y()
coordinate functions against a fixed real-world bounding box
(`BASEMAP_BOUNDS`, lon 50-104 / lat -2-28) so it pans and zooms in sync with
the coastline and data layers, and rendered at 55% opacity with a
`multiply` blend so it recedes behind the real data instead of competing
with it.

The actual image could not be fetched into this build: this sandbox's
network is restricted to a fixed allowlist (npm/pypi/github mirrors only)
and returns `host_not_allowed` for NASA's image hosts (confirmed directly:
`curl -I https://visibleearth.nasa.gov` -> 403). This is not a licensing or
technical-feasibility limitation, only a fetch-access one in this
environment.

**To finish this**: download NASA Visible Earth's "The Blue Marble" (a
public-domain MODIS true-color composite; credit "NASA Earth Observatory" /
Goddard Space Flight Center per NASA's own reuse terms) --
https://visibleearth.nasa.gov/images/57723/the-blue-marble or
https://visibleearth.nasa.gov/images/57735/ -- crop it to roughly
50 deg E-104 deg E, 2 deg S-28 deg N (the South Asia / Indian Ocean sector), and save it
as `frontend/public/basemap-earth.jpg`. No code change is needed after
that; the layer activates automatically the next time the app loads.

## 7. The real photo is now actually in the project

Following on from #6: you provided a real screenshot of NASA's Blue Marble
imagery (from science.nasa.gov), and it's now genuinely bundled at
`frontend/public/basemap-earth.jpg` -- not just coded-for this time.

Getting the crop right took three attempts, documented honestly:
- First attempt: framed correctly by luck, but I didn't trust it.
- Second attempt: recalibrated using two landmark reference points (Bab-el-
  Mandeb strait, Singapore) -- overshot far too far north (Central Asia/
  Himalayas), because those two reference points were themselves misread
  off the image.
- Third attempt: went back to a grid-overlaid version of the source image,
  read the pixel coordinates directly and carefully rather than estimating,
  and matched the crop to what the app's own Explore-tab screenshots
  already show (Pakistan top, India + Sri Lanka centre, Bay of Bengal,
  Myanmar/Malaysia/Sumatra right, open ocean south). This is the version
  bundled.

Two honest caveats about this specific asset, left in rather than glossed
over:
- The crop's alignment to `BASEMAP_BOUNDS` (lon 50-104, lat -2-28) is
  landmark-matched, not measured from precise reference coordinates -- it
  looks right, but hasn't been checked against a surveyed source.
- The crop's own pixel aspect ratio (980x480, ~2.04:1) doesn't exactly
  match the bounding box's geographic aspect (54deg lon / 30deg lat,
  ~1.8:1), so it renders mildly vertically stretched (~12%) when the
  browser fits it to the box. Acceptable for a low-opacity decorative
  layer; would be worth a tighter re-crop if this is ever pixel-audited.

Confirmed the file is actually picked up by the build, not just present in
the source tree: `dist/basemap-earth.jpg` appears in the production build
output after `vite build` (public/ assets are copied verbatim, unhashed).

Credit: NASA Earth Observatory / NASA Goddard Space Flight Center
(Blue Marble), per NASA's own reuse terms.

## 8. Caught the basemap was practically invisible, before you'd ever see it

Since I still can't render the app live (no headless browser available in
this sandbox -- confirmed again, no cached binary and the download CDN is
blocked), I built an offline approximation instead: composited the real
photo, the real `coastline.geojson` polygons, and the exact opacity/blend
values from the shipped code, using the same coordinate math `OceanMap.tsx`
uses. Two things came out of actually looking at that, rather than assuming
the shipped settings were fine:

- **Alignment is genuinely good.** India's coastline, Sri Lanka, Myanmar's
  coast all lined up sensibly between the vector polygons and the real
  photo underneath -- confirmed visually, not assumed.
- **The settings from #6/#7 were wrong.** `multiply` blend at 0.55 opacity,
  layered on top of an already-dark ocean gradient, crushed the real photo
  to near-black -- had to brighten a diagnostic render 2.2x just to see any
  texture at all. Shipped as-is, this real photo would have been
  practically invisible in the actual app despite being correctly bundled
  and positioned.

Fixed: photo now shown at 0.85 opacity with normal blending (not
multiplied against the dark gradient), with a separate translucent dark
navy scrim (`#061423` at 0.32 opacity) layered on top to tint it toward the
app's theme instead. Re-composited the same offline approximation with the
new settings and confirmed real photo detail (India's terrain colour,
Sri Lanka, Myanmar coastline) is now actually visible while still reading
as dark-themed, not a jarring bright daytime photo.

This offline composite is still an approximation, not the real SVG
pipeline -- it doesn't include the bloom/vignette filters or the thermal
data raster above it -- so the live result may look somewhat different
again. Recommend an actual screenshot from a real browser once one is
available, to close this out properly.

## 9. Full visual-quality pass: real photo, finer coastline, contours, resolution, performance fix

Everything below was verified individually (build, typecheck, or a targeted
numeric/logic test) before being combined -- not assumed to work together
just because each piece worked alone.

**Real basemap photo, properly calibrated.** The user's ChatGPT-edited
NASA Blue Marble crop (navy/cyan graded, per the earlier prompt) is now
the bundled `basemap-earth.jpg`. Recalibrated its crop against the real
`coastline.geojson` polygons using two landmark reference points (Strait
of Hormuz, Sri Lanka) rather than eyeballing -- confirmed by overlay: India,
Sri Lanka and Myanmar's coastlines all track tightly against the photo,
tighter than the previous crop.

**Finer coastline data.** Replaced the bundled 110m-resolution Natural
Earth country polygons with the 10m-resolution version (fetched live from
`raw.githubusercontent.com/nvkelso/natural-earth-vector`, clipped to a
generous margin around the region, mildly simplified for size). Caught a
real compatibility bug before shipping: after clipping, 19 of 42 country
features came back as plain `Polygon` geometry instead of `MultiPolygon`
-- the app's parser assumes every feature is `MultiPolygon` uniformly (
confirmed by checking the existing bundled file only ever contains that
type) and would have rendered those 19 countries' coastlines incorrectly.
Normalized all geometries to `MultiPolygon` and re-verified the exact
parsing logic from `OceanMap.tsx` against the new file directly (542
polygon rings parse with no errors). File grew from 43KB to ~1MB --
bundled and confirmed present in the production build (`dist/coastline.geojson`).

**Real contour lines**, added via `d3-contour` (genuine marching-squares,
not a decorative approximation): 5 threshold levels computed from the
same auto-fit range already driving the legend, derived directly from
`field.z`. Verified twice before wiring into the UI: (1) on a simulated
warm-blob field, produces correctly nested concentric rings, matching how
real isotherms should look; (2) with a simulated land/no-data region,
zero contour points fall inside it -- the -1e9 sentinel used for missing
cells (chosen because d3-contour has no native NaN handling) correctly
keeps false lines from ever being drawn over land or unsupported cells.

**Grid resolution doubled**, 64x76 -> 128x152 in `create_visual_demo.py`
-- more real computed points, not invented detail. Timed before
committing: `field_diagnostics`' per-cell Python loop scales from 0.123s
to 0.487s per request at this resolution, acceptable given the API layer's
existing response cache.

**A real performance bug caught before it shipped.** Combining the
doubled grid with an increased upsample factor (6x -> 9x) means the
raster is now ~1.6M pixels. The existing rendering approach drew this via
one `ctx.fillRect()` call per pixel -- measured the interpolation step
alone at ~190ms in Node for this size; per-pixel canvas draw calls are
markedly slower than a bulk write at this pixel count, which would have
meant visible lag on every date/variable change, worse on a phone.
Rewrote to build a single `ImageData` buffer and one `putImageData()`
call instead. Verified the rewrite is pixel-correct, not just faster:
tested the vertical-flip indexing in isolation with a traceable small
case (confirmed row 0 correctly lands at the last output row, matching
the original `fillRect(j, height-i-1, ...)` behaviour exactly) before
trusting it on real data.

**Fixed the double-darkening properly this time**, now that the photo
itself is already navy-graded: opacity raised to 0.9 (from 0.85), scrim
opacity cut to 0.12 (from 0.32) -- tested several combinations offline
against the actual new photo before picking these, rather than reusing
the settings tuned for the old (warmer) photo.

**Sharpening filter** added: a standard unsharp-mask SVG filter (Gaussian
blur, then arithmetic-composite subtract) applied to the basemap image.
Sharpens existing real detail; invents nothing.

## 10. A deeper cross-check pass, requested explicitly -- one more real bug found

Re-examined the session's own changes line by line rather than assuming
they were done once verified individually:

- **Variable shadowing checked, found harmless.** The raster rewrite
  declares its own local `w`/`h` (pixel dimensions) inside the same
  component that already has an outer `w`/`h` (map width/height in
  degrees). Confirmed by reading the full callback body that nothing
  inside it needs the outer values -- shadowing is real but inert here.

- **A real contour-line bug, found by tracing the actual pipeline, not an
  artificial test.** Fed the historical flat-MLD-T scenario (the exact
  numbers from before the mixed-layer-depth fix) through the real
  `autoRange()` logic rather than guessing: confirmed that near-uniform
  (not perfectly flat, just close) data can still produce a padded range
  where 2 of 5 contour thresholds fall entirely above or below every real
  value. Marching squares then has no interior crossing to trace and
  returns a ring following the *entire grid boundary* instead -- a
  picture-frame artifact, not a contour. Fixed: any ring whose every
  vertex sits on the grid's outer edge is discarded (a genuine interior
  contour only ever touches the edge at isolated points, never traces the
  whole perimeter). Verified both directions: the degenerate case's rings
  are now correctly dropped (2 -> 0), and the earlier legitimate warm-blob
  test case still keeps all 5 real rings (5 -> 5, unchanged) -- so the fix
  removes the artifact without removing real contour lines.

- **End-to-end performance timed as a whole, not just the piece measured
  earlier.** The full pipeline (bilinear upsample + colour mapping with
  caching) at the new 128x152 grid x 9x upsample (~1.6M pixels) measured
  ~109ms in Node -- upsample 50ms, colour-fill 59ms. Comfortably within a
  responsive feel for a per-date/per-variable update, not a per-frame one.

## 11. Deep code-review pass — five more real defects found and fixed

Requested explicitly as a line-by-line cross-verification. Five genuine
defects, four of them introduced earlier in this same session:

**(a) `fieldColor` could throw and blank the entire map.** Probed it
directly with nine edge cases rather than reading it: a degenerate range
(`hi === lo`) divides by zero and a non-finite `value` propagates NaN into
the palette index -- both index past the palette, yielding `undefined`, and
throw inside the hex parse. Because this runs inside React render, a throw
unmounts the whole map component rather than degrading one pixel. Traced
reachability honestly: *not* currently reachable via the API (its `clean()`
maps non-finite floats to `null`, and `autoRange()` never returns a
degenerate span), but `fieldColor` is exported and also called from
`Cutaway.tsx`, so the guard belongs at the function boundary rather than
depending on every present and future caller. Fixed; re-ran all nine cases
(none throw) and confirmed the normal case returns a byte-identical colour
to before, so no regression.

**(b) Contour lines froze in place on zoom.** `contourPaths` baked screen
coordinates (via `X()`/`Y()`, which depend on `zoom`) into its path strings
but was keyed only on `[field, range]`. Any user pressing the map's zoom
button would have seen the contour lines stay put while the basemap, raster
and coastline all moved. Fixed by splitting into two stages: `contourRings`
(marching squares, grid space, keyed on data only) and `contourPaths`
(cheap projection, keyed on the viewport). This is both the correctness fix
and the better structure -- the expensive algorithm no longer re-runs for a
zoom at all. Verified by projecting the same rings at zoom=1 vs zoom=2 and
confirming the output paths genuinely differ.

**(c) The coastline upgrade quietly created a hover-performance problem.**
`polygons` was computed inline on every render -- including every mousemove,
since hovering sets state. Measured with the newly-bundled 10m coastline:
~14.7ms and ~606,000 path characters across 542 rings, per render, before
counting React's own reconciliation of 542 large `d` attributes. Pure waste,
since the geometry only changes when the coastline or viewport does. Now
memoized on `[coast, l, t, w, h]`.

**(d) Same issue in the reliability overlay.** `marks` walked the full
~19,500-cell reliability grid building elements on every render. Now
memoized on `[reliability, field, l, t, w, h]`.

**(e) The contour lines would have been invisible where they matter most.**
Computed the WCAG contrast ratio of the plain white stroke against every
stop of all five palettes: it falls to **1.08-1.42** at each palette's
lightest stop -- effectively invisible in precisely the pale high-value
regions (an anomaly's warm core, TCHP's pale-yellow peak) the contours exist
to delineate. Replaced with a dark casing under a light core -- the standard
cartographic halo -- which raises the worst case across every palette stop
to **4.48**, because whichever stroke the background washes out, the other
still reads. Verified numerically across all 5 palettes before applying.

Also audited: every `useMemo` dependency array in the file is complete (no
stale-closure risks remain); no dead code left from earlier iterations of
these fixes (`toXY`, `fieldRange`, orphaned `.map-range` CSS all confirmed
absent); the one variable-shadowing case (`w`/`h` inside the raster
callback) confirmed inert by reading the full callback body.

## 12. The real cause of "big smooth blobs instead of fine detail"

The observation that the map looked like a few enormous smooth features,
where the reference imagery shows detailed fine-grained structure, turned
out to be correct and to have nothing to do with rendering. It was the
synthetic field itself.

**Measured, not guessed.** Computed the radially-averaged spatial power
spectrum of the anomaly field. It held ~14,000x less energy at fine scales
(wavenumber k=16) than at basin scale -- there was effectively no structure
below roughly 1000 km. Every previous version of this term was single-scale:
first a raw `sin(x)*cos(y)` product (periodic; the checkerboard bug), then
one Gaussian-smoothed noise field (aperiodic, but still only one scale).

**Why that is wrong.** A real ocean thermal field is turbulent and
multi-scale -- mesoscale eddies, filaments between them, and sharp fronts
coexist -- and its power spectrum follows roughly a k^-2 to k^-3 power law
instead of collapsing after the first couple of wavenumbers.

**Fix: spectral synthesis.** Build the field directly in Fourier space,
assigning each wavenumber an amplitude of k^(-beta/2) with a random phase,
then inverse-FFT. Validated the method first in isolation: requested slopes
of 2.0/2.5/3.0 came back measured as -1.99/-2.48/-2.97, within 0.03.
Synthesised in 3D over (time, lat, lon) with the time axis scaled so eddies
persist over days and *evolve* rather than being a frozen pattern pulsing in
amplitude.

**Tuned against the measurement, not by eye.** Two superposed fields (an
eddy field at beta=3.0 and a lower-amplitude filament field at beta=2.2)
put the quiet-day slope at **k^-2.33** -- inside the real k^-2..k^-3 band --
at ~+/-0.57 degC, a physically sensible mesoscale amplitude, with ~6x the
fine-scale energy of the old field. Shallower mixes were tried and rejected
on purpose: they carry more fine-scale energy (up to 30x) but drift outside
the realistic band (k^-1.75), trading physical plausibility for mere
noisiness. Still entirely synthetic, still fixed-seed reproducible -- the
claim is only that its *spatial statistics* are now plausible rather than
implausibly smooth.

**A consequence caught by checking rather than assuming.** The richer field
makes marching squares emit far more rings, and the minimum possible ring
is 5 vertices (a single cell). Measured: 90 of 140 rings came back under 8
vertices -- the majority were one- or two-cell loops that would have
rendered as confetti scattered across the map, not contour lines.
Suppressing a minimum feature size is standard cartographic practice;
added a 10-vertex floor. Regression-tested all three known cases
afterwards: the clean warm-blob case still keeps all 5 real contours (5/5),
the near-flat degenerate case still yields 0, and the real multi-scale
field keeps 35 meaningful rings while dropping 105 specks.

Also re-verified after the data change: all three diagnostics keep wide
spans (D26 52.6 m, TCHP 100.7 kJ/cm^2, MLD-T 40.3 m -- all far above
autoRange's 2% floor), no non-finite corruption, coverage stable, contour
compute 25 ms, generation 3.5 s.

**One self-inflicted bug caught during this edit:** the old single-scale
`ripple` assignment survived immediately below the new one and would have
silently overwritten the entire multi-scale field, reverting the change
while appearing to apply it. Found by reading the surrounding lines after
the edit rather than trusting it.

## Verified this pass

`tsc --noEmit` + `vite build`: clean (after `npm install`, which the earlier
delivered zip intentionally omits — see the project README). Backend suite:
109/109 non-torch, non-environment-broken tests pass
(`test_cli.py::test_doctor_runs` fails in this sandbox only, due to a torch
install left broken by an unrelated, unrecoverable disk-space error earlier
in this same sandbox session — not a code issue, and the same test V13/V14's
own notes already flagged as excluded for lacking a GPU-capable
environment). Real `.nc` file write confirmed end-to-end via the CLI
entrypoint, not just the in-memory mock used for the range checks above.

## 13. External audit response — two P1 findings confirmed and fixed

An independent audit of this archive reported findings across the codebase.
Several concerned code added in this session. Two were reproduced directly
and fixed; the rest are recorded below as accepted and outstanding.

**M01 (fixed).** The raster applies a gamma-1.6 contrast curve, but the
legend was a CSS `linear-gradient` over the raw palette stops -- evenly
spaced by *colour*, not by *value*. Measured the discrepancy: a value at
25% of the range renders at 16.5% of the ramp while its legend tick implies
25%, a misreading of up to 8.5 percentage points of the range (~1.7 degC on
a 10-30 degC scale). The contrast curve was added in this session; the
legend was not updated with it, so the legend actively misrepresented the
map. Fixed by generating the legend gradient from `fieldColor()` itself,
sampled at 33 evenly spaced *values* across the active range, so legend and
raster agree by construction regardless of what the transfer curve does.

**M06 (fixed).** The `-1e9` sentinel that marks missing cells for marching
squares makes every land/no-data cell an extreme low value, so the
algorithm finds a crossing all the way around any data hole and draws a
contour there -- at a temperature occurring nowhere near it. Reproduced the
audit's case exactly: a uniform 28 degC field with an interior 4x4 missing
hole produced a 17-vertex "26 degC isotherm" ringing the hole. The existing
boundary and minimum-size filters both passed it; the earlier hole test
passed only because that hole touched the grid edge, which the boundary
filter already caught. Fixed by rejecting rings whose vertices mostly abut
missing cells (a mask outline, not an isotherm). Verified across four
cases and five thresholds: the clean warm-blob case keeps all 5 real
contours, the interior-hole case now yields 0, the near-flat degenerate
case stays 0, and the real multi-scale field keeps 21 meaningful rings
(down from 35 -- the removed ones were coastline mask outlines).

**Accepted, not yet fixed.** Recorded here so they are not lost:
M03 (contour coordinates need a 0.5-cell shift for D3's grid-centre
convention), M04 (`bilinearUpsample` discards a valid sample when any of
the four neighbours is null, even at zero interpolation weight), M05
(upsample sample positions vs half-cell-expanded raster bounds), M07
(bloom/shimmer/fade alter the appearance of a quantitative layer), M09
("native grid cells" credit is now inaccurate given 9x interpolation),
M10 (opaque land polygons cover the photographic basemap this session
added). M04 and M05 are also from this session's changes. The audit's
backend findings (B01-B09) and interface findings (U01-U14) concern code
not modified in this session and are left for the owning authors.

## 14. Answering "why not fix them" — four more audit findings resolved

Pushed back on: three were fixable and empirically verifiable without a
screenshot, so there was no good reason to leave them as "accepted, not
fixed." One (M07) remains a deliberate design decision, explained below.

**M10 (fixed) — the opaque land layer was hiding this session's own basemap
photo on every landmass.** Checked the land gradient definition directly:
no alpha on any stop, no `fill-opacity` on the path. Fully opaque, on top
of the photo, for the entire session. Built an offline composite with the
real photo and real coastline data to confirm the fix visually (one of the
few things checkable without a browser): land is now a partial-opacity
(0.45) tint over the real photo rather than a solid cover, only when the
photo is present. India's terrain texture, Sri Lanka's shape and the
Himalayan foothills are now visible through it.

**M09 (fixed) — trivial, zero risk, no excuse.** Changed the "native grid
cells" credit line to "interpolated display," matching what the map
actually does at 9x upsampling.

**M03 (fixed) — resolved empirically, not by trusting either the audit or
my own assumption.** Built a smooth 1D ridge with a known analytical
threshold crossing, computed the reference linear interpolation by hand
from the exact same samples d3-contour sees, and compared: d3's reported
coordinate was exactly 0.5000 cells off, not approximately -- confirming
d3-contour places grid sample j at coordinate j+0.5. Applied a -0.5
correction in the lon/lat projection and re-measured: error dropped from
0.528 to 0.028 (the residual matches the expected small linear-vs-quadratic
interpolation error on the test's curved field, not a remaining bug).

**M04 (fixed) — reproduced the audit's exact case before touching
anything.** `[[20,null],[20,20]]` at factor=2 returned null at the
top-left output pixel, which sits exactly on the known sample of 20 -- the
old code rejected the whole pixel because ANY of the four neighbours was
null, even ones contributing zero interpolation weight. Rewrote to weight
each corner's nullness by its actual contribution: a corner with zero
weight can be null without affecting the result. Verified four cases:
the audit's exact repro now returns 20; a genuine interior interpolation
with all-finite corners still returns the correct blended value (25.00,
unchanged); a point where a real (nonzero-weight) corner is genuinely
missing still correctly returns null; and an exact-corner case where the
missing corner IS the corner being sampled (weight 1) still correctly
returns null. The fix adds correctness at zero-weight nulls without
weakening the missing-data guard anywhere else.

**M07 — still not fixed, and this one is a design decision, not
oversight.** Making the raw quantitative layer the default (bloom/shimmer/
fade optional) touches how every map looks and was added deliberately by
the project's other contributor for a specific aesthetic reason. Changing
a co-author's deliberate choice without discussion, at this hour, blind,
is a different kind of risk than the four fixed above -- those were
verifiable in isolation with no aesthetic judgment involved. Flagging for
a team decision rather than overriding it unilaterally.

Also re-verified M01/M06 (from the previous audit-response pass) still
hold after these additional edits: full suite re-run, all green.

## 15. "What about the other errors" — four more resolved, honest tally below

**M02 (fixed) — the scale bar was fake.** Confirmed by searching the file:
`scaleBarDeg`/`scaleBarX1`/`scaleBarX2` were computed and never referenced
anywhere else -- dead code sitting next to a completely separate, fully
hardcoded "1,000 km" SVG that never changed with zoom. Rewrote to derive
the bar from the actual current projection (zoom, map bounds, centre
latitude), picking the roundest real-world distance that fits a target
pixel width. Verified numerically: doubling zoom exactly halves the
computed km-per-pixel (ratio = 2.000, not approximately), and the label
updates correctly (500km -> 250km -> 100km -> 50km as zoom increases).

**M11 (fixed) — Cutaway's "Vertical exaggeration x40" was fake precision.**
Computed the true ratio from the same pixel constants the geometry itself
uses: (FLOOR_Y-SURF_Y)*last/(FX1-FX0). For a 1000km transect this gives
~476.6x, independently matching the audit's own worked calculation exactly.
The true ratio depends on transect length, which a fixed x40 could never
reflect. Now computed live from the actual drawn geometry.

**M12 (fixed) — `bathymetry[j] || 1000` treated valid 0m (land) as 1000m
(deep water)**, because 0 is falsy in JS -- demonstrated directly:
`0 || 1000` evaluates to `1000`. Replaced all three occurrences with one
shared `bathyDepth()` helper using an explicit `== null` check. Verified
four cases: land (0) now stays 0 (was 1000), a real seabed reading (500)
is unchanged, and missing data (null, or an out-of-range index) still
correctly defaults to 1000.

**M13 (fixed) — the frontend's D26 calculation didn't match the backend's,
in two ways, not just the one the audit named.** Reading the backend line
by line surfaced a second, larger discrepancy beyond the audit's `<26` vs
`<=26` boundary case: the backend treats an already-cold surface as
`d26 = 0.0` (a real, valid answer), while the frontend returned `null`
(no data) for the identical case. Rewrote to match the backend's exact
logic rather than just flip a comparison operator, then verified parity
directly: ran six identical test profiles through both the fixed frontend
port and the real Python `field_diagnostics()` function. All six matched
exactly, including the two cases that were previously wrong (exact-26.0
crossing: both now return 20.0; already-cold surface: both now return 0.0).

## Final honest tally

**Resolved and verified this session, in total: 11 of the audit's map/
interaction findings** (M01, M02, M03, M04, M06, M09, M10, M11, M12, M13,
plus the earlier session's own bugs). Each was reproduced or measured
before being called fixed, not assumed correct from the fix alone.

**Explicitly still open, and why:**
- **M05** (upsample sample alignment vs raster bounds) -- plausible, not
  yet isolated with the same rigor as the others; needs a dedicated
  analytical test like M03's before touching it, not a guess.
- **M07** -- a deliberate aesthetic choice by the project's other
  contributor, not an oversight; flagged for a team decision, not
  overridden unilaterally.
- **M08, M14** -- design/labelling clarity issues in code not modified
  this session (`App.tsx`'s Heat-events/Readiness sections, `api.py`).
- **B01-B09, U01-U14, and the "Risks requiring further validation" list**
  -- backend reliability/provenance logic and export/interface behaviour
  in `api.py`, `reliability.py`, `inference.py`, and the bulk of `App.tsx`.
  None of this was touched or claimed fixed. These are real, and several
  (B01, B04, B05 especially) look serious, but they're a different, larger
  body of work belonging to the code's original authors, not something to
  rush through blind at the tail of a single session.

## 16. Backend provenance pass + raster alignment

An important correction first: earlier in this session I stated that
`api.py` and `reliability.py` were untouched from the original V14. That
was wrong. Diffing against the original archive shows `api.py` (90 diff
lines), `reliability.py` (37) and `inference.py` (10) already carried
fixes -- including work matching audit findings B01, B02, B07 and B09 --
that I had not made and had not been tracking. Every finding below was
therefore re-tested against actual current behaviour rather than trusted
from the audit's list.

**Already fixed before this pass (verified by direct reproduction, not
assumed):** B01 (a constant 28 degC column with no 26 degC crossing now
correctly reports Abstain/`no_value` for TCHP/D26 rather than Supported),
B02 (reliability computed on the full grid, then values and reliability
cropped together), B07/B08 (shared edge/bathymetry rules via
`at_domain_edge`), B09 (`tile` validated as a positive integer, with a
note that the old path returned uninitialised `np.empty_like` memory).

**B03 (fixed).** `calibration_applies` was `bool(calibrated) and overall
!= ABSTAIN`, where `calibrated` came from `"lower" in ds and "upper" in
ds` -- true whenever the VARIABLES exist anywhere in the run, regardless
of whether this profile's actual bounds are finite at any depth. A
profile whose bounds are entirely NaN still reported
`calibration_applies: true`. `profile_state()` now takes the real
`lower`/`upper` arrays and counts depths where BOTH bounds are finite,
publishing `calibrated_depths` alongside the flag. Verified three cases:
all-NaN bounds -> false / 0 depths; genuinely calibrated at 5 of 7 depths
-> true / 5; and callers that pass no bound arrays fall back to the old
boolean so nothing regresses.

**B04 (fixed).** `obj.get("run_sha256") not in [cached_sha256(run),
dataset().attrs.get("base_run_sha256")]` accepted an artifact with NO
checksum whenever the active run also lacked `base_run_sha256`, because
`None in [hash, None]` is True -- a checksum-less artifact and a
checksum-less run "matched" each other. The Argo/RAMA path already
guarded against this; the cyclone endpoints never did. Now requires a
valid 64-char checksum on the artifact and builds the allowed set from
valid hashes only. Verified four cases: the exploit is rejected, a
missing checksum against a hashed run is rejected, a genuine match is
accepted, a wrong hash is rejected.

**B06 (partially fixed, scope stated).** The baseline endpoint only
excluded artifacts LABELLED synthetic; it never checked the artifact's
mode against the ACTIVE run's mode, so a synthetic run accepted an
artifact marked `research_blended`. Now rejects a genuine declared
mismatch. Notably, the first version of this fix was too strict and broke
the project's own `test_baselines_serves_evaluate_output` -- its fixture
declares no `source_mode` at all, and newly rejecting that would have
regressed legitimate older artifacts. Caught by the existing suite,
refined to only reject when BOTH sides declare a mode and they differ.
This still does not bind baselines to cube/grid/split identity; that
needs a schema addition to what `baseline-evaluate` writes and is NOT
done here.

**M05 (fixed).** The raster `<image>` box was sized to cell EDGES
(`lon[0]-dx/2` to `lon[N-1]+dx/2`) while `bilinearUpsample` places sample
0's value at the array's edge pixel -- a sample-CENTRE convention. A box
sized to edges but filled with a centre-sampled raster puts every value
about half a cell from where the coastline, contours and hover lookup
(all of which use sample centres via `X()`/`Y()`) say it belongs. Now
spans sample-centre to sample-centre. Verified numerically across every
sample in a test grid: hover lookup position, raster placement and
upsampler placement now agree exactly (offset 0.0000 at all samples),
where previously they differed by half a cell.

**Still open and explicitly not claimed:** B05 (looked correct on
inspection -- the 64-char guard is present -- but not deeply reproduced),
M07 (a co-author's deliberate aesthetic choice, flagged not overridden),
M08, M14, all of U01-U14, and the entire "Risks requiring further
validation" list. The real-data pilot and validation stages (audit
stages 3-4) need actual data and training runs, not code edits.
