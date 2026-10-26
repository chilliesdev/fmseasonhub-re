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
        self.put(self.TEAM + 0x0C, "I", 1714)
        self.put(self.TEAM + 0x30, "Q", self.CLUB)
        self.put(self.CLUB + 0x0C, "I", 1714)
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


if __name__ == "__main__":
    unittest.main()
