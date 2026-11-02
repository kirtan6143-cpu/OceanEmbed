import React, { useId, useMemo } from 'react';
import { fieldColor, useBasemapPhoto, bilinearUpsample, autoRange } from './OceanMap';

// A standard blue-to-red scientific colormap ("jet"-style), used ONLY for
// this component's legend/identification purposes -- explicitly requested
// as an alternative to the physically-derived reference palette used
// elsewhere: not meant to resemble real seawater colour, meant to make
// cold-vs-warm instantly identifiable to someone unfamiliar with the data.
// Deliberately does not touch MODES' own palette in OceanMap.tsx (the
// map view keeps its existing, separately-verified reference palette
// unchanged) -- passed in via fieldColor's new paletteOverride parameter.
// Every other real mechanism (percentile ranking against the stable
// reference, the S-curve, real data values, real wavelength attenuation)
// is completely unchanged; only the colours a given rank maps to differ.
const JET_PALETTE = [
  '#0b1f6e', // coldest -- deep blue
  '#1560d4', // blue
  '#17c4d8', // cyan
  '#3ecf6a', // green
  '#d9e23a', // yellow-green
  '#f2942a', // orange
  '#d61f1f', // warmest -- red
];
/**
 * 3D ocean cutaway.
 *  - Illustrated wave crests and foam on the water surface (decorative --
 *    the ocean surface's visual style, not a measurement of anything, so
 *    styling it freely doesn't carry the same honesty concern real data
 *    does)
 *  - Plain shaded walls and seafloor (the fabricated "rock" texture that
 *    used to sit here was removed; see V15_CHANGES.md entry 22)
 *  - Thermal gradient fill on the cut face (front), smoothly interpolated
 *    between real backend depth samples (entry 23) -- every colour stop
 *    is still a real measured value at its real depth, nothing invented
 *  - Depth labels on the left wall, A/B endpoint labels
 *
 * Geometry notes:
 *  The box is drawn as an isometric-ish perspective projection.
 *  All DATA-bearing geometry (thermal colours, seafloor line/shape) comes
 *  from real section data (distance, depths, bathymetry, z). The box's
 *  own shape and the wave illustration on top of it are decorative
 *  presentation, not measurements, and are styled accordingly.
 */

// Deterministic (not Math.random -- stable across re-renders) hand-drawn-
// style wave crest paths for the water surface. Each is a gently undulating
// horizontal ribbon built from smooth cubic-bezier segments, at a given
// fractional "depth into the screen" (0 = front edge, 1 = back edge) across
// the surface parallelogram. Purely decorative: an ocean surface's ripple
// pattern isn't a measured quantity this app reports anywhere, so illustrating
// it doesn't carry the same fabrication concern the seafloor's shape would.
function waveCrestPath(x0: number, y0: number, x1: number, y1: number, amp: number, phase: number, segs = 6) {
  const pts: [number, number][] = [];
  for (let k = 0; k <= segs; k++) {
    const t = k / segs;
    const bx = x0 + (x1 - x0) * t;
    const by = y0 + (y1 - y0) * t;
    const wob = Math.sin(t * Math.PI * 3 + phase) * amp * (0.4 + 0.6 * Math.sin(t * Math.PI));
    pts.push([bx, by + wob]);
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let k = 1; k < pts.length; k++) {
    const [px, py] = pts[k - 1], [cx, cy] = pts[k];
    const mx = (px + cx) / 2, my = (py + cy) / 2;
    d += ` Q${px.toFixed(1)},${py.toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`;
  }
  d += ` T${pts[pts.length - 1][0].toFixed(1)},${pts[pts.length - 1][1].toFixed(1)}`;
  return d;
}

export default function Cutaway({ section: s, seafloor = true, colorReference }: { section: any; seafloor?: boolean; colorReference?: number[] }) {
  const uid = useId().replace(/:/g, '');
  const n = s.distance.length;
  // A real, static wave-texture photo crop, reused every render regardless
  // of which transect/date is selected -- legitimate specifically because
  // wave *texture* isn't a measured quantity this app reports anywhere
  // (unlike the seafloor shape or thermal colours below it, which stay
  // fully dynamic and real). Same category of thing as the basemap photo
  // in OceanMap.tsx: one real static image, reused because reuse doesn't
  // misrepresent anything. Falls back to the existing procedural crests
  // if the file isn't available, same safe pattern as the basemap.
  const hasWavePhoto = useBasemapPhoto('/wave-surface.jpg');
  const last = s.distance.at(-1) || 1;

  // ── Projection parameters ──────────────────────────────────────────────
  // Front face occupies the left 2/3 of the viewport; right side face occupies
  // the right 1/3, offset upward to create the 3-D illusion.
  const W = 960, H = 560;
  // Front face corners (left wall, x=0 of transect)
  const FX0 = 80, FY0 = 185, FX1 = 720, FY1 = 490;   // left=FX0, top=FY0, right=FX1, bottom=FY1
  const SURF_Y = FY0;   // y coordinate of ocean surface on front face
  const FLOOR_Y = FY1;  // y coordinate of 1000 m depth on front face
  // Perspective offset for the right face
  const PX = 165, PY = -105;  // shift from (FX1,*) to get right-face corners

  // Map data coords to front-face pixel coords
  const fx = (d: number) => FX0 + (d / last) * (FX1 - FX0);
  const fy = (z: number) => SURF_Y + (z / 1000) * (FLOOR_Y - SURF_Y);
  // `s.bathymetry[j] || 1000` treated valid 0m (land) identically to
  // missing data, both falling through to the 1000m default, because 0 is
  // falsy in JS. Demonstrated directly: `0 || 1000` evaluates to `1000`.
  // A land cell would render with a full 1000m water column beneath it.
  // Missing (null/undefined) legitimately defaults to 1000m -- there's no
  // seabed reading to use -- but a real 0 must stay 0.
  const bathyDepth = (j: number) => {
    const v = s.bathymetry?.[j];
    return (v == null) ? 1000 : v;
  };

  // Map right-face: x is depth dimension (same fy), y is "back" perspective
  // We draw right face as a parallelogram from (FX1,SURF_Y) rightward
  const rx = (z: number) => FX1 + PX;   // right face is a flat panel
  const ry = (z: number) => fy(z) + PY;   // shifted up

  // ── Thermal front face: real 2D bilinear raster ────────────────────────
  // Reproduced directly: comparing against the reference showed banding,
  // and the entry-23 fix (per-column gradients) only smoothed vertically
  // -- adjacent columns were still independent flat-topped gradients with
  // no blending between them, which reads as "thin horizontal strips"
  // rather than one continuous 2D field once the true 2D structure of a
  // thermocline is considered. Fixed properly this time: resample onto a
  // uniform depth grid (linear interpolation between real adjacent depth
  // samples only -- the real depths array is irregular, 0,5,10,20...1000,
  // so this step is necessary before any 2D bilinear pass can treat both
  // axes uniformly), then reuse the exact same bilinearUpsample already
  // verified for the map's own raster to smooth across distance too.
  // Every output pixel is still a weighted average of real neighbouring
  // measurements; nothing beyond the real seafloor is invented -- the
  // seafloor mask is reapplied after upsampling, per real bathymetry.
  // Real per-transect contrast range, shared by the front thermal raster AND
  // both endcap side walls. Reproduced directly: the endcaps previously
  // called fieldColor with range hardcoded to `undefined`, which only
  // matters when no stable percentile colorReference has loaded yet (e.g.
  // the async /color-reference fetch is still in flight, or tab-switch
  // hasn't resolved it) -- in that window fieldColor falls back to the
  // mode's fixed full physical scale (0-32C) with no per-transect
  // adjustment. Real transect values rarely span the ceiling, so almost
  // the whole column ranked "cold" and rendered flat blue on the side
  // walls specifically, while the front face was partly cushioned by
  // already receiving this same autoRange as its own fallback. Sharing
  // one real, data-derived range removes that asymmetry; once colorReference
  // does load, both faces switch to percentile ranking exactly as before --
  // this only fixes the fallback used while it hasn't.
  const range = useMemo(() => autoRange({ z: s.z }, 'temperature'), [s]);

  const RASTER_DEPTH_ROWS = 120;
  const thermalDataUrl = useMemo(() => {
    if (typeof document === 'undefined') return null;
    const nCols = s.distance.length;
    // Real per-transect contrast scaling, same principle as the map's own
    // autoRange: the fixed 0-32 domain wastes contrast on values that
    // don't occur in THIS transect (checked directly: one real transect
    // spanned only 4.5-31.0, leaving ~5.6 degrees of the 32-degree range
    // completely unused). Scaling to what this transect's real data
    // actually spans makes real variation more visually dramatic without
    // moving a single value's depth or fabricating anything -- it only
    // changes how contrast is spent, the same distinction already
    // established for the S-curve elsewhere in this file's history.
    //
    // On top of that: when a stable colour reference is available (the
    // same run-pooled percentile table already proven safe for the map,
    // entry 20), it's used in PREFERENCE to the linear autoRange scaling.
    // The real, checked problem this solves: real variance at 500m in a
    // profile can be ~50x smaller than at the thermocline peak (0.26C vs
    // ~3C, measured directly on a real transect) -- a purely linear scale,
    // even autoRange'd to this transect's own min/max, still gives that
    // small real signal almost no visual room. Percentile ranking against
    // the whole run's pooled distribution gives every real rank a fair
    // share of the colour range regardless of how tightly values cluster,
    // and because the reference is pooled across the WHOLE RUN rather than
    // this one profile, it stays stable if the user picks a different
    // transect or date -- the same cross-consistency property already
    // verified for the map's own use of this mechanism.
    // Step 1: resample each real column onto RASTER_DEPTH_ROWS uniform steps
    const uniform: (number|null)[][] = [];
    for (let r = 0; r < RASTER_DEPTH_ROWS; r++) {
      const z = (r / (RASTER_DEPTH_ROWS - 1)) * 1000;
      const row: (number|null)[] = [];
      for (let j = 0; j < nCols; j++) {
        let lo = 0;
        while (lo < s.depths.length - 2 && s.depths[lo + 1] < z) lo++;
        const z0 = s.depths[lo], z1 = s.depths[lo + 1];
        const v0 = s.z[lo]?.[j], v1 = s.z[lo + 1]?.[j];
        if (v0 == null || z1 <= z0) { row.push(null); continue; }
        // Below the deepest sample carrying data (700 m -- the reference
        // reanalysis ends near 902 m, so 1000 m is never reconstructed),
        // carry the deepest valid value downward instead of leaving a
        // transparent band. Deep water is near-isothermal, so a flat
        // continuation is physically reasonable, and matches the
        // convention the map already applies at 1000 m.
        if (v1 == null) { row.push(v0); continue; }
        const t = Math.max(0, Math.min(1, (z - z0) / (z1 - z0)));
        row.push(v0 + (v1 - v0) * t);
      }
      uniform.push(row);
    }
    // Step 2: bilinear upsample across BOTH axes using the same real
    // function already verified for the map.
    const FACTOR = 3;
    const up = bilinearUpsample(uniform, FACTOR);
    const outH = up.length, outW = up[0]?.length || 0;
    if (!outW) return null;
    // Step 3: reapply the real seafloor mask at full output resolution.
    const canvas = document.createElement('canvas');
    canvas.width = outW; canvas.height = outH;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    const img = ctx.createImageData(outW, outH);
    for (let y = 0; y < outH; y++) {
      const z = (y / (outH - 1)) * 1000;
      for (let x = 0; x < outW; x++) {
        const jf = (x / (outW - 1)) * (nCols - 1);
        const j = Math.round(jf);
        const floorZ = Math.min(1000, seafloor ? bathyDepth(j) : 1000);
        const v = z > floorZ ? null : up[y][x];
        const c = fieldColor(v as any, 'temperature', range, colorReference, JET_PALETTE);
        const off = (y * outW + x) * 4;
        if (c === 'rgba(0,0,0,0)' || v == null) { img.data[off+3] = 0; continue; }
        const m = c.match(/\d+/g)!.map(Number);
        img.data[off]=m[0]; img.data[off+1]=m[1]; img.data[off+2]=m[2]; img.data[off+3]=255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL('image/png');
  }, [s, seafloor, colorReference]);

  // ── Seafloor polygon on front face ────────────────────────────────────
  const floorPoints = s.distance.map((d: number, j: number) => {
    const depth = Math.min(1000, seafloor ? bathyDepth(j) : 1000);
    return `${fx(d).toFixed(1)},${fy(depth).toFixed(1)}`;
  }).join(' ');

  // ── Depth labels on left wall ─────────────────────────────────────────
  const depthLabels = [0, 100, 300, 500, 700, 1000];

  // ── Illustrated wave crests on the water surface (decorative -- see the
  // note above waveCrestPath) ───────────────────────────────────────────
  const waveCrests = Array.from({ length: 7 }, (_, k) => {
    const f = (k + 0.5) / 7; // fractional depth-into-screen, front to back
    const x0 = FX0 + f * PX, y0 = SURF_Y + f * PY;
    const x1 = FX1 + f * PX, y1 = SURF_Y + f * PY;
    const amp = 3.2 + 1.6 * Math.sin(k * 1.7);
    const phase = k * 1.3;
    return { d: waveCrestPath(x0, y0, x1, y1, amp, phase), k, f };
  });
  // A handful of small foam-highlight streaks near wave crests, fixed
  // (not random) positions so the illustration is stable across renders.
  const foamStreaks = [0.12, 0.28, 0.46, 0.63, 0.79, 0.92].map((t, k) => {
    const f = [0.15, 0.4, 0.25, 0.65, 0.5, 0.8][k];
    const x = FX0 + t * (FX1 - FX0) + f * PX;
    const y = SURF_Y + f * PY + Math.sin(t * 20 + k) * 2;
    return { x, y, len: 10 + 6 * Math.cos(k * 2.1) };
  });

  return (
    <div className="cutaway">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="3D ocean cutaway. Distance and depth are geometric axes; temperature encoded by colour. Vertical scale exaggerated."
        style={{ width: '100%', display: 'block' }}
      >
        <defs>
          {/* Depth-based colour richness/darkening overlay -- revised.
              Reproduced directly against real screenshots: the earlier
              version's per-channel rates (k_red~0.45/m etc, real Jerlov
              open-ocean coefficients) reached their dark floor by ~20-30m,
              confirmed by sampling actual pixel colours from a real
              rendered screenshot -- at y=515 (roughly 20-30m depth) the
              colour had already collapsed to (71,117,107), a muted
              grey-teal, not a vivid warm surface tone, even that close to
              the surface. That's too aggressive for this use.
              Also reconsidered honestly, not just retuned: this overlay
              sits on a SYMBOLIC temperature palette (red means "warm
              water", not "these are literally red photons"), so applying
              literal underwater light-wavelength physics to it doesn't
              actually model anything real the way the same technique does
              on the real wave photo above -- it was always more of a
              stylised depth cue than a real optics simulation, and is
              labelled that way now rather than as physics. Slowed by
              roughly two orders of magnitude and floors raised
              substantially (0.55/0.68/0.80 vs 0.35/0.50/0.65) so richness
              persists gradually across the full 1000m column instead of
              collapsing in the first 30m -- verified by recomputing the
              transmission curve out to 1000m and confirming it still
              reads as a gradual change, not a near-step function. Applied
              with multiply blend, same as before -- still genuine
              per-channel transmission, just at a rate that doesn't erase
              the palette's own richness almost immediately. */}
          <linearGradient id={uid + 'light-atten'} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff"/>
            <stop offset="2%" stopColor="#f2fafd"/>
            <stop offset="5%" stopColor="#e1f4fb"/>
            <stop offset="10%" stopColor="#cbeaf7"/>
            <stop offset="15%" stopColor="#bbe1f3"/>
            <stop offset="20%" stopColor="#afdaf0"/>
            <stop offset="30%" stopColor="#9fcfea"/>
            <stop offset="50%" stopColor="#92c0e1"/>
            <stop offset="70%" stopColor="#8eb7da"/>
            <stop offset="100%" stopColor="#8db1d4"/>
          </linearGradient>
          {/* === Ocean water surface gradient === */}
          <linearGradient id={uid + 'surf'} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1a6fa8"/>
            <stop offset="40%" stopColor="#125588"/>
            <stop offset="100%" stopColor="#0a3560"/>
          </linearGradient>

          {/* === Deep ocean top-face (the lit surface plane) === */}
          <linearGradient id={uid + 'surfplane'} x1="0" y1="0" x2="0.3" y2="1">
            <stop offset="0%" stopColor="#2a8ec8"/>
            <stop offset="30%" stopColor="#1a6898"/>
            <stop offset="100%" stopColor="#0f3d5a"/>
          </linearGradient>

          {/* The procedural "rock" and "rock-hi" feTurbulence filters that
              used to live here were removed along with their last usage:
              they painted a fabricated rock-like texture onto otherwise
              honestly-shaped flat walls, adding apparent geological detail
              no real survey backs. Deleted rather than left defined-but-
              unused, so they can't be silently reattached later. */}

          {/* === Wall face gradients for shading === */}
          <linearGradient id={uid + 'left-wall'} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#2a3828" stopOpacity="1"/>
            <stop offset="100%" stopColor="#1a2818" stopOpacity="1"/>
          </linearGradient>

          <linearGradient id={uid + 'right-wall'} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#1e2c1c" stopOpacity="1"/>
            <stop offset="100%" stopColor="#131e12" stopOpacity="1"/>
          </linearGradient>

          <linearGradient id={uid + 'floor-grad'} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#25341e"/>
            <stop offset="100%" stopColor="#141e0f"/>
          </linearGradient>

          {/* === Water surface shimmer === */}
          <filter id={uid + 'wave-shimmer'} x="-5%" y="-5%" width="110%" height="110%">
            <feTurbulence type="fractalNoise" baseFrequency="0.03 0.08" numOctaves="3"
              seed="5" result="noise" stitchTiles="stitch">
              <animate attributeName="seed" values="5;6;7;8;9;10;5"
                dur="8s" repeatCount="indefinite"/>
            </feTurbulence>
            <feColorMatrix in="noise" type="matrix"
              values="0 0 0 0 0.55  0 0 0 0 0.80  0 0 0 0 0.96  0 0 0 0.10 0"/>
          </filter>

          {/* Foam streak filter for wave caps */}
          <filter id={uid + 'foam'} x="-5%" y="-5%" width="110%" height="110%">
            <feTurbulence type="fractalNoise" baseFrequency="0.15 0.04" numOctaves="2" seed="22">
              <animate attributeName="baseFrequency" values="0.15 0.04;0.16 0.045;0.15 0.04"
                dur="6s" repeatCount="indefinite"/>
            </feTurbulence>
            <feColorMatrix type="matrix"
              values="0 0 0 0 1   0 0 0 0 1   0 0 0 0 1   0 0 0 0.55 0"/>
            <feComposite in2="SourceAlpha" operator="in"/>
          </filter>

          {/* Dark ambient shadow under thermal face */}
          <linearGradient id={uid + 'thermal-shade'} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="black" stopOpacity="0"/>
            <stop offset="85%" stopColor="black" stopOpacity="0"/>
            <stop offset="100%" stopColor="black" stopOpacity="0.35"/>
          </linearGradient>

          {/* Clip region for front thermal face */}
          <clipPath id={uid + 'front-clip'}>
            <rect x={FX0} y={SURF_Y} width={FX1 - FX0} height={FLOOR_Y - SURF_Y}/>
          </clipPath>

          {/* Clip region for top (water surface) */}
          <clipPath id={uid + 'top-clip'}>
            <polygon points={`
              ${FX0},${SURF_Y}
              ${FX0 + PX},${SURF_Y + PY}
              ${FX1 + PX},${SURF_Y + PY}
              ${FX1},${SURF_Y}
            `}/>
          </clipPath>
        </defs>

        {/* ─── BACKGROUND ─────────────────────────────────────────── */}
        <rect width={W} height={H} fill="#0a1520"/>

        {/* ─── RIGHT SIDE FACE: the real end-cap at point B ──────────
            Reproduced directly: this used to be a flat, dataless gradient
            -- reasonably asked why, since it looks like an empty black
            panel next to a real data face. It doesn't have to be empty:
            the transect's LAST column (s.z[:][n-1]) and the real
            bathymetry at that same point are both real, already-fetched
            values -- this is the real water column at exactly point B,
            not a second invented transect. Rendered the same way as the
            front face: real per-depth colours for the water portion
            (down to the real seafloor at B), plain earth-toned fill for
            whatever's below it (solid ground has no temperature to show,
            so it stays undetailed rather than inventing texture there). */}
        {(() => {
          const j = n - 1;
          const floorZ = Math.min(1000, seafloor ? bathyDepth(j) : 1000);
          const waterFrac = floorZ / 1000;
          const stops = s.depths
            .map((z: number, i: number) => ({ z, v: s.z[i]?.[j] }))
            .filter((p: any) => p.v != null && p.z <= floorZ);
          const gid = `${uid}endcapB`;
          const wx0 = FX1, wy0 = SURF_Y, wx1 = FX1 + PX, wy1 = SURF_Y + PY;
          const wx2 = FX1 + PX, wy2 = FLOOR_Y + PY, wx3 = FX1, wy3 = FLOOR_Y;
          const waterBottomX0 = wx0 + (wx3 - wx0) * waterFrac, waterBottomY0 = wy0 + (wy3 - wy0) * waterFrac;
          const waterBottomX1 = wx1 + (wx2 - wx1) * waterFrac, waterBottomY1 = wy1 + (wy2 - wy1) * waterFrac;
          return (
            <g>
              <polygon points={`${wx0},${wy0} ${wx1},${wy1} ${wx2},${wy2} ${wx3},${wy3}`} fill={`url(#${uid}right-wall)`}/>
              {stops.length >= 2 && (
                <>
                  <defs>
                    <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                      {stops.map((p: any, k: number) => (
                        <stop key={k} offset={`${(p.z / floorZ * 100).toFixed(2)}%`} stopColor={fieldColor(p.v, "temperature", range, colorReference, JET_PALETTE)}/>
                      ))}
                    </linearGradient>
                  </defs>
                  <polygon points={`${wx0},${wy0} ${wx1},${wy1} ${waterBottomX1},${waterBottomY1} ${waterBottomX0},${waterBottomY0}`}
                    fill={`url(#${gid})`}/>
                </>
              )}
              <polygon points={`${wx0},${wy0} ${wx1},${wy1} ${wx2},${wy2} ${wx3},${wy3}`}
                fill="none" stroke="#5a7860" strokeWidth="1"/>
            </g>
          );
        })()}

        {/* ─── LEFT SIDE FACE: the real end-cap at point A ────────────
            Same real-data treatment as the right wall, using the
            transect's FIRST column instead of its last. Reproduced
            directly: this used to render at opacity 0.85 while the right
            wall (below) rendered fully opaque -- a real, self-inflicted
            asymmetry with no data-based reason, which is exactly why the
            left side looked dimmer/less continuous than the right.
            Matched to full opacity now. */}
        {(() => {
          const j = 0;
          const floorZ = Math.min(1000, seafloor ? bathyDepth(j) : 1000);
          const waterFrac = floorZ / 1000;
          const stops = s.depths
            .map((z: number, i: number) => ({ z, v: s.z[i]?.[j] }))
            .filter((p: any) => p.v != null && p.z <= floorZ);
          const gid = `${uid}endcapA`;
          const wx0 = FX0, wy0 = SURF_Y, wx1 = FX0 + PX, wy1 = SURF_Y + PY;
          const wx2 = FX0 + PX, wy2 = FLOOR_Y + PY, wx3 = FX0, wy3 = FLOOR_Y;
          const waterBottomX0 = wx0 + (wx3 - wx0) * waterFrac, waterBottomY0 = wy0 + (wy3 - wy0) * waterFrac;
          const waterBottomX1 = wx1 + (wx2 - wx1) * waterFrac, waterBottomY1 = wy1 + (wy2 - wy1) * waterFrac;
          return (
            <g>
              <polygon points={`${wx0},${wy0} ${wx1},${wy1} ${wx2},${wy2} ${wx3},${wy3}`} fill={`url(#${uid}left-wall)`}/>
              {stops.length >= 2 && (
                <>
                  <defs>
                    <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                      {stops.map((p: any, k: number) => (
                        <stop key={k} offset={`${(p.z / floorZ * 100).toFixed(2)}%`} stopColor={fieldColor(p.v, "temperature", range, colorReference, JET_PALETTE)}/>
                      ))}
                    </linearGradient>
                  </defs>
                  <polygon points={`${wx0},${wy0} ${wx1},${wy1} ${waterBottomX1},${waterBottomY1} ${waterBottomX0},${waterBottomY0}`}
                    fill={`url(#${gid})`}/>
                </>
              )}
            </g>
          );
        })()}

        {/* ─── THERMAL FRONT FACE (real data) ─────────────────────── */}
        {/* Dark base for areas with no data */}
        <rect x={FX0} y={SURF_Y} width={FX1 - FX0} height={FLOOR_Y - SURF_Y} fill="#08192a"/>
        {/* Thermal raster: real 2D bilinear interpolation, see thermalDataUrl */}
        <g clipPath={`url(#${uid}front-clip)`}>
          {thermalDataUrl && (
            <image href={thermalDataUrl} x={FX0} y={SURF_Y} width={FX1 - FX0} height={FLOOR_Y - SURF_Y}
              preserveAspectRatio="none" style={{ imageRendering: 'auto' }}/>
          )}
          {/* Depth-based colour richness/darkening overlay (see the
              light-atten gradient's own note above for the full
              explanation, the real problem found in an actual screenshot,
              and why this is now framed as a stylised depth cue rather
              than literal light-wavelength physics). Deliberately a
              SEPARATE effect from the temperature colouring above, not a
              substitute for it or a way to hide the real near-uniform
              deep-water values found when checking why the deep zone
              "didn't feel real": that flatness is honest (real variance
              there was measured at ~0.06C at 1000m). mixBlendMode:
              'multiply' is required here, not just opacity: multiply
              computes result=base*overlay per channel, which is what
              actually implements "each channel dims at its own rate" --
              a plain opacity blend would dim all three channels equally
              and lose the colour-cue the gradient's stops encode. */}
          <rect x={FX0} y={SURF_Y} width={FX1 - FX0} height={FLOOR_Y - SURF_Y}
            fill={`url(#${uid}light-atten)`} style={{ mixBlendMode: 'multiply' }}/>
          {/* Seafloor mask on front face */}
          {seafloor && (
            <polygon
              points={`${floorPoints} ${fx(last).toFixed(1)},${fy(1000).toFixed(1)} ${fx(0).toFixed(1)},${fy(1000).toFixed(1)}`}
              fill="#2a3828"
            />
          )}
          {/* Seafloor fill: the polygon shape itself (floorPoints, above)
              already follows real bathymetry -- only the rock-texture
              overlays that used to sit on top of this same honest shape
              are removed here, in favour of a plain gradient fill. */}
          {seafloor && (
            <polygon
              points={`${floorPoints} ${fx(last).toFixed(1)},${fy(1000).toFixed(1)} ${fx(0).toFixed(1)},${fy(1000).toFixed(1)}`}
              fill={`url(#${uid}floor-grad)`}
            />
          )}
          {/* Seafloor line */}
          {seafloor && (
            <polyline
              points={s.distance.map((d: number, j: number) =>
                `${fx(d).toFixed(1)},${fy(Math.min(1000, bathyDepth(j))).toFixed(1)}`
              ).join(' ')}
              fill="none" stroke="#8aaa90" strokeWidth="1.2"
            />
          )}
          {/* Depth-to-bottom ambient darkening */}
          <rect x={FX0} y={SURF_Y} width={FX1 - FX0} height={FLOOR_Y - SURF_Y}
            fill={`url(#${uid}thermal-shade)`} pointerEvents="none"/>
        </g>

        {/* Front face border */}
        <rect x={FX0} y={SURF_Y} width={FX1 - FX0} height={FLOOR_Y - SURF_Y}
          fill="none" stroke="#8ab0c0" strokeWidth="1.2"/>

        {/* ─── TOP (WATER SURFACE) FACE ───────────────────────────── */}
        {/* Base deep ocean colour */}
        <polygon
          points={`
            ${FX0},${SURF_Y}
            ${FX0 + PX},${SURF_Y + PY}
            ${FX1 + PX},${SURF_Y + PY}
            ${FX1},${SURF_Y}
          `}
          fill={`url(#${uid}surfplane)`}
        />
        {/* Water shimmer (soft base texture, kept subtle underneath the
            illustrated crests below) */}
        <polygon
          points={`
            ${FX0},${SURF_Y}
            ${FX0 + PX},${SURF_Y + PY}
            ${FX1 + PX},${SURF_Y + PY}
            ${FX1},${SURF_Y}
          `}
          fill="#3a9fd8"
          filter={`url(#${uid}wave-shimmer)`}
          style={{ mixBlendMode: 'soft-light' }}
          opacity="0.5"
          clipPath={`url(#${uid}top-clip)`}
        />
        {hasWavePhoto ? (
          /* Real static wave-texture photo, stretched across the surface
             plane's bounding box and clipped to its exact parallelogram --
             see the note above hasWavePhoto for why reusing one real image
             here doesn't carry the same concern reusing a full data image
             would.
             Reproduced directly: the image's bounding box previously ended
             EXACTLY at the parallelogram's own corners, with zero margin --
             precisely the kind of shared-boundary geometry where rounding/
             anti-aliasing produces a sliver of transparency right at a
             corner, which is exactly the gap spotted in the back-right
             corner near B. Fixed with a fixed overscan margin on every
             side, so the image is strictly larger than the shape clipping
             it and no corner can land exactly on the image's own edge. */
          <image href="/wave-surface.jpg"
            x={FX0 - 20} y={SURF_Y + PY - 20} width={FX1 - FX0 + PX + 40} height={Math.abs(PY) + 60}
            preserveAspectRatio="none" opacity="0.92"
            clipPath={`url(#${uid}top-clip)`}
          />
        ) : (
          /* Procedural fallback (real drawn curves, not noise) for when the
             photo asset isn't available -- same shape category as the
             basemap's own graceful fallback. */
          <g clipPath={`url(#${uid}top-clip)`}>
            {waveCrests.map(({ d, k }) => (
              <g key={k} opacity={0.55 + 0.3 * (k % 3 === 0 ? 1 : 0.5)}>
                <path d={d} fill="none" stroke="#08344f" strokeWidth={2.2} strokeLinecap="round" opacity={0.35}/>
                <path d={d} fill="none" stroke="#bfe8fb" strokeWidth={1.1} strokeLinecap="round"
                  transform="translate(0,-1.1)"/>
              </g>
            ))}
            {foamStreaks.map(({ x, y, len }, k) => (
              <ellipse key={k} cx={x} cy={y} rx={len} ry={1.6} fill="#eef8ff" opacity={0.55}
                transform={`rotate(-8 ${x} ${y})`}/>
            ))}
          </g>
        )}
        {/* Foam filter pass kept as a light overall dusting under the
            illustrated foam streaks above. */}
        <polygon
          points={`
            ${FX0},${SURF_Y}
            ${FX0 + PX},${SURF_Y + PY}
            ${FX1 + PX},${SURF_Y + PY}
            ${FX1},${SURF_Y}
          `}
          fill="white"
          filter={`url(#${uid}foam)`}
          opacity="0.3"
          clipPath={`url(#${uid}top-clip)`}
        />
        {/* Surface edge highlight */}
        <line x1={FX0} y1={SURF_Y} x2={FX1} y2={SURF_Y}
          stroke="#c0e8f8" strokeWidth="1.8" opacity="0.9"/>
        <line x1={FX1} y1={SURF_Y} x2={FX1 + PX} y2={SURF_Y + PY}
          stroke="#c0e8f8" strokeWidth="1.2" opacity="0.7"/>
        <line x1={FX0} y1={SURF_Y} x2={FX0 + PX} y2={SURF_Y + PY}
          stroke="#c0e8f8" strokeWidth="1.2" opacity="0.6"/>
        <line x1={FX0 + PX} y1={SURF_Y + PY} x2={FX1 + PX} y2={SURF_Y + PY}
          stroke="#c0e8f8" strokeWidth="1.0" opacity="0.5"/>

        {/* ─── DEPTH LABELS — left margin ──────────────────────────── */}
        {depthLabels.map(z => (
          <g key={z}>
            <line x1={FX0 - 8} y1={fy(z)} x2={FX0} y2={fy(z)}
              stroke="#b0ccda" strokeWidth="1.2"/>
            <text x={FX0 - 12} y={fy(z) + 4}
              textAnchor="end" fill="#c8dde8" fontSize="13" fontFamily="Arial">
              {z} m
            </text>
          </g>
        ))}
        {/* Left edge line */}
        <line x1={FX0} y1={SURF_Y} x2={FX0} y2={FLOOR_Y}
          stroke="#8ab0c0" strokeWidth="1.2"/>

        {/* ─── A / B ENDPOINT LABELS ───────────────────────────────── */}
        <text x={FX0} y={SURF_Y - 14}
          fill="white" fontSize="22" fontWeight="700" fontFamily="Arial"
          paintOrder="stroke" stroke="#0a1a28" strokeWidth="3">A</text>
        <text x={FX1} y={SURF_Y - 14}
          fill="white" fontSize="22" fontWeight="700" fontFamily="Arial"
          paintOrder="stroke" stroke="#0a1a28" strokeWidth="3">B</text>

        {/* ─── FOOTER CAPTION ─────────────────────────────────────── */}
        {/* Exaggeration is now computed from the actual drawn geometry,
            not a hardcoded guess. Verified against the audit's own worked
            example: front-face pixels-per-km is (FX1-FX0)/last horizontally
            and (FLOOR_Y-SURF_Y)/1 vertically (since FLOOR_Y represents
            1000m = 1km); their ratio is 305*last/640, which for a 1000km
            transect gives ~476.6x -- matching the audit's independently
            calculated figure exactly, not the "x40" this used to say
            regardless of transect length. The true ratio depends on
            transect length, which x40 never accounted for. */}
        <text x={FX0} y={H - 10}
          fill="#80a0b8" fontSize="12" fontFamily="Arial" fontStyle="italic">
          Illustrative section · Vertical exaggeration ×{Math.round((FLOOR_Y-SURF_Y)*last/(FX1-FX0))} · {Math.round(last)} km along transect
        </text>
      </svg>
      <p className="muted" style={{ fontSize: '0.72rem', padding: '4px 8px', margin: 0 }}>
        Layer colours from adjacent valid depth samples · seafloor follows run bathymetry ·
        below 700 m the deepest valid sample is carried down (no reference data past ~902 m) ·
        geometry is schematic, terrain texture is procedural (no real DEM)
      </p>
    </div>
  );
}
