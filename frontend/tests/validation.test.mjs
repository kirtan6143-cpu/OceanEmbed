import { test } from 'node:test';
import assert from 'node:assert/strict';
import { observationScatter } from '../src/validation.mjs';
for (const source of ['Argo', 'RAMA']) {
  test(`${source} observed/predicted chart contract`, () => {
    assert.deepEqual(observationScatter({source, matchups:[{observed:27.2,predicted:27.4}]}),
      {x:[27.2],y:[27.4],name:`${source} matchups`});
  });
}
test('null and legacy observation fields cannot become misleading zero points', () => {
  assert.deepEqual(observationScatter({source:'RAMA',matchups:[{temperature:27,predicted:28},{observed:null,predicted:28}]}).x, []);
});
