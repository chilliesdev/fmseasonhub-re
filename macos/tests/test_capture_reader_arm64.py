"""ARM64 capture layouts verified with FM26 26.3.2 binary and live rosters."""

import struct
import unittest

from test_save_reader_arm64 import MemoryFixture
from fm_reader import FmReader, BASIC_KEYS, ADV_KEYS
from capture_all import build_player_rows, primary_position


class CaptureMemory(MemoryFixture):
    PLAYER = 0x500000000
    TABLE = 0x600000000
    VECTOR = 0x600001000
    ITEMS = 0x600010000
    TEAM = 0x700000000
    CLUB = 0x710000000
    CINO = 0x720000000
    CINT = 0x730000000
    FIN = 0x740000000

    def __init__(self):
        super().__init__()
        self.reads = []
        self.write(self.PLAYER, bytes(0x4A0))
        self.put(self.PLAYER, "Q", self.base + 0x5492830)
        self.put(self.PLAYER + 0x394, "I", 67214451)
        self.put(self.PLAYER + 0x25C, "HH", 126, 133)
        self.put(self.PLAYER + 0x226, "B", 183)
        self.put(self.PLAYER + 0x2D0, "I", 0x07CE0085)
        self.put(self.PLAYER + 0x130, "Q", self.TEAM)
        self.write(self.TEAM, bytes(0xC0))
        self.put(self.TEAM + 0x0C, "I", 1714)
        self.put(self.TEAM + 0x28, "B", 0)
        self.put(self.TEAM + 0x30, "Q", self.CLUB)
        self.put(self.TEAM + 0xA8, "H", 7800)

        self.write(self.CLUB, bytes(0x200))
        self.put(self.CLUB + 0x0C, "I", 1714)
        for off, text in ((0xC0, "Real Betis Balompié"), (0xC8, "Betis")):
            record = 0x850000000 + off * 256
            raw = text.encode()
            self.write(record, struct.pack("<I", len(raw)) + raw)
            self.put(self.CLUB + off, "Q", record)

        self.put(self.CLUB + 0xB0, "Q", self.CINO)
        self.put(self.CLUB + 0x100, "Q", self.CINT)
        self.put(self.CLUB + 0x150, "Q", self.FIN)

        # CINO
        self.write(self.CINO, bytes(0x100))
        self.put(self.CINO + 0x68, "I", 52000)
        self.put(self.CINO + 0x6C, "I", 45000)
        self.put(self.CINO + 0x70, "I", 58000)
        nick_rec = 0x860000000
        raw_nick = b"Los Verdiblancos"
        self.write(nick_rec, struct.pack("<I", len(raw_nick)) + raw_nick)
        self.put(self.CINO + 0x90, "Q", nick_rec)
        fg_rec = 0x860000100
        raw_fg = b"#00FF00"
        self.write(fg_rec, struct.pack("<I", len(raw_fg)) + raw_fg)
        self.put(self.CINO + 0xA0, "Q", fg_rec)
        bg_rec = 0x860000200
        raw_bg = b"#FFFFFF"
        self.write(bg_rec, struct.pack("<I", len(raw_bg)) + raw_bg)
        self.put(self.CINO + 0xA8, "Q", bg_rec)

        # CINT
        self.write(self.CINT, bytes(0x150))
        self.put(self.CINT + 0xD0, "H", 1907)
        self.put(self.CINT + 0x118, "B", 16)
        self.put(self.CINT + 0x123, "B", 17)
        self.put(self.CINT + 0x124, "B", 15)
        self.put(self.CINT + 0x125, "B", 14)
        self.put(self.CINT + 0x11E, "B", 18)
        self.put(self.CINT + 0x10C, "B", 19)
        self.put(self.CINT + 0x10D, "B", 20)

        # FIN
        self.write(self.FIN, bytes(0x850))
        self.put(self.FIN + 0x14, "i", 12500000)
        self.put(self.FIN + 0x7CC, "q", 5000000)
        self.put(self.FIN + 0x810, "q", 850000)
        self.put(self.FIN + 0x818, "q", 720000)
        for off, text in ((0x288, "Luca Zinedine Zidane Fernández"),
                          (0x298, "Luca"), (0x2A0, "Zidane")):
            record = 0x800000000 + off * 256
            raw = text.encode()
            self.write(record, struct.pack("<I", len(raw)) + raw)
            if off != 0x288:
                self.put(record + 128, "Q", record)
                record += 128
            self.put(self.PLAYER + off, "Q", record)
        self.put(self.PLAYER + 0x148, "B", 20)  # GK position, unscaled.
        self.put(self.PLAYER + 0x15E, "B", 45)  # Passing, scaled by five.
        self.put(self.base + 0x55487C0, "Q", self.TABLE)
        self.put(self.TABLE + 0x80, "Q", 0)  # Old inline vector must fail.
        self.put(self.TABLE + 0x88, "Q", self.VECTOR)
        self.put(self.VECTOR, "QQ", self.ITEMS, self.ITEMS + 8)
        self.put(self.ITEMS, "Q", self.TEAM)

    def read_bytes(self, addr, size):
        self.reads.append((addr, size))
        if size > 65536:
            raise OSError("ERR_TOO_LARGE")
        return super().read_bytes(addr, size)

    bytes = read_bytes
    bytes_talvez = read_bytes

    def u16(self, addr):
        return struct.unpack("<H", self.read_bytes(addr, 2))[0]


class Arm64CaptureReaderTests(unittest.TestCase):
    def setUp(self):
        self.mem = CaptureMemory()
        self.reader = FmReader(self.mem)
        self.reader._strict_reads = True

    def test_team_table_dereferences_vector_at_88(self):
        self.assertEqual(self.reader.all_teams_with_players(), [self.mem.TEAM])
        with self.assertRaises(OSError):
            self.reader.vector(self.mem.TABLE + 0x80)

    def test_large_table_uses_bounded_bridge_frames(self):
        count = 9000
        self.mem.write(self.mem.ITEMS, struct.pack(f"<{count}Q", *range(count)))
        self.mem.put(self.mem.VECTOR, "QQ", self.mem.ITEMS, self.mem.ITEMS + count * 8)
        self.assertEqual(self.reader.all_teams_with_players(), list(range(count)))
        self.assertTrue(all(size <= 65536 for _, size in self.mem.reads))

    def test_missing_or_invalid_table_rejects_capture(self):
        for pointer in (0, 12):
            with self.subTest(pointer=pointer):
                self.mem.put(self.mem.TABLE + 0x88, "Q", pointer)
                with self.assertRaises(OSError):
                    self.reader.all_teams_with_players()
        self.mem.put(self.mem.TABLE + 0x88, "Q", self.mem.VECTOR)
        self.mem.put(self.mem.VECTOR, "QQ", self.mem.ITEMS, self.mem.ITEMS - 8)
        with self.assertRaises(OSError):
            self.reader.all_teams_with_players()

    def test_short_bridge_read_rejects_capture(self):
        del self.mem.data[self.mem.ITEMS]
        with self.assertRaises(OSError):
            self.reader.all_teams_with_players()

    def test_inline_table_keeps_legacy_behavior(self):
        self.reader.cfg = {"team_table_chain": {"team_root_rva": 0x55487C0,
                                              "container_off": 0x80}}
        self.mem.put(self.mem.TABLE + 0x80, "QQ", self.mem.ITEMS, self.mem.ITEMS + 8)
        self.assertEqual(self.reader.all_teams_with_players(), [self.mem.TEAM])

    def test_actual_player_reads_virtual_bases_and_real_identity(self):
        identity = self.reader.player_identity(self.mem.PLAYER)
        self.assertEqual(identity["uid"], 67214451)
        self.assertEqual(identity["full_name"], "Luca Zidane")
        self.assertEqual(identity["legal_name"], "Luca Zinedine Zidane Fernández")
        self.assertEqual((identity["ca"], identity["pa"]), (126, 133))
        self.assertEqual(identity["height_cm"], 183)
        self.assertEqual(identity["birth_date"], "1998-05-13")
        self.assertEqual((identity["team_uid"], identity["club_uid"]), (1714, 1714))

    def test_player_staff_uses_its_own_virtual_base_offsets(self):
        self.mem.put(self.mem.PLAYER, "Q", self.mem.base + 0x5498AA0)
        person = self.mem.read_bytes(self.mem.PLAYER + 0x278, 0x110)
        self.mem.write(self.mem.PLAYER + 0x370, person)
        self.mem.put(self.mem.PLAYER + 0x48C, "I", 12345)
        self.assertEqual(self.reader.player_identity(self.mem.PLAYER)["uid"], 12345)

    def test_virtual_fillers_are_skipped_unknown_types_rejected(self):
        self.mem.put(self.mem.PLAYER, "Q", self.mem.base + 0x54D49F0)
        self.assertIsNone(self.reader.jogador_do_elenco(self.mem.PLAYER))
        self.mem.put(self.mem.PLAYER, "Q", self.mem.base + 0x123456)
        with self.assertRaises(OSError):
            self.reader.player_identity(self.mem.PLAYER)

    def test_attributes_are_scaled_positions_are_not(self):
        profile = self.reader.player_profile(self.mem.PLAYER)
        self.assertEqual(profile["passing"], 9)
        self.assertEqual(profile["pos_gk"], 20)
        self.assertEqual(primary_position(profile), "GK")
        self.assertIsNone(profile["wage_weekly"])
        self.assertIsNone(profile["contract_end"])

    def test_unverified_stats_remain_null_in_capture_rows(self):
        stats = self.reader.player_season_stats(self.mem.PLAYER)
        self.assertEqual(stats, {key: None for key in (*BASIC_KEYS, *ADV_KEYS)})
        rows = build_player_rows(self.reader, self.mem.PLAYER, 1, "2026-02-07")
        self.assertTrue(all(value is None for value in rows[1][2:]))

    def test_manager_club_reads_managed_club_and_team(self):
        club_ptr, team_ptr, c_full, c_short = self.reader.manager_club()
        self.assertEqual(club_ptr, self.mem.CLUB)
        self.assertEqual(team_ptr, self.mem.TEAM)
        self.assertEqual(c_full, "Real Betis Balompié")
        self.assertEqual(c_short, "Betis")

    def test_club_profile_reads_complete_facilities_and_finances(self):
        cprof = self.reader.club_profile(self.mem.CLUB)
        self.assertEqual(cprof["club_uid"], 1714)
        self.assertEqual(cprof["name_full"], "Real Betis Balompié")
        self.assertEqual(cprof["name_short"], "Betis")
        self.assertEqual(cprof["nickname"], "Los Verdiblancos")
        self.assertEqual(cprof["year_founded"], 1907)
        self.assertEqual(cprof["color_fg"], "#00FF00")
        self.assertEqual(cprof["color_bg"], "#FFFFFF")
        self.assertEqual(cprof["avg_attendance"], 52000)
        self.assertEqual(cprof["min_attendance"], 45000)
        self.assertEqual(cprof["max_attendance"], 58000)
        self.assertEqual(cprof["balance"], 12500000)
        self.assertEqual(cprof["transfer_budget"], 5000000)
        self.assertEqual(cprof["wage_budget"], 850000)
        self.assertEqual(cprof["wage_total"], 720000)
        self.assertEqual(cprof["training_facilities"], 16)
        self.assertEqual(cprof["youth_facilities"], 17)
        self.assertEqual(cprof["youth_coaching"], 15)
        self.assertEqual(cprof["youth_recruitment"], 14)
        self.assertEqual(cprof["youth_importance"], 18)
        self.assertEqual(cprof["supporter_loyalty"], 19)
        self.assertEqual(cprof["supporter_passion"], 20)

    def test_club_teams_and_team_details_resolve_squad(self):
        teams = self.reader.club_teams(self.mem.CLUB)
        self.assertEqual(teams, [self.mem.TEAM])
        td = self.reader.team_details(self.mem.TEAM)
        self.assertEqual(td["team_uid"], 1714)
        self.assertEqual(td["club_uid"], 1714)
        self.assertEqual(td["team_type"], 0)
        self.assertEqual(td["label"], "First Team")
        self.assertEqual(td["reputation"], 7800)


if __name__ == "__main__":
    unittest.main()
