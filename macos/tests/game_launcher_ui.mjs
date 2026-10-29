import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('../fmsh/', import.meta.url));
const source = fs.readFileSync(root + 'frontend/dist/assets/index-Cvmv7E2F.js', 'utf8');
const start = source.indexOf('function wF()');
const end = source.indexOf('var TF=', start);
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
}
for (const locale of ['en', 'pt', 'de', 'es', 'fr', 'tr']) {
  const translations = Object.fromEntries(fs.readFileSync(root + `idiomas/${locale}/interface.txt`, 'utf8').split('\n').filter(line => line.startsWith('conn.') || line.startsWith('save.dismiss')).map(line => { const i = line.indexOf(' = '); return [line.slice(0, i), line.slice(i + 3)]; }));
  let platform = 'darwin', state = [null, false], cursor = 0, requests = [], error = 'access_denied';
  const jsx = (type, props) => typeof type === 'function' ? type(props) : ({type, props});
  const context = vm.createContext({
    z: {jsx, jsxs: jsx}, Y: props => ({type: 'button', props}),
    R: () => ({t: key => {assert(translations[key], `${locale}: missing ${key}`);return translations[key];}}),
    Gd: () => ({connError: error, clearConnError: () => {error = null;}, connect: () => {}}), Md: () => false,
    B: () => ({data: platform ? {platform} : undefined}),
    _: {useState: () => {const i = cursor++; return [state[i], value => {state[i] = value;}];}},
    fetch: async (url, options) => {requests.push([url, options]);return {ok: true, json: async () => ({ok: false, error_code: 'game_running'})};},
  });
  vm.runInContext(source.slice(start, end), context);
  const render = () => {cursor = 0; return context.wF();};
  let tree = render(), content = JSON.stringify(tree);
  assert(content.includes(translations['conn.macosAccessDeniedBody']));
  assert(!content.includes('Windows'));
  const launch = nodes(tree).find(node => node.type === 'button' && node.props.children === translations['conn.launchGame']);
  assert(launch);
  await launch.props.onClick();
  assert.equal(JSON.stringify(requests), JSON.stringify([['/api/game/launch', {method: 'POST'}]]));
  tree = render();
  assert(JSON.stringify(tree).includes(translations['conn.launch.game_running']));
  assert(nodes(tree).some(node => node.props?.role === 'status'));
  platform = 'win32';
  tree = render();
  assert(JSON.stringify(tree).includes(translations['conn.accessDeniedBody']));
  assert.equal(nodes(tree).filter(node => node.type === 'button').length, 2);
  platform = null;
  assert(JSON.stringify(render()).includes(translations['conn.accessDeniedPendingBody']));

  // Status-driven platform detection when launcher platform is pending
  context.Gd = () => ({connError: 'access_denied', clearConnError: () => {}, connect: () => {}, status: {ready: false, platform: 'darwin'}});
  let statusTree = render();
  assert(JSON.stringify(statusTree).includes(translations['conn.macosAccessDeniedBody']));
  assert(!JSON.stringify(statusTree).includes('Windows'));

  // Status response reporting access_denied directly
  context.Gd = () => ({connError: null, clearConnError: () => {}, connect: () => {}, status: {ready: false, error_code: 'access_denied', platform: 'darwin'}});
  let statusErrTree = render();
  assert(JSON.stringify(statusErrTree).includes(translations['conn.macosAccessDeniedBody']));
  assert(!JSON.stringify(statusErrTree).includes('Windows'));

  error = null;
  context.Gd = () => ({connError: error, clearConnError: () => {error = null;}, connect: () => {}});
  assert.equal(render(), null);
}
console.log('Game launch recovery renderer regressions passed');
