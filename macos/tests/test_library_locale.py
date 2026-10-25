"""Factory preset titles through HTTP and the shipped Library/apply renderer."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

import test_library_paths as fixtures
import server
import settings


class LibraryLocaleTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.LibraryPathTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.LibraryPathTests.tearDownClass.__func__)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.library = self.root / "Biblioteca"
        self.library.mkdir()
        for target, name, value in (
            (server, "_get_biblioteca_dir", lambda: self.library),
            (settings, "SETTINGS_PATH", str(self.root / "settings.json")),
        ):
            patched = patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def request(self, route="", raw=False):
        with urllib.request.urlopen(self.base + "/api/biblioteca" + route, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read() if raw else json.load(response)

    def test_factory_metadata_titles_and_raw_filter_contents_are_preserved(self):
        expected = {
            "listados-para-transferencia.fsh": ("Listados para transferência", "Transfer listed"),
            "agentes-livres.fsh": ("Agentes livres", "Free agents"),
            "contrato-acabando.fsh": ("Contrato acabando", "Contract running out"),
            "jovens-promessas.fsh": ("Jovens promessas (sub-21)", "Young prospects (u21)"),
        }
        before = {name: (server.FMSH_DIR / "src/presets_fabrica" / name).read_bytes()
                  for name in expected}
        listing = self.request()
        self.assertEqual(self.request("/listar"), listing)
        factories = {item["arquivo"]: item for item in listing["arquivos"] if item["fabrica"]}
        self.assertEqual(set(factories), set(expected))
        contents = {}
        for name, titles in expected.items():
            with self.subTest(name=name):
                self.assertEqual((factories[name]["nome"], factories[name]["nomeEn"]), titles)
                self.assertEqual(factories[name]["tipo"], "filtro")
                self.assertEqual(self.request(f"/{name}/bruto", raw=True), before[name])
                contents[name] = self.request(f"/{name}")
                self.assertEqual(contents[name], json.loads(before[name]))
                self.assertEqual((server.FMSH_DIR / "src/presets_fabrica" / name).read_bytes(), before[name])
        check = subprocess.run(["node", str(Path(__file__).with_name("library_locale_ui.mjs"))],
                               input=json.dumps({"listing": listing, "contents": contents}),
                               text=True, capture_output=True, check=False)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("Library locale renderer passed", check.stdout)

    def test_custom_filter_and_player_list_titles_remain_user_supplied(self):
        (self.library / "My tactics.fsh").write_text(json.dumps({"nome": "My tactics"}))
        (self.library / "My players.lsh").write_text(json.dumps({
            "nome": "My players", "jogadores": [{"uid": 1, "nome": "Player"}]}))
        custom = [item for item in self.request()["arquivos"] if not item["fabrica"]]
        self.assertEqual({item["arquivo"]: (item["nome"], item["nomeEn"]) for item in custom}, {
            "My tactics.fsh": ("My tactics", "My tactics"),
            "My players.lsh": ("My players", "My players"),
        })

    def test_missing_or_invalid_factory_titles_have_readable_fallbacks(self):
        presets = self.root / "src/presets_fabrica"
        presets.mkdir(parents=True)
        cases = [({}, ("Fallback Title", "Fallback Title")),
                 ({"nome": "Título"}, ("Título", "Título")),
                 ({"nomeEn": "English"}, ("Fallback Title", "English")),
                 ({"nome": "", "nomeEn": " "}, ("Fallback Title", "Fallback Title")),
                 ({"nome": [], "nomeEn": 31}, ("Fallback Title", "Fallback Title")),
                 ([], ("Fallback Title", "Fallback Title"))]
        with patch.object(server, "FMSH_DIR", self.root):
            for metadata, expected in cases:
                with self.subTest(metadata=metadata):
                    (presets / "fallback-title.fsh").write_text(json.dumps(metadata))
                    item = self.request()["arquivos"][0]
                    self.assertEqual((item["nome"], item["nomeEn"]), expected)
            for content in (b"not JSON", b"\xff"):
                (presets / "fallback-title.fsh").write_bytes(content)
                item = self.request()["arquivos"][0]
                self.assertEqual((item["nome"], item["nomeEn"]), ("Fallback Title", "Fallback Title"))
            with patch.object(Path, "read_text", side_effect=PermissionError("unreadable fixture")):
                item = self.request()["arquivos"][0]
                self.assertEqual((item["nome"], item["nomeEn"]), ("Fallback Title", "Fallback Title"))


if __name__ == "__main__":
    unittest.main()
