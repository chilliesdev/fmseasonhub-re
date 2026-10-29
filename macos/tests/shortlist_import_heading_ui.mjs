// Issue #87: Shortlist import heading duplicates the FM prefix.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';

const jsPath = fileURLToPath(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url));
const jsSource = fs.readFileSync(jsPath, 'utf8');

// 1. Static asset verification: shortlist import popover component invokes lista.naPasta with {jogo: e.jogo}
assert(
  jsSource.includes("t(`lista.naPasta`,{jogo:e.jogo})") || jsSource.includes('t("lista.naPasta",{jogo:e.jogo})'),
  'Popover header must translate lista.naPasta with jogo parameter'
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

const expectedResults = {
  en: 'In the Football Manager 26 folder',
  pt: 'Na pasta do Football Manager 26',
  de: 'Im Football Manager 26-Ordner',
  fr: 'Dans le dossier du Football Manager 26',
  es: 'En la carpeta de Football Manager 26',
  tr: 'Football Manager 26 klasöründe',
};

const locales = ['en', 'pt', 'de', 'es', 'fr', 'tr'];
for (const loc of locales) {
  const dict = parseInterfaceTxt(loc);
  const template = dict['lista.naPasta'];
  assert(template, `${loc} must define lista.naPasta`);
  assert(!template.includes('FM{{jogo}}'), `${loc} template must not contain FM{{jogo}}`);

  const interpolated = template.replace('{{jogo}}', 'Football Manager 26');
  assert.equal(
    interpolated,
    expectedResults[loc],
    `${loc} interpolated heading mismatch: expected "${expectedResults[loc]}", got "${interpolated}"`
  );
  assert(!interpolated.includes('FMFootball'), `${loc} heading must not contain duplicated "FMFootball"`);
}

console.log('Shortlist import heading UI contract passed');
