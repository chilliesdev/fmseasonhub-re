// Verify player profile height tooltip formatting (Issue #82).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const jsPath = fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url));
const jsSource = fs.readFileSync(jsPath, 'utf8');

// 1. Static asset verification
assert(
  jsSource.includes('et.map(([e,t,n,r])=>(0,z.jsxs)(`div`,{title:`${e}: ${n||r||t}`,'),
  'Profile overview list must support fallback title text parameter (r)'
);
assert(
  jsSource.includes('Qe?s(`pf.altura.ajuda`,{nome:le.find(e=>e.sid===ke)?.name||``,antes:Ze}):``,Xe?`${Xe} cm`:`—`]'),
  'Height entry must declare human-readable text fallback for tooltip title'
);
assert(
  !jsSource.includes('et.map(([e,t,n])=>(0,z.jsxs)(`div`,{title:`${e}: ${n||t}`,'),
  'Legacy interpolation exposing object serialization must not exist'
);

// 2. Component execution in VM
const startKP = jsSource.indexOf('function kP(');
const endKP = jsSource.indexOf('function AP(', startKP);
assert(startKP >= 0 && endKP > startKP, 'Player profile modal component (kP) exists');

const jsx = (type, props) => ({type, props});

function renderProfileModal({height_cm, comparison_height = null, comparison_name = 'Previous Season'}) {
  const playerData = {
    identity: {height_cm, club_id: 1, position: 'ST'},
    stats: {},
    profile: {birth_date: '2000-01-01', squad_number: 9, cur_rep: 5000, nationality: 'Brazil'}
  };

  const seasons = [{sid: 1, carreira_id: 'c1', height_cm}];
  if (comparison_height !== null) {
    seasons.push({sid: 2, carreira_id: 'c1', height_cm: comparison_height, name: comparison_name});
  }

  const baseContext = {
    z: {jsx, jsxs: jsx, Fragment: 'fragment'},
    R: () => ({
      t: (key, opts) => {
        if (key === 'pf.f.height') return 'Height';
        if (key === 'pf.altura.ajuda') return `Difference since ${opts?.nome} (${opts?.antes} cm)`;
        return opts ? `${key}:${JSON.stringify(opts)}` : key;
      },
      i18n: {language: 'en'}
    }),
    B: (opts) => {
      const qk = opts?.queryKey;
      if (qk && qk[0] === 'player-temporadas') return {data: seasons};
      if (qk && qk[0] === 'player') return {data: playerData, isLoading: false, isError: false};
      return {data: null, isLoading: false, isError: false};
    },
    w_: {createPortal: e => e},
    rf: () => ({ clube: () => null }),
    qm: () => [],
    Jg: () => [],
    Bg: [],
    BN: () => comparison_height !== null ? 2 : 1,
    mg: (p, t) => ['player', p, t],
    hg: () => ['top20'],
    $h: () => 'ST',
    eg: () => [],
    wP: {amplo: {fichaY: '', fichaRot: '', fichaVal: ''}, compacto: {fichaY: '', fichaRot: '', fichaVal: ''}},
    pP: () => 1,
    hP: () => true,
    wd: () => 'career_1',
    aP: e => typeof e === 'number' ? e : parseFloat(String(e ?? '')) || 0,
    sP: e => String(e),
    lP: () => '7500',
    Sv: () => ({}),
    Um: () => ({}),
    Bm: () => '',
    Em: () => [],
    _: {
      useState: v => [typeof v === 'function' ? v() : v, () => {}],
      useEffect: () => {},
      useLayoutEffect: () => {},
      useMemo: fn => fn(),
      useRef: v => ({current: {getBoundingClientRect: () => ({width: 500})}}),
      useCallback: fn => fn,
    },
    q: (...args) => args.filter(Boolean).join(' '),
    localStorage: {getItem: () => null, setItem: () => {}},
    window: {innerWidth: 1440, innerHeight: 900, addEventListener: () => {}, removeEventListener: () => {}},
    document: {querySelector: () => null, body: {}},
    Object, Set, Map, Date, Array, String, Number, Boolean, Math, RegExp,
  };

  const context = vm.createContext(new Proxy(baseContext, {
    get(target, prop) {
      if (prop in target) return target[prop];
      return () => null;
    },
  }));

  vm.runInContext(jsSource.slice(startKP, endKP), context);
  const tree = context.kP({sid: 1, uid: 100});

  function nodes(tree) {
    if (tree == null || typeof tree !== 'object') return [];
    return [tree, ...Object.values(tree).flatMap(value => Array.isArray(value) ? value.flatMap(nodes) : nodes(value))];
  }

  const all = nodes(tree);
  const divsWithTitle = all.filter(n => n.props?.title);
  const heightDiv = divsWithTitle.find(d => d.props.title.startsWith('Height:'));
  return {
    title: heightDiv?.props?.title,
    allTitles: divsWithTitle.map(d => d.props.title)
  };
}

// Case 1: Valid height with no comparison difference
const validHeight = renderProfileModal({height_cm: 188});
assert.equal(validHeight.title, 'Height: 188 cm', 'Tooltip title must format valid height as human-readable string');
assert(!validHeight.title.includes('[object Object]'), 'Tooltip must not contain object serialization');

// Case 2: Zero or null height (missing data)
const missingHeightNull = renderProfileModal({height_cm: null});
assert.equal(missingHeightNull.title, 'Height: —', 'Tooltip title must format missing height as dash');
assert(!missingHeightNull.title.includes('[object Object]'), 'Tooltip must not contain object serialization');

const missingHeightZero = renderProfileModal({height_cm: 0});
assert.equal(missingHeightZero.title, 'Height: —', 'Tooltip title must format 0 cm height as dash');

// Case 3: Comparison mode with height difference
const comparisonDiff = renderProfileModal({height_cm: 188, comparison_height: 180, comparison_name: 'Previous Season'});
assert.equal(
  comparisonDiff.title,
  'Height: Difference since Previous Season (180 cm)',
  'Tooltip title in comparison mode must retain difference help text'
);
assert(!comparisonDiff.title.includes('[object Object]'), 'Tooltip must not contain object serialization');

// Case 4: Verify no title in profile modal exposes [object Object]
for (const title of validHeight.allTitles) {
  assert(!title.includes('[object Object]'), `Title "${title}" must not contain [object Object]`);
}

console.log('Player height tooltip formatting contract passed');
