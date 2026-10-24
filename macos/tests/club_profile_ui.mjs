// Execute the shipped Club renderer and currency helpers with saved data.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const start = source.indexOf('function QU(');
const end = source.indexOf('function eW(', start);
const currencyStart = source.indexOf('var Zu=`fmsh_currency`');
const currencyEnd = source.indexOf('var fd=', currencyStart);
assert(start >= 0 && end > start, 'shipped Club renderers exist');
assert(currencyStart >= 0 && currencyEnd > currencyStart, 'shipped currency helpers exist');
const jsx = (type, props) => typeof type === 'function' ? type(props) : ({type, props});
let profile;
let query;
let language = 'en';
const storage = new Map([
  ['fmsh_currency_list', JSON.stringify([{uid: 87, symbol: '€', rate: 1.5}])],
]);
const context = vm.createContext({
  z: {jsx, jsxs: jsx},
  R: () => ({t: key => key, i18n: {language}}),
  Gd: () => ({connected: false}),
  Zd: () => ({sid: 903, temporadas: [{id: 903, name: 'QA 903'}]}),
  B: options => { query = options; return {data: profile, isPending: false, isError: false}; },
  W: {clubProfile: sid => sid},
  localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
  ZU: 'club-logo', Zc: 'empty-icon', Gf: 'page', Kf: 'title',
  q: (...values) => values.filter(Boolean).join(' '),
});
vm.runInContext(source.slice(currencyStart, currencyEnd), context);
vm.runInContext(source.slice(start, end), context);
// The actual shared helper intentionally hides zero for other screens.
assert.equal(context.ld(0, 'en'), '—');
function nodes(tree) {
  if (tree == null || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
}
function row(key, value) {
  profile = {name_full: 'QA Club 88', club_uid: 88, [key]: value, training_facilities: 12};
  const tree = context.$U();
  const result = nodes(tree).find(node => node.type === 'div' &&
    node.props.children?.[0]?.props?.children === `club.${{
      balance: 'balance', transfer_budget: 'transferBudget',
      wage_budget: 'wageBudget', wage_total: 'wageTotal',
    }[key]}`);
  return result.props.children[1].props;
}
for (const key of ['balance', 'transfer_budget', 'wage_budget', 'wage_total']) {
  const suffix = key.startsWith('wage_') ? ' club.perWeek' : '';
  assert.equal(row(key, 0).children, `£ 0${suffix}`, `${key} preserves zero`);
  assert.equal(row(key, null).children, `—${suffix}`, `${key} preserves null`);
  assert.equal(row(key, undefined).children, `—${suffix}`, `${key} preserves missing value`);
}
assert(!row('balance', 0).className.includes('text-off'));
assert.equal(row('balance', -1200000).children, '− £ 1.2M');
assert(row('balance', -1200000).className.includes('text-off'));
assert.equal(row('transfer_budget', 2500000).children, '£ 2.5M');
context.od(87);
assert.equal(row('balance', 0).children, '€ 0');
assert.equal(row('transfer_budget', 10000).children, '€ 15K');
language = 'pt';
assert.match(row('balance', -1200000).children, /^− € 1,8\s?M$/u);
assert.equal(query.queryKey[1], 903);
assert.equal(query.queryFn(), 903);
profile = null;
const empty = context.$U();
assert(JSON.stringify(empty).includes('club.none'));
assert(!nodes(empty).some(node => node.type === 'h1'));
console.log('Club profile renderer regressions passed');
