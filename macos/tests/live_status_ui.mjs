// Run the shipped status hook, connection provider and Save Season renderer.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url), 'utf8');
const section = (start, end) => {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert(from >= 0 && to > from, start);
  return source.slice(from, to);
};
const connected = {
  ready: true, sid: 999999999, save_name: 'Career A', game_date: '2027-06-30',
  club: 'Club A', manager: 'Manager A', build: 'qa', read_at: '2026-10-26T10:00:00',
  savegame_id: 'a', session_nonce: 1, fm_running: true,
};
const disconnected = Object.fromEntries(Object.keys(connected).map(key => [key, null]));
Object.assign(disconnected, {ready: false, fm_running: true, save_changed: true});
const cache = new Map([['live', connected], ['snapshots', [{id: 7, name: 'Saved season'}]]]);
const options = new Map();
let response = disconnected, requestError = null, connection, stateIndex = 0;
const poll = signal => options.get('status').queryFn({signal: signal ?? new AbortController().signal});
const states = {connection: [], save: []};
let state = states.connection;
const jsx = (type, props) => ({type, props});
const queryClient = {
  setQueryData: (key, value) => cache.set(key[0], value),
  invalidateQueries() {},
};
const context = vm.createContext({
  z: {jsx, jsxs: jsx, Fragment: 'fragment'}, Wd: {Provider: 'connection'},
  _: {
    useState: initial => {
      const index = stateIndex++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = value; }];
    },
    useRef: value => ({current: value}), useEffect() {},
  },
  Ga: () => queryClient, Kn: () => () => {},
  B: config => {
    options.set(config.queryKey[0], config);
    return {data: cache.get(config.queryKey[0]), isLoading: false};
  },
  W: {live() {}, job() {}, status: async () => {
    if (requestError) throw requestError;
    return response;
  }},
  Od: () => ({}), Bd: () => ({}), Vd: () => ({}), Hd: () => ({}), Ud: () => ({}),
  Dd: ['carreiras'], Md: () => true,
  Gd: () => connection, R: () => ({t: key => key}),
  q: (...values) => values.filter(Boolean).join(' '), Gf: '',
  Ep: 'game', Y: 'button', iU: 'connection-detail', JH: 'scope-detail', Af: 'limit',
  sm: () => false, om: () => 'recent',
});
vm.runInContext(section('function Ld(){return B({queryKey:[`live`]', 'function Bd()'), context);
vm.runInContext(section('function Kd({children:e})', 'var qd=`fmsh_db_snap`'), context);
vm.runInContext(section('function aU()', 'var oU='), context);
const renderConnection = () => {
  state = states.connection;
  stateIndex = 0;
  connection = context.Kd({children: null}).props.value;
  return connection;
};
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...Object.values(tree).flatMap(nodes)];
const renderSave = () => { state = states.save; stateIndex = 0; return context.aU(); };
const captureButton = tree => nodes(tree).find(node => node.type === 'button' && node.props.children === 'btn.capture');

assert.equal(renderConnection().connected, true);
assert.equal(captureButton(renderSave()).props.disabled, false);
assert.equal(options.get('status').refetchInterval, 30000);
assert.equal(options.get('status').refetchIntervalInBackground, true);
await poll();
cache.set('status', response);
assert.equal(renderConnection().connected, false);
assert.equal(connection.pill, 'off');
assert.equal(connection.status.save_changed, true);
for (const key of ['club', 'manager', 'save_name', 'game_date', 'read_at', 'build', 'sid', 'savegame_id', 'session_nonce']) {
  assert.equal(connection.live[key], null, `${key} cleared in shared state`);
}
let tree = renderSave();
assert.equal(captureButton(tree).props.disabled, true);
assert(nodes(tree).some(node => node.type === 'button' && node.props.children === 'top.connect'));
assert(!JSON.stringify(tree).includes('Career A'));
// Navigation remounts consumers without restoring old live data or removing saved seasons.
renderConnection();
assert.equal(captureButton(renderSave()).props.disabled, true);
assert.equal(cache.get('snapshots')[0].name, 'Saved season');

response = {...connected, save_name: 'Career B', savegame_id: 'b', session_nonce: 2};
await poll();
cache.set('status', response);
assert.equal(renderConnection().connected, true);
assert.equal(connection.live.save_name, 'Career B');
assert.equal(captureButton(renderSave()).props.disabled, false);
requestError = new Error('network unavailable');
await assert.rejects(poll(), /network unavailable/);
assert.equal(cache.get('live'), response, 'failed poll does not write invalid data');
requestError = null;
const cancelled = new AbortController();
cancelled.abort();
response = connected;
await assert.rejects(poll(cancelled.signal), {name: 'AbortError'});
assert.equal(cache.get('live').save_name, 'Career B', 'cancelled old status cannot restore Career A');
response = {...disconnected, fm_running: false, save_changed: false};
await poll();
cache.set('status', response);
assert.equal(renderConnection().connected, false);
assert.equal(captureButton(renderSave()).props.disabled, true);
console.log('Live status UI regression checks passed');
