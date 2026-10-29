// Verify portal feature cards i18n status labels (Issue #80).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const jsPath = fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url));
const jsSource = fs.readFileSync(jsPath, 'utf8');

// 1. Static asset verification
assert(
  !jsSource.includes('children:[e,n?` · em breve`:``]'),
  'Feature card badge must not hardcode Portuguese status label'
);
assert(
  jsSource.includes('s(`portal.soon`)'),
  'Feature card badge must interpolate localized portal.soon translation key'
);

// 2. Read live locale dictionaries
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

const enDict = parseInterfaceTxt('en');
const ptDict = parseInterfaceTxt('pt');

assert.equal(enDict['portal.soon'], 'Coming soon', 'English dictionary must map portal.soon to Coming soon');
assert.equal(ptDict['portal.soon'], 'em breve', 'Portuguese dictionary must map portal.soon to em breve');

// 3. Component extraction and VM execution
const startLL = jsSource.indexOf('function lL({tag:e,title:t,soon:n');
assert(startLL >= 0, 'Portal feature card component (lL) must be defined');
const endLL = jsSource.indexOf('function uL(', startLL);
assert(endLL > startLL, 'End boundary of lL component found');
const llCode = jsSource.slice(startLL, endLL);

const jsx = (type, props) => ({type, props});

function renderCard(props, currentDict) {
  const baseContext = {
    z: {jsx, jsxs: jsx},
    q: (...args) => args.filter(Boolean).join(' '),
    R: () => ({
      t: (key) => currentDict[key] || key,
    }),
  };

  const context = vm.createContext(baseContext);
  vm.runInContext(`${llCode}; this.lL = lL;`, context);
  return context.lL(props);
}

function extractBadgeText(tree) {
  // lL returns root div; second child is the badge div
  const rootChildren = tree.props.children;
  const badgeNode = rootChildren[1];
  assert(badgeNode && badgeNode.props && badgeNode.props.children, 'Badge node must exist');
  return badgeNode.props.children.join('');
}

// English test cases
const enCards = [
  {key: 'portal.moneyballTag', expectedTag: 'Analysis'},
  {key: 'portal.financesTag', expectedTag: 'Club'},
  {key: 'portal.shortlistTag', expectedTag: 'Market'},
];

for (const {key, expectedTag} of enCards) {
  const tag = enDict[key];
  assert.equal(tag, expectedTag, `English tag for ${key} must match ${expectedTag}`);

  // Card with soon: true
  const treeSoon = renderCard({tag, title: 'Title', soon: true}, enDict);
  const badgeSoon = extractBadgeText(treeSoon);
  assert.equal(badgeSoon, `${expectedTag} · Coming soon`, `English soon badge for ${expectedTag}`);

  // Card with soon: false (active feature)
  const treeActive = renderCard({tag, title: 'Title', soon: false}, enDict);
  const badgeActive = extractBadgeText(treeActive);
  assert.equal(badgeActive, expectedTag, `English active badge for ${expectedTag}`);
}

// Portuguese test cases
const ptCards = [
  {key: 'portal.moneyballTag', expectedTag: 'Análise'},
  {key: 'portal.financesTag', expectedTag: 'Clube'},
  {key: 'portal.shortlistTag', expectedTag: 'Mercado'},
];

for (const {key, expectedTag} of ptCards) {
  const tag = ptDict[key];
  assert.equal(tag, expectedTag, `Portuguese tag for ${key} must match ${expectedTag}`);

  // Card with soon: true
  const treeSoon = renderCard({tag, title: 'Title', soon: true}, ptDict);
  const badgeSoon = extractBadgeText(treeSoon);
  assert.equal(badgeSoon, `${expectedTag} · em breve`, `Portuguese soon badge for ${expectedTag}`);

  // Card with soon: false (active feature)
  const treeActive = renderCard({tag, title: 'Title', soon: false}, ptDict);
  const badgeActive = extractBadgeText(treeActive);
  assert.equal(badgeActive, expectedTag, `Portuguese active badge for ${expectedTag}`);
}

console.log('Portal feature cards UI contract passed');
