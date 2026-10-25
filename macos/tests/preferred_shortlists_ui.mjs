// Exercise the shipped list wrapper and its actual no-season render branch.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url), 'utf8');
let listing = JSON.parse(fs.readFileSync(0, 'utf8'));
const first = listing.listas[0], second = listing.listas[1];
assert(first && second);
const section = (start, end) => {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert(from >= 0 && to > from, start);
  return source.slice(from, to);
};
const gate = section('hn==null)return ', ';function bi(e)').slice('hn==null)return '.length);
const jsx = (type, props) => typeof type === 'function' ? type(props ?? {}) : ({type, props});
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...Object.values(tree).flatMap(nodes)];
const text = tree => tree == null || typeof tree === 'boolean' ? '' : typeof tree !== 'object' ? String(tree)
  : Array.isArray(tree) ? tree.map(text).join(' ') : text(tree.props?.children);
const states = [], pending = [], calls = [];
let hook = 0, mutation = 0, snapshot = false, mutationError = null;
const translate = (key, params) => key + (params?.nome ? `:${params.nome}` : '');
const context = vm.createContext({
  Date, setTimeout() {},
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  _: {useMemo: fn => fn(), useEffect() {}, useState: initial => {
    const index = hook++;
    if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial;
    return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
  }},
  localStorage: {getItem: () => null, setItem() {}},
  R: () => ({t: translate}), rt: () => 'en', GV: () => null, QV: () => '',
  Ga: () => ({setQueryData: (_key, value) => { listing = value; }}),
  B: () => ({data: listing}), of: () => ({data: {lista_fm_completa: true}}), iH: ['listas-preferenciais'],
  V: options => {
    const index = mutation++;
    return {error: index === 0 ? mutationError : null, mutate: value => {
      pending.push(Promise.resolve(options.mutationFn(value)).then(options.onSuccess));
    }};
  },
  W: {
    listaAtualizar: async id => { calls.push(['refresh', id]); return listing; },
    listaRemover: async id => { calls.push(['remove', id]); return {listas: listing.listas.filter(item => item.id !== id)}; },
  },
  BV: props => ({type: 'tabs', props}),
  KV: props => jsx('section', {children: [jsx('h2', {children: props.titulo}), jsx('b', {children: props.uids.length})]}),
  oH: () => jsx('button', {children: 'Import from FM list'}),
  qN: props => jsx('dialog', props), du: 'done', Au: 'refresh',
  ee: false, D: translate,
});
vm.runInContext(source.slice(source.indexOf('function fmshListaSemTemporada(')), context);
context.PV = ({lista}) => {
  if (snapshot) return {type: 'players', props: {lista}};
  context.e = lista;
  return vm.runInContext(gate, context);
};
vm.runInContext(section('var sH=', 'var dH='), context);
function render() {
  hook = mutation = 0;
  return context.uH();
}
let tree = render();
assert(text(tree).includes('db.noSnapshot'), 'season requirement remains on player rows');
assert(text(tree).includes(first.nome), 'saved list title stays visible with no season');
assert(text(tree).includes(String(first.uids.length)), 'saved member count stays visible');
assert(text(tree).includes('Import from FM list'), 'another list can be imported without a season');
let tabs = nodes(tree).find(node => node.type === 'tabs');
assert.equal(tabs.props.itens.length, 2);
assert.equal(tabs.props.itens[0].quantidade, first.uids.length);
assert.equal(tabs.props.itens[1].quantidade, second.uids.length);
tabs.props.aoSelecionar(second.id);
tree = render();
assert(text(tree).includes(second.nome), 'list selection works without a season');
const refresh = nodes(tree).find(node => node.type === 'button' && text(node).trim() === 'lista.atualizar');
assert(refresh && !refresh.props.disabled, 'source refresh remains usable');
refresh.props.onClick();
await Promise.all(pending.splice(0));
assert.deepEqual(calls[0], ['refresh', second.id]);
mutationError = new Error('The source file is missing');
assert(text(render()).includes(mutationError.message), 'failed refresh remains visible');
mutationError = null;
tabs = nodes(render()).find(node => node.type === 'tabs');
tabs.props.aoRemover(second.id, 20, 20);
tree = render();
const remove = nodes(tree).find(node => node.type === 'button' && text(node).trim() === 'lista.remover');
assert(remove, 'remove confirmation remains available without a season');
remove.props.onClick();
await Promise.all(pending.splice(0));
assert.deepEqual(calls[1], ['remove', second.id]);
assert.equal(listing.listas.length, 1);
tree = render();
assert(text(tree).includes(first.nome), 'remaining list stays visible after removal');
snapshot = true;
tree = render();
assert(nodes(tree).some(node => node.type === 'players'), 'selected-season player view remains in use');
context.e = {tipo: 'favoritos', topo: 'unrelated'};
const otherScreen = vm.runInContext(gate, context);
assert.equal(text(otherScreen), 'db.noSnapshot', 'other screens retain their existing no-season gate');
listing = {listas: []};
snapshot = false;
tree = render();
assert(text(tree).includes('lista.vazioTitulo'));
assert(nodes(tree).some(node => node.type === 'tabs' && node.props.acoes), 'empty state retains its import slot');
console.log('Preferred shortlist renderer passed');
