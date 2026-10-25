// Execute shipped browse assembly, Favorites date rendering, and mutation hooks.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const fixtures = JSON.parse(fs.readFileSync(0, 'utf8'));
function section(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert(from >= 0 && to > from, start);
  return source.slice(from, to);
}
function component(name) {
  const start = source.indexOf(`function ${name}(`);
  for (let end = source.indexOf('function ', start + 10); end >= 0; end = source.indexOf('function ', end + 9)) {
    const candidate = source.slice(start, end);
    try { new vm.Script(candidate); return candidate; } catch {}
  }
  throw Error(`Missing component: ${name}`);
}
const jsx = (type, props) => typeof type === 'function' ? type(props ?? {}) : ({type, props});
let cache;
let response;
let onlyCareer = false;
let browsing;
let query;
const urls = [];
const context = vm.createContext({
  URLSearchParams,
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  _: {useState: value => [typeof value === 'function' ? value() : value, () => {}],
    useEffect() {}, useMemo: fn => fn(), useCallback: fn => fn},
  R: () => ({t: (key, values) => key === 'fav.subtitulo' ? `Created ${values.data}` : key}), rt: () => 'en',
  Ga: () => ({setQueryData: (_key, value) => { cache = value; }}),
  _d: () => ({data: cache}), fd: ['favoritos-listas'],
  eH: () => null, $V: 'test', GV: () => null, tH() {}, QV: () => '',
  q: (...values) => values.filter(Boolean).join(' '),
  AB: () => [onlyCareer, () => {}],
  B: options => { query = options; return {data: browsing.outside}; },
  H: async url => { urls.push(url); return browsing.outside; },
  e: {id: 'test', versao: 'v1'}, kn: null, hn: 901, F: 'all', Tn: 'name', En: false,
  rn: {}, an: {}, on: {}, je: '', A: '', Wn: '', Jn: [], Cn: [], Xn: [], Yn: [], ia: undefined,
  L: 0, bV: 100, ar: () => ({snapshot: 901, group: 'all', favListaId: 'test'}),
});
for (const name of ['YN', 'Kl', 'Pu', 'ku', 'XV', 'ZN', 'KV']) context[name] = props => ({type: name, props});
context.BV = props => ({type: 'tabs', props});
context.PV = props => ({type: 'table', props});
vm.runInContext(section('function ho(', 'var go='), context);
context.W = vm.runInContext('({' + section('moneyballBrowse:e=>', ',moneyballExportUrl:') + '})', context);
for (const name of ['bd', 'vd', 'rH']) vm.runInContext(component(name), context);
for (const fixture of fixtures.browse) {
  browsing = fixture;
  context.tr = fixture.current;
  for (onlyCareer of [false, true]) {
    vm.runInContext('{' + section('let[or,sr]=AB(),cr=', ',gr=nr?null:rr??ir') +
      ';globalThis.assembled={rows:hr,outside:pr};}', context);
    const rows = context.assembled.rows;
    const ids = rows.map(row => row.uid);
    assert.equal(new Set(ids).size, ids.length, 'shipped current/outside assembly has no duplicate players');
    assert.equal(rows.length, fixture.current.rows.length + (onlyCareer ? 0 : fixture.outside.rows.length));
    assert.equal(query.enabled, !onlyCareer);
    if (!onlyCareer) {
      await query.queryFn();
      assert.equal(new URLSearchParams(urls.at(-1).split('?')[1]).get('fora'), '1');
    }
  }
}
for (const event of fixtures.events) {
  response = event.response;
  for (const method of ['favoritosCriar', 'favoritosEditar', 'favoritosMarcar', 'favoritosDuplicar', 'favoritosApagar']) {
    context.W[method] = async () => response;
  }
  await context.bd()[event.method]('test', 'name', true);
  assert.equal(cache, response, 'shipped mutation hook gets complete state');
  assert(Array.isArray(cache.listas));
  context.vd(); // Real overlapping-list index must have membership metadata.
  const tree = context.rH();
  const serialized = JSON.stringify(tree);
  assert(!serialized.includes('Invalid Date'));
  for (const list of cache.listas) {
    assert(Number.isFinite(Date.parse(list.criada_em)));
    assert(Number.isFinite(Date.parse(list.atualizada_em)));
  }
  if (cache.listas.length) {
    const expected = new Date(cache.listas[0].criada_em).toLocaleDateString('en');
    assert(serialized.includes(`Created ${expected}`), 'actual Favorites header uses saved creation date');
  }
}
console.log('Favorites flow renderer regressions passed');
