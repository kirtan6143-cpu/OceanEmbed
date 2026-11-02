import { test } from 'node:test';
import assert from 'node:assert/strict';
import { depthOptionLabel, displayFieldFor, isDisplayEstimate, estimateBadge } from '../src/depthSemantics.mjs';

const estimate = {
  depth: 1000, depth_status: 'display_estimate', estimate_source_depth: 700,
  reliability_applies_to_display: false, z: [[null]], estimated_z: [[6.1]],
  reliability: [[2]], reliability_summary: {counts: {Abstain: 1}, total_cells: 1}, reliability_reason: [['unsupported_depth']],
};
const native = {depth: 700, depth_status: 'native_reconstruction', z: [[6.1]], estimated_z: null, reliability: [[0]]};

test('1000 m option is labelled as an estimate from 700 m', () => {
  assert.equal(depthOptionLabel(1000), '1000 m — ESTIMATE (source 700 m)');
  assert.equal(depthOptionLabel(700), '700 m');
});
test('display estimate uses estimated values and removes every reliability state', () => {
  const d = displayFieldFor(estimate);
  assert.deepEqual(d.z, [[6.1]]);
  assert.equal(d.reliability, null);
  assert.equal(d.reliability_summary, null);
  assert.equal(d.reliability_reason, null);
  assert.equal(d.reliability_status, 'not_applicable');
  assert.equal(d.estimate_badge, 'ESTIMATE — source 700 m');
});
test('native depths are passed through unchanged', () => {
  assert.equal(displayFieldFor(native), native);
  assert.equal(isDisplayEstimate(native), false);
});
test('a 1000 m payload without the API status flag is not silently relabelled', () => {
  assert.equal(isDisplayEstimate({...estimate, depth_status: 'native_reconstruction'}), false);
  assert.equal(estimateBadge({}), 'ESTIMATE — source 700 m');
});
