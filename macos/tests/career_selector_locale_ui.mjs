// Issue #76: Career selector displays properly translated season count and never raw key.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const jsPath = fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url));
const jsSource = fs.readFileSync(jsPath, 'utf8');

// 1. Static asset verification
assert(
  jsSource.includes('{count:g.temporadas??g.n_temporadas??0}'),
  'Sidebar career selector must safely provide integer count'
);
assert(
  jsSource.includes('{count:n.temporadas??n.n_temporadas??0}'),
  'Tray menu career selector must safely provide integer count'
);
assert(
  jsSource.includes('children:e.temporadas??e.n_temporadas'),
  'Career dropdown list must safely display season count'
);

// 2. Read and verify locale dictionaries
function parseInterfaceTxt(locale) {
  const filePath = fileURLToPath(new URL(`../fmsh/idiomas/${locale}/interface.txt`, import.meta.url));
  const content = fs.readFileSync(filePath, 'utf8');
  const dict = {};
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx !== -1) {
      dict[trimmed.slice(0, eqIdx).trim()] = trimmed.slice(eqIdx + 1).trim();
    }
  }
  return dict;
}

const locales = ['en', 'pt', 'de', 'es', 'fr', 'tr'];
const dicts = {};
for (const loc of locales) {
  dicts[loc] = parseInterfaceTxt(loc);
  assert(dicts[loc]['carreira.seasons_one'], `${loc} must have carreira.seasons_one`);
  assert(dicts[loc]['carreira.seasons_other'], `${loc} must have carreira.seasons_other`);
  assert(dicts[loc]['carreira.seasons'], `${loc} must have base fallback carreira.seasons`);
}

assert.equal(dicts.en['carreira.seasons_one'], '1 season');
assert.equal(dicts.en['carreira.seasons_other'], '{{count}} seasons');
assert.equal(dicts.en['carreira.seasons'], '{{count}} seasons');

assert.equal(dicts.pt['carreira.seasons_one'], '1 temporada');
assert.equal(dicts.pt['carreira.seasons_other'], '{{count}} temporadas');
assert.equal(dicts.pt['carreira.seasons'], '{{count}} temporadas');

assert.equal(dicts.de['carreira.seasons_one'], '1 Saison');
assert.equal(dicts.de['carreira.seasons_other'], '{{count}} Saisons');
assert.equal(dicts.de['carreira.seasons'], '{{count}} Saisons');

assert.equal(dicts.es['carreira.seasons_one'], '1 temporada');
assert.equal(dicts.es['carreira.seasons_other'], '{{count}} temporadas');
assert.equal(dicts.es['carreira.seasons'], '{{count}} temporadas');

assert.equal(dicts.fr['carreira.seasons_one'], '1 saison');
assert.equal(dicts.fr['carreira.seasons_other'], '{{count}} saisons');
assert.equal(dicts.fr['carreira.seasons'], '{{count}} saisons');

assert.equal(dicts.tr['carreira.seasons_one'], '1 sezon');
assert.equal(dicts.tr['carreira.seasons_other'], '{{count}} sezon');
assert.equal(dicts.tr['carreira.seasons'], '{{count}} sezon');

// 3. Helper to simulate i18next translation resolution
function createT(dict) {
  return function t(key, opts = {}) {
    const count = opts.count;
    let target = key;
    if (count !== undefined && count !== null) {
      if (count === 1 && dict[key + '_one']) {
        target = key + '_one';
      } else if (dict[key + '_other']) {
        target = key + '_other';
      }
    }
    let res = dict[target] ?? dict[key] ?? key;
    for (const [k, v] of Object.entries(opts)) {
      res = res.replace(new RegExp('{{' + k + '}}', 'g'), v !== undefined ? v : '');
    }
    return res;
  };
}

// Check translation formatting
const tEn = createT(dicts.en);
const tPt = createT(dicts.pt);

assert.equal(tEn('carreira.seasons', {count: 1}), '1 season');
assert.equal(tEn('carreira.seasons', {count: 2}), '2 seasons');
assert.equal(tEn('carreira.seasons', {count: 8}), '8 seasons');
assert.equal(tEn('carreira.seasons', {count: 0}), '0 seasons');

assert.equal(tPt('carreira.seasons', {count: 1}), '1 temporada');
assert.equal(tPt('carreira.seasons', {count: 2}), '2 temporadas');
assert.equal(tPt('carreira.seasons', {count: 8}), '8 temporadas');
assert.equal(tPt('carreira.seasons', {count: 0}), '0 temporadas');

// Fallback when count is undefined or missing must never return raw translation key
assert(!tEn('carreira.seasons', {count: undefined}).includes('carreira.seasons'));
assert(!tPt('carreira.seasons', {count: undefined}).includes('carreira.seasons'));
assert(!tEn('carreira.seasons').includes('carreira.seasons'));
assert(!tPt('carreira.seasons').includes('carreira.seasons'));

// 4. Component extraction and VM execution for sidebar career selector
const seasonIdx = jsSource.indexOf('carreira.seasons');
const compStart = jsSource.lastIndexOf('function Np()', seasonIdx);
assert(compStart >= 0, 'Sidebar component Np start found');
const nextComp = jsSource.indexOf('var Pp=', compStart);
assert(nextComp > compStart, 'Sidebar component Np end found');
const npCode = jsSource.slice(compStart, nextComp);

const jsx = (type, props) => ({type, props});

function renderSidebar(careerPayload, dict, openDropdown = false) {
  const t = createT(dict);
  let stateCall = 0;
  const context = vm.createContext({
    z: {jsx, jsxs: jsx, Fragment: 'fragment'},
    _: {
      useState: (init) => {
        stateCall++;
        if (openDropdown && stateCall === 3) return [true, () => {}];
        return [typeof init === 'function' ? init() : init, () => {}];
      },
      useEffect: () => {},
    },
    R: () => ({t}),
    Kn: () => () => {},
    Ga: () => ({setQueryData: () => {}}),
    Gd: () => ({connected: false}),
    W: {version: () => ({}), summary: () => ({})},
    B: () => ({data: {}}),
    ap: () => ({data: {}}),
    of: () => ({data: {}}),
    kd: () => [[]],
    Od: () => ({data: careerPayload}),
    V: () => ({mutate: () => {}, isPending: false}),
    rp: () => ({iniciar: () => {}, modal: null}),
    q: (...args) => args.filter(Boolean).join(' '),
    Op: 'fmsh_sidebar_collapsed',
    Dd: ['carreiras'],
    af: ['acesso'],
    jp: 'btn-class',
    Ap: 'active-class',
    kp: 'link-class',
    Mp: () => null,
    bp: (props) => ({type: 'ClubBadge', props}),
    Ep: (props) => ({type: 'FmVersion', props}),
    pu: 'arrow-icon',
    ml: 'icon', Jc: 'icon', ol: 'icon', Tl: 'icon', Lu: 'icon',
    Zc: 'icon', ru: 'icon', nl: 'icon', ll: 'icon', zf: 'icon',
    Kl: 'icon', Dp: [], xl: 'icon', iu: 'icon', Gl: 'icon',
    $l: 'icon', Gc: 'icon', Yc: 'icon', dl: 'icon', Sl: 'icon',
    yu: 'icon', hi: 'link', Cl: 'icon', vl: 'icon', Au: 'icon',
    wl: 'icon', cu: 'icon', ep: () => null, zl: 'icon', ql: 'icon',
    _l: 'icon', Iu: 'icon', Xc: 'icon', mu: 'icon', sf: () => '',
    localStorage: {getItem: () => '0', setItem: () => {}},
  });

  vm.runInContext(npCode + '; this.Np = Np;', context);
  return context.Np();
}

function text(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node !== 'object') return String(node);
  if (Array.isArray(node)) return node.map(text).join(' ');
  return text(node.props?.children);
}

// Test with full API response payload
const payload8 = {
  carreiras: [
    {id: 'career_default', nome: 'Hull City', ativa: true, temporadas: 8, n_temporadas: 8, ultima: '2026-02-07'},
    {id: 'qa_test', nome: 'Leeds', ativa: false, temporadas: 1, n_temporadas: 1, ultima: '2026-07-01'}
  ]
};

const renderedEn = text(renderSidebar(payload8, dicts.en));
const renderedPt = text(renderSidebar(payload8, dicts.pt));

assert(renderedEn.includes('8 seasons'), 'English sidebar renders "8 seasons"');
assert(renderedPt.includes('8 temporadas'), 'Portuguese sidebar renders "8 temporadas"');
assert(!renderedEn.includes('carreira.seasons'), 'English sidebar must not contain raw key');
assert(!renderedPt.includes('carreira.seasons'), 'Portuguese sidebar must not contain raw key');

// Test with fallback when only n_temporadas is present
const payloadFallback = {
  carreiras: [
    {id: 'career_default', nome: 'Hull City', ativa: true, n_temporadas: 3}
  ]
};

const renderedFallback = text(renderSidebar(payloadFallback, dicts.en));
assert(renderedFallback.includes('3 seasons'), 'Fallback properly renders 3 seasons');
assert(!renderedFallback.includes('carreira.seasons'), 'Fallback must not contain raw key');

// Test dropdown list displays season count
const renderedDropdown = text(renderSidebar(payload8, dicts.en, true));
assert(renderedDropdown.includes('Hull City') && renderedDropdown.includes('8'), 'Dropdown displays 8');
assert(renderedDropdown.includes('Leeds') && renderedDropdown.includes('1'), 'Dropdown displays 1');

console.log('Career selector locale UI contract passed');
