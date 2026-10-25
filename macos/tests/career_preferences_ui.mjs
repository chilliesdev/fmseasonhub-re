// Exercise shipped career API responses and the rendered formatting previews.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  assert(from >= 0 && to > from, `shipped section exists: ${start}`);
  return source.slice(from, to);
}
const storage = new Map([
  ['fmsh_currency', '3'], ['fmsh_wage_period', 'month'], ['fmsh_carreira', 'beta'],
  ['fmsh_currency_list', JSON.stringify([
    {uid: 2, name: 'Pound', symbol: '£', rate: 0.85},
    {uid: 3, name: 'Dollar', symbol: '$', rate: 1.08},
  ])],
]);
const alpha = {ativa: 'alpha', prefs: {moeda: 2, periodo_salario: 'year'}};
const beta = {ativa: 'beta', prefs: {moeda: 3, periodo_salario: 'month'}};
let response = alpha;
let rejectResponse = false;
const calls = [];
const jsx = (type, props) => typeof type === 'function' ? type(props) : ({type, props});
const context = vm.createContext({
  z: {jsx, jsxs: jsx},
  R: () => ({t: key => key, i18n: {language: 'en'}}),
  q: (...values) => values.filter(Boolean).join(' '),
  localStorage: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  },
  H: async path => {
    calls.push([path]);
    if (rejectResponse) throw new Error('request failed');
    return response;
  },
  U: async (path, body) => {
    calls.push([path, body]);
    if (rejectResponse) throw new Error('request failed');
    return response;
  },
});
vm.runInContext('var ' + section('Wu=`fmsh_wage_period`', 'var fd='), context);
vm.runInContext(section('var Sd=`fmsh_carreira`', 'var Dd='), context);
vm.runInContext(section('var dI=24e3', 'var _I='), context);
// Run the actual API methods used by the query and both career-switch controls.
context.W = vm.runInContext('({' + section('carreiras:()=>', ',moverTemporada:') + '})', context);
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree !== 'object') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  return text(tree.props?.children);
}
function checkPreviews(career, symbol, wage, weekly) {
  assert.equal(context.Ju(), career.prefs.periodo_salario);
  assert.equal(context.id().uid, career.prefs.moeda);
  const currency = context.id();
  assert(text(context.gI({moeda: currency})).includes(wage), 'currency WAGE uses selected career period');
  const preview = text(context.pI({periodo: career.prefs.periodo_salario}));
  assert(preview.includes(weekly), 'wage examples use selected career currency');
  assert(!preview.includes(symbol === '£' ? '$' : '£'), 'previous career currency is absent');
}
// Query response must synchronize before any rendering, without a React effect.
assert.equal(await context.W.carreiras(), alpha);
checkPreviews(alpha, '£', '£ 1.1M', '£ 20.4K');
// Preserve career-change detection for the provider's existing cache invalidation.
assert.equal(context.Td(alpha.ativa, alpha.prefs), true);
assert.equal(context.Td(alpha.ativa, alpha.prefs), false);
for (const career of [beta, alpha, beta]) {
  response = career;
  assert.equal(await context.W.ativarCarreira(career.ativa), career);
  checkPreviews(career, career === alpha ? '£' : '$',
    career === alpha ? '£ 1.1M' : '$ 112.3K',
    career === alpha ? '£ 20.4K' : '$ 25.9K');
  assert.equal(context.Td(career.ativa, career.prefs), true);
}
assert.equal(calls[0][0], '/api/carreiras');
assert.equal(calls[1][0], '/api/carreiras/ativa');
assert.equal(calls[1][1].id, 'beta');
// A failed response must leave the previously rendered career unchanged.
rejectResponse = true;
await assert.rejects(context.W.ativarCarreira('alpha'), /request failed/);
checkPreviews(beta, '$', '$ 112.3K', '$ 25.9K');
console.log('Career preference renderer regressions passed');
