// Verify real API chart payloads reach each chart in the shipped detail view.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const jsx = (type, props) => ({type, props});
const context = vm.createContext({
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  R: () => ({t: (key, values) => key + (values ? JSON.stringify(values) : ''), i18n: {language: 'en'}}),
  bg: (value, language, digits) => value.toFixed(digits),
  Nb: () => 'color', dx: value => value, Cx: () => 'UNAVAILABLE',
  lS: (name, metric) => ({name, metric}), uS: (name, metric, sub) => ({name, metric, sub}),
  Lb: {}, Rb: {fin: [], cri: [], def: [], gk: []},
  Ix: 'scatter', zx: 'histogram', _x: 'card', dS: 'tile',
  Lx: 'zones', Vx: 'rings', Ux: 'discipline', Rx: 'radar',
  fS: 'contribution', pS: 'match-context', vx: 'value', wx: 'peers'
});
const start = source.indexOf('function cS(');
const end = source.indexOf('function lS(', start);
assert(start >= 0 && end > start);
vm.runInContext(source.slice(start, end), context);
function nodes(tree) {
  if (tree == null || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
}
function render(tab, data) {
  return nodes(context.cS({d: data, aba: tab, nomeCurto: 'QA', sid: 901, aoAbrirJogador: () => {}}));
}
function checkScatter(tree, points) {
  assert(tree.some(node => node.type === 'scatter' && JSON.stringify(node.props.pontos) === JSON.stringify(points)),
    `scatter points reached actual renderer: ${JSON.stringify(points)}`);
}
function checkHistogram(tree, histogram) {
  assert(tree.some(node => node.type === 'histogram' && JSON.stringify(node.props.caixas) === JSON.stringify(histogram.caixas) &&
    node.props.min === histogram.min && node.props.max === histogram.max), 'histogram data reached actual renderer');
}
const fin = render('fin', payload.outfield);
checkScatter(fin, payload.outfield.dispersao.volume_qualidade);
checkHistogram(fin, payload.outfield.histograma.gols_menos_xg);
assert(fin.some(node => node.type === 'value' && node.props.valor === `${payload.outfield.poisson.gols}%`));
const creation = render('cri', payload.outfield);
checkScatter(creation, payload.outfield.dispersao.progressao_seguranca);
checkHistogram(creation, payload.outfield.histograma.assist_menos_xa);
const defence = render('def', payload.outfield);
checkScatter(defence, payload.outfield.dispersao.reativo_proativo);
checkScatter(defence, payload.outfield.dispersao.posse);
const keeper = render('gk', payload.keeper);
checkScatter(keeper, payload.keeper.dispersao.trabalho_eficiencia);
checkScatter(keeper, payload.keeper.dispersao.esperado_evitado);
checkHistogram(keeper, payload.keeper.goleiro.histograma);
console.log('All consumed chart payloads reached shipped renderers');
