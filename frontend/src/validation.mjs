// Shared chart adapter: both observation sources use the same numerical contract.
export function observationScatter(result) {
  const rows = (result.matchups || []).filter(r => Number.isFinite(r.observed) && Number.isFinite(r.predicted));
  return {x: rows.map(r => r.observed), y: rows.map(r => r.predicted), name: `${result.source || 'Observation'} matchups`};
}
