// Execute the shipped screen and report dialog with the live backend contract.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const start = source.indexOf('function JU(');
const end = source.indexOf('function ZU(', start);
assert(start >= 0 && end > start, 'shipped Diagnostics renderers exist');

function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
}
for (const language of ['en', 'pt']) {
  const strings = fs.readFileSync(fileURLToPath(new URL(`../fmsh/idiomas/${language}/interface.txt`, import.meta.url)), 'utf8');
  const translations = Object.fromEntries(strings.split('\n').filter(line => /^diag\./u.test(line)).map(line => {
    const separator = line.indexOf(' = ');
    return [line.slice(0, separator), line.slice(separator + 3)];
  }));
  const report = {...payload.report, arquivo: `/QA/long output path/${'folder with spaces/'.repeat(12)}diagnostico.txt`};
  let state = 0;
  const jsx = (type, props) => typeof type === 'function' ? type(props) : ({type, props});
  const context = vm.createContext({
    z: {jsx, jsxs: jsx, Fragment: 'fragment'},
    _: {useState: () => [[false, false, true, false][state++], () => {}]},
    R: () => ({t: key => translations[key] ?? key, i18n: {language}}),
    B: options => ({data: options.queryKey[0] === 'diagnostico' ? payload.status : report}),
    Ga: () => ({}), V: () => ({isPending: false}), Rd: () => ({data: {state: 'idle'}}),
    W: {}, Gf: 'page', Kf: 'title', Y: 'button', cl: 'folder-icon', el: 'copy-icon',
    du: 'done-icon', ql: 'scan-icon', rl: 'external-icon', ol: 'report-icon', Pu: 'close-icon',
    q: (...values) => values.filter(Boolean).join(' '),
  });
  vm.runInContext(source.slice(start, end), context);
  const tree = context.XU();
  const rendered = JSON.stringify(tree);
  for (const value of [payload.status.so, payload.status.python, payload.status.pasta_dados,
    payload.status.banco.caminho, 'ERROR QA existing failure', report.arquivo]) {
    assert(rendered.includes(value), `${language}: screen renders ${value}`);
  }
  const description = translations['diag.fullHelp'];
  assert(description.includes('macOS') && description.includes('SQLite'), `${language}: describes measured checks`);
  assert(!/WebView2|antiv|memory addresses|endereços de memória/u.test(description), `${language}: excludes unsupported promises`);
  assert(rendered.includes(description), `${language}: screen uses the corrected description`);
  assert(rendered.includes('DATABASE'));
  assert(rendered.includes('Snapshots: 1; players: 1'));
  assert(rendered.includes('text-off'), 'report highlights real failures');
  const path = nodes(tree).find(node => node.props?.title === report.arquivo);
  assert(path, `${language}: full output path remains available`);
  const dialog = context.JU({texto: report.texto, linhas: report.linhas, arquivo: report.arquivo, onFechar: () => {}});
  const dialogNodes = nodes(dialog);
  assert.equal(dialogNodes.filter(node => node.type === 'h2').length, 1, `${language}: one dialog title`);
  const actions = dialogNodes.filter(node => node.type === 'button');
  assert.equal(actions.length, 3, `${language}: folder, copy and close actions remain available`);
  assert(actions.every(node => typeof node.props.onClick === 'function'), `${language}: actions remain connected`);
  for (const key of ['diag.openFolder', 'diag.copiarRelatorio']) {
    assert(JSON.stringify(dialog).includes(translations[key]), `${language}: action label is visible`);
  }
}
console.log('Diagnostics renderer regressions passed');
