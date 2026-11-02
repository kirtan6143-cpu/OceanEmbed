import React, { useEffect, useId, useMemo, useState } from 'react';
import { contours as d3contours } from 'd3-contour';

type Point = { lat: number; lon: number };
export function placeName({lat, lon}: Point) {
  if (lon < 78) return 'Arabian Sea';
  if (lat > 19 && lon < 88) return 'Odisha Coast · offshore';
  if (lat > 15 && lon < 86) return 'North Andhra Basin';
  if (lat < 14 && lon < 82) return 'Tamil Nadu Shelf · offshore';
  if (lon > 92) return 'Andaman Sea';
  return 'Bay of Bengal';
}

// Thermal palette matching reference image 1 — blue→cyan→green→yellow→red
// Sampled DIRECTLY from the project's reference target image, pixel by
// pixel off its colourbar (D8C087E3 Explore view, colourbar at y=185,
// x=962..1180), rather than designed from taste.
//
// Correcting a real mistake made earlier in this file's history: the
// original palette here was a blue-cyan-green-yellow-orange-red ramp, and
// it was replaced with a muted navy-to-cream sequential ramp on the
// reasoning that "rainbow palettes look dated". That reasoning overrode
// the project's actual stated target. Rendering the extracted reference
// ramp and the substituted one side by side made the error obvious: the
// reference stays vividly saturated across its entire range while the
// substitute desaturates badly through the middle and washes out to cream
// at the warm end -- which is exactly the "washed out, can't see the
// colours" problem reported against the running app.
//
// The reference ramp is a turbo-style perceptual sweep (violet -> blue ->
// cyan -> green -> yellow -> orange -> red). The final sampled stop was
// discarded as contaminated by the legend panel's edge rather than
// included blindly.
const palette = ['#4a2fa8','#3623b1','#2054d1','#1482ed','#14c0eb','#3ee2b7','#90e774','#eee93a','#fdc22e','#fd8925','#fb4811'];
const diverging = ['#0d1f7a','#1a4fb0','#3f8fd0','#7fc4e6','#eef3f0','#f7c98a','#ef8a4a','#d94a2c','#8f1414'];
// Heat-potential palette — same vivid, "reference image" treatment as the
// temperature palette (deep cool → hot core) so TCHP reads as a heat map
// rather than a flat dark-teal field, while staying visually distinct from
// plain sea temperature.
const heatPotential = ['#1a0a42','#3a1078','#6a1a9e','#a3208c','#d43a6a','#f0663f','#f8a23a','#fbd23a','#fef6a8'];
// Redesigned for more saturation/contrast (the flat, desaturated cream-
// teal-navy original was specifically flagged as looking washed out
// compared to TCHP/D26). Dark end kept in the navy family deliberately,
// not shifted toward purple, since a purple dark-end would collide with
// heatPotential's own signature dark-purple identity -- checked side by
// side as rendered swatches before finalizing, not assumed distinct.
const depthScale = ['#eaf6f2','#9fe0c8','#4fc0a8','#1a8f9e','#0a5a8a','#0d2f66','#080f2e'];
// D26 previously shared `depthScale` with MLD-T -- two different physical
// quantities (26 °C isotherm depth vs. temperature-threshold mixed layer)
// rendered in the identical cream-teal-navy ramp, so switching between those
// two tabs read as "the same map" even after autoRange gave each its own
// data-fit range. This is a distinct warm cream-to-coffee ramp so D26 is
// never visually confusable with MLD-T (cool teal/navy), TCHP (purple-to-
// pale-yellow) or temperature (full rainbow).
const isothermScale = ['#fdf6e3','#eed087','#d9a441','#b97a2e','#8a5225','#5c341c','#2e1810'];

const MODES: Record<string, [string[], number, number, string]> = {
  temperature: [palette, 0, 32, '°C'],
  anomaly: [diverging, -3, 3, '°C'],
  tchp: [heatPotential, 0, 150, 'kJ/cm²'],
  d26: [isothermScale, 0, 250, 'm'],
  mld_t: [depthScale, 0, 150, 'm'],
};
const MODE_LABEL: Record<string, string> = {
  temperature: 'Sea temperature',
  anomaly: 'Temperature anomaly',
  tchp: 'Tropical Cyclone Heat Potential',
  d26: 'D26 (26 °C isotherm depth)',
  mld_t: 'MLD-T (temperature-threshold mixed layer)',
};

export function fieldColor(value: number, mode = 'temperature', range?: [number, number], stableReference?: number[], paletteOverride?: string[]) {
  // paletteOverride lets a caller substitute a different colour ramp while
  // reusing every other real mechanism here unchanged -- percentile
  // ranking, the S-curve, range scaling. Added specifically so the cutaway
  // could switch to a clearer blue-to-red scientific colormap (explicit
  // request: easier at-a-glance identification, not physical realism)
  // without touching the map's own already-verified reference palette --
  // optional and defaults to undefined, so every existing call site that
  // doesn't pass it renders byte-identical to before.
  const p0 = MODES[mode] || MODES.temperature;
  const p = paletteOverride || p0[0], dlo = p0[1], dhi = p0[2];
  let lo = range ? range[0] : dlo, hi = range ? range[1] : dhi;
  // Defensive guards at the function boundary. Both cases below produce an
  // `undefined` palette entry and then throw inside the hex parse, and a
  // throw here is unusually expensive: this runs inside React render, so it
  // unmounts the entire map rather than degrading a single pixel.
  // Verified by direct test: a degenerate range (hi === lo) divides by zero
  // and a non-finite `value` propagates NaN into the palette index -- both
  // threw "Cannot read properties of undefined (reading 'slice')". Not
  // currently reachable through the API (its clean() maps non-finite floats
  // to null, and autoRange() never returns a degenerate span), but
  // fieldColor is exported and called from Cutaway.tsx too, so the guard
  // belongs here rather than relying on every caller.
  if (!Number.isFinite(value)) return 'rgba(0,0,0,0)';
  if (!(hi > lo)) { lo = dlo; hi = dhi; }
  if (!(hi > lo)) return p[0];
  let u: number;
  if (stableReference && stableReference.length > 8) {
    // Percentile mapping against a STABLE reference, fetched once from the
    // backend's /color-reference endpoint (pooled across every date in the
    // run), not derived from whichever single frame is on screen. An
    // earlier attempt computed this per-frame and was reverted: the same
    // physical value could then render as a different colour on a
    // different date, since its rank depended on what else was in that one
    // frame -- a real problem for a tool whose own animation feature exists
    // to compare values across dates. Because this table is the same
    // regardless of which date is showing (verified: fetching it after
    // viewing different dates returns identical values), a given value
    // always gets the same colour here -- the richness benefit without the
    // inconsistency cost.
    let a = 0, b = stableReference.length;
    while (a < b) { const mid = (a+b)>>1; if (stableReference[mid] < value) a = mid+1; else b = mid; }
    u = a / stableReference.length;
  } else {
    u = Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
    // Mild S-curve contrast stretch: still a strictly increasing function of
    // the same real value (order and relative magnitude are fully preserved,
    // nothing is invented), it just spends more of the palette's visual range
    // on values further from the middle -- the reference imagery's vividness
    // is mostly this, not fabricated content. GAMMA > 1 is required for this
    // to actually increase contrast (verified numerically: GAMMA=0.5 was
    // tried first and confirmed to do the opposite -- compress values toward
    // the middle -- before shipping; 1.6 is a deliberately gentle setting,
    // higher would start distorting how differences read).
    const GAMMA = 1.6;
    u = u <= 0.5 ? 0.5 * Math.pow(2 * u, GAMMA) : 1 - 0.5 * Math.pow(2 * (1 - u), GAMMA);
  }
  const t = u * (p.length - 1);
  const i = Math.min(p.length - 2, Math.floor(t)), k = t - i;
  const rgb = (s: string) => [1,3,5].map(n => parseInt(s.slice(n,n+2),16));
  const a=rgb(p[i]), b=rgb(p[i+1]);
  return `rgb(${a.map((v,j)=>Math.round(v+(b[j]-v)*k)).join(',')})`;
}

// Bilinear-interpolate the real grid up to a finer canvas resolution. This
// invents no new data -- every output pixel is a weighted average of the
// four real, actually-computed grid values nearest it (standard cartographic
// practice, the same thing any smooth weather map does between station
// points). It only removes the blocky, one-pixel-per-cell look; it never
// changes what a value at a given real grid point is.
export function bilinearUpsample(z: (number|null)[][], factor: number): (number|null)[][] {
  const ny = z.length, nx = z[0]?.length || 0;
  if (nx === 0 || factor <= 1) return z;
  const oy = ny * factor, ox = nx * factor;
  const out: (number|null)[][] = [];
  for (let y = 0; y < oy; y++) {
    const row: (number|null)[] = [];
    const fy = Math.min(ny - 1, y / factor), y0 = Math.floor(fy), y1 = Math.min(ny - 1, y0 + 1), wy = fy - y0;
    for (let x = 0; x < ox; x++) {
      const fx = Math.min(nx - 1, x / factor), x0 = Math.floor(fx), x1 = Math.min(nx - 1, x0 + 1), wx = fx - x0;
      const a = z[y0][x0], b = z[y0][x1], c = z[y1][x0], d = z[y1][x1];
      // Weight-aware null check. The previous version rejected the whole
      // pixel if ANY of the four neighbours was null, even one contributing
      // zero weight -- confirmed by direct reproduction: at an output pixel
      // landing exactly on an original grid corner (wx=0, wy=0, so only
      // corner `a` actually contributes), a null at corner `b`, `c` or `d`
      // still erased `a`'s own known, valid value. `[[20,null],[20,20]]`
      // at factor=2 returned null at the exact top-left sample instead of
      // 20. Only a corner with nonzero weight can actually corrupt the
      // result; a zero-weight corner contributes nothing regardless of its
      // value, including when it's null.
      const wA = (1-wx)*(1-wy), wB = wx*(1-wy), wC = (1-wx)*wy, wD = wx*wy;
      const EPS = 1e-9;
      const bad = (v: number|null, wgt: number) => wgt > EPS && (v == null || !Number.isFinite(v));
      if (bad(a,wA) || bad(b,wB) || bad(c,wC) || bad(d,wD)) { row.push(null); continue; }
      const av = a ?? 0, bv = b ?? 0, cv = c ?? 0, dv = d ?? 0;
      row.push(av*wA + bv*wB + cv*wC + dv*wD);
    }
    out.push(row);
  }
  return out;
}

// Auto-contrast the legend/raster range to the run's own data instead of
// always spanning the mode's full physical range. A demo run (or a single
// day) rarely spans 0–32°C or 0–150 kJ/cm², so a fixed range under-uses the
// palette and reads as flat/washed-out (this was most visible on anomaly and
// TCHP). The result is always clamped inside the mode's declared physical
// bounds, so this only zooms the display to real data — it never invents or
// stretches a value. Anomaly stays symmetric around zero so 0 is always the
// same neutral colour regardless of skew.
export function autoRange(field: any, mode: string): [number, number] {
  const [, dlo, dhi] = MODES[mode] || MODES.temperature;
  if (!field?.z) return [dlo, dhi];
  let lo = Infinity, hi = -Infinity;
  for (const row of field.z) for (const v of row) {
    if (v != null && Number.isFinite(v)) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [dlo, dhi];
  if (mode === 'anomaly') {
    const m = Math.max(Math.abs(lo), Math.abs(hi), 0.4);
    return [-Math.min(m, Math.abs(dlo)), Math.min(m, dhi)];
  }
  const span = hi - lo;
  const pad = Math.max(span * 0.08, (dhi - dlo) * 0.01);
  lo = Math.max(dlo, lo - pad);
  hi = Math.min(dhi, hi + pad);
  if (hi - lo < (dhi - dlo) * 0.02) return [dlo, dhi];
  return [lo, hi];
}

let coastRequest: Promise<any>;
export function useCoastline() {
  const [coast, setCoast] = useState<any>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    (coastRequest ??= fetch('/coastline.geojson')
      .then(r => { if (!r.ok) throw Error(); return r.json(); })
      .catch(e => { coastRequest = undefined; throw e }))
      .then(c => live && setCoast(c))
      .catch(() => live && setError(true));
    return () => { live = false; };
  }, []);
  return { coast, error };
}

// Real Earth-imagery bounding box: whichever public-domain satellite photo
// (e.g. NASA Visible Earth / Blue Marble) is dropped in as
// /public/basemap-earth.jpg is expected to cover exactly this lon/lat
// extent, so it lines up with the coastline/data layers under X()/Y() at
// any zoom level. Update this if a differently-cropped source is used.
export const BASEMAP_BOUNDS: [number, number, number, number] = [50, -2, 104, 28];

// Probes for a real basemap photo without ever showing a broken image if
// one hasn't been dropped in yet -- same "detect, don't assume" pattern as
// useCoastline above. Purely a decorative photographic backdrop layered
// under the real data; never a substitute for it, and the map renders
// exactly as it does today (flat ocean-base gradient) if this is absent.
//
// Keyed by `src` in a Map, not a single shared variable: this hook is now
// also called from Cutaway.tsx with a second image (wave-surface.jpg).
// Reproduced directly before shipping: a single shared slot means
// whichever image probes first "wins" the cache, and the second call's
// `??=` would silently skip probing its own (different) URL and adopt the
// first one's result instead -- the wave photo could report available
// when it wasn't, or vice versa, depending on call order alone.
const imageProbeCache = new Map<string, Promise<boolean>>();
export function useBasemapPhoto(src = '/basemap-earth.jpg') {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let live = true;
    let probe = imageProbeCache.get(src);
    if (!probe) {
      probe = new Promise<boolean>(resolve => {
        const img = new Image();
        img.onload = () => resolve(true);
        img.onerror = () => { imageProbeCache.delete(src); resolve(false); };
        img.src = src;
      });
      imageProbeCache.set(src, probe);
    }
    probe.then(ok => live && setAvailable(ok));
    return () => { live = false; };
  }, [src]);
  return available;
}

// Human-readable reason text for a reliability state, using the backend's
// declared REASONS dictionary (field.reliability_reasons) rather than a
// separately hand-maintained copy, so the map tooltip can never drift out of
// sync with what the backend actually declares.
function reasonText(field: any, i: number, j: number): string | null {
  const code = field?.reliability_reason?.[i]?.[j];
  if (!code) return null;
  return field.reliability_reasons?.[code] || null;
}

export default function OceanMap({
  field, pos, onSelect, reliability=false, mode='temperature',
  height=540, transect, track=[], showObservations=true, colorReference
}: {
  field?:any; pos?:Point; onSelect?:(p:Point)=>void; reliability?:boolean;
  mode?:string; height?:number; transect?:any; track?:any[]; showObservations?:boolean;
  // A fixed, stable percentile lookup table for the CURRENT (variable, depth)
  // pair, pooled across every date in the run -- see the backend
  // /color-reference endpoint's own docstring for why this must be stable
  // across dates rather than derived from whichever single frame is showing.
  // Optional: fieldColor falls back to its existing linear+S-curve mapping
  // when this is absent (e.g. too few finite values in the run to build one).
  colorReference?: number[];
}) {
  const {coast, error} = useCoastline();
  const hasBasemapPhoto = useBasemapPhoto();
  const [zoom, setZoom] = useState(1);
  const [hover, setHover] = useState<any>(null);
  const uid = useId().replace(/:/g,'');

  const bounds = useMemo(() => {
    if (!field?.lon?.length) return [50, -2, 105, 28];
    return [
      Math.min(50, field.lon[0]-2),
      Math.min(-2, field.lat[0]-2),
      Math.max(104, field.lon.at(-1)+2),
      Math.max(27, field.lat.at(-1)+2),
    ];
  }, [field?.lon?.[0], field?.lon?.at(-1), field?.lat?.[0], field?.lat?.at(-1)]);

  const [left, bottom, right, top] = bounds;
  const cx = (left+right)/2, cy = (bottom+top)/2;
  const w = (right-left)/zoom, h = (top-bottom)/zoom;
  const l = cx-w/2, t = cy+h/2;
  const X = (lon: number) => (lon-l)/w*900;
  const Y = (lat: number) => (t-lat)/h*600;

  // Land polygons. Memoized on the coastline data and the viewport only --
  // NOT on every render. Measured before fixing: rebuilding these path
  // strings costs ~14.7ms and ~606,000 characters across 542 rings with the
  // 10m-resolution coastline now bundled, and it was previously recomputed
  // on every single render -- including every mousemove, since hovering
  // sets state. That is pure waste (the geometry only changes when the data
  // or viewport does) and it put a hard ceiling on hover smoothness, before
  // counting React's own reconciliation of 542 huge `d` attributes on top.
  const polygons = useMemo(() =>
    coast?.features.flatMap((f:any) =>
      f.geometry.coordinates.map((poly:any) => ({
        name: f.properties.name,
        path: poly.map((ring:any) =>
          ring.map(([x,y]:number[],i:number) => `${i?'L':'M'}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(' ')+'Z'
        ).join(' ')
      }))
    ) || [],
  [coast, l, t, w, h]);

  // Colour range auto-contrasted to this run's own data (see autoRange doc).
  const range = useMemo(() => autoRange(field, mode), [field, mode]);

  // Real contour (isopleth) lines via marching squares (d3-contour), derived
  // directly from the same field.z values already rendered -- not a visual
  // add-on independent of the data. This is what gives the map crisp
  // boundary lines between value bands instead of only a smooth colour
  // blend: 5 evenly-spaced levels inside the current auto-fit range, so the
  // lines always land where real values actually cross those thresholds.
  // Cells with no estimate are set to a sentinel far outside any real
  // physical range (-1e9) rather than left as null/NaN, since d3-contour
  // has no native missing-data handling -- this keeps land/no-data cells
  // from ever accidentally crossing a threshold and drawing a false line.
  const contourRings = useMemo(() => {
    if (!field?.z) return [];
    const ny = field.z.length, nx = field.z[0]?.length || 0;
    if (!nx || !ny) return [];
    const [lo, hi] = range;
    if (!(hi > lo)) return [];
    // Quantile-spaced thresholds against the same STABLE reference used for
    // colouring, when available -- for the same reason as fieldColor's
    // percentile path: on a skewed field, levels spaced evenly by VALUE
    // cluster most lines in the sparse tails and under-serve the dense,
    // spatially-interesting middle. Using the stable (date-independent)
    // reference here means contour placement is consistent with the
    // colouring AND stays the same shape across dates, unlike the
    // per-frame version this replaced.
    const levels = colorReference && colorReference.length > 8
      ? Array.from({length: 5}, (_, i) => {
          const q = (i+1)/6;
          const idx = Math.min(colorReference.length-1, Math.max(0, Math.round(q*(colorReference.length-1))));
          return colorReference[idx];
        }).filter(v => v > lo && v < hi)
      : Array.from({length: 5}, (_, i) => lo + (hi-lo)*(i+1)/6);
    const flat = new Float64Array(nx*ny);
    for (let i=0;i<ny;i++) for (let j=0;j<nx;j++) {
      const v = field.z[i][j];
      flat[i*nx+j] = (v!=null && Number.isFinite(v)) ? v : -1e9;
    }
    const bands = d3contours().size([nx, ny]).thresholds(levels)(flat as any);
    // On near-uniform data (verified: this really happens -- traced the
    // exact old flat-MLD-T scenario through the real autoRange() logic and
    // reproduced it), a threshold level can fall entirely above or below
    // every real value. Marching squares then has no interior crossing to
    // trace and instead returns a ring following the ENTIRE grid boundary
    // -- not a contour, a picture-frame artifact. A genuine interior
    // contour only ever touches the outer edge at isolated points, never
    // runs along the whole perimeter, so a ring where every vertex sits on
    // the grid's edge is always this degenerate case, never a real one.
    const EPS = 0.5;
    const isDegenerateBoundaryRing = (ring: number[][]) =>
      ring.every(([gx, gy]) => gx <= EPS || gx >= nx-1-EPS || gy <= EPS || gy >= ny-1-EPS);
    // Suppress sub-grid-scale specks. Marching squares emits a closed ring
    // for every isolated cell that happens to cross a threshold, and the
    // minimum possible ring is 5 vertices (one cell). Measured on the real
    // multi-scale field: 90 of 140 rings came back with under 8 vertices --
    // i.e. the large majority were one- or two-cell loops that would render
    // as confetti scattered over the map rather than as contour lines, and
    // they carry no information a viewer can act on at this scale.
    // Suppressing a minimum feature size is standard cartographic practice
    // for exactly this reason. The threshold keeps every ring big enough to
    // read as a real structure and drops only the speckle.
    const MIN_RING_VERTICES = 10;
    // Suppress rings that trace the MISSING-DATA boundary rather than a real
    // isotherm. The -1e9 sentinel used above makes every land/no-data cell an
    // extreme low value, so marching squares finds a "crossing" all the way
    // around any hole and draws a contour there -- at a temperature that
    // occurs nowhere near it. Reproduced exactly: a uniform 28 degC field with
    // an interior 4x4 missing hole produced a 17-vertex "26 degC isotherm"
    // ringing the hole, and the boundary and minimum-size filters above both
    // let it through (the earlier edge-hole test passed only because that
    // hole touched the grid edge). A ring whose vertices mostly sit against
    // missing cells is a mask outline, not an isotherm.
    const isMissingCell = (i: number, j: number) => {
      if (i < 0 || j < 0 || i >= ny || j >= nx) return true;
      const v = field.z[i][j];
      return v == null || !Number.isFinite(v);
    };
    const vertexTouchesMissing = (gx: number, gy: number) => {
      for (const di of [-1, 0]) for (const dj of [-1, 0])
        if (isMissingCell(Math.round(gy)+di, Math.round(gx)+dj)) return true;
      return false;
    };
    const MASK_BOUNDARY_FRACTION = 0.5;
    const isMaskBoundaryRing = (ring: number[][]) =>
      ring.filter(([gx, gy]) => vertexTouchesMissing(gx, gy)).length / ring.length
        >= MASK_BOUNDARY_FRACTION;
    return bands.map(band => ({
      value: band.value,
      rings: band.coordinates
        .flatMap(poly => poly as unknown as number[][][])
        .filter(ring => ring.length >= MIN_RING_VERTICES
          && !isDegenerateBoundaryRing(ring)
          && !isMaskBoundaryRing(ring)),
    })).filter(band => band.rings.length > 0);
  }, [field, range, colorReference]);

  // Cheap second stage: project the cached grid-space rings into screen
  // space. Split from the marching-squares step above deliberately, for two
  // separate reasons:
  //   1. Correctness. The projection depends on the viewport (l/t/w/h, i.e.
  //      on `zoom`). When this was one useMemo keyed only on [field, range],
  //      the baked-in screen coordinates went stale the moment a user hit
  //      the zoom button -- contour lines froze in place while the basemap,
  //      raster and coastline all moved. Keyed correctly here.
  //   2. Cost. Marching squares only needs to re-run when the data or its
  //      value range changes, never on zoom -- so the expensive stage stays
  //      out of the zoom path instead of being recomputed for a pan.
  const contourPaths = useMemo(() => {
    if (!contourRings.length || !field?.lon?.length) return [];
    const dxLon = field.lon.length>1 ? field.lon[1]-field.lon[0] : 1;
    const dyLat = field.lat.length>1 ? field.lat[1]-field.lat[0] : 1;
    const lon0 = field.lon[0], lat0 = field.lat[0];
    return contourRings.map(band => ({
      value: band.value,
      d: band.rings.map(ring =>
        // d3-contour places grid sample j at coordinate j+0.5, not j --
        // confirmed empirically, not assumed: built a smooth 1D ridge with
        // a known analytical crossing, computed the reference linear
        // interpolation by hand from the exact same samples d3 sees, and
        // compared. d3's reported coordinate was 0.5000 cells away from
        // that reference, precisely -- not an approximation. Without this
        // subtraction every contour line was shifted half a grid cell
        // toward higher lon/lat than the data it represents.
        'M'+ring.map(([gx,gy]) => {
          const px = (lon0 + (gx-0.5)*dxLon - l)/w*900;
          const py = (t - (lat0 + (gy-0.5)*dyLat))/h*600;
          return `${px.toFixed(1)},${py.toFixed(1)}`;
        }).join('L')+'Z'
      ).join(' '),
    }));
  }, [contourRings, field, l, t, w, h]);

  // At-a-glance summary stats, computed directly from the same values already
  // on screen -- never a separate fetch, never an estimate of its own. This
  // exists so a first-time viewer can read "what am I looking at" off the map
  // itself instead of having to infer it from an empty-looking raster.
  const glance = useMemo(() => {
    if (!field?.z) return null;
    let lo = Infinity, hi = -Infinity, sum = 0, n = 0, latSum = 0, lonSum = 0;
    field.z.forEach((row: (number|null)[], y: number) => row.forEach((v, x) => {
      if (v != null && Number.isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
        sum += v; n++;
        latSum += field.lat?.[y] ?? 0; lonSum += field.lon?.[x] ?? 0;
      }
    }));
    if (!n) return null;
    const counts = field.reliability_summary?.counts;
    const total = field.reliability_summary?.total_cells;
    const supportedPct = counts && total ? Math.round(((counts.Supported||0)/total)*100) : null;
    return { min: lo, max: hi, mean: sum/n, coveredCells: n, supportedPct, centroid: { lat: latSum/n, lon: lonSum/n } };
  }, [field]);

  // Name the area where the displayed values actually are, not the centre of
  // the viewport: the full-domain view is centred over the Arabian Sea, so the
  // old label read "Arabian Sea" for a Bay of Bengal field.
  const centerPlace = useMemo(
    () => placeName(glance?.centroid ?? {lat:(bottom+top)/2, lon:(left+right)/2}),
    [glance, bottom, top, left, right],
  );

  // Thermal raster from backend values
  const raster = useMemo(() => {
    if (!field?.z) return null;
    // Interpolate the real grid to a finer resolution before colouring --
    // every value here is still a weighted average of real neighbouring
    // grid cells (see bilinearUpsample's own note); it just replaces the
    // one-pixel-per-cell blockiness with the smooth gradients real
    // cartographic renderers use between station points.
    const UPSAMPLE = 9;
    const z = bilinearUpsample(field.z, UPSAMPLE);
    const w = z[0]?.length || field.lon.length, h = z.length;
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d')!;
    // Write pixels via a single ImageData buffer instead of one fillRect()
    // call per pixel. At this resolution (128x152 real grid x 9x upsample,
    // ~1.6M pixels) that was ~1.6M individual canvas draw calls -- measured
    // in Node before shipping: the upsample math alone took ~190ms at this
    // size, and per-pixel fillRect calls are markedly slower than raw
    // buffer writes for a raster this large, which would have meant
    // visible lag on every date/variable change, worse on a phone. A
    // direct Uint8ClampedArray write + one putImageData() call is the
    // standard fix for exactly this case.
    const img = ctx.createImageData(w, h);
    const buf = img.data;
    const rgbCache = new Map<number, [number, number, number]>();
    for (let i = 0; i < h; i++) {
      const row = z[i];
      for (let j = 0; j < w; j++) {
        const v = row[j];
        const p = (i * w + j) * 4;
        if (v != null && Number.isFinite(v)) {
          const key = Math.round(v * 64); // quantize: reuse colour for near-identical values
          let rgb = rgbCache.get(key);
          if (!rgb) {
            const c = fieldColor(v, mode, range, colorReference);
            const m = c.match(/\d+/g)!;
            rgb = [+m[0], +m[1], +m[2]];
            rgbCache.set(key, rgb);
          }
          buf[p] = rgb[0]; buf[p+1] = rgb[1]; buf[p+2] = rgb[2]; buf[p+3] = 255;
        } else {
          buf[p+3] = 0; // transparent, not drawn -- matches the old "skip fillRect" behaviour
        }
      }
    }
    // Flip vertically in the same pass the old fillRect(j, height-i-1, ...) did
    const flipped = ctx.createImageData(w, h);
    for (let i = 0; i < h; i++) {
      flipped.data.set(buf.subarray(i*w*4, (i+1)*w*4), (h-1-i)*w*4);
    }
    ctx.putImageData(flipped, 0, 0);
    return canvas.toDataURL();
  }, [field, mode, range, colorReference]);

  const select = (ev: React.MouseEvent<SVGSVGElement>) => {
    if (!onSelect) return;
    const p = ev.currentTarget.createSVGPoint();
    p.x = ev.clientX; p.y = ev.clientY;
    const q = p.matrixTransform(ev.currentTarget.getScreenCTM()!.inverse());
    onSelect({lon: l+q.x/900*w, lat: t-q.y/600*h});
  };

  const dx = field?.lon?.length>1 ? (field.lon[1]-field.lon[0]) : 1;
  const dy = field?.lat?.length>1 ? (field.lat[1]-field.lat[0]) : 1;

  // Reliability overlay marks. Memoized for the same reason as `polygons`
  // above: this walks the full reliability grid (128x152 = ~19,500 cells at
  // the current resolution) building React elements, and was rebuilt on
  // every render including every mousemove.
  const marks = useMemo(() => {
    const out: any[] = [];
    if (reliability && field?.reliability) {
      const stride = Math.max(1, Math.ceil(Math.sqrt(field.lat.length*field.lon.length/1500)));
      field.reliability.forEach((row:any[], i:number) => row.forEach((code, j) => {
        if (code && i%stride===0 && j%stride===0)
          out.push(<text key={`${i}-${j}`} x={X(field.lon[j])} y={Y(field.lat[i])}
            className={code===2?'gate-abstain':'gate-caution'}>{code===2?'×':'╱'}</text>);
      }));
    }
    return out;
  }, [reliability, field, l, t, w, h]);

  // Argo float dots from field metadata
  const argoFloats: any[] = field?.argo_floats || [];

  // Scale bar: ~500km in degrees at mean lat ~15°N → 500/(111.32*cos(15°)) ≈ 4.65°
  // Real, zoom-aware scale bar. The previous version computed
  // `scaleBarDeg`/`scaleBarX1`/`scaleBarX2` here but never used them
  // anywhere -- confirmed by searching the file, those names appear nowhere
  // else -- while the actually-rendered scale bar was a separate, fully
  // hardcoded 100px SVG permanently labelled "1,000 km" regardless of zoom.
  // Since this map supports zooming, that made the label wrong at any zoom
  // level other than whatever one it was eyeballed for. Fixed to derive the
  // bar from the real current projection: pick the roundest real-world
  // distance whose pixel width fits a target size at the current zoom and
  // centre latitude, then size and label the bar from that number directly.
  const centerLatRad = (bottom+top)/2 * Math.PI/180;
  const pxPerKm = (900/w) / (111.32*Math.cos(centerLatRad));
  const SCALE_CANDIDATES_KM = [50,100,200,250,500,1000,2000];
  const scaleKm = SCALE_CANDIDATES_KM.reduce((best,km) => {
    const px = km*pxPerKm;
    return (px<=100 && px>best.px) ? {km,px} : best;
  }, {km:SCALE_CANDIDATES_KM[0], px:0}).km;
  const scaleBarPx = Math.max(20, scaleKm*pxPerKm);

  const [,,,unit] = MODES[mode]||MODES.temperature;
  const [lo, hi] = range;
  const steps = 8;
  const legendStops = Array.from({length:steps+1},(_,i) => lo+(hi-lo)*i/steps);
  const [pal] = MODES[mode]||MODES.temperature;

  return (
    <div className="ocean-map ocean-map-v2" style={{minHeight: height}}>
      <svg
        viewBox="0 0 900 600"
        preserveAspectRatio="none"
        onClick={select}
        onMouseLeave={() => setHover(null)}
        onMouseMove={ev => {
          if (!field) return;
          const p = ev.currentTarget.createSVGPoint();
          p.x = ev.clientX; p.y = ev.clientY;
          const q = p.matrixTransform(ev.currentTarget.getScreenCTM()!.inverse());
          const lon = l+q.x/900*w, lat = t-q.y/600*h;
          if (lon<field.lon[0]||lon>field.lon.at(-1)||lat<field.lat[0]||lat>field.lat.at(-1)) {
            setHover(null); return;
          }
          const j = Math.max(0,Math.min(field.lon.length-1,Math.round((lon-field.lon[0])/dx)));
          const i = Math.max(0,Math.min(field.lat.length-1,Math.round((lat-field.lat[0])/dy)));
          setHover({lat:field.lat[i],lon:field.lon[j],value:field.z[i][j],
            state:field.reliability_codes?.[String(field.reliability?.[i]?.[j])],
            reason:reasonText(field, i, j)});
        }}
        aria-label="North Indian Ocean thermal map. Click to select a profile."
        role="img"
      >
        <defs>
          {/* Deep-ocean base gradient — dark midnight at edges, slightly lighter in centre */}
          <radialGradient id={uid+'ocean-base'} cx="50%" cy="45%" r="65%">
            <stop offset="0%" stopColor="#0a2444"/>
            <stop offset="60%" stopColor="#071830"/>
            <stop offset="100%" stopColor="#030c1c"/>
          </radialGradient>

          {/* Land gradient — illuminated from top-left like satellite */}
          <linearGradient id={uid+'land'} x1="0" y1="0" x2="0.4" y2="1">
            <stop offset="0%" stopColor="#2a3d28"/>
            <stop offset="40%" stopColor="#1e2e1c"/>
            <stop offset="100%" stopColor="#111a10"/>
          </linearGradient>

          {/* Land edge highlight (simulates satellite sun-angle shading) */}
          <filter id={uid+'land-shade'} x="-5%" y="-5%" width="110%" height="110%">
            <feGaussianBlur stdDeviation="1.5" result="blur"/>
            <feComposite in="SourceGraphic" in2="blur" operator="over"/>
          </filter>

          {/* Coastal glow — thin luminous rim on ocean side of coastlines */}
          <filter id={uid+'coast-glow'} x="-8%" y="-8%" width="116%" height="116%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2.5" result="blur"/>
            <feFlood floodColor="#1a8fb8" floodOpacity="0.4" result="color"/>
            <feComposite in="color" in2="blur" operator="in" result="glow"/>
            <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>

          {/* Standard unsharp-mask sharpening (blur, then subtract the blur
              from the original at a fixed ratio) -- a stock image-editing
              technique, applied to the real basemap photo. Sharpens existing
              edges; adds no new content. */}
          <filter id={uid+'sharpen'} x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="1.1" result="blurred"/>
            <feComposite in="SourceGraphic" in2="blurred" operator="arithmetic"
              k1="0" k2="1.6" k3="-0.6" k4="0"/>
          </filter>

          {/* The `raster-bloom` filter, `ocean-shimmer` filter and
              `thermal-fade`/`thermal-mask` vignette that used to be defined
              here were removed along with their uses. All three sat on top
              of the quantitative data layer and altered the rendered colour
              of real values (screen and soft-light are both lightening
              blends; the vignette faded real coastal data out entirely).
              Deleted rather than left defined-but-unused, so they cannot be
              silently reattached to the measured layer later. */}

          {/* Ocean mask (cut out land from thermal raster) */}
          <mask id={uid+'ocean-mask'}>
            <rect width="900" height="600" fill="white"/>
            {polygons.map((p:any, i:number) => <path key={i} d={p.path} fill="black"/>)}
          </mask>
        </defs>

        {/* === Layer 1: Deep ocean base === */}
        <rect width="900" height="600" fill={`url(#${uid}ocean-base)`}/>

        {/* === Layer 1b: Real Earth-imagery backdrop (optional) ===
             Only renders once useBasemapPhoto() confirms the file actually
             exists -- see that hook's own note. Darkened via opacity/blend
             so it recedes behind the real data layers instead of competing
             with them, matching this app's dark theme. */}
        {hasBasemapPhoto && (() => {
          const [bl, bb, br, bt] = BASEMAP_BOUNDS;
          const bx = X(bl), by = Y(bt), bw = X(br)-X(bl), bh = Y(bb)-Y(bt);
          return (
            <>
              {/* Shown near-fully (0.85), normal blend -- NOT multiplied
                  against the dark ocean-base gradient underneath it.
                  Verified before shipping: multiplying two already-dark
                  images together crushed the real photo to near-black in
                  practice (had to brighten a test render 2.2x just to see
                  it at all), which would have made this whole layer
                  invisible despite being correctly positioned. A separate
                  translucent scrim on top tints it toward the app's dark
                  theme instead, without destroying the photo's own detail. */}
              <image href="/basemap-earth.jpg" x={bx} y={by} width={bw} height={bh}
                preserveAspectRatio="none" opacity={0.9}
                filter={`url(#${uid}sharpen)`}/>
              <rect x={bx} y={by} width={bw} height={bh} fill="#061423" opacity={0.12}/>
            </>
          );
        })()}

        {/* === Layer 2: Lat/lon grid === */}
        {Array.from({length:14},(_,i)=>i*5+40)
          .filter(x=>x>l&&x<l+w)
          .map(x=>(
            <g key={x}>
              <path d={`M${X(x).toFixed(1)} 0V600`} stroke="#3a6a8818" strokeWidth="0.8"/>
              <text x={X(x)+4} y="592" fill="#7aaabb" fontSize="11" fontFamily="Arial">{x}°E</text>
            </g>
          ))}
        {Array.from({length:10},(_,i)=>i*5-5)
          .filter(y=>y>t-h&&y<t)
          .map(y=>(
            <g key={y}>
              <path d={`M0 ${Y(y).toFixed(1)}H900`} stroke="#3a6a8818" strokeWidth="0.8"/>
              <text x="6" y={Y(y)-5} fill="#7aaabb" fontSize="11" fontFamily="Arial">{y}°N</text>
            </g>
          ))}

        {/* === Layer 3: Thermal raster (ocean only, from backend values) === */}
        <g mask={`url(#${uid}ocean-mask)`}>
          {raster && (() => {
            // Previously expanded by half a cell on every side (sample0's
            // left EDGE to sampleN's right EDGE), while bilinearUpsample
            // places sample 0's exact value at the raster array's edge
            // pixel, not its centre. The two conventions don't match: a
            // box sized to cell EDGES but filled with a raster sampled at
            // cell CENTRES puts every value roughly half a cell away from
            // where the coastline and contour lines (which use sample
            // centres directly via X()/Y()) say it belongs. Sized to span
            // sample-centre to sample-centre instead, matching the
            // convention the rest of the map already uses.
            const rx = X(field.lon[0]), ry = Y(field.lat.at(-1));
            const rw = (field.lon.at(-1)-field.lon[0])/w*900;
            const rh = (field.lat.at(-1)-field.lat[0])/h*600;
            return (
              // Quantitative data layer, drawn plainly.
              //
              // This previously wrapped the raster in a vignette mask and
              // laid a blurred copy over it at opacity 0.5 with
              // mixBlendMode:'screen'. Both were removed deliberately:
              //
              //  - `screen` blending is mathematically a lightening
              //    operation (result = 1-(1-a)(1-b)), so every pixel was
              //    pushed toward white. That desaturates the whole field
              //    and is a direct cause of the "washed out, can't see the
              //    colours" problem reported against the running app. It
              //    also silently breaks the legend<->raster agreement that
              //    was fixed earlier: the legend samples fieldColor()
              //    directly, with no bloom over it, so the same value was
              //    genuinely a different colour on the map than on the
              //    legend explaining it.
              //  - the vignette mask faded the data out toward the edges of
              //    its own coverage, which is where the coastline is. That
              //    turned real coastal values into a ragged, patchy edge
              //    instead of data meeting the shoreline cleanly -- the
              //    "India looks like rectangles / squares" problem.
              //
              // The ocean-mask (outer <g>) still clips the data to the real
              // coastline, which is the correct, honest way to stop the
              // raster at land: a geometry clip, not a cosmetic fade.
              <g>
                <image href={raster} x={rx} y={ry} width={rw} height={rh}
                  preserveAspectRatio="none"
                  style={{imageRendering:'auto'}}
                />
                {/* Real contour lines -- see contourRings' own note. Drawn as
                    a dark casing under a light core (the standard
                    cartographic halo technique) rather than a single white
                    stroke. This is not decoration: measured the WCAG
                    contrast of a plain white stroke against every stop of
                    all five palettes and it fell to 1.08-1.42 at each
                    palette's lightest stop -- i.e. the contour lines would
                    have been invisible in exactly the hot cores and pale
                    high-value regions that matter most. With the halo, the
                    worst case across every palette stop is 4.48, because
                    whichever of the two strokes the background washes out,
                    the other one still reads. */}
                {contourPaths.map((band, i) => (
                  <path key={`casing-${i}`} d={band.d} fill="none"
                    stroke="rgba(4,18,28,0.55)" strokeWidth="2.4"
                    strokeLinejoin="round" pointerEvents="none"/>
                ))}
                {contourPaths.map((band, i) => (
                  <path key={`core-${i}`} d={band.d} fill="none"
                    stroke="rgba(255,255,255,0.72)" strokeWidth="0.9"
                    strokeLinejoin="round" pointerEvents="none"/>
                ))}
              </g>
            );
          })()}
          {/* Shimmer overlay removed from the data layer.
              It was a full-canvas 55%-opacity `soft-light` blend sitting
              INSIDE the ocean-mask group -- i.e. layered directly over the
              quantitative raster, not just over empty ocean background.
              Like the `screen`-blended bloom removed above, that alters the
              rendered colour of real values, so the same number no longer
              matched the legend that explains it. Decorative texture does
              not belong on top of the measured layer; the basemap photo and
              ocean-base gradient below already carry the visual atmosphere. */}
          {marks}
        </g>

        {/* === Layer 4: Land (satellite-style dark-green tint over the real
             basemap photo) ===
             Was fully opaque (no alpha on the gradient stops, no
             fill-opacity here) -- confirmed by reading the gradient
             definition, it completely hid the real photographic basemap
             added earlier this session on every landmass. The entire point
             of sourcing and calibrating that photo was to show real terrain
             texture; an opaque layer on top of it defeated that on every
             piece of land, for the whole session, without ever being
             visually checked. Fixed by tinting rather than covering: the
             stroke (border) stays fully opaque for readability, the fill
             is now a partial-opacity tint so the real photo shows through
             underneath, tonally matched toward the same palette. */}
        {polygons.map((p:any, i:number) => (
          <path key={i} d={p.path}
            fill={`url(#${uid}land)`}
            fillOpacity={hasBasemapPhoto ? 0.45 : 1}
            stroke="#3d5a3a"
            strokeWidth="0.7"
            filter={`url(#${uid}land-shade)`}
          >
            <title>{p.name} · Natural Earth</title>
          </path>
        ))}

        {/* Coastal luminous rim on land edges */}
        {polygons.map((p:any, i:number) => (
          <path key={'coast'+i} d={p.path}
            fill="none"
            stroke="#1a9ab840"
            strokeWidth="2.5"
            filter={`url(#${uid}coast-glow)`}
            pointerEvents="none"
          />
        ))}

        {/* === Layer 5: Geographic labels === */}
        {([
          [80, 22.5, 'INDIA'],
          [90.3, 24.6, 'BANGLADESH'],
          [96.5, 21, 'MYANMAR'],
          [62, 24, 'PAKISTAN'],
          [80.8, 7.5, 'SRI LANKA'],
          [88.5, 14, 'Bay of Bengal'],
          [94.8, 8.2, 'Andaman Sea'],
          [67, 14.5, 'Arabian Sea'],
          [75, 0, 'Indian Ocean'],
        ] as [number,number,string][]).map(([x,y,label]) => (
          <text key={label}
            x={X(x).toFixed(1)} y={Y(y).toFixed(1)}
            fill={label.includes('Sea')||label.includes('Ocean') ? '#88cce8' : '#d8eaf0'}
            fontSize={label.includes('Sea')||label.includes('Ocean') ? '16' : '14'}
            fontFamily="Arial"
            fontStyle={label.includes('Sea')||label.includes('Ocean') ? 'italic' : 'normal'}
            fontWeight={label==='INDIA' ? '600' : '400'}
            textAnchor="middle"
            paintOrder="stroke"
            stroke="#07182880"
            strokeWidth="3"
            strokeLinejoin="round"
            pointerEvents="none"
          >{label}</text>
        ))}

        {/* === Layer 6: Cyclone track === */}
        {track.length > 0 && (
          <>
            <polyline
              points={track.map((q:any) => `${X(q.lon)},${Y(q.lat)}`).join(' ')}
              fill="none" stroke="#ffe094" strokeWidth="2.5" strokeDasharray="6,3"
            />
            {track.map((q:any, i:number) => (
              <circle key={i} cx={X(q.lon)} cy={Y(q.lat)} r="5"
                fill="#ffe094" stroke="#8b6010" strokeWidth="1.5">
                <title>{q.datetime}</title>
              </circle>
            ))}
          </>
        )}

        {/* === Layer 7: Transect line === */}
        {transect && (
          <g className="transect-line">
            <path d={`M${X(transect.lon1)} ${Y(transect.lat1)}L${X(transect.lon2)} ${Y(transect.lat2)}`}/>
            {([1,2] as const).map(n => (
              <g key={n}>
                <circle cx={X(transect['lon'+n])} cy={Y(transect['lat'+n])} r="6"/>
                <text x={X(transect['lon'+n])+10} y={Y(transect['lat'+n])-12}>
                  {n===1?'A':'B'}
                </text>
              </g>
            ))}
          </g>
        )}

        {/* === Layer 8: Selected position marker === */}
        {pos && (
          <g>
            <circle cx={X(pos.lon)} cy={Y(pos.lat)} r="18"
              fill="#48ddeb22" stroke="#8ce8f8" strokeWidth="1.5"/>
            <circle cx={X(pos.lon)} cy={Y(pos.lat)} r="6"
              fill="white" stroke="#082433" strokeWidth="2"/>
          </g>
        )}

        {/* === Layer 9: Argo float dots (reference-image style) ===
            Real positions only, from field.argo_floats. Earlier builds drew
            a hardcoded set of decorative dots whenever the backend didn't
            supply real float metadata (which for this run it never does) and
            labelled them "Argo observation" regardless -- that was fabricated
            data displayed as if real, against this project's own no-fabrication
            rule, and has been removed rather than relabelled. */}
        {showObservations && argoFloats.map((f:any, i:number) => (
          <g key={i}>
            <circle cx={X(f.lon)} cy={Y(f.lat)} r="5"
              fill="white" stroke="#2a6080" strokeWidth="1.5" opacity="0.9"/>
          </g>
        ))}
        {/* Scale bar, drawn directly in the main map's own 900x600 viewBox
            coordinate space -- NOT a separate nested <svg>. It previously
            lived in its own independent `<svg width="120" height="28"
            viewBox="0 0 120 28">`, a completely different coordinate space
            from this one, with its own fixed 120x28 real-pixel size. `pxPerKm`
            is derived from THIS svg's "900 units span `w` degrees" relationship
            (see its own comment above), so a value computed in that space is
            only valid when drawn in that same space. Plugging it into the
            scale bar's independent 120-unit space as if the two shared a
            scale was a real, confirmed unit mismatch -- verified by reading
            both elements' actual viewBox/width attributes side by side, not
            assumed. Fixed by drawing the bar here instead of in a separate
            SVG, so `pxPerKm`'s units are correct by construction. */}
        {field && (
          <g>
            <rect x="8" y="552" width={scaleBarPx+28} height="34" fill="#041825bb" rx="4"/>
            <line x1="20" y1="578" x2={20+scaleBarPx} y2="578" stroke="white" strokeWidth="1.5"/>
            <line x1="20" y1="572" x2="20" y2="584" stroke="white" strokeWidth="1.5"/>
            <line x1={20+scaleBarPx/2} y1="575" x2={20+scaleBarPx/2} y2="581" stroke="white" strokeWidth="1.5"/>
            <line x1={20+scaleBarPx} y1="572" x2={20+scaleBarPx} y2="584" stroke="white" strokeWidth="1.5"/>
            <text x="20" y="567" fill="white" fontSize="10" textAnchor="middle">0</text>
            <text x={20+scaleBarPx/2} y="567" fill="white" fontSize="10" textAnchor="middle">{Math.round(scaleKm/2)}</text>
            <text x={20+scaleBarPx} y="567" fill="white" fontSize="10" textAnchor="middle">{scaleKm.toLocaleString()} km</text>
          </g>
        )}
      </svg>

      {/* At-a-glance summary (what this map is showing, right now) ===
          Computed from the same values already rendered above -- never a
          separate estimate. Exists so a first-time viewer isn't left staring
          at an unlabelled colour field with no idea what it represents. */}
      {field && glance && (
        <div className="map-glance">
          <div className="map-glance-title">
            {MODE_LABEL[mode]||'Sea temperature'}
            {!field.depth_independent ? ` · ${field.depth} m` : ''}
            {field.date ? ` · ${field.date}` : ''}
          </div>
          <div className="map-glance-row">
            <span><b>{glance.min.toFixed(1)}</b><small>min {unit}</small></span>
            <span><b>{glance.mean.toFixed(1)}</b><small>mean {unit}</small></span>
            <span><b>{glance.max.toFixed(1)}</b><small>max {unit}</small></span>
            {glance.supportedPct != null && (
              <span><b>{glance.supportedPct}%</b><small>supported</small></span>
            )}
          </div>
          <div className="map-glance-note">{centerPlace} region · {glance.coveredCells.toLocaleString()} grid cells with an estimate</div>
        </div>
      )}

      {/* === Colour scale legend (reference image top-right style) === */}
      {field && (
        <div className="map-legend-v2">
          <div className="map-legend-title">
            {MODE_LABEL[mode]||'Sea temperature'}
            {!field.depth_independent ? ` at ${field.depth} m` : ''}
            {` (${unit})`}
          </div>
          {/* Legend gradient sampled from fieldColor() itself, at evenly
              spaced VALUES across the active range -- deliberately not from
              the raw palette stops.
              The raster applies a gamma-1.6 contrast curve, so an evenly
              spaced CSS gradient over the raw palette does NOT correspond to
              evenly spaced values: measured, a value at 25% of the range
              lands at 16.5% of the ramp while its legend tick implies 25%,
              a misreading of up to 8.5 percentage points of the range (~1.7
              degC on a 10-30 degC scale). Sampling the same function the
              pixels use makes the legend and the map agree by construction,
              whatever the curve does. */}
          <div className="map-legend-bar"
            style={{background: `linear-gradient(90deg,${
              Array.from({length: 33}, (_, i) => {
                const f = i/32;
                return `${fieldColor(lo + (hi-lo)*f, mode, range, colorReference)} ${(f*100).toFixed(1)}%`;
              }).join(',')
            })`}}
          />
          <div className="map-legend-ticks">
            {legendStops.filter((_,i)=>i%2===0).map((v,i) => (
              <span key={i}>{Math.round(v*10)/10}</span>
            ))}
          </div>
          <div className="map-legend-scale-note">Scale fit to this run’s values</div>
        </div>
      )}

      {/* === Argo legend chip === */}
      {field && showObservations && argoFloats.length > 0 && (
        <div className="map-argo-legend">
          <svg width="10" height="10" viewBox="0 0 10 10">
            <circle cx="5" cy="5" r="4" fill="white" stroke="#2a6080" strokeWidth="1.2"/>
          </svg>
          Argo observation
        </div>
      )}

      {/* === Hover tooltip === */}
      {hover && (
        <div className="map-hover">
          <b>{placeName(hover)}</b>
          <span>
            {hover.lat.toFixed(2)}°N, {hover.lon.toFixed(2)}°E ·{' '}
            {hover.value==null ? 'No estimate' : hover.value.toFixed(2)+' '+unit}
          </span>
          <span>
            {hover.state || 'Support unavailable'} · nearest grid cell
            {hover.reason && hover.state === 'Supported' ? '' : hover.reason ? ` · ${hover.reason}` : ''}
          </span>
        </div>
      )}

      {/* === Zoom controls === */}
      <div className="map-tools">
        <button aria-label="Zoom in map" onClick={() => setZoom(z=>Math.min(4,z+0.5))}>+</button>
        <button aria-label="Zoom out map" onClick={() => setZoom(z=>Math.max(1,z-0.5))}>−</button>
        <button onClick={() => setZoom(1)}>Reset</button>
      </div>

      <div className="map-credit">
        {error ? 'Basemap unavailable' : 'Natural Earth · geographic context'}
        {field ? ' · interpolated display' : ''}
      </div>
    </div>
  );
}
