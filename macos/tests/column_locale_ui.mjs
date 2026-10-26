// Run shipped column headings, tooltips and Advanced filter names with HTTP payloads.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../fmsh/frontend/dist/assets/index-Cvmv7E2F.js', import.meta.url), 'utf8');
const {languages, catalog, fields} = JSON.parse(fs.readFileSync(0, 'utf8'));
const section = (start, end) => {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `shipped section: ${start}`);
  return source.slice(first, last);
};
let language = 'en';
const context = vm.createContext({
  fetch: async route => ({ok: true, json: async () => languages[decodeURIComponent(route.split('/').at(-1))]}),
  Ae: {addResourceBundle() {}, t: () => ''}, rt: () => language,
  Xm: {}, zm: key => key,
});
vm.runInContext(section('var it=new Set,at={};', 'function ct(e){localStorage'), context);
vm.runInContext(section('function Az(', 'function Mz('), context);
vm.runInContext(section('function mB(', 'function gB('), context);
const columns = [...catalog.current, ...catalog.sections.flatMap(section => section.columns)];
const general = {
  apps_total: ['Total Appearances', 'Apps'], apps_starts: ['Starting Appearances', 'St Apps'],
  apps_sub: ['Sub Appearances', 'Sub'], minutes: ['Minutes', 'Mins'],
  avg_rating: ['Average Rating', 'Av Rat'], goals: ['Goals', 'Gls'], assists: ['Assists', 'Ast'],
  xg: ['Expected Goals (xG)', 'xG'], xa: ['Expected Assists (xA)', 'xA'],
};
for (language of ['en', 'pt', 'qa']) {
  assert.equal(await context.st(language), true, 'language loads through shipped loader');
  const dictionary = languages[language].colunas;
  for (const column of columns) {
    if (!column.tkey) continue;
    const expected = dictionary[`${column.tkey}.nome`] || (language !== 'pt' && column.labelEn) || column.label;
    const short = dictionary[`${column.tkey}.sigla`] || (language !== 'pt' && column.shortEn) || column.short;
    assert.equal(context.mB(column, language), expected, `${language}: heading tooltip ${column.key}`);
    assert.equal(context.hB(column, language), short, `${language}: heading abbreviation ${column.key}`);
    assert.equal(context.jz(column, column.key, language !== 'pt'), expected, `${language}: filter label ${column.key}`);
  }
  for (const field of fields.filter(field => field.tkey)) {
    const expected = dictionary[`${field.tkey}.nome`] || (language !== 'pt' && field.labelEn) || field.label;
    assert.equal(context.jz(field, field.key, language !== 'pt'), expected, `${language}: Advanced ${field.key}`);
  }
  if (language === 'en') {
    for (const [key, [name, short]] of Object.entries(general)) {
      const column = catalog.current.find(column => column.key === key);
      assert.equal(context.mB(column, language), name, key);
      assert.equal(context.hB(column, language), short, key);
    }
    for (const [key, name] of [['golsnacarreira', 'Career Goals'], ['passesdecisivos', 'Key Passes'], ['passesdecisivos90', 'Key Passes /90']]) {
      const column = columns.find(column => column.tkey === key);
      assert(column, `${key}: real catalog translation key exists`);
      assert.equal(context.mB(column, language), name);
    }
  }
  if (language === 'qa') {
    const goals = catalog.current.find(column => column.key === 'goals');
    assert.equal(context.mB(goals, language), 'QA goals');
    assert.equal(context.hB(goals, language), 'QG');
  }
  const missing = {key: 'future_stat', tkey: 'missing', label: 'Estatística', short: 'Est', labelEn: 'Statistic', shortEn: 'Stat'};
  assert.equal(context.mB(missing, language), language === 'pt' ? 'Estatística' : 'Statistic');
  assert.equal(context.hB(missing, language), language === 'pt' ? 'Est' : 'Stat');
  assert.equal(context.jz(missing, missing.key, language !== 'pt'), language === 'pt' ? 'Estatística' : 'Statistic');
  assert.equal(context.mB({key: 'unknown', label: 'Original'}, language), 'Original');
}
// Preferences can change the active language without a browser reload.
language = 'en';
assert.equal(context.mB(catalog.current.find(column => column.key === 'goals'), language), 'Goals');
console.log('Column locale renderer passed');
