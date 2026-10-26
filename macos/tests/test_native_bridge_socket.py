"""Exercise the compiled bridge in disposable hosts with default SIGPIPE handling."""

import json
import os
from pathlib import Path
import shutil
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "native" / "libfmsh_bridge.c"
HOST = r'''
import ctypes, json, os, signal, sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
bridge = ctypes.CDLL(sys.argv[1])
data = ctypes.create_string_buffer(bytes(range(256)) * 256)
assert bridge.fmsh_start_socket_server() == 0
print(json.dumps({"address": ctypes.addressof(data)}), flush=True)
for command in sys.stdin:
    if command.strip() == "restart":
        bridge.fmsh_stop_socket_server()
        assert bridge.fmsh_start_socket_server() == 0
        print("restarted", flush=True)
    elif command.strip() == "signal":
        bridge.fmsh_stop_socket_server()
        os.kill(os.getpid(), signal.SIGPIPE)
    elif command.strip() == "stop":
        bridge.fmsh_stop_socket_server()
        print("stopped", flush=True)
        break
'''


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang"), "macOS clang required")
class NativeBridgeSocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fmsh-socket-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.socket_path = str(Path(cls.temp.name) / "bridge.sock")
        cls.library = str(Path(cls.temp.name) / "bridge.dylib")
        subprocess.run([
            "clang", "-shared", "-O3", f'-DFMSH_SOCKET_PATH="{cls.socket_path}"',
            str(SOURCE), "-o", cls.library,
        ], check=True, capture_output=True, text=True)

    def setUp(self):
        self.host = subprocess.Popen(
            [sys.executable, "-u", "-c", HOST, self.library],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={key: value for key, value in os.environ.items() if key != "DYLD_INSERT_LIBRARIES"},
        )
        self.addCleanup(self.cleanup_host)
        self.address = json.loads(self.host_line())["address"]
        self.client = self.connect()
        self.addCleanup(self.client.close)
        self.assertEqual(self.command(self.client, b"PING"), b"PONG\n")

    def cleanup_host(self):
        if self.host.poll() is None:
            self.host.kill()
        self.host.communicate(timeout=5)

    def host_line(self):
        ready, _, _ = select.select([self.host.stdout], [], [], 3)
        self.assertTrue(ready, "bridge host did not respond")
        return self.host.stdout.readline()

    @staticmethod
    def line(client):
        result = bytearray()
        while not result.endswith(b"\n"):
            chunk = client.recv(1)
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)

    def command(self, client, command):
        client.sendall(command + b"\n")
        return self.line(client)

    def connect(self):
        deadline = time.monotonic() + 3
        while True:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1)
            try:
                client.connect(self.socket_path)
                return client
            except (FileNotFoundError, ConnectionRefusedError):
                client.close()
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    def reconnect(self):
        deadline = time.monotonic() + 3
        while True:
            client = self.connect()
            try:
                response = self.command(client, b"PING")
                if response == b"PONG\n":
                    return client
                self.assertEqual(response, b"ERR_BUSY\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            client.close()
            if time.monotonic() >= deadline:
                self.fail("active client was not released")
            time.sleep(0.01)

    def test_second_client_is_busy_during_partial_command(self):
        self.client.sendall(b"PI")
        with self.connect() as second:
            self.assertEqual(self.line(second), b"ERR_BUSY\n")
        self.client.sendall(b"NG\n")
        self.assertEqual(self.line(self.client), b"PONG\n")
        # Reproduce the closed B, then closed A sequence from issue #65.
        for _ in range(20):
            second = self.connect()
            second.sendall(b"PING\n")
            second.close()
        self.client.close()
        with self.reconnect() as later:
            self.assertEqual(self.command(later, b"PING"), b"PONG\n")
        self.assertIsNone(self.host.poll())

    def test_protocol_and_binary_read_integrity(self):
        for command, expected in [
            (b"IS_ATTACHED", b"0\n"), (b"READ invalid", b"ERR_SYNTAX\n"),
            (b"READ 0 65537", b"ERR_TOO_LARGE\n"), (b"READ 0 1", b"ERR_READ\n"),
            (b"invalid", b"ERR_UNKNOWN\n"), (b"ATTACH 0", b"OK\n"),
            (b"IS_ATTACHED", b"1\n"),
        ]:
            self.assertEqual(self.command(self.client, command), expected)
        self.assertTrue(self.command(self.client, b"GET_BASE").startswith(b"OK "))
        self.assertEqual(self.command(self.client, f"READ {self.address:x} 65536".encode()), b"OK 65536\n")
        data = bytearray()
        while len(data) < 65536:
            chunk = self.client.recv(min(257, 65536 - len(data)))
            self.assertTrue(chunk, "binary response was truncated")
            data.extend(chunk)
        self.assertEqual(data, bytes(range(256)) * 256)
        self.assertEqual(self.command(self.client, b"DETACH"), b"OK\n")
        self.assertEqual(self.command(self.client, b"PING"), b"PONG\n")

    def test_busy_while_writer_is_backpressured_and_complete_reads(self):
        self.assertEqual(self.command(self.client, b"ATTACH 0"), b"OK\n")
        read = f"READ {self.address:x} 65536\n".encode()
        self.client.sendall(read * 32)
        time.sleep(0.05)
        with self.connect() as second:
            self.assertEqual(self.line(second), b"ERR_BUSY\n")
        expected = bytes(range(256)) * 256
        for _ in range(32):
            self.assertEqual(self.line(self.client), b"OK 65536\n")
            data = bytearray()
            while len(data) < len(expected):
                chunk = self.client.recv(len(expected) - len(data))
                self.assertTrue(chunk, "binary response was truncated")
                data.extend(chunk)
            self.assertEqual(data, expected)
        self.assertEqual(self.command(self.client, b"PING"), b"PONG\n")

    def test_closed_response_readers_do_not_kill_host(self):
        # Queue enough replies to force a partial/nonblocking send before close.
        self.assertEqual(self.command(self.client, b"ATTACH 0"), b"OK\n")
        read = f"READ {self.address:x} 65536\n".encode()
        for command in (b"PING\n", b"IS_ATTACHED\n", b"GET_BASE\n", b"READ bad\n", read):
            self.client.sendall(command * 32)
            time.sleep(0.02)
            self.client.close()
            self.client = self.reconnect()
            self.addCleanup(self.client.close)
        self.assertIsNone(self.host.poll())
        self.assertEqual(self.command(self.client, b"PING"), b"PONG\n")

    def test_stop_restart_and_host_sigpipe_disposition(self):
        self.client.sendall(b"incomplete")
        self.host.stdin.write("restart\n")
        self.host.stdin.flush()
        self.assertEqual(self.host_line(), "restarted\n")
        self.client.close()
        with self.reconnect() as later:
            self.assertEqual(self.command(later, b"PING"), b"PONG\n")
        self.host.stdin.write("signal\n")
        self.host.stdin.flush()
        self.assertEqual(self.host.wait(timeout=3), -signal.SIGPIPE)


if __name__ == "__main__":
    unittest.main()
