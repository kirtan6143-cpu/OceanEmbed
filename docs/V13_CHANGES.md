# V13 — vivid heat visuals, a new Disaster Readiness tab, and three real bugs closed

Scope of this pass: frontend only. No backend science, reliability rules, or
data contracts were touched — `src/oceanembed/` and its 109 tests (everything
except the torch-dependent model tests, which need a GPU-capable environment
this pass did not have) are unchanged and still pass.

## 1. Anomaly and TCHP now read as heat maps, not flat fields

`OceanMap.tsx`'s temperature layer already matched the reference mockup
(dark basemap, jet-style colour ramp, Argo dots, coastal glow). Anomaly and
TCHP did not, and not for a styling reason: both used a **fixed** colour
range (anomaly ±3°C, TCHP 0–150 kJ/cm²) against a demo run whose real values
only span a fraction of that — anomaly mostly 0–2°C, TCHP mostly under 20
kJ/cm². Against the full fixed range that rendered as a near-flat, washed-out
field, confirmed by rendering both and comparing pixel colours before and
after.

Fixed with `autoRange()`: the legend and raster now scale to the *actual*
finite values in the run's own field, clamped inside each variable's declared
physical bounds, with anomaly kept symmetric around zero. This changes
nothing about the underlying numbers — it only stops a real but narrow-range
field from being displayed as flat. The legend now says "Scale fit to this
run's values" so this is disclosed, not silent. TCHP also got a new,
purpose-built palette (deep purple → hot yellow) instead of reusing a dim
dark-teal-to-orange ramp, so it reads as ocean *heat* potential rather than a
duller cousin of the temperature layer.

## 2. New tab: Disaster Readiness & Awareness

A sixth tab, built from data the app already computes — nothing new was
fabricated to fill it:

- **Ocean heat potential gauge** — the selected point's real TCHP
  (`/profile`'s `diagnostics.tchp_kj_cm2`) plotted on a semicircular gauge
  against commonly cited tropical-cyclone heat-potential research bands
  (Low/Moderate/High/Very high). Captioned as reference context, explicitly
  not a forecast — ocean heat alone does not predict intensification.
- **Marine heatwave severity** — the most recent qualifying event at the
  selected point (`/events`), shown on the same Moderate/Strong/Severe/Extreme
  ladder `science.heat_events()` already computes. A heat classification, not
  a storm-intensity class, and labelled as such.
- **Estimate reliability donut** — `/field`'s existing
  `reliability_summary` counts (Supported/Caution/Abstain), the same
  three-state gate used everywhere else in the app. Explicitly captioned
  "not a danger level," per `reliability.py`'s own docstring.
- **Cyclone thermal snapshot** — peak TCHP along the loaded best track, or
  the same honest empty state the Heat events tab already uses when no track
  is configured (never a fabricated storm).
- **Public awareness (before/during/after)** — general cyclone-preparedness
  guidance, and **Get official alerts** — links to IMD (mausam.imd.gov.in)
  and NDMA's SACHET alert portal, plus the national emergency number. The
  panel says outright that this prototype does not send alerts.

The whole tab opens with a red disclaimer banner: ocean thermal context only,
not a cyclone forecast, always follow IMD/NDMA/state authorities for real
warnings — consistent with the operational-notice footer the rest of the app
already carries.

## 3. Bugs found and fixed

- **Invalid SVG colour** — `Cutaway.tsx`'s unused water-gradient stop used a
  7-digit hex (`#1255880`), which is not a legal colour; browsers drop it
  silently. Currently dead code (nothing references that gradient), but
  fixed rather than left latent. `#125588`.
- **Invalid SVG attribute** — the new gauge's `<svg height="auto">` is not a
  valid SVG length and threw a live console error
  (`Expected length, "auto"`). Moved to `style={{height:'auto'}}`; confirmed
  zero console errors afterward across all six tabs.
- **Dead import** — `MapPin` was imported from `lucide-react` in `App.tsx`
  and never used anywhere. Removed.
- **Six tabs overflow the header on narrow screens** — nav had no overflow
  handling; a 6th tab pushed "Readiness" fully off-screen on mobile widths
  with no way to reach it. `nav` now scrolls horizontally
  (`overflow-x:auto`, hidden scrollbar) instead of clipping.

## Verified this pass

Real, not assumed: fresh `npm ci` + `tsc --noEmit` + `vite build` all clean;
109/109 non-torch backend tests pass; all 3 frontend contract tests pass; all
six tabs screenshotted against the production build with zero console
errors, at both desktop (1600px) and mobile (390px) widths.
