// Exercise the shipped Library and both destination apply handlers in each language.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url), 'utf8');
const {listing, contents} = JSON.parse(fs.readFileSync(0, 'utf8'));
const section = (start, end) => {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `shipped section: ${start}`);
  return source.slice(first, last);
};
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...Object.values(tree).flatMap(nodes)];
const jsx = (type, props) => ({type, props});
let language;
let applied;
let active;
let conditions;
let navigated;
let appliedFile;
const context = vm.createContext({
  z: {jsx, jsxs: jsx},
  _: {useState: value => [value, () => {}], useRef: () => ({current: null}), useMemo: fn => fn()},
  R: () => ({t: key => key}), rt: () => language, Ga: () => ({invalidateQueries() {}}),
  Kn: () => route => {navigated = route;}, Zd: () => ({sid: 901}),
  B: () => ({data: listing, isLoading: false}), V: () => ({mutate() {}}),
  Yv: values => values, q: (...values) => values.filter(Boolean).join(' '), QV() {},
  W: {bibliotecaLer: async name => contents[name]}, setTimeout: fn => fn(),
  $I: (preset, warnings, file) => {appliedFile = file; context.vi(preset, warnings, file);},
  e: false, F: 'all', Fe: false,
  Oe: value => {conditions = value;}, Me() {}, Pt() {}, ge() {}, Ot() {},
  It: value => {applied = value;}, Et: value => {active = value;},
  fe: value => {conditions = value;}, Ce() {},
  je: value => {active = value;}, Te: value => {applied = value;},
});
for (const name of ['bu', 'Rl', '_u', 'Ll', 'Kl', 'xl', 'Pu', 'Ql', 'cl', 'Wc', 'Nl', 'rl', 'Yl', 'Ep', 'Sl']) context[name] = name;
vm.runInContext(section('var BI=', 'function YI('), context);
vm.runInContext(section('function QB(', 'function $B('), context);
vm.runInContext(section('var WH=', 'function KH('), context);
vm.runInContext(section('function vi(t,n,r){', '(0,_.useEffect)(()=>{function e(e){let{preset:t,avisos:n,arquivo:r}=e.detail;vi'), context);
vm.runInContext(section('function tn(e,t,n){', '(0,_.useEffect)(()=>{let e=e=>{let{preset:t,avisos:n,arquivo:r}=e.detail;tn'), context);

for (language of ['en', 'pt']) {
  const rendered = nodes(context.GH());
  for (const item of listing.arquivos.filter(item => item.fabrica)) {
    const expected = language === 'en' ? item.nomeEn : item.nome;
    const row = rendered.find(node => node.type === 'tr' && JSON.stringify(node).includes(item.arquivo));
    assert(row, `${language}: factory appears`);
    assert(nodes(row).some(node => node.type === 'span' && node.props.children === expected), `${language}: Library title`);
    const apply = nodes(row).find(node => node.type === 'button' && node.props.title === 'bib.aplicar');
    assert(apply, 'Library apply action exists');
    await apply.props.onClick();
    assert.equal(navigated, '/database');
    assert.equal(applied.nome, expected, `${language}: Database applied message`);
    assert.equal(active.nome, expected, `${language}: Database active chip`);
    assert.equal(active.arquivo, item.arquivo);
    assert.equal(appliedFile, item.arquivo);
    assert.equal(JSON.stringify(conditions), JSON.stringify(contents[item.arquivo].busca.conds));
    const {preset, avisos} = context.qI(JSON.stringify(contents[item.arquivo]));
    context.tn(preset, avisos, item.arquivo);
    assert.equal(applied.nome, expected, `${language}: My Team applied message`);
    assert.equal(active.nome, expected, `${language}: My Team active chip`);
    assert.equal(active.arquivo, item.arquivo);
    assert.equal(JSON.stringify(conditions), JSON.stringify(contents[item.arquivo].busca.conds));
  }
  const custom = {fmsh: 1, tipo: 'filtro', nome: 'My tactics', busca: {v: 2, conds: []}};
  const {preset, avisos} = context.qI(JSON.stringify(custom));
  for (const apply of [context.vi, context.tn]) {
    apply(preset, avisos, 'My tactics.fsh');
    assert.equal(applied.nome, 'My tactics', `${language}: custom title unchanged`);
    assert.equal(active.nome, 'My tactics');
    assert.equal(active.arquivo, 'My tactics.fsh');
  }
}
console.log('Library locale renderer passed');
