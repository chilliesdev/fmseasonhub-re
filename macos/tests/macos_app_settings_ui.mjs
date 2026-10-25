// Execute the shipped Settings card with the backend's effective capabilities.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const macos = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url)), 'utf8');
const start = source.indexOf('var DU=');
const end = source.indexOf('function kU(', start);
assert(start >= 0 && end > start, 'shipped App Settings renderer exists');

function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
}

const lastWindow = {
  de: 'des letzten App-Fensters', en: 'the last app window', es: 'la última ventana de la app',
  fr: 'la dernière fenêtre de l’app', pt: 'a última janela do app', tr: 'Son uygulama penceresini',
};

for (const language of ['de', 'en', 'es', 'fr', 'pt', 'tr']) {
  const strings = fs.readFileSync(fileURLToPath(new URL(`../fmsh/idiomas/${language}/interface.txt`, import.meta.url)), 'utf8');
  const translations = Object.fromEntries(strings.split('\n').filter(line => /^config\./u.test(line)).map(line => {
    const separator = line.indexOf(' = ');
    return [line.slice(0, separator), line.slice(separator + 3)];
  }));
  const writes = [];
  let data = macos;
  const jsx = (type, props) => typeof type === 'function' ? type(props) : ({type, props});
  const context = vm.createContext({
    z: {jsx, jsxs: jsx}, R: () => ({t: key => translations[key] ?? key}),
    Ga: () => ({setQueryData: () => {}}), B: () => ({data}),
    W: {bandeja: () => {}, setBandeja: body => {writes.push(body); return Promise.resolve(body);}},
    Wf: props => ({type: 'toggle', props}), Kf: 'title',
    q: (...values) => values.filter(Boolean).join(' '),
  });
  vm.runInContext(source.slice(start, end), context);
  const tree = context.OU();
  const rendered = JSON.stringify(tree);
  for (const key of ['config.macosTitulo', 'config.macosAjuda', 'config.macosInicioAjuda']) {
    assert(translations[key], `${language}: ${key} has a shipped translation`);
    assert(rendered.includes(translations[key]), `${language}: renders ${key}`);
  }
  assert(!rendered.includes('Windows'), `${language}: no Windows guidance on macOS`);
  assert(!rendered.includes('config.'), `${language}: no raw translation keys`);
  assert(!nodes(tree).some(node => ['button', 'toggle'].includes(node.type)), `${language}: no unsupported controls`);
  assert(!translations['config.dbDirHelp'].includes('Windows'), `${language}: disk guidance is platform-neutral`);
  assert(translations['config.macosAjuda'].includes('Window > Minimize (⌘M)'), `${language}: uses actual native menu labels`);
  assert(translations['config.macosAjuda'].includes(lastWindow[language]), `${language}: quitting applies to the last app window`);

  data = undefined;
  assert.equal(context.OU(), null, `${language}: loading does not flash Windows guidance`);
  data = {plataforma: 'win32', ao_fechar: 'perguntar', icone_ativo: true, iniciar_disponivel: true};
  const windows = context.OU();
  assert(JSON.stringify(windows).includes(translations['config.bandejaTitulo']), `${language}: keeps Windows card`);
  const buttons = nodes(windows).filter(node => node.type === 'button');
  assert.equal(buttons.length, 3, `${language}: keeps close choices`);
  buttons[1].props.onClick();
  const toggle = nodes(windows).find(node => node.type === 'toggle');
  assert(toggle && !toggle.props.desabilitado, `${language}: keeps available Windows startup control`);
  toggle.props.onMudar(true);
  assert.equal(JSON.stringify(writes), JSON.stringify([{ao_fechar: 'bandeja'}, {iniciar_com_windows: true}]));
}
console.log('macOS Settings renderer regressions passed');
