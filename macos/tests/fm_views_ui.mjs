// Run the shipped FM review Apply adapter with real HTTP reviews and catalogs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  assert(from >= 0 && to > from, `shipped section exists: ${start}`);
  return source.slice(from, to);
}
const teamKeys = [...section('ph=[{k:`name`', ',mh=').matchAll(/\{k:`([^`]+)`/g)].map(match => match[1]);
const context = vm.createContext({});
vm.runInContext(section('var lV=', 'var fV='), context);
vm.runInContext(section('function NV(', 'function PV('), context);
const expected = [
  ['name', '_age', 'goals'],
  ['name', 'apps_total', 'minutes', 'assists', 'xg', 'xa'],
  ['name', 'gk_R'],
  ['name', 'age', 'goals'],
];
for (const [index, fixture] of cases.entries()) {
  const {review, catalog} = fixture;
  const team = review.destino === 'meutime';
  const config = context.uV(review, new Set(), team ? teamKeys : undefined);
  const available = team ? teamKeys : [...catalog.current.map(column => column.key), ...config.extras];
  const visible = context.NV(config.ordem, available.filter(key => config.colunas[key] !== false));
  assert.equal(JSON.stringify(visible), JSON.stringify(expected[index]), 'Apply shows only mapped columns in review order');
  for (const row of review.colunas.filter(row => row.chave && !team)) {
    const column = catalog.current.find(column => column.key === row.chave);
    if (column?.section === 'geral') {
      assert.deepEqual(row.coluna, column, 'review metadata matches displayed catalog');
      assert.equal(row.extra, false, 'current general columns need no extra lookup');
    }
  }
  if (index === 0) {
    const excluded = context.uV(review, new Set(['goals']));
    assert.equal(excluded.colunas.goals, false, 'unchecking a review row excludes it');
    assert.deepEqual(Array.from(context.NV(excluded.ordem, available.filter(key => excluded.colunas[key] !== false))), ['name', '_age']);
  }
  if (index === 2) assert.deepEqual(Array.from(config.extras), ['gk_R'], 'positional extra remains loadable');
  assert.equal(Boolean(config.semAbas), !team, 'Base-only view state does not affect My Team');
}
console.log(`FM view Apply regressions passed: ${cases.length} cases`);
