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

import db
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

    def saved_snapshot(self, name):
        with closing(server.get_db_connection()) as conn, conn:
            return conn.execute("INSERT INTO snapshots (name) VALUES (?)", (name,)).lastrowid

    def portal_fixture(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.executescript("""
                INSERT INTO snapshots(id,name,game_date,in_game_season,scope,club_uid,carreira_id) VALUES
                (901,'QA 901','2027-05-30','2026/27','squad',77,'qa_alpha'),
                (902,'QA 902','2028-05-30','2027/28','full',77,'qa_alpha'),
                (903,'QA 903','2027-05-30','2026/27','squad',88,'qa_beta'),
                (904,'Transient','2029-05-30','2028/29','live_temp',77,'qa_alpha');
                INSERT INTO players(snapshot_id,uid,full_name,club_id) VALUES
                (901,1,'Alpha old',77),(902,1,'Alpha new',77),(903,2,'Beta',88);
                INSERT INTO player_stats(snapshot_id,uid,avg_rating) VALUES
                (901,1,7.1),(902,1,7.2),(903,2,7.3);
            """)
        settings.save(carreira_ativa='qa_alpha')

    def test_portal_empty_database_and_unknown_selection(self):
        status, result = self.request('/api/portal')
        self.assertEqual(status, 200)
        self.assertEqual(result['seasons'], 0)
        self.assertEqual(result['total_seasons'], 0)
        self.assertIsNone(result['base'])
        self.assertIsNone(result['ultima'])
        self.assertEqual(result['season'], {})
        self.assertEqual(result['highlights'], [])
        self.assertEqual(self.request('/api/carreiras')[1]['carreiras'], [])
        for snapshot in (901, 0, -1, 999999999):
            self.assertEqual(self.request(f'/api/portal?snapshot={snapshot}')[0], 404)
        self.assertEqual(self.request('/api/portal?snapshot=invalid')[0], 422)

    def test_portal_selected_saved_season_and_career_counts_while_disconnected(self):
        self.portal_fixture()
        with patch.object(server, '_LIVE_STATUS', dict(server._EMPTY_LIVE_STATUS)):
            for sid, career, count, label, player in (
                (901, 'qa_alpha', 2, '2026/27', 'Alpha old'),
                (902, 'qa_alpha', 2, '2027/28', 'Alpha new'),
                (903, 'qa_beta', 1, '2026/27', 'Beta'),
            ):
                with self.subTest(snapshot=sid):
                    status, result = self.request(f'/api/portal?snapshot={sid}')
                    self.assertEqual(status, 200)
                    self.assertFalse(result['connected'])
                    self.assertEqual(result['seasons'], count)
                    self.assertEqual(result['total_seasons'], 3)
                    self.assertEqual(result['carreira_id'], career)
                    self.assertEqual(result['base']['id'], sid)
                    self.assertEqual(result['ultima']['id'], sid)
                    self.assertEqual(result['base']['n_players'], 1)
                    self.assertEqual(result['season']['label'], label)
                    self.assertIsNone(result['season']['days_left'])
                    self.assertEqual([row['full_name'] for row in result['highlights']], [player])
            self.assertEqual(self.request('/api/portal')[1]['ultima']['id'], 902)
            self.assertEqual(self.request('/api/portal?snapshot=904')[0], 404)
            self.assertEqual(self.request('/api/portal?snapshot=9999')[0], 404)

    def test_portal_career_switch_persists_and_uses_latest_saved_capture(self):
        self.portal_fixture()
        self.assertEqual(self.request('/api/carreiras')[1]['ativa'], 'qa_alpha')
        status, activation = self.request('/api/carreiras/ativa', {'id': 'qa_beta'})
        self.assertEqual(status, 200)
        self.assertTrue(activation.pop('ok'))
        self.assertEqual(activation, self.request('/api/carreiras')[1])
        self.assertEqual([row['id'] for row in activation['carreiras'] if row['ativa']],
                         ['qa_beta'])
        self.assertEqual(activation['prefs'], {'moeda': 1, 'periodo_salario': 'week'})
        self.assertEqual(settings.load()['carreira_ativa'], 'qa_beta')
        careers = self.request('/api/carreiras')[1]
        self.assertEqual(careers['ativa'], 'qa_beta')
        self.assertEqual({row['id']: row['n_temporadas'] for row in careers['carreiras']},
                         {'qa_alpha': 2, 'qa_beta': 1})
        result = self.request('/api/portal')[1]
        self.assertEqual((result['seasons'], result['ultima']['id']), (1, 903))
        self.assertEqual(self.request('/api/carreiras/ativa', {'id': 'missing'})[0], 404)
        self.assertEqual(settings.load()['carreira_ativa'], 'qa_beta')
        settings.save(carreira_ativa='deleted')
        self.assertEqual(self.request('/api/carreiras')[1]['ativa'], 'qa_alpha')
        self.assertEqual(self.request('/api/portal')[1]['ultima']['id'], 902)

    def test_portal_live_status_does_not_add_stored_seasons_or_override_explicit_selection(self):
        self.portal_fixture()
        live = dict(server._EMPTY_LIVE_STATUS, ready=True, game_date='2029-01-01', club='Live club')
        with patch.object(server, '_LIVE_STATUS', live):
            for route in ('/api/portal', '/api/portal?snapshot=999999999'):
                result = self.request(route)[1]
                self.assertTrue(result['connected'])
                self.assertEqual((result['seasons'], result['total_seasons']), (2, 3))
                self.assertEqual(result['live'], live)
                self.assertEqual(result['club'], 'Live club')
            result = self.request('/api/portal?snapshot=901')[1]
            self.assertFalse(result['connected'])
            self.assertEqual(result['ultima']['id'], 901)
            self.assertEqual(result['game_date'], '2027-05-30')

    def test_moneyball_columns_supply_iterable_catalog_sections_for_every_group(self):
        catalog = server._load_moneyball_catalog()
        self.assertTrue(catalog)
        expected_keys = {column["key"] for columns in catalog.values() for column in columns}
        for group in ("all", "fav", *catalog):
            with self.subTest(group=group):
                status, payload = self.request(f"/api/moneyball/columns?group={group}&snapshot=901")
                self.assertEqual(status, 200)
                self.assertEqual(payload["group"], group)
                self.assertIsInstance(payload["sections"], list)
                self.assertIsInstance(payload["current"], list)
                self.assertEqual([section["group"] for section in payload["sections"]], list(catalog))
                seen = set()
                for section in payload["sections"]:
                    self.assertIsInstance(section["columns"], list)
                    self.assertEqual(len(section["columns"]), len(catalog[section["group"]]))
                    for column in section["columns"]:
                        self.assertNotIn(column["key"], seen)
                        seen.add(column["key"])
                        self.assertEqual(column["from"], section["group"])
                        self.assertTrue(column["label"])
                        self.assertTrue(column["short"])
                        self.assertTrue(column["fmt"])
                self.assertEqual(seen, expected_keys)
                selected = [column["key"] for column in payload["current"] if not column.get("general")]
                self.assertEqual(selected, [column["key"] for column in catalog.get(group, [])])
                self.assertEqual(payload, self.request(f"/api/moneyball/columns?group={group}")[1])

    def test_search_fields_supply_field_metadata_and_supported_ui_operators(self):
        catalog = server._load_moneyball_catalog()
        expected_keys = {column["key"] for columns in catalog.values() for column in columns}
        for group in ("all", "fav", *catalog):
            with self.subTest(group=group):
                status, payload = self.request(f"/api/search/fields?group={group}&snapshot=901")
                self.assertEqual(status, 200)
                self.assertNotIn("columns", payload)
                fields = payload["fields"]
                self.assertIsInstance(fields, list)
                by_key = {field["key"]: field for field in fields}
                self.assertEqual(len(fields), len(by_key))
                self.assertTrue(expected_keys <= by_key.keys())
                for field in fields:
                    self.assertTrue(field["label"])
                    self.assertIn(field["section"], payload["sectionOrder"])
                    self.assertIn(field["type"], payload["opsByType"])
                    self.assertEqual(field["ops"], payload["opsByType"][field["type"]])
                    self.assertTrue(field["ops"])
                    for op in field["ops"]:
                        self.assertIn(op, payload["valueSlots"])
                self.assertEqual(by_key["name"]["type"], "text")
                self.assertEqual(by_key["name"]["ops"][0], "contains")
                self.assertEqual(by_key["_age"]["ops"][0], "gte")
                self.assertEqual(by_key["_value"]["type"], "money")
                self.assertEqual(by_key["xg"]["fmt"], "dec2")
                self.assertEqual(set(payload["opsByType"]["num"]), server.player_search.NUM_OPS)
                self.assertEqual(set(payload["opsByType"]["text"]), server.player_search.TEXT_OPS)
                self.assertEqual(payload["valueSlots"]["between"], 2)
                self.assertEqual(payload["valueSlots"]["contains"], 1)
                self.assertEqual(payload, self.request(f"/api/search/fields?group={group}")[1])

    def test_moneyball_metadata_handles_empty_catalog_and_invalid_groups(self):
        for endpoint in ("/api/moneyball/columns", "/api/search/fields"):
            with self.subTest(endpoint=endpoint):
                for group in ("unknown", ""):
                    status, payload = self.request(f"{endpoint}?group={group}")
                    self.assertEqual(status, 400)
                    self.assertIn("grupo invalido", payload["detail"])
        with patch.object(server, "_load_moneyball_catalog", return_value={}):
            status, payload = self.request("/api/moneyball/columns")
            self.assertEqual(status, 200)
            self.assertEqual(payload["sections"], [])
            self.assertIsInstance(payload["current"], list)
            status, payload = self.request("/api/search/fields")
            self.assertEqual(status, 200)
            self.assertIn("name", {field["key"] for field in payload["fields"]})

    def test_fresh_startup_supplies_legacy_empty_snapshot_metrics(self):
        db.init_db(str(self.database))
        with closing(sqlite3.connect(self.database)) as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(snapshots)")]
        self.assertNotIn("n_players", columns)
        self.assertNotIn("size_bytes", columns)
        self.assertEqual(self.request("/api/snapshots?include_live=false"), (200, []))
        sid = self.saved_snapshot("Legacy empty season")
        status, snapshots = self.request("/api/snapshots?include_live=false")
        self.assertEqual(status, 200)
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot["id"], sid)
        self.assertEqual((snapshot["n_players"], snapshot["size_bytes"]), (0, 0))
        self.assertIs(type(snapshot["n_players"]), int)
        self.assertIs(type(snapshot["size_bytes"]), int)
        self.assertEqual(self.request(f"/api/snapshots/{sid}"), (200, snapshot))
        self.assertEqual(self.request("/api/snapshots/987654321")[0], 404)

    def assert_storage(self, expected, database=None):
        status, result = self.request("/api/armazenamento")
        self.assertEqual(status, 200)
        self.assertEqual({key: result[key] for key in expected}, expected)
        self.assertEqual(set(result), set(expected) | {"banco", "disco"})
        self.assertEqual(result["banco"], (database or self.database).stat().st_size)
        for size in (result["banco"], result["disco"]["total"], result["disco"]["livre"]):
            self.assertIs(type(size), int)
            self.assertGreaterEqual(size, 0)
        self.assertGreaterEqual(result["disco"]["total"], result["disco"]["livre"])
        return result

    def test_storage_reports_active_database_file_and_volume_sizes(self):
        selected = self.root / "selected volume" / "fm26_snapshots.db"
        selected.parent.mkdir()
        disk = server.shutil.disk_usage(selected.parent)
        with patch.object(server, "get_db_path", return_value=selected), \
                patch.object(server.shutil, "disk_usage", return_value=disk) as disk_usage:
            result = self.assert_storage({"carreiras": [], "outros": 0, "total": 0}, selected)
        self.assertEqual(result["disco"], {"total": disk.total, "livre": disk.free})
        disk_usage.assert_called_once_with(selected.parent)
        self.assertGreater(result["banco"], 0)
        self.assertFalse(self.database.exists(), "Storage must use the configured database")

    def test_storage_keeps_widget_contract_when_filesystem_sizes_unavailable(self):
        db.init_db(str(self.database))
        empty = {"carreiras": [], "outros": 0, "total": 0}
        with patch.object(Path, "stat", side_effect=PermissionError("size unavailable")):
            status, result = self.request("/api/armazenamento")
        self.assertEqual(status, 200)
        self.assertEqual(result["banco"], 0)
        self.assertGreater(result["disco"]["total"], 0)
        with patch.object(server.shutil, "disk_usage", side_effect=OSError("volume unavailable")):
            result = self.assert_storage(empty)
        self.assertEqual(result["disco"], {"total": 0, "livre": 0})
        with patch.object(Path, "stat", side_effect=OSError("size unavailable")), \
                patch.object(server.shutil, "disk_usage", side_effect=OSError("volume unavailable")):
            self.assertEqual(self.request("/api/armazenamento"),
                             (200, dict(empty, banco=0, disco={"total": 0, "livre": 0})))

    def test_storage_fresh_app_database_and_empty_snapshot(self):
        db.init_db(str(self.database))
        self.assert_storage({"carreiras": [], "outros": 0, "total": 0})
        with closing(db.connect(str(self.database))) as conn:
            db.create_snapshot(conn, "Empty season", carreira_id="qa_empty")
        expected = {"carreiras": [{"nome": "qa_empty", "bytes": 0}], "outros": 0, "total": 0}
        for _ in range(2):
            result = self.assert_storage(expected)
            self.assertIs(type(result["total"]), int)
            self.assertIs(type(result["outros"]), int)
            self.assertIs(type(result["carreiras"][0]["bytes"]), int)
        with closing(sqlite3.connect(self.database)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
        self.assertNotIn("bytes_crus", columns)

    def test_storage_uses_saved_payload_in_both_database_schemas(self):
        for startup_schema in (True, False):
            with self.subTest(startup_schema=startup_schema):
                database = self.root / f"storage-{startup_schema}.db"
                if startup_schema:
                    db.init_db(str(database))
                with patch.object(server, "get_db_path", return_value=database):
                    with closing(server.get_db_connection()) as conn, conn:
                        conn.executemany(
                            "INSERT INTO snapshots (id, name, carreira_id) VALUES (?, ?, ?)",
                            [(901, "First", "qa_alpha"), (902, "Second", "qa_alpha"),
                             (903, "Teams only", "qa_beta"), (904, "Unassigned", None),
                             (905, "Empty career ID", ""), (906, "Empty season", "qa_empty")])
                        conn.executemany(
                            "INSERT INTO players (snapshot_id, uid, full_name) VALUES (?, ?, ?)",
                            [(901, 1, "João"), (902, 2, "李"), (904, 3, "No career")])
                        conn.executemany(
                            "INSERT INTO teams (snapshot_id, team_uid, label, team_type, n_players) "
                            "VALUES (?, ?, ?, NULL, NULL)",
                            [(901, 10, "Équipe"), (903, 20, "Équipe"), (905, 30, "未分配")])
                    # Independent expected UTF-8 payload sizes, excluding snapshot_id links.
                    sizes = {901: len("1João10Équipe".encode("utf-8")),
                             902: len("2李".encode("utf-8")),
                             903: len("20Équipe".encode("utf-8")),
                             904: len("3No career".encode("utf-8")),
                             905: len("30未分配".encode("utf-8")), 906: 0}
                    expected = {"carreiras": [
                        {"nome": "qa_alpha", "bytes": sizes[901] + sizes[902]},
                        {"nome": "qa_beta", "bytes": sizes[903]},
                        {"nome": "qa_empty", "bytes": 0}],
                        "outros": sizes[904] + sizes[905], "total": sum(sizes.values())}
                    self.assert_storage(expected, database)
                    with closing(sqlite3.connect(database)) as conn, conn:
                        if startup_schema:
                            columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
                            self.assertNotIn("bytes_crus", columns)
                            conn.execute("ALTER TABLE snapshots ADD COLUMN bytes_crus INTEGER")
                            conn.execute("ALTER TABLE snapshots ADD COLUMN n_players INTEGER")
                        conn.execute("ALTER TABLE snapshots ADD COLUMN size_bytes INTEGER")
                        conn.execute("UPDATE snapshots SET bytes_crus=999999, n_players=999, size_bytes=999999")
                        conn.execute("UPDATE snapshots SET bytes_crus=NULL, n_players=NULL, size_bytes=NULL WHERE id=902")
                    with closing(sqlite3.connect(database)) as conn:
                        before = list(conn.iterdump())
                    for _ in range(2):
                        self.assert_storage(expected, database)
                    status, snapshots = self.request("/api/snapshots?include_live=false")
                    self.assertEqual(status, 200)
                    self.assertEqual({row["id"]: row["size_bytes"] for row in snapshots}, sizes)
                    self.assertEqual(sum(row["n_players"] for row in snapshots), 3)
                    for sid in sizes:
                        status, snapshot = self.request(f"/api/snapshots/{sid}")
                        self.assertEqual(status, 200)
                        self.assertEqual(snapshot["size_bytes"], sizes[sid])
                    with closing(sqlite3.connect(database)) as conn:
                        self.assertEqual(list(conn.iterdump()), before)

    def test_snapshot_metrics_use_saved_rows_in_both_database_schemas(self):
        for startup_schema in (True, False):
            with self.subTest(startup_schema=startup_schema):
                database = self.root / f"schema-{startup_schema}.db"
                if startup_schema:
                    db.init_db(str(database))
                with patch.object(server, "get_db_path", return_value=database):
                    first = self.saved_snapshot("Populated")
                    second = self.saved_snapshot("Legacy empty")
                    with closing(sqlite3.connect(database)) as conn:
                        with conn:
                            if startup_schema:
                                conn.execute("ALTER TABLE snapshots ADD COLUMN n_players INTEGER")
                                conn.execute("ALTER TABLE snapshots ADD COLUMN bytes_crus INTEGER")
                            conn.execute("ALTER TABLE snapshots ADD COLUMN size_bytes INTEGER")
                            conn.execute("UPDATE snapshots SET n_players=999, size_bytes=999, bytes_crus=999 WHERE id=?", (first,))
                            conn.execute("UPDATE snapshots SET n_players=NULL, size_bytes=NULL, bytes_crus=NULL WHERE id=?", (second,))
                            conn.executemany("INSERT INTO players (snapshot_id, uid, full_name) VALUES (?, ?, ?)",
                                             [(first, 1, "João"), (first, 2, "李")])
                            conn.execute("INSERT INTO teams (snapshot_id, team_uid, label) VALUES (?, ?, ?)",
                                         (first, 10, "Équipe"))
                            # A third snapshot must not contribute to the first count/size.
                            third = conn.execute("INSERT INTO snapshots (name) VALUES ('Other')").lastrowid
                            conn.execute("INSERT INTO players (snapshot_id, uid, full_name) VALUES (?, ?, ?)",
                                         (third, 3, "Other player"))
                    snapshots = self.request("/api/snapshots?include_live=false")[1]
                    snapshots = {snapshot["id"]: snapshot for snapshot in snapshots}
                    self.assertEqual(snapshots[first]["n_players"], 2)
                    # Server schema gives team_type/n_players zero defaults; startup leaves them null.
                    expected = len("1João2李10Équipe".encode("utf-8")) + (0 if startup_schema else 2)
                    self.assertEqual(snapshots[first]["size_bytes"], expected)
                    self.assertEqual((snapshots[second]["n_players"], snapshots[second]["size_bytes"]), (0, 0))
                    self.assertEqual(snapshots[third]["n_players"], 1)
                    self.assertEqual(self.request(f"/api/snapshots/{first}"), (200, snapshots[first]))
                    with closing(sqlite3.connect(database)) as conn:
                        # Normalization is read-only: legacy metadata stays untouched.
                        self.assertEqual(conn.execute("SELECT n_players, size_bytes FROM snapshots WHERE id=?", (first,)).fetchone(), (999, 999))

    def test_player_list_uses_startup_schema_and_keeps_filters_and_missing_profiles(self):
        db.init_db(str(self.database))
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executemany("INSERT INTO snapshots (id, name) VALUES (?, ?)",
                             [(901, "QA first"), (902, "QA other"), (903, "QA empty")])
            conn.executemany(
                "INSERT INTO players (snapshot_id, uid, full_name, common_name, club_id, team_uid) VALUES (?, ?, ?, ?, ?, ?)",
                [(901, 900001, "QA Alpha", "QA nickname", 77, 771),
                 (901, 900002, "QA Missing Profile", None, 88, 881),
                 (902, 900001, "Other season", None, 77, 771)])
            conn.executemany(
                "INSERT INTO player_profile (snapshot_id, uid, guide_value, transfer_value, contract_wage, contract_end) VALUES (?, ?, ?, ?, ?, ?)",
                [(901, 900001, 1000000, 2000000, 10000, "2030-06-30"),
                 (902, 900001, 3000000, 4000000, 20000, "2031-06-30")])
            conn.executemany(
                "INSERT INTO player_stats (snapshot_id, uid, apps_total, goals, assists, avg_rating) VALUES (?, ?, ?, ?, ?, ?)",
                [(901, 900001, 20, 10, 5, 7.1), (902, 900001, 30, 20, 10, 8.1)])

        status, rows = self.request("/api/snapshots/901/players")
        self.assertEqual(status, 200)
        by_uid = {row["uid"]: row for row in rows}
        self.assertEqual(set(by_uid), {900001, 900002})
        player = by_uid[900001]
        self.assertEqual((player["value"], player["wage"], player["contract_end"]),
                         (1000000, 10000, "2030-06-30"))
        self.assertEqual((player["apps_total"], player["goals"], player["assists"], player["avg_rating"]),
                         (20, 10, 5, 7.1))
        for key in ("value", "wage", "contract_end", "apps_total", "goals", "assists", "avg_rating"):
            self.assertIsNone(by_uid[900002][key], key)
        for query, expected in (
            ("search=Alpha", {900001}), ("search=nickname", {900001}),
            ("team=771", {900001}), ("club=77", {900001}),
            ("search=Alpha&team=771&club=77", {900001}),
            ("search=Alpha&team=881", set()), ("search=Absent", set()),
            ("team=999", set()), ("club=999", set()),
        ):
            with self.subTest(query=query):
                status, filtered = self.request("/api/snapshots/901/players?" + query)
                self.assertEqual(status, 200)
                self.assertEqual({row["uid"] for row in filtered}, expected)
                self.assertTrue(all(row["snapshot_id"] == 901 for row in filtered))
        for sid in (903, 999):
            self.assertEqual(self.request(f"/api/snapshots/{sid}/players"), (200, []))
        pages = [self.request(f"/api/snapshots/901/players?limit=1&offset={offset}") for offset in (0, 1)]
        self.assertTrue(all(status == 200 and len(page) == 1 for status, page in pages))
        self.assertEqual({page[0]["uid"] for _, page in pages}, {900001, 900002})
        self.assertEqual(self.request("/api/snapshots/901/players?limit=1&offset=2"), (200, []))

    def test_player_list_finance_fallback_preserves_zero_and_unknown_values(self):
        db.init_db(str(self.database))
        sid = self.saved_snapshot("Startup finances")
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executemany("INSERT INTO players (snapshot_id, uid) VALUES (?, ?)",
                             [(sid, uid) for uid in (1, 2, 3)])
            conn.executemany(
                "INSERT INTO player_profile (snapshot_id, uid, guide_value, transfer_value, contract_wage) VALUES (?, ?, ?, ?, ?)",
                [(sid, 1, None, 2000000, 10000), (sid, 2, 0, 2000000, 0),
                 (sid, 3, None, None, None)])
        status, rows = self.request(f"/api/snapshots/{sid}/players")
        self.assertEqual(status, 200)
        self.assertEqual({row["uid"]: (row["value"], row["wage"]) for row in rows},
                         {1: (2000000, 10000), 2: (0, 0), 3: (None, None)})

    def test_player_list_keeps_legacy_finance_columns(self):
        sid = self.saved_snapshot("Legacy finances")
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO players (snapshot_id, uid) VALUES (?, 1)", (sid,))
            conn.execute("INSERT INTO player_profile (snapshot_id, uid, value, wage) VALUES (?, 1, 500000, 2500)", (sid,))
        status, rows = self.request(f"/api/snapshots/{sid}/players")
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["value"], rows[0]["wage"]), (500000, 2500))

    def test_player_list_mixed_schema_prefers_current_fields_with_null_fallback(self):
        db.init_db(str(self.database))
        sid = self.saved_snapshot("Mixed finances")
        with closing(sqlite3.connect(self.database)) as conn, conn:
            for column in ("value", "wage"):
                conn.execute(f"ALTER TABLE player_profile ADD COLUMN {column} INTEGER")
            conn.executemany("INSERT INTO players (snapshot_id, uid) VALUES (?, ?)",
                             [(sid, uid) for uid in (1, 2, 3, 4)])
            conn.executemany(
                "INSERT INTO player_profile (snapshot_id, uid, guide_value, transfer_value, value, wage_weekly, contract_wage, wage) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(sid, 1, 1000000, 2000000, 3000000, 1000, 2000, 3000),
                 (sid, 2, None, 2000000, 3000000, None, 2000, 3000),
                 (sid, 3, None, None, 3000000, None, None, 3000),
                 (sid, 4, 0, 2000000, 3000000, 0, 2000, 3000)])
        status, rows = self.request(f"/api/snapshots/{sid}/players")
        self.assertEqual(status, 200)
        self.assertEqual({row["uid"]: (row["value"], row["wage"]) for row in rows},
                         {1: (1000000, 1000), 2: (2000000, 2000),
                          3: (3000000, 3000), 4: (0, 0)})

    def test_live_snapshot_placeholder_has_safe_metadata(self):
        with patch.object(server, "_LIVE_STATUS", {"ready": True, "read_at": None}):
            status, snapshots = self.request("/api/snapshots")
            self.assertEqual(status, 200)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual((snapshots[0]["n_players"], snapshots[0]["size_bytes"]), (0, 0))
            self.assertEqual(snapshots[0]["created_at"], "")
            self.assertTrue(snapshots[0]["is_live"])
            self.assertEqual(self.request("/api/snapshots?include_live=false"), (200, []))

    def test_archived_leagues_has_unavailable_agenda_and_empty_history(self):
        # The shipped Archived component checks proximos===null and reads lidas.length.
        expected = {"auto": None, "proximos": None, "lidas": [], "ligas": []}
        for state in ("no-database", "startup", "stored"):
            if state == "startup":
                db.init_db(str(self.database))
            elif state == "stored":
                self.saved_snapshot("Archived legacy empty season")
            for career in ("carreira_default", "unknown-career"):
                with self.subTest(state=state, career=career):
                    self.assertEqual(self.request(f"/api/carreiras/{career}/outras-ligas"), (200, expected))

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
