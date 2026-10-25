// Run the shipped hook, Favorites gate, denied-tier card and coming-soon screens.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const states = JSON.parse(fs.readFileSync(0, 'utf8'));
function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  assert(from >= 0 && to > from, `shipped section exists: ${start}`);
  return source.slice(from, to);
}
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree !== 'object') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  return text(tree.props?.children);
}
const calls = [];
let access;
let query;
let lists = [];
const translate = (key, values = {}) => key + (values.nivel === undefined ? '' : ` ${values.nivel}`);
const jsx = (type, props) => typeof type === 'function' ? type(props ?? {}) : ({type, props});
const marker = type => props => ({type, props});
const context = vm.createContext({
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  R: () => ({t: translate}), rt: () => 'en',
  B: options => { query = options; return {data: access}; },
  H: async route => { calls.push(route); return access; },
  Kn: () => () => {}, rp: () => ({iniciar() {}, modal: null}),
  q: (...values) => values.filter(Boolean).join(' '),
  ht: {t: () => ''},
  _: {useState: value => [typeof value === 'function' ? value() : value, () => {}], useEffect() {}},
  _d: () => ({data: {listas: lists}}), bd: () => ({}),
  eH: () => null, tH() {}, $V: 'qa-favorites', GV: () => false,
  QV: () => '', Lu() {}, Dp: ['Free', 'Free', 'Season Analyst', 'Moneyball Scout', 'FMSH Pro'],
});
for (const name of ['du', 'Sl', 'Y', 'Kl', 'ku', 'Pu', 'dl', 'Gl', 'yu', 'KV', 'ZN', 'YN', 'XV']) {
  context[name] = marker(name);
}
// Preserve children passed through the list panels; child internals are outside this gate regression.
context.BV = props => jsx('list-tabs', {...props, children: [props.itens.map(item => item.nome), props.acoes]});
context.PV = ({lista}) => jsx('favorites-panel', {children: [lista.topo, lista.acoes, lista.resumo]});
context.W = vm.runInContext('({' + section('acesso:(e=!1)=>', ',resgatarCodigo:') + '})', context);
vm.runInContext(section('var af=[`acesso`]', 'var uf=e=>'), context);
vm.runInContext(section('function FV(', 'var LV='), context);
vm.runInContext(section('function nH()', 'var iH='), context);
vm.runInContext(section('function eW(', 'function rW('), context);

for (const state of states) {
  access = state;
  context.of();
  assert.equal(await query.queryFn(), state, 'raw access hook keeps backend contract');
  assert.equal(calls.at(-1), '/api/acesso');
  assert.equal(await context.W.acesso(true), state);
  assert.equal(calls.at(-1), '/api/acesso?revalidar=1');

  for (const fixture of [[], [{id: 'qa-list', nome: 'QA Favorites', uids: [900001],
    cor: '#00aa55', criada_em: '2026-10-25', atualizada_em: '2026-10-25'}]]) {
    lists = fixture;
    const rendered = text(context.nH());
    if (state.nivel === 0) {
      assert(rendered.includes(`trava.assinar ${state.escada[state.nivel_favoritos].nome}`),
        'denied tier has a named subscription target');
      assert(rendered.includes('conta.patreonEnter'), 'denied tier retains sign-in');
      assert(!rendered.includes('fav.novaLista'));
    } else {
      assert(rendered.includes('fav.novaLista'), 'allowed tier renders actual New list control');
      assert(!rendered.includes('trava.assinar'), 'allowed tier has no subscription gate');
      assert(!rendered.includes('conta.patreonEnter'));
      assert(rendered.includes(fixture.length ? 'QA Favorites' : 'fav.vazioTitulo'));
    }
  }
  for (const screen of ['tW', 'nW']) {
    const rendered = text(context[screen]());
    if (state.nivel < 2) {
      assert(rendered.includes('trava.assinar Season Analyst'), 'related gate uses the existing required tier');
      assert(!rendered.includes('breve.corpo'));
    } else {
      assert(rendered.includes('breve.corpo'), 'allowed Finances/Assistant stays coming soon');
      assert.equal(rendered.includes('breve.temAntecipado'), state.nivel >= 3);
    }
  }
}
console.log('Access renderer regressions passed: 5 tiers');
