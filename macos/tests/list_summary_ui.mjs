// Execute the shipped KV summary and qV provenance menu with real HTTP responses.
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
function component(name) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf('function ', start + 10);
  assert(start >= 0 && end > start, `shipped component exists: ${name}`);
  return source.slice(start, end);
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [...tree.props ? [tree] : [], ...Object.values(tree).flatMap(nodes)];
}
const jsx = (type, props) => typeof type === 'function' ? type(props ?? {}) : ({type, props});
let current;
let potential = true;
const opened = [];
const requests = [];
const context = vm.createContext({
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  _: {useState: value => [value, value => opened.push(value)]},
  R: () => ({t: key => key, i18n: {language: 'en'}}),
  kd: () => [[1]], fh: () => potential,
  B: ({queryKey}) => ({data: current[queryKey[0] === 'resumo-jogadores' ? 'summary' : 'outside']}),
  U: async (route, body) => { requests.push([route, body]); return current[route === '/api/resumo-jogadores' ? 'summary' : 'outside']; },
  q: (...values) => values.filter(Boolean).join(' '),
  yh: value => value == null ? '—' : `value:${value}`,
  bh: value => value == null ? '—' : `wage:${value}`, Ju: () => 'week',
});
for (const name of ['JV', 'jl', 'Ml', 'gu', 'pu', 'Ep', 'YV', 'kP', 'gv', 'Wc', 'tm']) {
  context[name] = props => ({type: name, props});
}
context.W = vm.runInContext('({' + section('resumoJogadores:', ',live:') + '})', context);
vm.runInContext(section('var VV=', 'function GV('), context);
vm.runInContext(component('qV'), context);
vm.runInContext(component('KV'), context);

for (const fixture of cases) {
  current = fixture;
  for (const [method, route, field] of [
    ['resumoJogadores', '/api/resumo-jogadores', 'summary'],
    ['jogadoresForaDaCaptura', '/api/jogadores-fora-da-captura', 'outside'],
  ]) {
    assert.equal(await context.W[method](fixture.uids, fixture.snapshot), fixture[field]);
    assert.equal(requests.at(-1)[0], route);
    assert.equal(JSON.stringify(requests.at(-1)[1]), JSON.stringify({uids: fixture.uids, snapshot: fixture.snapshot}));
  }
  for (potential of [true, false]) {
    const tree = context.KV({uids: fixture.uids, titulo: 'QA Favorites', snapshot: fixture.snapshot});
    const rendered = nodes(tree);
    const count = rendered.find(node => node.type === 'YV' && node.props.rotulo === 'lista.kpiJogadores');
    assert.equal(count.props.valor, String(fixture.summary.qtd));
    assert(!JSON.stringify(tree).includes('NaN'), 'missing data must not produce NaN');
    for (const player of fixture.summary[potential ? 'pa' : 'idades']) {
      const button = rendered.find(node => node.type === 'button' && node.props.title?.startsWith(`${player.nome} · `));
      assert(button, 'actual summary chart renders saved player');
      button.props.onClick();
      assert.equal(opened.at(-1).uid, player.uid);
      assert.equal(opened.at(-1).sid, fixture.snapshot);
    }
    const menu = rendered.find(node => node.type === 'gv');
    const outsideCount = fixture.outside.linhas.length + fixture.outside.sem_dado;
    assert.equal(Boolean(menu), outsideCount > 0);
    if (menu) {
      assert.equal(menu.props.itens.length, fixture.outside.linhas.length);
      for (let i = 0; i < menu.props.itens.length; i++) {
        const row = fixture.outside.linhas[i];
        assert.equal(menu.props.itens[i].rotulo, row.nome);
        menu.props.itens[i].aoEscolher();
        assert.equal(opened.at(-1).uid, row.uid);
        assert.equal(opened.at(-1).sid, row.snapshot);
      }
    }
  }
}
console.log(`List renderer regressions passed: ${cases.length} cases`);
