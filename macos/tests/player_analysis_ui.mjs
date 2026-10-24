// Execute the shipped renderers with known, zero and unavailable measurements.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const jsx = (type, props) => ({type, props});
const context = vm.createContext({
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  _: {useState: value => [value, () => {}], useEffect: () => {}},
  R: () => ({t: (key, values) => key + (values ? JSON.stringify(values) : ''), i18n: {language: 'en'}}),
  Nb: () => 'color', Ex: 'muted', Tx: 'text', Fb: 'background',
  bg: (value, language, digits) => value.toFixed(digits),
  Ib: () => 'level', q: (...values) => values.join(' '), dx: value => value,
  Wm: {attack: {fill: 'fill', bd: 'border'}}, kg: 20, rt: () => 'en', Jm: slice => slice.label,
  AN: 16, iN: () => true, QM: value => ({value, set() {}}),
  tN: (motion, format) => format(motion.value), ZM: {circle: 'motion-circle', text: 'motion-text', b: 'motion-rank'},
  _x: 'card', Q: 'text', yx: 'tabs', Bx: 'contributions', Wx: 'comparison', bx: 'button', Pb: () => 'color'
});
for (const [name, next] of [['Vx', 'Hx'], ['nS', 'rS'], ['dS', 'fS'], ['fS', 'pS'], ['aS', 'oS'], ['Ag', 'jg'], ['NN', 'PN']]) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf(`function ${next}(`, start);
  assert(start >= 0 && end > start, `shipped renderer ${name} exists`);
  vm.runInContext(source.slice(start, end), context);
}
function nodes(tree) {
  if (tree == null || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
}
const unavailable = {v: 0, ok: false, n: 0, p: 0, rank: 0, mediana: 0};
const missingTile = context.dS({chave: 'xg90', col: 1, m: unavailable, nome: 'xG', unidade: '/90', casas: 2});
assert(nodes(missingTile).some(node => node.type === 'b' && node.props.children === '—'));
assert(!JSON.stringify(missingTile).includes('0.00'));
const knownZero = {...unavailable, ok: true, n: 2, rank: 1};
const zeroTile = context.dS({chave: 'g90', col: 1, m: knownZero, nome: 'Goals', unidade: '/90', casas: 2});
assert(nodes(zeroTile).some(node => node.type === 'b' && node.props.children === '0.00'));
const missingRing = context.Vx({itens: [{nome: 'Rate', valor: 0, mediana: 0, ok: false, sub: '0 / 0'}],
  rotuloPercentil: String, rotuloMediana: String, rotuloSemAmostra: 'UNAVAILABLE'});
assert(!JSON.stringify(missingRing).includes('0 / 0'));
assert(nodes(missingRing).some(node => node.type === 'text' && node.props.children?.[0] === '—'));
const zeroRing = context.Vx({itens: [{nome: 'Rate', valor: 0, mediana: 0, ok: true, sub: '0 / 20'}],
  rotuloPercentil: String, rotuloMediana: String, rotuloSemAmostra: 'UNAVAILABLE'});
assert(JSON.stringify(zeroRing).includes('0 / 20'));
const missingDuel = context.nS({nome: 'Duels', mt: unavailable, ganhos: 0, total: 0,
  textoGanhos: '0 won of 0', n: String, rotuloPercentil: '0th', rotuloMediana: 'median 0%', semAmostra: 'UNAVAILABLE'});
assert(!JSON.stringify(missingDuel).includes('0 won of 0'));
assert(!JSON.stringify(missingDuel).includes('median 0%'));
const match = {peso: {campos: {}, fatia_justa: 9.09}, cobertura: 'parcial', jogos: 4, jogos_da_temporada: 20};
const missingContribution = context.fS({aba: 'cri', pa: match, n: String, lang: 'en', nome: 'Player', semDados: 'UNAVAILABLE'});
assert(!nodes(missingContribution).some(node => node.type === 'contributions'));
assert(JSON.stringify(missingContribution).includes('UNAVAILABLE'));
const zeroContribution = context.fS({aba: 'fin', pa: {...match, peso: {campos: {goals: {v: 0, t: 3, p: 0}}, fatia_justa: 9.09}}, n: String, lang: 'en', nome: 'Player', semDados: 'UNAVAILABLE'});
const rows = nodes(zeroContribution).find(node => node.type === 'contributions').props.linhas;
assert.equal(rows.length, 1);
assert.equal(rows[0].v, 0);
assert.equal(rows[0].t, 3);
assert.equal(rows[0].p, 0);
console.log('Shipped analysis renderer regressions passed');

const unknownDuration = context.fS({aba: 'fin', pa: {...match, peso: {campos: {goals: {v: 4, t: 6, p: 66.67}}, fatia_justa: null}}, n: String, lang: 'en', nome: 'Player', semDados: 'UNAVAILABLE'});
assert(!JSON.stringify(unknownDuration).includes('est.fin.l4.peso'));
assert.equal(nodes(unknownDuration).find(node => node.type === 'contributions').props.justo, null);
const unknownRate = context.aS({pa: {cobertura: 'parcial', jogos: 2, jogos_da_temporada: 20,
  contexto: {casa: {jogos: 2, nota: 7, min: null, g: 4, a: 2}, fora: null, titular: null, reserva: null, competicoes: []}},
  lang: 'en', gk: false, semDados: 'UNAVAILABLE'});
assert(nodes(unknownRate).some(node => node.type === 'span' && node.props.children === '—'));

// Sparse profile: supported goals stay; absent/nonfinite axes do not become 0/90.
const slices = [{k: 'goals', label: 'Goals', grp: 'attack'},
  {k: 'xg', label: 'xG', grp: 'attack'}, {k: 'dribbles', label: 'Dribbles', grp: 'attack'}];
const sparseProfile = context.Ag({fatias: slices, dados: {goals: {v: .25, pct: 37.5}}, nomeCoorte: 'ST'});
const sparsePaths = nodes(sparseProfile).filter(node => node.type === 'path' && node.props.className === 'pizza-fatia');
assert.equal(sparsePaths.length, 1);
assert(JSON.stringify(sparseProfile).includes('0.25'));
assert(!JSON.stringify(sparseProfile).includes('0.00'));
assert.equal(nodes(sparseProfile).filter(node => node.type === 'text' && node.props.children?.[0] === '—').length, 2);
const zeroProfile = context.Ag({fatias: slices, dados: {goals: {v: 0, pct: 0}, xg: {v: 0, pct: 50}, dribbles: {v: NaN, pct: 10}}, nomeCoorte: 'ST'});
assert.equal(nodes(zeroProfile).filter(node => node.type === 'path' && node.props.className === 'pizza-fatia').length, 2);
assert.equal(nodes(zeroProfile).filter(node => node.type === 'text' && node.props.children?.[0] === '0.00').length, 2);
const missingRankRadar = context.Ag({fatias: slices, dados: {goals: {v: 1, pct: NaN}, xg: {v: Infinity, pct: 50}}, nomeCoorte: 'ST'});
assert(!nodes(missingRankRadar).some(node => node.type === 'path' && node.props.className === 'pizza-fatia'));
assert(JSON.stringify(missingRankRadar).includes('1.00'));
const preview = (value, percentile) => context.NN({titulo: 'Profile', valor: Number.isFinite(value) ? value.toFixed(2) : '—',
  valorNum: value, formatar: value => value.toFixed(2), pct: percentile, cor: 'color', rotuloValor: 'VALUE', topo: 'label'});
for (const [value, percentile] of [[null, null], [NaN, 50], [Infinity, 50], [1, NaN]]) {
  const card = preview(value, percentile);
  assert(!nodes(card).some(node => node.type === 'motion-circle'));
  assert.equal(nodes(card).find(node => node.type === 'motion-rank').props.children, '—');
}
for (const percentile of [0, 50]) {
  const card = preview(0, percentile);
  assert(nodes(card).some(node => node.type === 'motion-circle'));
  assert.equal(nodes(card).find(node => node.type === 'motion-rank').props.children, `${percentile}º`);
  assert.equal(nodes(card).find(node => node.type === 'motion-text').props.children, '0.00');
}
console.log('Sparse and known-zero profile renderer regressions passed');
