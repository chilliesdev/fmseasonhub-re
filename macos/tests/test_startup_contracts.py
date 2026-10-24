"""HTTP contracts consumed by the original shipped frontend during startup."""

import importlib
import json
from contextlib import closing
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import idiomas
import graphics
import server
import settings
import uvicorn


class StartupContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.listener.getsockname()[1]}"
        cls.srv = uvicorn.Server(uvicorn.Config(server.app, log_level="error"))
        cls.thread = threading.Thread(target=cls.srv.run, kwargs={"sockets": [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.srv.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.srv.started:
            raise RuntimeError("Contract test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.settings_path = self.root / "fmsh_settings.json"
        self.database = self.root / "fm26_snapshots.db"
        self.settings_patch = patch.object(settings, "SETTINGS_PATH", str(self.settings_path))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        database_patch = patch.object(server, "get_db_path", return_value=self.database)
        database_patch.start()
        self.addCleanup(database_patch.stop)
        for name in ("_STATE", "_PORTRAITS", "_LOGOS", "_FLAGS", "_COMPS"):
            graphics_patch = patch.object(graphics, name, dict(getattr(graphics, name)))
            graphics_patch.start()
            self.addCleanup(graphics_patch.stop)

    def request(self, route, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + route, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_original_language_object_contains_resolved_ui_and_columns(self):
        for code in ("en", "pt"):
            with self.subTest(code=code):
                status, data = self.request("/api/idiomas/" + code)
                self.assertEqual(status, 200)
                self.assertEqual(set(data), {"interface", "colunas"})
                self.assertEqual(data["interface"], idiomas.resolver(code))
                self.assertEqual(data["colunas"], idiomas.resolver(code, "colunas"))
                self.assertTrue(data["colunas"])
                self.assertNotEqual(data["interface"]["ob.title"], "ob.title")
        self.assertEqual(self.request("/api/idiomas/en")[1]["interface"]["ob.next"], "Continue")

    def test_game_request_poll_does_not_reopen_the_window(self):
        with patch.object(server, "AO_PEDIDO_DO_JOGO") as show_for_game_request:
            for _ in range(3):
                self.assertEqual(self.request("/api/jogo/pedido"), (200, {"pedido": None}))
            show_for_game_request.assert_not_called()
        with patch.object(server, "AO_MOSTRAR_JANELA") as show_on_request:
            self.assertEqual(self.request("/api/janela/mostrar", {}), (200, {"ok": True}))
            show_on_request.assert_called_once_with()

    def test_partial_language_inherits_fallback_and_rejects_unknown_paths(self):
        language = self.root / "idiomas" / "qa"
        language.mkdir(parents=True)
        (language / "interface.txt").write_text("ob.title = Test setup\n", encoding="utf-8")
        with patch.object(idiomas.paths, "idiomas_dir", return_value=str(language.parent)):
            status, data = self.request("/api/idiomas/qa")
            self.assertEqual(status, 200)
            self.assertEqual(data["interface"]["ob.title"], "Test setup")
            self.assertEqual(data["interface"]["ob.next"], "Continue")
            self.assertTrue(data["colunas"])
        for code in ("missing-language", "..", "%2E%2E", "%5C..%5Cetc"):
            self.assertEqual(self.request("/api/idiomas/" + code)[0], 404)

    def test_onboarding_partial_updates_completion_and_reload(self):
        default = dict(settings.DEFAULTS["onboarding"])
        self.assertEqual(self.request("/api/onboarding"), (200, default))
        first = self.request("/api/onboarding", {"etapa": 4, "escopo_primeira": "squad", "carreira": "sg:test"})[1]
        self.assertFalse(first["concluido"])
        final = self.request("/api/onboarding", {"concluido": True, "pulado": True})[1]
        self.assertEqual(final, dict(first, concluido=True, pulado=True))
        # Reimport settings as a new process would: state must come from disk.
        importlib.reload(settings)
        with patch.object(settings, "SETTINGS_PATH", str(self.settings_path)):
            self.assertEqual(self.request("/api/onboarding"), (200, final))
            unchanged = self.request("/api/onboarding", {})[1]
            self.assertEqual(unchanged, final)
            reset_step = self.request("/api/onboarding", {"etapa": 0, "pulado": False, "carreira": None})[1]
            self.assertEqual(reset_step["etapa"], 0)
            self.assertFalse(reset_step["pulado"])
            self.assertIsNone(reset_step["carreira"])
            self.assertTrue(reset_step["concluido"])

    def test_repeat_only_resets_guide_and_does_not_modify_defaults(self):
        preferences = {"idioma": "en", "graphics_dir": "/test/graphics", "currencies": ["GBP"], "overall_modo": "misto"}
        settings.save(**preferences)
        self.request("/api/onboarding", {"etapa": 9, "concluido": True, "carreira": "sg:test"})
        self.assertEqual(self.request("/api/onboarding/refazer", {}), (200, settings.DEFAULTS["onboarding"]))
        for key, value in preferences.items():
            self.assertEqual(settings.load()[key], value)
        self.assertFalse(settings.DEFAULTS["onboarding"]["concluido"])

    def test_legacy_installation_skips_guide_until_explicit_repeat(self):
        self.settings_path.write_text(json.dumps({"acesso_nivel": 4}), encoding="utf-8")
        self.assertTrue(self.request("/api/onboarding")[1]["concluido"])
        self.request("/api/onboarding/refazer", {})
        self.assertFalse(self.request("/api/onboarding")[1]["concluido"])
        self.settings_path.unlink()
        with sqlite3.connect(self.database) as conn:
            conn.execute("CREATE TABLE snapshots (id INTEGER)")
            conn.execute("INSERT INTO snapshots VALUES (1)")
        self.assertTrue(self.request("/api/onboarding")[1]["concluido"])

    def test_plugin_offer_always_contains_unseen_list_used_by_home(self):
        # The shipped home component directly reads nao_vistos.length.
        expected = {"plugins": [], "nao_vistos": [], "avisar": True}
        self.assertEqual(self.request("/api/plugins/oferta"), (200, expected))
        for enabled in (False, True):
            expected["avisar"] = enabled
            self.assertEqual(self.request("/api/plugins/avisar-novos", {"ligado": enabled}), (200, expected))
            self.assertEqual(self.request("/api/plugins/oferta"), (200, expected))
            self.assertEqual(settings.load()["plugins_avisar_novos"], enabled)

    def test_unconfigured_settings_contains_actual_paths_and_graphics_state(self):
        missing = self.root / "missing graphics"
        self.database.write_bytes(b"database-size-fixture")
        with patch.object(graphics, "default_graphics_dir", return_value=str(missing)):
            server._boot_graphics()
            status, data = self.request("/api/settings")
        self.assertEqual(status, 200)
        self.assertIsNone(data["graphics_dir"])
        self.assertEqual(data["graphics_dir_detected"], str(missing))
        self.assertEqual(data["db_path"], str(self.database))
        self.assertEqual(data["db_size"], self.database.stat().st_size)
        self.assertEqual(data["data_dir"], server.paths.data_root())
        self.assertEqual(data["local_dir"], server.paths.local_root())
        self.assertEqual(data["portraits"]["dir"], str(missing))
        self.assertEqual(data["portraits"]["count"], 0)
        self.assertEqual(data["portraits"]["error"], "pasta nao encontrada")
        self.assertGreater(data["memoria_fisica_mb"], 0)
        self.assertGreater(data["memoria_em_uso_mb"], 0)
        self.assertIn("memoria_max_permitida_mb", data)
        self.assertFalse(self.settings_path.exists(), "Reading Settings must not save preferences")

    def test_plugin_status_and_preference_responses_retain_original_cache_shape(self):
        status, data = self.request("/api/plugins")
        self.assertEqual(status, 200)
        self.assertEqual(data["jogos"], [])
        self.assertEqual(data["historico"], [])
        self.assertIsNone(data["ultima"])
        for key in ("tem_lista", "instalado", "disponivel"):
            self.assertFalse(data[key])
        self.assertIn("aceito", data)
        self.assertFalse(self.settings_path.exists())
        settings.save(plugins_desligados=["keep"])
        for enabled in (False, True):
            self.assertEqual(self.request("/api/plugins/ligar", {"id": "example", "ligado": enabled}), (200, data))
            self.assertEqual(settings.load()["plugins_desligados"], ["keep"] if enabled else ["example", "keep"])
        expected_offer = self.request("/api/plugins/oferta")[1]
        for route, body in [("dispensar", {"id": "example"}), ("oferta-vista", {"ids": ["example", "other"]})]:
            self.assertEqual(self.request("/api/plugins/" + route, body), (200, expected_offer))
        self.assertEqual(settings.load()["plugins_dispensados"], ["example"])
        self.assertEqual(settings.load()["plugins_oferta_vista"], ["example", "other"])

    def test_unsupported_plugin_actions_do_not_claim_success_or_open_dialog(self):
        for route, body in [("verificar", {}), ("instalar", {"id": "example"}),
                            ("voltar", {"id": "example", "pasta": "/fake"}),
                            ("pasta-jogo", {"antiga": None})]:
            with self.subTest(route=route), patch.object(server.subprocess, "run") as run:
                status, response = self.request("/api/plugins/" + route, body)
                self.assertEqual(status, 501)
                self.assertIn("macOS", response["detail"])
                run.assert_not_called()
        self.assertFalse(self.settings_path.exists())

    def test_graphics_save_returns_indexed_state_and_serves_mapped_files(self):
        folder = self.root / "facepack"
        folder.mkdir()
        records = []
        fixtures = [("person", "portrait", "face", 101, "portrait"),
                    ("club", "logo", "badge", 102, "club_logo"),
                    ("nation", "flag", "flag", 103, "flag"),
                    ("comp", "logo", "league", 104, "comp_logo")]
        for entity, image_kind, filename, uid, route in fixtures:
            (folder / (filename + ".png")).write_bytes(filename.encode())
            records.append(f'<record from="{filename}" to="graphics/pictures/{entity}/{uid}/{image_kind}"/>')
        (folder / "config.xml").write_text("<list>" + "".join(records) + "</list>", encoding="utf-8")
        settings.save(idioma="en")
        status, saved = self.request("/api/settings/graphics", {"dir": str(folder)})
        self.assertEqual(status, 200)
        self.assertEqual(saved["portraits"]["dir"], str(folder))
        self.assertEqual(saved["portraits"]["count"], 1)
        self.assertEqual(saved["portraits"]["logos"], 1)
        self.assertEqual(saved["portraits"]["flags"], 1)
        self.assertIsNone(saved["portraits"]["error"])
        self.assertTrue(saved["portraits"]["indexed_at"])
        loaded = self.request("/api/settings")[1]
        self.assertEqual(loaded["portraits"], saved["portraits"])
        self.assertEqual(loaded["graphics_dir"], str(folder))
        self.assertEqual(settings.load()["idioma"], "en")
        for _, _, filename, uid, route in fixtures:
            with urllib.request.urlopen(self.base + f"/api/{route}/{uid}") as response:
                self.assertEqual(response.read(), filename.encode())
        self.assertEqual(self.request("/api/settings/graphics", {"dir": str(self.root / 'absent')})[0], 400)
        self.assertEqual(settings.load()["graphics_dir"], str(folder))

    def test_memory_setting_uses_same_persisted_key_as_settings_response(self):
        status, data = self.request("/api/settings/memoria", {"mb": 1024})
        self.assertEqual(status, 200)
        self.assertEqual(data["memoria_max_mb"], 1024)
        self.assertEqual(self.request("/api/settings")[1]["memoria_max_mb"], 1024)
        self.assertEqual(self.request("/api/settings/memoria", {"mb": 1})[0], 400)
        self.assertEqual(settings.load()["memoria_max_mb"], 1024)

    def create_database(self, path, value):
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute("CREATE TABLE qa_existing_data (value TEXT)")
                connection.execute("INSERT INTO qa_existing_data VALUES (?)", (value,))

    def database_value(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute("SELECT value FROM qa_existing_data").fetchone()[0]

    def test_database_move_rejects_existing_destination_and_preserves_settings(self):
        destination = self.root / "destination"
        destination.mkdir()
        target = destination / self.database.name
        self.create_database(self.database, "source")
        self.create_database(target, "keep-me")
        for path in (self.database, target):
            for suffix in ("-wal", "-shm"):
                Path(str(path) + suffix).write_bytes((path.name + suffix).encode())
        settings.save(db_dir=str(self.root), idioma="en")
        files = [self.settings_path] + [Path(str(path) + suffix)
                  for path in (self.database, target) for suffix in ("", "-wal", "-shm")]
        before = {path: path.read_bytes() for path in files}
        status, data = self.request("/api/settings/db_dir", {"dir": str(destination), "move": True})
        self.assertEqual(status, 409)
        self.assertIn("pasta vazia", data["detail"])
        self.assertEqual({path: path.read_bytes() for path in files}, before)
        self.assertEqual(self.request("/api/settings")[1]["db_path"], str(self.database))
        # Remove only disposable invalid sidecar fixtures before opening SQLite.
        for path in (self.database, target):
            for suffix in ("-wal", "-shm"):
                Path(str(path) + suffix).unlink()
        self.assertEqual(self.database_value(self.database), "source")
        self.assertEqual(self.database_value(target), "keep-me")
        empty = self.root / "empty"
        self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(empty), "move": True})[0], 200)
        self.assertEqual(self.database_value(empty / self.database.name), "source")
        self.assertFalse(self.database.exists())
        self.assertEqual(settings.load()["db_dir"], str(empty))

    def test_database_move_rejects_destination_links_directories_and_sidecars(self):
        self.create_database(self.database, "source")
        settings.save(db_dir=str(self.root))
        source_before = self.database.read_bytes()
        settings_before = self.settings_path.read_bytes()
        for kind in ("symlink", "dangling", "hardlink", "directory", "-wal", "-shm"):
            with self.subTest(kind=kind):
                destination = self.root / kind
                destination.mkdir()
                target = destination / self.database.name
                if kind in ("symlink", "dangling"):
                    target.symlink_to(self.database if kind == "symlink" else self.root / "missing")
                elif kind == "hardlink":
                    target.hardlink_to(self.database)
                elif kind == "directory":
                    target.mkdir()
                else:
                    target = Path(str(target) + kind)
                    target.write_bytes(b"keep-sidecar")
                self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(destination), "move": True})[0], 409)
                self.assertTrue(server.os.path.lexists(target))
                if kind in ("-wal", "-shm"):
                    self.assertEqual(target.read_bytes(), b"keep-sidecar")
                self.assertEqual(self.database.read_bytes(), source_before)
                self.assertEqual(self.settings_path.read_bytes(), settings_before)

    def test_database_same_folder_and_explicit_use_existing_preserve_both_files(self):
        self.create_database(self.database, "source")
        source_before = self.database.read_bytes()
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for folder in (self.root, alias):
            self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(folder), "move": True})[0], 200)
            self.assertEqual(self.database.read_bytes(), source_before)
        destination = self.root / "existing"
        destination.mkdir()
        target = destination / self.database.name
        self.create_database(target, "keep-me")
        target_before = target.read_bytes()
        probe = destination / ".fmsh_write_test"
        probe.write_bytes(b"user-file")
        self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(destination), "move": False})[0], 200)
        self.assertEqual(settings.load()["db_dir"], str(destination))
        self.assertEqual(self.database.read_bytes(), source_before)
        self.assertEqual(target.read_bytes(), target_before)
        self.assertEqual(probe.read_bytes(), b"user-file")

    def test_database_move_copies_all_components_before_removing_source(self):
        self.create_database(self.database, "source")
        for suffix in ("-wal", "-shm"):
            Path(str(self.database) + suffix).write_bytes(suffix.encode())
        source_before = {suffix: Path(str(self.database) + suffix).read_bytes()
                         for suffix in ("", "-wal", "-shm")}
        destination = self.root / "new"
        self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(destination), "move": True})[0], 200)
        for suffix, content in source_before.items():
            self.assertFalse(Path(str(self.database) + suffix).exists())
            self.assertEqual(Path(str(destination / self.database.name) + suffix).read_bytes(), content)

    def test_database_move_late_collision_does_not_replace_new_file(self):
        self.create_database(self.database, "source")
        settings.save(db_dir=str(self.root))
        source_before = self.database.read_bytes()
        settings_before = self.settings_path.read_bytes()
        for suffix in ("", "-wal", "-shm"):
            with self.subTest(suffix=suffix):
                destination = self.root / ("late" + suffix)
                destination.mkdir()
                target = destination / self.database.name
                collision = Path(str(target) + suffix)
                original_open = Path.open

                def create_collision(path, mode="r", *args, **kwargs):
                    if path == collision and mode == "xb":
                        with original_open(path, "wb") as file:
                            file.write(b"late-user-data")
                    return original_open(path, mode, *args, **kwargs)

                with patch.object(Path, "open", create_collision):
                    self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(destination), "move": True})[0], 409)
                self.assertEqual(collision.read_bytes(), b"late-user-data")
                self.assertEqual(list(destination.iterdir()), [collision])
                self.assertEqual(self.database.read_bytes(), source_before)
                self.assertEqual(self.settings_path.read_bytes(), settings_before)

    def test_database_move_copy_or_settings_failure_keeps_original_and_active_path(self):
        self.create_database(self.database, "source")
        settings.save(db_dir=str(self.root))
        source_before = self.database.read_bytes()
        settings_before = self.settings_path.read_bytes()
        for failure in ("copy", "settings"):
            with self.subTest(failure=failure):
                destination = self.root / failure
                destination.mkdir()
                if failure == "copy":
                    operation = patch.object(server.shutil, "copyfileobj", side_effect=OSError("copy failed"))
                else:
                    operation = patch.object(settings, "save", side_effect=OSError("save failed"))
                with operation:
                    self.assertEqual(self.request("/api/settings/db_dir", {"dir": str(destination), "move": True})[0], 500)
                self.assertEqual(list(destination.iterdir()), [])
                self.assertEqual(self.database.read_bytes(), source_before)
                self.assertEqual(self.settings_path.read_bytes(), settings_before)
                self.assertEqual(self.request("/api/settings")[1]["db_path"], str(self.database))

if __name__ == "__main__":
    unittest.main()
