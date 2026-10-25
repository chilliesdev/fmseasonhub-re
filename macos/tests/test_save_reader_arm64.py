"""ARM64 26.3.2 save metadata, using read-only byte fixtures from live probes."""

from datetime import date
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fm_reader import FmReader


class MemoryFixture:
    base = 0x100000000
    build = "steam_macos_arm64"
    UI = 0x200000000
    SAVE = 0x300000000
    NAME = 0x400000000

    def __init__(self, loaded=True):
        self.data = {}
        # GAME_UI serializes the persistent unique-game ID at +0xB8.
        self.put(self.base + 0x5547838, "Q", self.UI)
        self.put(self.UI, "Q", self.base + 0x533C760)
        session = (4384013, 4996031) if loaded else (0, 0)
        self.put(self.UI + 0xB8, "II", *session)
        self.put(self.base + 0x55270D0, "Q", self.SAVE)
        self.put(self.SAVE, "Q", self.base + 0x54186C8)
        self.put(self.SAVE + 0x28, "Q", self.NAME if loaded else 0)
        name = b"Hull career"
        self.write(self.NAME, struct.pack("<I", len(name)) + name)
        self.put(self.base + 0x553E3A8, "I", 0x07EA6A26 if loaded else 0x076C0001)
        # Old root +0xB8 is beyond the 0x78-byte SAVE_SYSTEM allocation.
        # Adjacent heap data can be positive even with no save loaded.
        self.put(self.SAVE + 0xB8, "II", 27, 0)
        # The old date RVA contains pointers, not an encoded FM date.
        self.put(self.base + 0x5547638, "Q", 0xC4E356168)

    def write(self, addr, raw):
        self.data.update((addr + offset, value) for offset, value in enumerate(raw))

    def put(self, addr, fmt, *values):
        self.write(addr, struct.pack("<" + fmt, *values))

    def read_bytes(self, addr, size):
        try:
            return bytes(self.data[addr + offset] for offset in range(size))
        except KeyError:
            raise OSError("Unmapped memory") from None

    bytes = read_bytes
    bytes_talvez = read_bytes

    def u32(self, addr):
        return struct.unpack("<I", self.read_bytes(addr, 4))[0]

    def u64(self, addr):
        return struct.unpack("<Q", self.read_bytes(addr, 8))[0]

    def rva(self, value):
        return self.base + (int(value, 0) if isinstance(value, str) else value)


class Arm64SaveReaderTests(unittest.TestCase):
    def setUp(self):
        self.mem = MemoryFixture()
        self.reader = FmReader(self.mem)

    def test_loaded_save_uses_game_ui_identity_live_date_and_separate_name(self):
        self.assertEqual(self.reader.save_session(), ("4384013", 4996031))
        self.assertEqual(self.reader.savegame_id(), "4384013")
        self.assertEqual(self.reader.game_date(), date(2026, 2, 7))
        self.assertEqual(self.reader.save_name(), "Hull career")
        self.assertTrue(self.reader.save_loaded())

    def test_main_menu_does_not_accept_adjacent_heap_bytes_as_save_identity(self):
        reader = FmReader(MemoryFixture(loaded=False))
        self.assertEqual(reader.save_session(), (None, 0))
        self.assertIsNone(reader.save_name())
        self.assertFalse(reader.save_loaded())

    def test_zero_or_unreadable_id_rejects_loaded_date(self):
        self.mem.put(self.mem.UI + 0xB8, "I", 0)
        self.assertFalse(self.reader.save_loaded())
        del self.mem.data[self.mem.UI + 0xB8]
        self.assertEqual(self.reader.save_session(), (None, 0))

    def test_null_or_wrong_object_cannot_supply_an_identity(self):
        self.mem.put(self.mem.UI, "Q", self.mem.base + 0x54186C8)
        self.assertEqual(self.reader.save_session(), (None, 0))
        self.mem.put(self.mem.base + 0x5547838, "Q", 0)
        self.assertFalse(self.reader.save_loaded())

    def test_invalid_or_unloaded_date_rejects_nonzero_identity(self):
        for raw in (0, 0xFFFFFFFF, 0x076C0001):
            with self.subTest(raw=raw):
                self.mem.put(self.mem.base + 0x553E3A8, "I", raw)
                self.assertFalse(self.reader.save_loaded())

    def test_identity_and_session_changes_are_read_without_cached_metadata(self):
        self.assertEqual(self.reader.save_session(), ("4384013", 4996031))
        self.mem.put(self.mem.UI + 0xBC, "I", 6000021)
        self.assertEqual(self.reader.save_session(), ("4384013", 6000021))
        self.mem.put(self.mem.UI + 0xB8, "I", 7123456)
        self.assertEqual(self.reader.save_session(), ("7123456", 6000021))

    def test_name_failure_does_not_invent_a_name_or_change_identity(self):
        for raw in (0, 257, 0xFFFFFFFF):
            with self.subTest(length=raw):
                self.mem.put(self.mem.NAME, "I", raw)
                self.assertIsNone(self.reader.save_name())
                self.assertEqual(self.reader.savegame_id(), "4384013")
        self.mem.put(self.mem.SAVE, "Q", self.mem.base + 0x533C760)
        self.assertIsNone(self.reader.save_name())

    def test_root_change_during_session_read_is_rejected(self):
        read = self.mem.u32
        def changing_root(addr):
            result = read(addr)
            if addr == self.mem.UI + 0xBC:
                self.mem.put(self.mem.base + 0x5547838, "Q", 0)
            return result
        self.mem.u32 = changing_root
        self.assertEqual(self.reader.save_session(), (None, 0))

    def test_legacy_configuration_without_vtable_requirement_still_reads_ids(self):
        self.reader.cfg = {"savegame_id_chain": {"savegame_id_rva": "0x1000",
                          "field_off": "0x90", "session_nonce_off": "0xA0"}}
        self.mem.put(self.mem.base + 0x1000, "Q", self.mem.UI)
        self.mem.put(self.mem.UI + 0x90, "I", 123456)
        self.mem.put(self.mem.UI + 0xA0, "I", 789)
        self.assertEqual(self.reader.save_session(), ("123456", 789))


class Arm64ReaderConnectionTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        server.parar_leitura_viva()
        self.addCleanup(server.parar_leitura_viva)
        self.mem = MemoryFixture()
        self.mem.process_id = 1234
        self.mem.is_alive = lambda: True
        self.mem.close = lambda: None
        memory_patch = patch.object(server, "FmMemory", return_value=self.mem)
        memory_patch.start()
        self.addCleanup(memory_patch.stop)

    def test_real_reader_connects_loaded_bytes_and_clears_on_unload(self):
        self.assertTrue(self.server._connect_game()["connected"])
        status = self.server._connection_status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["savegame_id"], "4384013")
        self.assertEqual(status["game_date"], "2026-02-07")
        self.assertEqual(status["save_name"], "Hull career")
        self.mem.put(self.mem.UI + 0xB8, "II", 0, 0)
        status = self.server._connection_status()
        self.assertFalse(status["ready"])
        self.assertTrue(status["save_changed"])
        self.assertIsNone(status["savegame_id"])

    def test_same_career_reload_nonce_invalidates_the_previous_connection(self):
        self.assertTrue(self.server._connect_game()["connected"])
        self.mem.put(self.mem.UI + 0xBC, "I", 6000021)
        status = self.server._connection_status()
        self.assertFalse(status["ready"])
        self.assertTrue(status["save_changed"])
        self.assertTrue(self.server._connect_game()["connected"])
        self.assertEqual(self.server._connection_status()["savegame_id"], "4384013")
        self.assertEqual(self.server._connection_status()["session_nonce"], 6000021)

    def test_real_reader_rejects_main_menu_despite_positive_adjacent_heap_data(self):
        self.mem.put(self.mem.UI + 0xB8, "II", 0, 0)
        self.mem.put(self.mem.base + 0x553E3A8, "I", 0x076C0001)
        result = self.server._connect_game()
        self.assertFalse(result["connected"])
        self.assertEqual(result["error_code"], "no_save")


if __name__ == "__main__":
    unittest.main()
