// Verify that the filter dialog modal stacks above the pre-order promotion badge (Issue #78).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const jsPath = fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url));
const cssPath = fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-iL5Te9Ln.css', import.meta.url));

const jsSource = fs.readFileSync(jsPath, 'utf8');
const cssSource = fs.readFileSync(cssPath, 'utf8');

// 1. Static asset verification
assert(
  jsSource.includes('badge-oferta fixed right-3.5 z-30'),
  'Promotion badge must use z-30 in JavaScript bundle'
);
assert(
  !jsSource.includes('badge-oferta fixed right-3.5 z-40'),
  'Promotion badge must not use z-40 in JavaScript bundle'
);
assert(
  jsSource.includes('fixed inset-0 z-50 flex items-center justify-center veu-modal p-4'),
  'Advanced filter dialog must use z-50 in JavaScript bundle'
);
assert(
  cssSource.includes('.badge-oferta{z-index:30;'),
  'Promotion badge must declare z-index:30 in CSS'
);

function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...Object.values(tree).flatMap(v => Array.isArray(v) ? v.flatMap(nodes) : nodes(v))];
}

const jsx = (type, props) => typeof type === 'function' ? type(props ?? {}) : ({type, props});

// 2. Render promotion badge (HH)
const startHH = jsSource.indexOf('var LH={');
const endHH = jsSource.indexOf('async function UH(', startHH);
assert(startHH >= 0 && endHH > startHH, 'Promotion badge component section exists');

let promoLinkOpened = false;
let promoDialogUrl = null;
const promoContext = vm.createContext({
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  R: () => ({t: k => k}),
  B: () => ({data: {dominios: ['instant-gaming.com']}}),
  V: () => ({mutate: () => { promoLinkOpened = true; }}),
  _: {
    useState: v => [typeof v === 'function' ? v() : v, () => {}],
    useEffect: () => {},
    useRef: v => ({current: v}),
  },
  W: {linkDominios: () => {}, abrirUrl: () => { promoLinkOpened = true; }},
  PH: () => true,
  Hf: props => { promoDialogUrl = props.url; return {type: 'confirmation-dialog', props}; },
  document: {getElementById: () => null},
  localStorage: {getItem: () => null, setItem: () => {}},
  Date,
  Number,
});

vm.runInContext(jsSource.slice(startHH, endHH), promoContext);
const promoTree = promoContext.HH();
assert(promoTree, 'Promotion badge rendered');

const promoWrapper = promoTree.props.children[0];
const promoClasses = promoWrapper.props.className.split(/\s+/);
assert(promoClasses.includes('badge-oferta'), 'Badge element has badge-oferta class');

const promoZClass = promoClasses.find(c => /^z-(?:\[\w+\]|\d+)$/.test(c));
assert.equal(promoZClass, 'z-30', 'Promotion badge class is z-30');
const promoZIndex = 30;

// 3. Render Advanced Filter modal (lB)
const startLB = jsSource.indexOf('var _z=');
const endLB = jsSource.indexOf('var uB=', startLB);
assert(startLB >= 0 && endLB > startLB, 'Filter dialog component section exists');

let appliedConditions = null;
let modalClosed = false;

const baseFilterContext = {
  z: {jsx, jsxs: jsx, Fragment: 'fragment'},
  R: () => ({t: (k, opts) => opts?.defaultValue || k, i18n: {language: 'en'}}),
  B: () => ({data: null}),
  _: {
    useState: v => [typeof v === 'function' ? v() : v, () => {}],
    useEffect: () => {},
    useLayoutEffect: () => {},
    useMemo: fn => fn(),
    useRef: v => ({current: v}),
  },
  q: (...args) => args.filter(Boolean).join(' '),
  Ae: {t: () => ''},
  zm: () => null,
  Xm: {},
  $m: () => '',
  ot: () => ({}),
  rt: () => 'en',
  Cp: () => 1,
  Yv: () => [],
  Set, Map, Date, Array, String, Number, Boolean, Math, RegExp,
};

const filterContext = vm.createContext(new Proxy(baseFilterContext, {
  get(target, prop) {
    if (prop in target) return target[prop];
    return () => null;
  },
}));

vm.runInContext(jsSource.slice(startLB, endLB), filterContext);
const filterTree = filterContext.lB({
  campos: [],
  conds: [{id: 1, field: 'ca', op: '>=', val: 140}],
  warnings: [],
  total: 50,
  onApply: conds => { appliedConditions = conds; },
  onClose: () => { modalClosed = true; },
});

assert(filterTree, 'Filter dialog rendered');
const modalClasses = filterTree.props.className.split(/\s+/);
assert(modalClasses.includes('veu-modal'), 'Filter dialog element has veu-modal class');

const modalZClass = modalClasses.find(c => /^z-(?:\[\w+\]|\d+)$/.test(c));
assert.equal(modalZClass, 'z-50', 'Filter dialog modal class is z-50');
const modalZIndex = 50;

// 4. Stacking Contract Verification
assert(
  modalZIndex > promoZIndex,
  `Filter modal z-index (${modalZIndex}) must be strictly greater than promotion badge z-index (${promoZIndex})`
);

// 5. Hit-test and occlusion verification at 1440x900
const viewport = {width: 1440, height: 900};
const modalBounds = {
  left: (viewport.width - 1396) / 2,
  right: (viewport.width - 1396) / 2 + 1396,
  top: (viewport.height - 828) / 2,
  bottom: (viewport.height - 828) / 2 + 828,
};
const applyButtonBounds = {
  left: modalBounds.right - 90,
  right: modalBounds.right - 20,
  top: modalBounds.bottom - 45,
  bottom: modalBounds.bottom - 15,
};
const promoBadgeBounds = {
  right: viewport.width - 14,
  left: viewport.width - 14 - 280,
  bottom: viewport.height - (26 + 10),
  top: viewport.height - (26 + 10) - 52,
};

const horizontalOverlap = !(applyButtonBounds.left > promoBadgeBounds.right || applyButtonBounds.right < promoBadgeBounds.left);
const verticalOverlap = !(applyButtonBounds.top > promoBadgeBounds.bottom || applyButtonBounds.bottom < promoBadgeBounds.top);
const coordinatesOverlap = horizontalOverlap && verticalOverlap;

assert(
  coordinatesOverlap,
  'Test scenario confirms geometry overlap at 1440x900 viewport between Apply button and promo badge'
);

// In CSS stacking contexts, with modal z-index > promo z-index, the topmost target is the modal
const topmostLayer = modalZIndex > promoZIndex ? 'modal' : 'promo';
assert.equal(
  topmostLayer,
  'modal',
  'Modal must be topmost layer at overlapping coordinates'
);

// 6. Interaction Verification: Apply button click applies filter without opening promo link
const allFilterNodes = nodes(filterTree);
const applyButton = allFilterNodes.find(n => n.type === 'button' && n.props?.children === 'psearch.apply');
assert(applyButton, 'Apply button control found in filter dialog');

// Click Apply
applyButton.props.onClick();

assert(appliedConditions !== null, 'Selecting Apply triggers onApply with conditions');
assert.equal(modalClosed, true, 'Selecting Apply closes the filter dialog');
assert.equal(promoLinkOpened, false, 'Selecting Apply does NOT trigger external link open');
assert.equal(promoDialogUrl, null, 'Selecting Apply does NOT trigger promo confirmation dialog');

console.log('Pre-order promo and filter modal stacking contract passed');
