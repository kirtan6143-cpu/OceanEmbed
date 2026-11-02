import React, { useMemo } from 'react';
import { useCoastline } from './OceanMap';

type T = { lat1: number; lon1: number; lat2: number; lon2: number };

/** Compact, non-interactive locator: where is this transect, in the wider
 * basin? Uses the same offline Natural Earth data OceanMap draws from --
 * no separate asset, no network tile call, no fabricated terrain. This is
 * a locator, not a navigation tool: it exists to answer "roughly where is
 * A-to-B", not to support panning/zooming/clicking. */
export default function Locator({ transect }: { transect: T }) {
  const { coast, error } = useCoastline();
  // Fixed regional bounds (North Indian Ocean) rather than fitting to the
  // transect: a locator's value is showing the transect IN CONTEXT of the
  // basin, not zoomed to fill the frame.
  const [left, bottom, right, top] = [66, 4, 100, 26];
  const w = right - left, h = top - bottom;
  const X = (lon: number) => ((lon - left) / w) * 260;
  const Y = (lat: number) => ((top - lat) / h) * 150;
  const polygons = useMemo(
    () =>
      coast?.features.flatMap((f: any) =>
        f.geometry.coordinates.map((poly: any) => ({
          name: f.properties.name,
          path:
            poly
              .map(
                (ring: any) =>
                  ring
                    .map(([x, y]: number[], i: number) => `${i ? 'L' : 'M'}${X(x)},${Y(y)}`)
                    .join(' ') + 'Z',
              )
              .join(' '),
        })),
      ) || [],
    [coast],
  );
  const inBounds = (lat: number, lon: number) => lat >= bottom && lat <= top && lon >= left && lon <= right;
  const clampedLine = inBounds(transect.lat1, transect.lon1) && inBounds(transect.lat2, transect.lon2);
  return (
    <div className="locator-inset">
      <svg viewBox="0 0 260 150" role="img" aria-label="Locator: transect position within the North Indian Ocean">
        <rect width="260" height="150" fill="#0c2338" />
        {polygons.map((p: any, i: number) => (
          <path key={i} d={p.path} className="locator-land" />
        ))}
        <text x="118" y="55" className="locator-label">INDIA</text>
        <text x="176" y="88" className="locator-label locator-label-sea">Bay of Bengal</text>
        {clampedLine ? (
          <>
            <line
              x1={X(transect.lon1)} y1={Y(transect.lat1)}
              x2={X(transect.lon2)} y2={Y(transect.lat2)}
              className="locator-transect"
            />
            <circle cx={X(transect.lon1)} cy={Y(transect.lat1)} r="3.5" className="locator-point" />
            <circle cx={X(transect.lon2)} cy={Y(transect.lat2)} r="3.5" className="locator-point" />
            <text x={X(transect.lon1) - 8} y={Y(transect.lat1) - 6} className="locator-endpoint">A</text>
            <text x={X(transect.lon2) + 6} y={Y(transect.lat2) - 6} className="locator-endpoint">B</text>
          </>
        ) : (
          <text x="130" y="140" textAnchor="middle" className="locator-label">
            Transect outside this locator's regional frame
          </text>
        )}
      </svg>
      <span className="locator-credit">{error ? 'Basemap unavailable' : 'Natural Earth · orientation only'}</span>
    </div>
  );
}
