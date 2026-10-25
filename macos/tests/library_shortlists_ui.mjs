// Run the shipped Library renderer against the real HTTP listing.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url), 'utf8');
const listing = JSON.parse(fs.readFileSync(0, 'utf8'));
const start = source.indexOf('var WH=');
const end = source.indexOf('function KH(', start);
assert(start >= 0 && end > start);
const downloads = [];
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...Object.values(tree).flatMap(nodes)];
const jsx = (type, props) => ({type, props});
const context = vm.createContext({
  z: {jsx, jsxs: jsx},
  _: {useState: value => [value, () => {}], useRef: () => ({current: null}), useMemo: fn => fn()},
  R: () => ({t: (key, params) => key + (params?.count == null ? '' : `:${params.count}`)}),
  rt: () => 'en', Ga: () => ({invalidateQueries() {}}), Kn: () => () => {}, Zd: () => ({sid: 901}),
  B: () => ({data: listing, isLoading: false}), V: () => ({mutate() {}}),
  Yv: values => values, q: (...values) => values.filter(Boolean).join(' '),
  QB: item => item.nome, QV: () => '', Cb: (...args) => downloads.push(args),
  W: {bibliotecaBrutoUrl: name => `/api/biblioteca/${encodeURIComponent(name)}/bruto`},
});
for (const name of ['bu', 'Rl', '_u', 'Ll', 'Kl', 'xl', 'Pu', 'Ql', 'cl', 'Wc', 'Nl', 'rl', 'Yl', 'Ep', 'Sl']) context[name] = name;
vm.runInContext(source.slice(start, end), context);
const rendered = nodes(context.GH());
const row = rendered.find(node => node.type === 'tr' && JSON.stringify(node).includes('Équipe.lsh'));
assert(row, 'saved list appears in actual Library table');
const contents = JSON.stringify(row);
assert(contents.includes('arq.tipo.lista'), 'player list label');
assert(contents.includes('lista.qtd:2'), 'selected player count');
assert(!contents.includes('arq.tipo.filtro'), 'list must not use filter label');
const download = nodes(row).find(node => node.type === 'button' && node.props.title === 'bib.baixarArquivo');
assert(download, 'saved list download action exists');
await download.props.onClick();
assert.equal(downloads[0][0], '/api/biblioteca/%C3%89quipe.lsh/bruto');
assert.equal(downloads[0][1], 'Équipe.lsh');
const broken = rendered.find(node => node.type === 'tr' && JSON.stringify(node).includes('broken.lsh'));
assert(broken);
assert(!nodes(broken).some(node => node.type === 'button' && node.props.title === 'bib.baixarArquivo'), 'invalid list cannot be downloaded as valid');
console.log('Library shortlist renderer passed');
