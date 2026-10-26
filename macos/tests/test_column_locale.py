"""Issue #67: HTTP statistics metadata must use the selected column dictionary."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_startup_contracts as fixtures
import idiomas


class ColumnLocaleTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.StartupContractTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.StartupContractTests.tearDownClass.__func__)
    request = fixtures.StartupContractTests.request

    def test_statistics_names_abbreviations_and_filter_labels_in_selected_language(self):
        with tempfile.TemporaryDirectory() as folder:
            language = Path(folder) / 'qa'
            language.mkdir()
            (language / 'interface.txt').write_text('_idioma.nome = QA\n', encoding='utf-8')
            (language / 'colunas.txt').write_text('gols.nome = QA goals\ngols.sigla = QG\n', encoding='utf-8')
            with patch.object(idiomas.paths, 'idiomas_dir', return_value=folder):
                idiomas._CACHE.clear()
                try:
                    languages = {}
                    for code in ('en', 'pt', 'qa'):
                        status, languages[code] = self.request('/api/idiomas/' + code)
                        self.assertEqual(status, 200)
                    status, catalog = self.request('/api/moneyball/columns?group=all')
                    self.assertEqual(status, 200)
                    status, search = self.request('/api/search/fields?group=all')
                    self.assertEqual(status, 200)
                    check = subprocess.run(['node', str(Path(__file__).with_name('column_locale_ui.mjs'))],
                                           input=json.dumps({'languages': languages, 'catalog': catalog,
                                                             'fields': search['fields']}),
                                           text=True, capture_output=True, check=False)
                    self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                    self.assertIn('Column locale renderer passed', check.stdout)
                finally:
                    idiomas._CACHE.clear()


if __name__ == '__main__':
    unittest.main()
