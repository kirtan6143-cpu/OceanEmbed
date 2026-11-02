// V2 depth semantics shared by the UI and the node contract tests.
// 1000 m is NOT natively supported (source support ends ~902 m). The API marks
// it as `depth_status: "display_estimate"` carried from 700 m; the UI must say so
// everywhere the value is visible and must not show a reliability state for it.
export const ESTIMATE_DEPTH_M = 1000;
export const ESTIMATE_SOURCE_DEPTH_M = 700;

export function isDisplayEstimate(field) {
  return !!field && field.depth_status === 'display_estimate' && field.estimated_z != null;
}

export function estimateBadge(field) {
  const src = field?.estimate_source_depth ?? ESTIMATE_SOURCE_DEPTH_M;
  return `ESTIMATE — source ${src} m`;
}

export function depthOptionLabel(z) {
  return Number(z) === ESTIMATE_DEPTH_M
    ? `${z} m — ESTIMATE (source ${ESTIMATE_SOURCE_DEPTH_M} m)`
    : `${z} m`;
}

// Field actually handed to the map. For a display estimate the values come from
// estimated_z and every reliability array is removed, so no map colour, legend
// count or hover tooltip can present a Supported/Caution/Abstain state for it.
export function displayFieldFor(field) {
  if (!isDisplayEstimate(field)) return field;
  return {
    ...field,
    z: field.estimated_z,
    reliability: null,
    reliability_summary: null,
    reliability_reason: null,
    reliability_status: 'not_applicable',
    estimate_badge: estimateBadge(field),
  };
}
