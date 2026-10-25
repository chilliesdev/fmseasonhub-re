"""Favorites must survive fresh server processes using the same data folders."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Event, current_thread
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"


class FavoritesRestartTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.settings_path = self.data / "fmsh_settings.json"
        self.process = None
        self.addCleanup(self.stop)
        self.log = (self.root / "server.log").open("w+")
        self.addCleanup(self.log.close)

    def start(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, PYTHONPATH=str(SRC), FMSH_PASTA_DADOS=str(self.data),
                   FMSH_PASTA_LOCAL=str(self.root / "local"))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
             "--port", str(port), "--log-level", "error"],
            cwd=SRC, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                self.request("/api/favoritos/listas")
                return
            except (OSError, urllib.error.URLError):
                time.sleep(0.03)
        self.log.seek(0)
        self.fail("Server did not start: " + self.log.read())

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def restart(self):
        self.stop()
        self.start()

    def request(self, route, body=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + route, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def create(self, name="QA List", color="#00aa55", uids=None):
        return self.request("/api/favoritos/listas", {
            "nome": name, "cor": color, "uids": uids or [900001],
        })["lista"]

    def test_issue_18_lists_colors_membership_and_other_settings_survive_restart(self):
        self.start()
        self.request("/api/settings/memoria", {"mb": 1536})
        first = self.create(name="QA List · São Paulo")
        second = self.create(name="Second", color="#aa0055", uids=[900002, 900003])
        self.assertNotEqual(first["id"], second["id"])
        expected = self.request("/api/favoritos/listas")
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas"), expected)
        self.assertEqual(self.request("/api/favoritos"), expected)
        saved = json.loads(self.settings_path.read_text())
        self.assertEqual(saved["favoritos_listas"], expected["listas"])
        self.assertEqual(saved["memoria_max_mb"], 1536)
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas"), expected)

    def test_all_list_and_membership_mutations_survive_restart(self):
        self.start()
        original = self.create(uids=[900001, 900002])
        route = "/api/favoritos/listas/" + original["id"]
        self.request(route, {"nome": "Edited", "cor": "#123456"}, "PATCH")
        self.request(route + "/jogadores", {"uids": [900003, 900004]})
        self.request(route + "/jogadores", {"uids": [900002], "marcar": False})
        copy = self.request(route + "/duplicar", {"nome": "Copy"})["lista"]
        self.assertNotEqual(copy["id"], original["id"])
        self.assertEqual(copy["cor"], "#123456")
        self.assertEqual(set(copy["uids"]), {900001, 900003, 900004})
        self.restart()
        self.request(route + "/jogadores", {"uids": [900005]})
        self.request("/api/favoritos/tirar-de-todas", {"uids": [900001]})
        expected = self.request("/api/favoritos/listas")
        edited = next(x for x in expected["listas"] if x["id"] == original["id"])
        copied = next(x for x in expected["listas"] if x["id"] == copy["id"])
        self.assertEqual(edited["nome"], "Edited")
        self.assertEqual(set(edited["uids"]), {900003, 900004, 900005})
        self.assertEqual(set(copied["uids"]), {900003, 900004})
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas"), expected)
        self.request(route, method="DELETE")
        self.restart()
        self.assertFalse(any(x["id"] == original["id"] for x in self.request("/api/favoritos/listas")["listas"]))
        self.assertTrue(any(x["id"] == copy["id"] for x in self.request("/api/favoritos/listas")["listas"]))

    def test_deleted_default_and_empty_collection_stay_deleted(self):
        self.start()
        self.assertEqual(self.request("/api/favoritos/listas")["listas"][0]["id"], "fav_default")
        self.request("/api/favoritos/listas/fav_default", method="DELETE")
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas")["listas"], [])
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas")["listas"], [])

    def test_existing_saved_lists_are_loaded_without_replacing_them(self):
        saved = [{"id": "existing-id", "nome": "Saved", "cor": "#f0876a", "uids": [71, 72],
                  "entrou": {"71": 1, "72": 2}}]
        self.settings_path.write_text(json.dumps({"favoritos_listas": saved, "idioma": "en"}))
        timestamp = 1700000000
        os.utime(self.settings_path, (timestamp, timestamp))
        self.start()
        loaded = self.request("/api/favoritos/listas")["listas"][0]
        self.assertEqual({key: loaded[key] for key in saved[0]}, saved[0])
        expected_date = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        self.assertEqual((loaded["criada_em"], loaded["atualizada_em"]), (expected_date, expected_date))
        self.create()
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas")["listas"][0], loaded)
        self.assertEqual(json.loads(self.settings_path.read_text())["idioma"], "en")

    def test_creation_dates_and_mutation_state_are_stable_across_restart(self):
        self.start()
        before = datetime.now(timezone.utc)
        created = self.create(uids=[900001, 900002])
        after = datetime.now(timezone.utc)
        creation = datetime.fromisoformat(created["criada_em"])
        self.assertLessEqual(before, creation)
        self.assertLessEqual(creation, after)
        self.assertEqual(created["criada_em"], created["atualizada_em"])
        self.assertEqual(set(created["entrou"]), {"900001", "900002"})
        route = "/api/favoritos/listas/" + created["id"]
        previous = created["atualizada_em"]
        for endpoint, body, method in (
            (route, {"nome": "Dated rename"}, "PATCH"),
            (route + "/jogadores", {"uids": [900003]}, "POST"),
            (route + "/jogadores", {"uids": [900001], "marcar": False}, "POST"),
            (route, {"esvaziar": True}, "PATCH"),
        ):
            state = self.request(endpoint, body, method)
            self.assertTrue({"listas", "padrao", "paleta", "aviso", "lista"} <= state.keys())
            changed = state["lista"]
            self.assertEqual(changed["criada_em"], created["criada_em"])
            self.assertGreater(changed["atualizada_em"], previous)
            previous = changed["atualizada_em"]
            self.assertEqual(next(item for item in state["listas"] if item["id"] == created["id"]), changed)
        self.assertEqual((changed["uids"], changed["entrou"]), ([], {}))
        expected = self.request("/api/favoritos/listas")
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas"), expected)
        saved = json.loads(self.settings_path.read_text())
        self.assertEqual(saved["favoritos_listas"], expected["listas"])

    def test_existing_native_dates_and_metadata_are_preserved(self):
        saved = {"id": "native", "nome": "Native", "cor": "#f0876a", "uids": [71],
                 "entrou": {"71": 35}, "criada_em": "2025-01-02T03:04:05",
                 "atualizada_em": "2026-02-03T04:05:06", "custom": {"keep": True}}
        self.settings_path.write_text(json.dumps({"favoritos_listas": [saved]}))
        self.start()
        self.assertEqual(self.request("/api/favoritos/listas")["listas"], [saved])
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas")["listas"], [saved])

    def test_parallel_creates_and_membership_updates_are_not_lost(self):
        self.start()
        with ThreadPoolExecutor(max_workers=8) as pool:
            created = list(pool.map(lambda i: self.create(name=f"List {i}"), range(12)))
        self.assertEqual(len({x["id"] for x in created}), 12)
        route = "/api/favoritos/listas/" + created[0]["id"] + "/jogadores"
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.request(route, {"uids": [910000 + i]}), range(12)))
        expected = self.request("/api/favoritos/listas")
        self.assertEqual(len(expected["listas"]), 13)
        target = next(x for x in expected["listas"] if x["id"] == created[0]["id"])
        self.assertEqual(set(target["uids"]), {900001, *range(910000, 910012)})
        self.restart()
        self.assertEqual(self.request("/api/favoritos/listas"), expected)


    def test_pending_preference_writes_cannot_erase_saved_favorites(self):
        sys.path.insert(0, str(SRC))
        import server
        import settings
        cases = [
            ("overall", lambda: server.set_overall_modo(server.OverallModoBody(modo="ca")),
             "overall_modo", "ca"),
            ("language", lambda: server.set_idioma(server.IdiomaBody(idioma="pt")),
             "idioma", "pt"),
            ("tray", lambda: server.set_bandeja_settings({"ligado": False}),
             "bandeja", {"keep": True, "ligado": False}),
            ("graphics", lambda: server.set_graphics(server.GraphicsBody(dir=str(self.data))),
             "graphics_dir", str(self.data)),
            ("database", lambda: server.set_db_dir(server.DbDirBody(dir=str(self.data))),
             "db_dir", str(self.data)),
            ("season", lambda: server.set_fim_de_temporada(server.FimDeTemporadaBody(ligado=True)),
             "fim_de_temporada_auto", True),
            ("snapshot", lambda: server.set_auto_snapshot(server.AutoSnapshotBody(ligado=True)),
             "auto_snapshot_ligado", True),
            ("sound", lambda: server.set_captura_som(server.CapturaSomBody(ligado=False)),
             "captura_som_ligado", False),
        ]
        with patch.object(settings, "SETTINGS_PATH", str(self.settings_path)), patch.object(
            server.graphics, "reindex"
        ), patch.object(server.graphics, "state", return_value={}), patch.object(
            server, "get_db_path", return_value=self.data / "fm26_snapshots.db"
        ):
            settings.save(idioma="en", bandeja={"keep": True}, captura_som={"keep": True})
            original_save = settings.save
            for name, handler, key, value in cases:
                with self.subTest(preference=name):
                    paused, resume = Event(), Event()

                    def pending_save(**changes):
                        if current_thread().name.startswith("preference-writer"):
                            paused.set()
                            if not resume.wait(5):
                                raise TimeoutError("Preference write was not resumed")
                        return original_save(**changes)

                    with patch.object(settings, "save", side_effect=pending_save), ThreadPoolExecutor(
                        max_workers=1, thread_name_prefix="preference-writer"
                    ) as pool:
                        pending = pool.submit(handler)
                        try:
                            self.assertTrue(paused.wait(5), "Preference handler did not reach save")
                            server.post_favoritos_criar(server.FavListaNovaBody(
                                nome="Saved during " + name, cor="#00aa55", uids=[900001]
                            ))
                            expected = server.get_favoritos_listas()
                        finally:
                            resume.set()
                        self.assertTrue(pending.result(timeout=5)["ok"])
                    self.assertEqual(server.get_favoritos_listas(), expected)
                    self.assertEqual(settings.load()[key], value)
        self.start()
        self.assertEqual(self.request("/api/favoritos/listas"), expected)
        self.assertEqual(len(expected["listas"]), len(cases) + 1)


class FavoritesWriteFailureTests(unittest.TestCase):
    def test_failed_atomic_write_does_not_publish_or_retain_unsaved_favorites(self):
        sys.path.insert(0, str(SRC))
        import server
        import settings
        with tempfile.TemporaryDirectory() as folder, patch.object(
            settings, "SETTINGS_PATH", str(Path(folder) / "settings.json")
        ):
            settings.save(idioma="en")
            before = server.get_favoritos_listas()
            with patch.object(settings.os, "replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    server.post_favoritos_criar(server.FavListaNovaBody(nome="Unsaved", cor="#00aa55"))
            self.assertEqual(server.get_favoritos_listas(), before)
            self.assertEqual(settings.load()["idioma"], "en")
            self.assertFalse(Path(settings.SETTINGS_PATH + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
