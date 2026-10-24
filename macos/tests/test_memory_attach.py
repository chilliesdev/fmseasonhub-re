"""Attachment selection must avoid redundant macOS authorization requests."""

import os
import socket
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import fm_memory


class TestMemoryAttach(unittest.TestCase):
    def setUp(self):
        self.mem = fm_memory.FmMemory.__new__(fm_memory.FmMemory)
        self.sock = Mock()
        self.mem._bridge_socket = None
        self.mem._bridge_dylib = Mock()
        self.mem._bridge_dylib.fmsh_attach.return_value = 0
        self.mem.process_handle = None
        self.native_pid = 0
        self.mem._bridge_dylib.fmsh_get_attached_pid.side_effect = lambda: self.native_pid
        self.mem._bridge_dylib.fmsh_is_attached.side_effect = lambda: bool(self.native_pid)
        self.mem._bridge_dylib.fmsh_detach.side_effect = self.detach_native
        self.mem._bridge_dylib.fmsh_attach.side_effect = self.attach_native
        self.mem._try_socket_connect = Mock(side_effect=self.connect_socket)
        self.mem._resolve_macos_module_base = Mock()
        log_patch = patch.object(fm_memory, "_log")
        self.log = log_patch.start()
        self.addCleanup(log_patch.stop)

    def connect_socket(self):
        self.mem._bridge_socket = self.sock
        return True

    def detach_native(self):
        self.native_pid = 0

    def attach_native(self, pid):
        self.native_pid = pid
        return 0

    def attach(self):
        self.mem._open_game_process_macos(1234)
        self.assertEqual(self.mem.process_id, 1234)
        self.mem._resolve_macos_module_base.assert_called_once_with()

    def test_socket_success_does_not_request_native_authorization(self):
        self.sock.recv.side_effect = [b"O", b"K", b"\n"]
        self.attach()
        self.sock.sendall.assert_called_once_with(b"ATTACH 1234\n")
        self.mem._bridge_dylib.fmsh_attach.assert_not_called()
        self.sock.close.assert_not_called()
        self.assertIs(self.mem._bridge_socket, self.sock)

    def test_unavailable_socket_uses_native_attachment(self):
        self.mem._try_socket_connect.side_effect = None
        self.mem._try_socket_connect.return_value = False
        self.mem._bridge_socket = None
        self.attach()
        self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(1234)
        self.sock.sendall.assert_not_called()

    def test_rejected_or_incomplete_socket_uses_native_attachment(self):
        for reply in (b"ERR 5\n", b"NOT_OK\n", b"OK", b""):
            with self.subTest(reply=reply):
                self.sock.reset_mock()
                self.mem._bridge_dylib.reset_mock()
                self.native_pid = 0
                self.mem._resolve_macos_module_base.reset_mock()
                self.mem._bridge_socket = None
                self.sock.recv.side_effect = [bytes([c]) for c in reply] + [b""]
                self.attach()
                self.sock.close.assert_called_once_with()
                self.assertIsNone(self.mem._bridge_socket)
                self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(1234)

    def test_socket_timeout_uses_native_attachment(self):
        self.sock.recv.side_effect = socket.timeout("timed out")
        self.attach()
        self.sock.close.assert_called_once_with()
        self.assertIsNone(self.mem._bridge_socket)
        self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(1234)

    def test_native_failure_is_reported(self):
        self.mem._try_socket_connect.side_effect = None
        self.mem._try_socket_connect.return_value = False
        self.mem._bridge_socket = None
        self.mem._bridge_dylib.fmsh_attach.side_effect = None
        self.mem._bridge_dylib.fmsh_attach.return_value = 5
        with self.assertRaises(fm_memory.FmAccessDenied):
            self.mem._open_game_process_macos(1234)
        self.mem._resolve_macos_module_base.assert_not_called()
        self.log.assert_called_with("task_for_pid falhou com codigo 5")

    def socket_attach(self):
        self.sock.recv.side_effect = [b"O", b"K", b"\n"]
        self.attach()

    def test_successful_socket_read_keeps_native_attachment_lazy(self):
        self.socket_attach()
        self.sock.recv.side_effect = [b"O", b"K", b" ", b"4", b"\n", b"data"]
        self.assertEqual(self.mem.read_bytes(0x1000, 4), b"data")
        self.mem._bridge_dylib.fmsh_attach.assert_not_called()

    def test_heap_scan_lazily_attaches_native_target(self):
        self.socket_attach()
        def regions(addrs, sizes, limit):
            self.assertEqual(self.native_pid, 1234)
            addrs[0], sizes[0] = 0x1000, 8
            return 1
        self.mem._bridge_dylib.fmsh_get_regions.side_effect = regions
        self.assertEqual(self.mem.heap_regions(), [(0x1000, 8)])
        self.sock.recv.side_effect = [b"O", b"K", b" ", b"8", b"\n", (42).to_bytes(8, "little")]
        self.assertEqual(self.mem.scan_qwords([42]), {42: [0x1000]})
        self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(1234)

    def test_socket_read_failure_lazily_attaches_native_target(self):
        for response in (b"ERR_TOO_LARGE\n", b""):
            with self.subTest(response=response):
                self.native_pid = 0
                self.mem._bridge_dylib.reset_mock()
                self.mem._resolve_macos_module_base.reset_mock()
                self.socket_attach()
                self.sock.recv.side_effect = [bytes([c]) for c in response] + [b""]
                def read(addr, buf, size):
                    self.assertEqual(self.native_pid, 1234)
                    buf[:] = b"data"
                    return size
                self.mem._bridge_dylib.fmsh_read.side_effect = read
                self.assertEqual(self.mem.read_bytes(0x1000, 4), b"data")
                self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(1234)

    def test_external_detach_or_target_change_is_repaired(self):
        self.socket_attach()
        self.mem._bridge_dylib.fmsh_get_regions.return_value = 0
        for stale_pid in (0, 9999):
            with self.subTest(stale_pid=stale_pid):
                self.native_pid = stale_pid
                self.mem._bridge_dylib.reset_mock()
                self.mem.heap_regions()
                self.assertEqual(self.native_pid, 1234)
                self.mem._bridge_dylib.fmsh_detach.assert_called_once_with()
                self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(1234)

    def test_native_failure_does_not_read_stale_target(self):
        self.socket_attach()
        self.native_pid = 9999
        self.mem._bridge_dylib.fmsh_attach.side_effect = None
        self.mem._bridge_dylib.fmsh_attach.return_value = 5
        self.assertEqual(self.mem.heap_regions(), [])
        self.mem._bridge_dylib.fmsh_get_regions.assert_not_called()
        self.sock.recv.side_effect = socket.timeout("timed out")
        with self.assertRaises(OSError):
            self.mem.read_bytes(0x1000, 4)
        self.mem._bridge_dylib.fmsh_read.assert_not_called()
        self.assertEqual(self.native_pid, 0)

    def test_reopen_closes_old_socket_and_uses_new_native_target(self):
        self.socket_attach()
        self.native_pid = 1234
        self.mem.base = 0x1234000
        self.sock.recv.side_effect = [b"O", b"K", b"\n"]
        self.mem._open_game_process_macos(5678)
        self.sock.close.assert_called_once_with()
        self.assertEqual(self.mem.base, 0)
        self.mem._bridge_dylib.fmsh_get_regions.return_value = 0
        self.mem.heap_regions()
        self.assertEqual(self.native_pid, 5678)
        self.mem._bridge_dylib.fmsh_attach.assert_called_once_with(5678)
