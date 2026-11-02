# V14 — high-quality map rendering, an at-a-glance summary, a regional grid map for Readiness, and one more fabrication bug closed

Scope: frontend map rendering/UX plus one small, additive backend field. No
science, reliability rules, or existing data contracts changed. Backend
suite: **110/110** passing (torch-dependent `test_model.py` still excluded —
unchanged limitation from V13, still no GPU-capable environment available
this pass).

## 1. Map visual quality — closer to the reference imagery

The V13 map already had the dark satellite basemap, coastal glow and
shimmer. Two things still separated it from the reference screenshots:

- **No bloom.** The thermal raster was a single sharp layer, so it read as a
  flat, hard-edged grid rather than a soft heat "blob." Fixed by rendering a
  second, blurred, lower-opacity copy of the exact same raster underneath the
  sharp one (`screen` blend). Same per-cell colours, same data — purely a
  rendering treatment, confirmed by pixel-comparing the two image layers.
- **A dead vignette mask.** `OceanMap.tsx` already defined a
  `thermal-mask` radial-gradient mask in V13 but never applied it anywhere —
  found while re-reading the component for this pass. Wired it onto the
  raster layer so the thermal field now fades into the deep-ocean base near
  its own coverage edges instead of stopping at a hard rectangle.

## 2. "What am I looking at?" — an at-a-glance summary on the map itself

The map had a colour legend but no plain-language summary, so a first-time
viewer saw a colour field with no immediate read on what it represented.
Added a small panel (top-left) computed directly from the same values
already rendered — never a separate estimate or fetch — showing: variable +
depth + date, min/mean/max in the field's own unit, and % of the grid
Supported (from the existing `reliability_summary`). A one-line footer names
the region (reusing the existing `placeName()` helper) and the count of
grid cells actually carrying an estimate.

## 3. A second fabricated-data bug, found and removed

`/field` has never returned real Argo float positions (confirmed by
reading `api.py` and `observations.py` — real float positions only exist
inside `/validation` matchup payloads, not per-map-cell). Despite that,
`OceanMap.tsx` drew **14 hardcoded fake dot positions** on every map
whenever no real `argo_floats` were present — which, given the above, was
always — and labelled them "Argo observation" regardless. That is
fabricated data presented as real, which is exactly the failure mode this
project's own reliability gate exists to prevent elsewhere. Removed the
fallback outright rather than relabelling it: the dot layer and its legend
chip now render only when the backend actually supplies real float
positions, and there is a new "Observations (Argo)" layer toggle (matching
the reference UI) that governs it.

## 4. Regional grid map added to the Readiness tab

The Readiness tab previously summarised heat potential only at the single
selected point (gauge, severity ladder, reliability donut). Added a full
regional map at the top of the tab, reusing the same map component already
used everywhere else in the app (so it gets the same bloom, glance panel,
reliability overlay and legend for free) — coloured by TCHP, the same
variable and colour bands as the gauge beneath it, so heat potential can be
compared point-to-point across the whole domain rather than read at one
location only. Clicking it updates the point-specific cards below it, the
same click-to-select interaction the Explore tab already uses.

## 5. Backend: per-cell reliability *reason*, not only *state*

`/field` already returned a Supported/Caution/Abstain grid. It now
additionally returns `reliability_reason` (the per-cell reason code) and
`reliability_reasons` (the backend's own declared code → text mapping,
`reliability.REASONS`), so a map tooltip can say *why* a cell reads
Caution or Abstain, not only which state it's in. Additive only — the
existing `reliability` array and its semantics are unchanged. Covered by a
new backend test, `test_field_carries_per_cell_reliability_reason`
(asserts the reason grid's shape matches the state grid, every reason code
is one of the declared ones, and every Supported cell's reason is exactly
`"ok"`). The map's hover tooltip now shows this text for any non-Supported
cell.

## 6. A mobile-layout bug introduced, then fixed, in the same pass

Adding the at-a-glance panel next to the existing colour legend (both
absolutely positioned in the map's top corners) collided on narrow phone
widths once both panels' text wrapped taller than the fixed corner
spacing assumed. Caught via a Playwright screenshot at 390px width before
shipping, not after. First attempted fix (switching both panels to normal
in-flow stacking below the map on narrow screens) turned out to have its
own bug: the map's SVG layer is itself `position:absolute`, so it painted
over the now-static panels and hid them entirely — also caught by
re-screenshotting rather than assumed to have worked. Fixed properly by
keeping both panels `position:absolute` (matching the SVG's own
stacking) and giving the legend a fixed offset that clears the glance
panel's shortened mobile content (its footnote hidden, and its stat row
trimmed to two figures instead of four) — verified against actual
measured element geometry, not just a screenshot, via a headless
DOM-inspection script before re-screenshotting to confirm.

## What was deliberately not built this pass

Scoped out to avoid fabricating anything the backend doesn't genuinely
have, consistent with the project's own no-fabrication rule:

- **Multilingual UI** — translation quality/accuracy risk for safety-critical
  wording (evacuation guidance) without a reviewed translation process.
- **SMS/USSD alerting** — needs real telecom-gateway infrastructure this
  prototype has no access to; the tab already links to NDMA's real SACHET
  alert portal instead of simulating one.
- **Population/vulnerability overlays** — would need a real demographic
  dataset; none is bundled, and fabricating density numbers would be a
  worse failure than not showing them.
- **A multi-storm historical track archive** — needs multiple real,
  reviewed best-track files; only one optional track is currently wired
  end-to-end (`OCEAN_CYCLONE`).
- **District/taluk boundary polygons** — needs real administrative geodata
  beyond the bundled Natural Earth coastline; out of scope for a heat-context
  prototype.
- **A decorative "3D" map toggle** — the reference screenshot's mockup has
  one; not added, because the project's own documented design philosophy
  explicitly rejects decorative 3D globes that add nothing quantitative.

## Verified this pass

Fresh `npm ci` already in place from V13; `tsc --noEmit` and `vite build`
both clean; 110/110 non-torch backend tests pass, including the new
reliability-reason test; Explore, Heat events and Readiness tabs
screenshotted against the dev build with zero console errors at both
desktop (1600px) and mobile (390px) widths; mobile overlay geometry
double-checked via `getBoundingClientRect()`, not screenshot inspection
alone, after the stacking bug above.
