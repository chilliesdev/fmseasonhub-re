"""Capture HTTP contracts with disposable data and controlled game-reader records."""

from contextlib import closing
from datetime import date
import json
from pathlib import Path
import socket
import sqlite3
import struct
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import db
from fm_memory import FmMemory
from fm_reader import FmReader
import server
import uvicorn



class ReaderMemory(FmMemory):
    """Raw readable regions for real reader and memory buffer methods."""

    def __init__(self):
        self.base = 0x100000
        self.process_id = 1234
        self.build = "steam_macos_arm64"
        self.fm_version = "26.3.2+2329565"
        self.is_alive = Mock(return_value=True)
        self.close = Mock()
        self._FALHAS = self.MAX_FALHAS_LOGADAS
        self.regions = [(self.base, self.base + 0x2000)]
        self.regions += [(address, address + 0x10000) for address in
                         (0x20000, 0x30000, 0x40000, 0x50000, 0x60000,
                          0x70000, 0x80000, 0x90000)]
        self.data = {}
        self.failures = set()
        self.read_requests = []
        self.short_reads = set()
        self.write(self.base + 0x1000, "Q", 0x61000)
        self.write(0x61080, "QQ", 0x62000, 0x62010)
        self.write(0x62000, "QQ", 0x40000, 0x50000)
        for team, roster, player in ((0x40000, 0x63000, 0x20000),
                                     (0x50000, 0x64000, 0x30000)):
            self.write(team + 0x38, "QQ", roster, roster + 8)
            self.write(roster, "Q", player)
            self.write(player + 0x294, "I", player)
            self.write(player + 0x264, "HH", 135, 165)
            self.write(player + 0x240, "B", 182)
            self.write(player + 0x120, "BB", 16, 20)
        self.write(0x30018, "Q", 0x70000)
        self.write(0x70000, "Q", 0x71000)
        self.write(0x71000, "I", 7)
        self.data.update({0x71004 + i: byte for i, byte in enumerate(b"QA real")})
        self.write(0x30108, "Q", 0x80000)
        self.write(0x80048, "Q", 0x81000)
        self.write(0x81000, "Q", 0x82000)
        self.write(0x8100A, "H", 1234)
        self.write(0x8100F, "B", 7)
        self.write(0x300C8, "Q", 0x83000)
        self.write(0x83150, "I", 2500)

    def write(self, address, fmt, *values):
        self.data.update({address + i: byte for i, byte in
                          enumerate(struct.pack("<" + fmt, *values))})

    def read_bytes(self, address, size):
        self.read_requests.append((address, size))
        if (address, size) in self.failures:
            raise OSError(f"Controlled raw memory failure at 0x{address:X}")
        if not any(start <= address and address + size <= end for start, end in self.regions):
            raise OSError(f"Unreadable fixture memory at 0x{address:X}")
        raw = bytes(self.data.get(address + i, 0) for i in range(size))
        return raw[:-1] if (address, size) in self.short_reads else raw


class CaptureTests(unittest.TestCase):
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
            raise RuntimeError("Capture test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = Path(folder.name) / "capture-tests.db"
        self.start_patch(patch.object(server, "get_db_path", return_value=self.database))
        self.notice = self.start_patch(patch.object(server, "AO_AVISO_DA_CAPTURA", Mock()))
        server.parar_leitura_viva()
        self.addCleanup(server.parar_leitura_viva)
        self.mem = SimpleNamespace(process_id=1234, base=0x12340000, build="steam_macos_arm64",
                                   fm_version="26.3.2+2329565", is_alive=Mock(return_value=True), close=Mock())
        self.reader = SimpleNamespace(
            save_session=Mock(return_value=("778899", 42)), game_date=Mock(return_value=date(2027, 6, 30)),
            save_loaded=Mock(return_value=True), save_name=Mock(return_value="QA career"),
            all_teams_with_players=Mock(return_value=[0x40000]), roster=Mock(return_value=[0x20000, 0x30000]),
            jogador_do_elenco=Mock(side_effect=lambda entry: entry), player_block=Mock(return_value=b"records"),
            player_identity=Mock(side_effect=lambda obj, *args: {
                "uid": obj, "full_name": f"QA player {obj}", "display_norm": f"QA player {obj}",
                "club_uid": 100, "team_uid": 101, "ca": 135, "pa": 165, "height_cm": 182,
            }),
            player_profile=Mock(return_value={"passing": 16, "pos_mc": 20, "wage_weekly": 2500, "guide_value": 750000}),
            player_season_stats=Mock(return_value={"goals": 7, "minutes": 1234, "xg": 5.25}),
            player_form=Mock(return_value=[{"date": "2027-06-20", "comp_uid": 10, "rating": 7.5}]),
        )
        self.start_patch(patch.object(server, "FmMemory", return_value=self.mem))
        self.start_patch(patch.object(server, "FmReader", return_value=self.reader))

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def request(self, path, body=None):
        request = urllib.request.Request(self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def connect(self):
        status, response = self.request("/api/connect", {})
        self.assertEqual(status, 200)
        self.assertTrue(response["connected"])

    def seed_existing(self):
        with closing(server.get_db_connection()) as conn, conn:
            sid = conn.execute("INSERT INTO snapshots (name) VALUES ('Keep existing')").lastrowid
            conn.execute("INSERT INTO players (snapshot_id, uid, full_name) VALUES (?, 99, 'Keep player')", (sid,))
        return sid

    def assert_no_capture(self, expected_status, scope=None):
        payload = {"name": "Must not be saved", "game_date": "2040-01-01"}
        if scope is not None:
            payload["scope"] = scope
        status, response = self.request("/api/capture", payload)
        self.assertEqual(status, expected_status, response)
        self.assertNotIn("sid", response)
        with closing(server.get_db_connection()) as conn:
            self.assertEqual([tuple(row) for row in conn.execute("SELECT name FROM snapshots")], [("Keep existing",)])
            self.assertEqual([tuple(row) for row in conn.execute("SELECT uid, full_name FROM players")], [(99, "Keep player")])
        self.notice.assert_not_called()
        job = self.request("/api/job")[1]
        self.assertEqual(job["state"], "error")
        self.assertIsNone(job["sid"])
        self.assertTrue(job["error"])

    def use_real_reader(self):
        memory = ReaderMemory()
        reader = FmReader(memory)
        reader.cfg = {
            "team_table_chain": {"team_root_rva": 0x1000, "container_off": 0x80},
            "attrs_u8": {"passing": 0x120}, "positions_u8": {"pos_mc": 0x121},
        }
        for method in ("save_session", "game_date", "save_loaded", "save_name"):
            setattr(reader, method, getattr(self.reader, method))
        self.start_patch(patch.object(server, "FmMemory", return_value=memory))
        self.start_patch(patch.object(server, "FmReader", return_value=reader))
        self.mem, self.reader = memory, reader
        return memory, reader

    def test_arm64_layout_captures_real_fields_and_preserves_null_stats(self):
        from test_capture_reader_arm64 import CaptureMemory
        memory = CaptureMemory()
        memory.process_id = 1234
        memory.fm_version = "26.3.2+2329565"
        memory.is_alive = Mock(return_value=True)
        memory.close = Mock()
        memory.put(memory.TEAM + 0x38, "QQ", memory.ITEMS + 0x100, memory.ITEMS + 0x108)
        memory.put(memory.ITEMS + 0x100, "Q", memory.PLAYER)
        reader = FmReader(memory)
        self.start_patch(patch.object(server, "FmMemory", return_value=memory))
        self.start_patch(patch.object(server, "FmReader", return_value=reader))
        self.connect()
        for scope in ("squad", "full"):
            status, response = self.request("/api/capture", {"name": scope, "scope": scope})
            self.assertEqual(status, 200, response)
            sid = response["sid"]
            with closing(server.get_db_connection()) as conn:
                player = conn.execute("SELECT uid, full_name, ca, pa FROM players WHERE snapshot_id=?", (sid,)).fetchone()
                self.assertEqual(tuple(player), (67214451, "Luca Zidane", 126, 133))
                stats = conn.execute("SELECT goals, minutes, xg FROM player_stats WHERE snapshot_id=?", (sid,)).fetchone()
                self.assertEqual(tuple(stats), (None, None, None))
                profile = conn.execute("SELECT passing, pos_gk, contract_end, wage_weekly FROM player_profile WHERE snapshot_id=?", (sid,)).fetchone()
                self.assertEqual(tuple(profile), (9, 20, None, None))
            status, response = self.request(f"/api/snapshots/{sid}/players")
            self.assertEqual(status, 200, response)
        memory.put(memory.TABLE + 0x88, "Q", 0)
        status, response = self.request("/api/capture", {"name": "Must fail"})
        self.assertEqual(status, 500, response)
        with closing(server.get_db_connection()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)

    def test_hidden_roster_and_vector_failures_are_not_saved(self):
        self.seed_existing()
        memory, reader = self.use_real_reader()
        for failure, scope in (((0x40038, 8), "squad"),
                               ((0x63000, 8), "squad"),
                               ((0x50038, 8), "full"),
                               ((0x64000, 8), "full")):
            with self.subTest(failure=failure, scope=scope):
                self.connect()
                memory.failures = {failure}
                memory.read_requests.clear()
                self.assert_no_capture(500, scope=scope)
                self.assertIn(failure, memory.read_requests)
                self.assertFalse(reader._strict_reads)
                team = 0x40000 if scope == "squad" else 0x50000
                self.assertEqual(reader.roster(team), [])
                memory.failures.clear()

    def test_hidden_player_data_failures_are_not_saved(self):
        self.seed_existing()
        memory, reader = self.use_real_reader()
        failures = {
            "identity": (0x30294, 4), "attribute": (0x30120, 1),
            "position": (0x30121, 1), "contract": (0x300C8, 8),
            "stats_pointer": (0x30108, 8), "stats_buffer": (0x81000, 0x20),
            "stats_metrics": (0x82000, 0x78), "name": (0x71004, 7),
            "nested_name": (0x70000, 8), "player_block": (0x300F8, 720),
        }
        for field, failure in failures.items():
            with self.subTest(field=field):
                self.connect()
                memory.failures = {failure}
                memory.read_requests.clear()
                self.assert_no_capture(500, scope="full")
                self.assertIn(failure, memory.read_requests)
                self.assertFalse(reader._strict_reads)
                memory.failures.clear()
        memory.failures = {(0x30294, 4)}
        self.assertIsNone(reader.player_identity(0x30000))
        memory.failures = {(0x30120, 1)}
        self.assertEqual(reader.player_profile(0x30000)["passing"], 10)
        memory.failures = {(0x81000, 0x20)}
        self.assertEqual(reader.player_season_stats(0x30000)["goals"], 0)
        memory.failures = {(0x300F8, 720)}
        self.assertEqual(reader.player_block(0x30000), b"")

    def test_short_reader_buffers_and_malformed_vectors_are_not_saved(self):
        self.seed_existing()
        memory, reader = self.use_real_reader()
        for address, size in ((0x300F8, 720), (0x81000, 0x20), (0x71004, 7), (0x64000, 8)):
            with self.subTest(address=address, size=size):
                self.connect()
                memory.short_reads = {(address, size)}
                memory.read_requests.clear()
                self.assert_no_capture(500, scope="full")
                self.assertIn((address, size), memory.read_requests)
                self.assertFalse(reader._strict_reads)
                memory.short_reads.clear()
        memory.write(0x50040, "Q", 0x64007)
        self.connect()
        self.assert_no_capture(500, scope="full")
        self.assertFalse(reader._strict_reads)
        self.assertEqual(reader.roster(0x50000), [])

    def test_real_reader_preserves_empty_teams_and_optional_data(self):
        memory, reader = self.use_real_reader()
        memory.write(0x62010, "Q", 0x90000)
        memory.write(0x61088, "Q", 0x62018)
        for startup_schema in (False, True):
            with self.subTest(startup_schema=startup_schema):
                self.database.unlink(missing_ok=True)
                if startup_schema:
                    db.init_db(str(self.database))
                existing = self.seed_existing()
                self.connect()
                status, response = self.request("/api/capture", {"name": "Raw reader season", "scope": "full"})
                self.assertEqual(status, 200, response)
                sid = response["sid"]
                self.assertNotEqual(sid, existing)
                status, players = self.request(f"/api/snapshots/{sid}/players")
                self.assertEqual(status, 200)
                self.assertEqual([player["uid"] for player in players], [0x20000, 0x30000])
                self.assertEqual([player["goals"] for player in players], [0, 7])
                self.assertEqual([player["wage"] for player in players], [0, 2500])
                with closing(sqlite3.connect(self.database)) as conn:
                    self.assertEqual(conn.execute("SELECT passing, pos_mc FROM player_profile WHERE snapshot_id=?", (sid,)).fetchall(), [(16, 20), (16, 20)])
                job = self.request("/api/job")[1]
                self.assertEqual((job["done"], job["total"]), (2, 2))
                self.assertFalse(reader._strict_reads)
                self.notice.assert_called_with({"sid": sid, "nome": "Raw reader season"})

    def test_never_connected_and_explicit_disconnect_reject_capture(self):
        self.seed_existing()
        self.assert_no_capture(409)
        self.connect()
        self.assertEqual(self.request("/api/disconnect", {})[0], 200)
        self.assert_no_capture(409)
        self.reader.all_teams_with_players.assert_not_called()

    def test_stale_connection_or_metadata_rejects_capture(self):
        self.seed_existing()
        for field, value in (("alive", False), ("loaded", False), ("session", ("other-save", 99)),
                             ("date", None), ("date", date(1999, 1, 1)), ("name", None)):
            with self.subTest(field=field, value=value):
                self.mem.is_alive.return_value = True
                self.reader.save_loaded.return_value = True
                self.reader.save_session.return_value = ("778899", 42)
                self.reader.game_date.return_value = date(2027, 6, 30)
                self.reader.save_name.return_value = "QA career"
                self.connect()
                {"alive": self.mem.is_alive, "loaded": self.reader.save_loaded,
                 "session": self.reader.save_session, "date": self.reader.game_date,
                 "name": self.reader.save_name}[field].return_value = value
                self.assert_no_capture(409)
                self.assertFalse(server._LIVE_STATUS["ready"])

    def test_success_reads_real_scanner_records_and_metadata_in_both_schemas(self):
        for startup_schema in (False, True):
            with self.subTest(startup_schema=startup_schema):
                self.database.unlink(missing_ok=True)
                if startup_schema:
                    db.init_db(str(self.database))
                existing = self.seed_existing()
                self.connect()
                status, response = self.request("/api/capture", {
                    "name": "Read season", "scope": "squad", "game_date": "2040-01-01",
                })
                self.assertEqual(status, 200, response)
                self.assertTrue(response["ok"])
                sid = response["sid"]
                self.assertNotEqual(sid, existing)
                with closing(sqlite3.connect(self.database)) as conn:
                    snapshot = conn.execute("SELECT name, scope, game_date, save_name, savegame_id, carreira_id, fm_version FROM snapshots WHERE id=?", (sid,)).fetchone()
                    self.assertEqual(snapshot, ("Read season", "squad", "2027-06-30", "QA career", "778899", "sg:778899", self.mem.fm_version))
                    self.assertEqual(conn.execute("SELECT uid, ca, pa, club_id, team_uid, position FROM players WHERE snapshot_id=? ORDER BY uid", (sid,)).fetchall(),
                                     [(0x20000, 135, 165, 100, 101, "MC"), (0x30000, 135, 165, 100, 101, "MC")])
                    self.assertEqual(conn.execute("SELECT goals, minutes, xg FROM player_stats WHERE snapshot_id=?", (sid,)).fetchall(), [(7, 1234, 5.25)] * 2)
                    self.assertEqual(conn.execute("SELECT passing, pos_mc, wage_weekly FROM player_profile WHERE snapshot_id=?", (sid,)).fetchall(), [(16, 20, 2500)] * 2)
                    self.assertEqual(conn.execute("SELECT rating FROM player_form WHERE snapshot_id=?", (sid,)).fetchall(), [(7.5,)] * 2)
                    self.assertEqual(conn.execute("SELECT full_name FROM players WHERE snapshot_id=?", (existing,)).fetchone(), ("Keep player",))
                self.assertEqual(self.request(f"/api/snapshots/{sid}")[1]["n_players"], 2)
                player_status, players = self.request(f"/api/snapshots/{sid}/players")
                self.assertEqual(player_status, 200)
                self.assertEqual([player["wage"] for player in players], [2500, 2500])
                self.assertEqual([player["value"] for player in players], [750000, 750000])
                job = self.request("/api/job")[1]
                self.assertEqual((job["sid"], job["state"]), (sid, "done"))
                self.assertEqual((job["done"], job["total"]), (len(players), len(players)))
                self.notice.assert_called_with({"sid": sid, "nome": "Read season"})
                second_status, second = self.request("/api/capture", {"name": "Second season", "scope": "full"})
                self.assertEqual(second_status, 200, second)
                self.assertNotEqual(second["sid"], sid)
                saved_count = self.request(f"/api/snapshots/{second['sid']}")[1]["n_players"]
                self.assertEqual(saved_count, 2)
                job = self.request("/api/job")[1]
                self.assertEqual((job["sid"], job["done"], job["total"]),
                                 (second["sid"], saved_count, saved_count))

    def test_empty_or_unusable_roster_is_not_saved(self):
        self.seed_existing()
        self.connect()
        self.reader.roster.return_value = []
        self.assert_no_capture(422)
        self.reader.roster.return_value = [0x20000]
        self.reader.player_identity.return_value = None
        self.reader.player_identity.side_effect = None
        self.assert_no_capture(422)

    def test_exception_after_committed_scanner_batch_is_not_published(self):
        self.seed_existing()
        self.connect()
        self.reader.roster.return_value = [0x20000 + i for i in range(2001)]
        identity = self.reader.player_identity.side_effect

        def fail_after_batch(obj, *args):
            if obj == 0x20000 + 2000:
                raise RuntimeError("Controlled read failure after 2000-row commit")
            return identity(obj, *args)

        self.reader.player_identity.side_effect = fail_after_batch
        self.assert_no_capture(500)

    def test_reader_failure_before_any_batch_is_not_saved(self):
        self.seed_existing()
        self.connect()
        self.reader.all_teams_with_players.side_effect = OSError("Controlled unreadable team table")
        self.assert_no_capture(500)

    def test_legacy_profile_values_remain_readable_after_capture(self):
        existing = self.seed_existing()
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO player_profile (snapshot_id, uid, value, wage) VALUES (?, 99, 120000, 1500)", (existing,))
        self.connect()
        self.assertEqual(self.request("/api/capture", {})[0], 200)
        status, players = self.request(f"/api/snapshots/{existing}/players")
        self.assertEqual(status, 200)
        self.assertEqual((players[0]["value"], players[0]["wage"]), (120000, 1500))

    def test_session_or_memory_change_during_scan_is_not_saved(self):
        self.seed_existing()
        original_form = self.reader.player_form.return_value
        for change in ("session", "memory", "date"):
            with self.subTest(change=change):
                self.mem.is_alive.return_value = True
                self.reader.save_session.return_value = ("778899", 42)
                self.reader.game_date.return_value = date(2027, 6, 30)
                self.connect()

                def change_during_read(*args):
                    if change == "session":
                        self.reader.save_session.return_value = ("different", 99)
                    elif change == "memory":
                        self.mem.is_alive.return_value = False
                    else:
                        self.reader.game_date.return_value = date(2027, 7, 1)
                    return original_form

                self.reader.player_form.side_effect = change_during_read
                self.assert_no_capture(409)

    def test_publish_failure_rolls_back_snapshot_players_and_migration(self):
        self.seed_existing()
        self.connect()
        with closing(sqlite3.connect(self.database)) as conn:
            before = conn.execute("PRAGMA table_info(players)").fetchall()
            conn.execute("CREATE TRIGGER reject_capture BEFORE INSERT ON player_stats BEGIN SELECT RAISE(ABORT, 'Controlled database failure'); END")
        self.assert_no_capture(500)
        with closing(sqlite3.connect(self.database)) as conn:
            self.assertEqual(conn.execute("PRAGMA table_info(players)").fetchall(), before)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_form'").fetchall(), [])

    def test_session_change_during_publish_rolls_back_all_new_rows(self):
        self.seed_existing()
        self.connect()
        original_publish = db.publish_capture

        def publish_with_changed_save(conn, staged, sid, validate):
            def change_before_commit():
                self.reader.save_session.return_value = ("different", 99)
                validate()
            return original_publish(conn, staged, sid, change_before_commit)

        with patch.object(db, "publish_capture", side_effect=publish_with_changed_save):
            self.assert_no_capture(409)

    def test_notification_failure_does_not_misreport_a_saved_season(self):
        self.seed_existing()
        self.connect()
        self.notice.side_effect = RuntimeError("Controlled notification failure")
        status, response = self.request("/api/capture", {"name": "Saved despite notification"})
        self.assertEqual(status, 200, response)
        self.assertEqual(self.request(f"/api/snapshots/{response['sid']}")[1]["n_players"], 2)

    def test_capture_notification_with_app_main_callback_succeeds_without_exception(self):
        import app_main
        self.seed_existing()
        self.connect()
        tocar_som = Mock()
        janelas = {}
        trava = threading.Lock()
        webview_mock = Mock()
        webview_mock.create_window.return_value = Mock()
        real_aviso = app_main.criar_aviso_da_captura(
            server,
            tocar_som,
            janelas,
            trava,
            "http://127.0.0.1:8000",
            webview_mod=webview_mock,
        )
        self.notice.side_effect = real_aviso
        with patch.object(server.logger, "exception") as mock_logger_exc:
            status, response = self.request("/api/capture", {"name": "Saved and notified"})
            self.assertEqual(status, 200, response)
            mock_logger_exc.assert_not_called()
        tocar_som.assert_called_once_with("captura-fim")
        webview_mock.create_window.assert_called_once()
        self.assertEqual(janelas.get("faixa_tamanho"), (app_main.LARGURA_FAIXA, app_main.ALTURA_FAIXA))

    def test_capture_scope_squad_captures_only_active_squad_and_ignores_other_teams(self):
        team_a = 0x40000
        team_b = 0x50000
        players_a = [0x20000, 0x20001]
        players_b = [0x30000, 0x30001]

        self.reader.all_teams_with_players.return_value = [team_a, team_b]
        self.reader.manager_team = Mock(return_value=team_a)
        self.reader.roster = Mock(side_effect=lambda team: players_a if team == team_a else players_b)

        self.connect()
        status, response = self.request("/api/capture", {"name": "Squad 2027", "scope": "squad"})
        self.assertEqual(status, 200, response)
        sid = response["sid"]

        with closing(server.get_db_connection()) as conn:
            scope = conn.execute("SELECT scope FROM snapshots WHERE id=?", (sid,)).fetchone()[0]
            self.assertEqual(scope, "squad")
            saved_uids = [row[0] for row in conn.execute("SELECT uid FROM players WHERE snapshot_id=? ORDER BY uid", (sid,)).fetchall()]
            self.assertEqual(saved_uids, players_a)

        self.reader.roster.assert_called_once_with(team_a)

    def test_capture_scope_full_and_all_captures_all_teams_and_players(self):
        team_a = 0x40000
        team_b = 0x50000
        players_a = [0x20000, 0x20001]
        players_b = [0x30000, 0x30001]
        all_players = sorted(players_a + players_b)

        self.reader.all_teams_with_players.return_value = [team_a, team_b]
        self.reader.manager_team = Mock(return_value=team_a)
        self.reader.roster = Mock(side_effect=lambda team: players_a if team == team_a else players_b)

        self.connect()

        for scope in ("full", "all"):
            with self.subTest(scope=scope):
                status, response = self.request("/api/capture", {"name": f"DB {scope}", "scope": scope})
                self.assertEqual(status, 200, response)
                sid = response["sid"]

                with closing(server.get_db_connection()) as conn:
                    saved_scope = conn.execute("SELECT scope FROM snapshots WHERE id=?", (sid,)).fetchone()[0]
                    self.assertEqual(saved_scope, scope)
                    saved_uids = [row[0] for row in conn.execute("SELECT uid FROM players WHERE snapshot_id=? ORDER BY uid", (sid,)).fetchall()]
                    self.assertEqual(saved_uids, all_players)

    def test_capture_scope_squad_empty_roster_raises_422(self):
        team_a = 0x40000
        self.reader.all_teams_with_players.return_value = [team_a]
        self.reader.manager_team = Mock(return_value=team_a)
        self.reader.roster = Mock(return_value=[])

        self.connect()
        status, response = self.request("/api/capture", {"name": "Empty Squad", "scope": "squad"})
        self.assertEqual(status, 422, response)
        self.assertIn("Nenhum jogador foi lido", response.get("detail", ""))

        job = self.request("/api/job")[1]
        self.assertEqual(job["state"], "error")
        self.assertIsNone(job["sid"])

    def test_capture_scope_squad_reports_progress(self):
        team_a = 0x40000
        players_a = [0x20000, 0x20001, 0x20002]
        progress_calls = []

        self.reader.all_teams_with_players.return_value = [team_a]
        self.reader.manager_team = Mock(return_value=team_a)
        self.reader.roster = Mock(return_value=players_a)

        import capture
        orig_scan_squad = capture.scan_squad

        def spy_scan_squad(conn, sid, rdr, team, ref_date, progress=None):
            def wrapped_progress(done, total, phase):
                progress_calls.append((done, total, phase))
                if progress:
                    progress(done, total, phase)
            return orig_scan_squad(conn, sid, rdr, team, ref_date, progress=wrapped_progress)

        self.start_patch(patch.object(capture, "scan_squad", side_effect=spy_scan_squad))

        self.connect()
        status, response = self.request("/api/capture", {"name": "Progress Squad", "scope": "squad"})
        self.assertEqual(status, 200, response)
        self.assertEqual(progress_calls, [
            (1, 3, "lendo_elenco"),
            (2, 3, "lendo_elenco"),
            (3, 3, "lendo_elenco"),
        ])


if __name__ == "__main__":
    unittest.main()
