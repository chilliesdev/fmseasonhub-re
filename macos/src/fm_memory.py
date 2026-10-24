"""Camada de acesso a memoria do Football Manager (somente leitura).

Suporta macOS (Mach VM APIs via libfmsh_bridge ou socket UNIX) e Windows (Win32).
Permite conexao direta, deteccao de versoes, resolucao de base de modulos e leitura de tipos primitivos.
"""

import os
import sys
import struct
import socket
import ctypes
from ctypes import c_uint, c_ulong, c_ulonglong, c_void_p, c_size_t, byref, sizeof
import platform
import subprocess

try:
    import numpy as np
except ImportError:
    np = None

import paths


class FmNotRunning(Exception):
    """O Football Manager nao esta aberto. Abra o FM e carregue um save."""


class FmElevado(Exception):
    """O Football Manager esta aberto com privilegios elevados que impedem a conexao."""


class FmUnsupportedBuild(Exception):
    """O modulo de memoria do Football Manager nao foi encontrado."""


class FmAccessDenied(Exception):
    """O sistema operacional negou acesso a memoria do processo do Football Manager."""


def _to_int(val):
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        val = val.strip()
        if val.startswith("0x") or val.startswith("0X"):
            return int(val, 16)
        return int(val)
    return int(val)


def _log(msg):
    p = paths.local_data_path("logs")
    os.makedirs(p, exist_ok=True)
    log_file = os.path.join(p, "memory.log")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[mem] {msg}\n")
    except Exception:
        pass


class FmMemory:
    MAX_FALHAS_LOGADAS = 10
    ALL_ACCESS = 0x1F0FFF

    def __init__(self, pid=None, pref="steam"):
        self.pref = pref
        self.process_id = None
        self.process_handle = None
        self.task = None
        self.base = 0
        self.fm_version = "26.3.2+2329565"
        self.game_module = "game_plugin"
        self.dll_path = ""
        self.build = "steam"
        self._modules = []
        self._bridge_socket = None
        self._bridge_dylib = None
        self._FALHAS = 0

        self._init_bridge_backend()
        try:
            self._open_game_process(pid)
        except Exception:
            self.close()
            raise

    def _init_bridge_backend(self):
        """Inicializa backend nativo C / dylib ou socket IPC para macOS."""
        if sys.platform != "darwin":
            return

        # 1. Tenta carregar a dylib direta
        dylib_paths = [
            paths.resource_path("..", "native", "libfmsh_bridge.dylib"),
            os.path.join(paths.app_dir(), "native", "libfmsh_bridge.dylib"),
            "/usr/local/lib/libfmsh_bridge.dylib",
        ]
        for dp in dylib_paths:
            dp = os.path.abspath(dp)
            if os.path.isfile(dp):
                try:
                    lib = ctypes.CDLL(dp)
                    lib.fmsh_attach.argtypes = [ctypes.c_int]
                    lib.fmsh_attach.restype = ctypes.c_int
                    lib.fmsh_detach.argtypes = []
                    lib.fmsh_detach.restype = None
                    lib.fmsh_is_attached.argtypes = []
                    lib.fmsh_is_attached.restype = ctypes.c_int
                    lib.fmsh_get_attached_pid.argtypes = []
                    lib.fmsh_get_attached_pid.restype = ctypes.c_int
                    lib.fmsh_read.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
                    lib.fmsh_read.restype = ctypes.c_size_t
                    lib.fmsh_get_regions.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
                    lib.fmsh_get_regions.restype = ctypes.c_size_t
                    self._bridge_dylib = lib
                    break
                except Exception as e:
                    _log(f"Falha ao carregar {dp}: {e}")

    def _try_socket_connect(self):
        sock_path = "/tmp/fmsh_mem_bridge.sock"
        if os.path.exists(sock_path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect(sock_path)
                s.sendall(b"PING\n")
                resp = s.recv(16)
                if b"PONG" in resp:
                    self._bridge_socket = s
                    return True
            except Exception as e:
                _log(f"_try_socket_connect failed: {e}")
        return False

    def _open_game_process(self, pid=None):
        if sys.platform == "darwin":
            self._open_game_process_macos(pid)
        else:
            self._open_game_process_windows(pid)

    def _open_game_process_macos(self, target_pid=None):
        if self._bridge_socket:
            self._bridge_socket.close()
            self._bridge_socket = None
        self.base = 0
        self.process_id = None
        # Localiza o processo do Football Manager
        if target_pid is None:
            # Procura apenas nomes exatos do executavel do jogo.
            pids = []
            try:
                out = subprocess.check_output(["pgrep", "-x", "fm"], timeout=3).decode().split()
                pids = [int(p) for p in out]
            except Exception as e:
                _log(f"_try_socket_connect failed: {e}")

            if not pids:
                try:
                    out = subprocess.check_output(["pgrep", "-x", "Football Manager"], timeout=3).decode().split()
                    pids = [int(p) for p in out]
                except Exception:
                    pass

            if not pids:
                raise FmNotRunning("O Football Manager nao esta aberto. Abra o FM e carregue um save.")

            target_pid = pids[0]

        self.process_id = target_pid

        # Tenta conectar via UNIX domain socket se ativo
        socket_attached = False
        if self._try_socket_connect():
            try:
                self._bridge_socket.sendall(f"ATTACH {target_pid}\n".encode())
                resp = b""
                while b"\n" not in resp:
                    c = self._bridge_socket.recv(1)
                    if not c:
                        break
                    resp += c
                socket_attached = resp == b"OK\n"
                if socket_attached:
                    _log(f"Conectado ao FM PID {target_pid} via socket bridge")
            except OSError as e:
                _log(f"Socket ATTACH falhou: {e}")
            finally:
                if not socket_attached:
                    self._bridge_socket.close()
                    self._bridge_socket = None

        # Socket in-process ja permite leitura; task_for_pid pode pedir autorizacao.
        if not socket_attached and not self._ensure_native_attached():
            raise FmAccessDenied("O macOS negou acesso ao FM. Abra o jogo pelo iniciador do Hub e tente novamente.")

        # Localiza endereco base de game_plugin no processo
        self._resolve_macos_module_base()

    def _ensure_native_attached(self):
        """Confirma o alvo nativo antes de enumerar ou ler sem socket."""
        lib = self._bridge_dylib
        if not lib or not self.process_id:
            return False
        if lib.fmsh_is_attached() and lib.fmsh_get_attached_pid() == self.process_id:
            return True
        lib.fmsh_detach()
        res = lib.fmsh_attach(self.process_id)
        if res != 0:
            lib.fmsh_detach()
            _log(f"task_for_pid falhou com codigo {res}")
            return False
        return True

    def _resolve_macos_module_base(self):
        """Descobre o endereco base virtual de game_plugin no processo alvo."""
        steam_plugin = "/Users/apple/Library/Application Support/Steam/steamapps/common/Football Manager 26/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin"
        if os.path.isfile(steam_plugin):
            self.dll_path = steam_plugin

        arch = platform.machine()
        if arch == "arm64":
            self.build = "steam_macos_arm64"
        else:
            self.build = "steam_macos_x86_64"

        # 1. Tenta resolver via socket bridge in-process
        if self._bridge_socket:
            try:
                self._bridge_socket.sendall(b"GET_BASE game_plugin\n")
                resp = b""
                while b"\n" not in resp:
                    c = self._bridge_socket.recv(1)
                    if not c:
                        break
                    resp += c
                resp_str = resp.decode(errors="ignore").strip()
                if resp_str.startswith("OK"):
                    base_hex = resp_str.split()[1]
                    val = int(base_hex, 16)
                    if val > 0:
                        self.base = val
                        _log(f"game_plugin base detectado via socket bridge: 0x{self.base:X}")
                        return
            except Exception as e:
                _log(f"Falha ao obter GET_BASE via socket: {e}")

        # 2. Usa vmmap se o processo estiver rodando
        if self.process_id:
            try:
                out = subprocess.check_output(["vmmap", str(self.process_id)], timeout=5).decode(errors="ignore")
                for line in out.splitlines():
                    if "game_plugin" in line and "__TEXT" in line:
                        parts = line.split()
                        for p in parts:
                            if "-" in p and len(p) >= 9:
                                start_hex = p.split("-")[0]
                                self.base = int(start_hex, 16)
                                _log(f"game_plugin base detectado via vmmap: 0x{self.base:X}")
                                return
            except Exception as e:
                _log(f"_try_socket_connect failed: {e}")

        raise FmUnsupportedBuild("O modulo game_plugin nao foi encontrado. Carregue um save em uma versao suportada do FM.")

    def close(self):
        """Libera somente a conexao de memoria deste leitor."""
        if self._bridge_socket:
            self._bridge_socket.close()
            self._bridge_socket = None
        if self._bridge_dylib and self._bridge_dylib.fmsh_get_attached_pid() == self.process_id:
            self._bridge_dylib.fmsh_detach()
        if self.process_handle and sys.platform == "win32":
            ctypes.windll.kernel32.CloseHandle(self.process_handle)
        self.process_handle = None
        self.process_id = None
        self.base = 0

    def _open_game_process_windows(self, target_pid=None):
        import pymem
        import pymem.process

        if target_pid:
            pids = [target_pid]
        else:
            pids = []
            for p in pymem.process.list_processes():
                if p.szExeFile.decode(errors="ignore").lower() == "fm.exe":
                    pids.append(p.th32ProcessID)

        if not pids:
            raise FmNotRunning("O Football Manager nao esta aberto. Abra o FM e carregue um save.")

        for pid in pids:
            try:
                pm = pymem.Pymem()
                pm.open_process_from_id(pid)
                # Verifica se game_plugin.dll esta carregado
                for m in pm.list_modules():
                    mname = m.name.lower()
                    if "game_plugin" in mname or "fm.exe" in mname:
                        self.process_id = pid
                        self.process_handle = pm.process_handle
                        self.base = m.lpBaseOfDll
                        self.game_module = m.name
                        self.dll_path = m.filename or ""
                        self.build = "steam"
                        return
            except Exception:
                continue

        raise FmAccessDenied("O Windows negou o acesso ao Football Manager.")

    def read_bytes(self, addr, size):
        """Leitura crua de buffer de memoria."""
        if size <= 0:
            return b""

        # 1. Socket Bridge
        if self._bridge_socket:
            try:
                cmd = f"READ {addr:x} {size}\n".encode()
                self._bridge_socket.sendall(cmd)
                header = b""
                while b"\n" not in header:
                    chunk = self._bridge_socket.recv(1)
                    if not chunk:
                        break
                    header += chunk
                if header.startswith(b"OK"):
                    read_len = int(header.split()[1])
                    buf = b""
                    while len(buf) < read_len:
                        c = self._bridge_socket.recv(read_len - len(buf))
                        if not c:
                            break
                        buf += c
                    if len(buf) == size:
                        return buf
            except Exception as e:
                _log(f"_try_socket_connect failed: {e}")

        # 2. C dylib (Mach VM)
        if self._ensure_native_attached():
            buf = (ctypes.c_uint8 * size)()
            n = self._bridge_dylib.fmsh_read(addr, buf, size)
            if n == size:
                return bytes(buf)

        # 3. Windows Win32 ReadProcessMemory
        if self.process_handle and sys.platform == "win32":
            buf = (ctypes.c_uint8 * size)()
            read_bytes_count = c_size_t(0)
            ok = ctypes.windll.kernel32.ReadProcessMemory(
                self.process_handle,
                c_void_p(addr),
                buf,
                size,
                byref(read_bytes_count)
            )
            if ok:
                return bytes(buf)

        raise OSError(f"Leitura de memoria falhou em 0x{addr:X} ({size} bytes)")

    def bytes(self, addr, size):
        """Leitura com tratamento e registro de falhas."""
        try:
            return self.read_bytes(addr, size)
        except Exception as e:
            if self._FALHAS < self.MAX_FALHAS_LOGADAS:
                self._FALHAS += 1
                _log(f"leitura falhou em 0x{addr:X} ({size} bytes): {e}")
            raise

    def bytes_talvez(self, addr, max_size):
        """Leitura especulativa: tenta ler ate max_size, diminuindo se cruzar paginas invalidas."""
        try:
            return self.read_bytes(addr, max_size)
        except Exception:
            # Tenta ler ate o final da pagina atual (4096 bytes)
            page_remain = 4096 - (addr & 0xFFF)
            tentar = min(max_size, max(8, page_remain))
            try:
                return self.read_bytes(addr, tentar)
            except Exception:
                return b""

    def u8(self, addr):
        data = self.read_bytes(addr, 1)
        return data[0] if data else 0

    def u16(self, addr):
        data = self.read_bytes(addr, 2)
        return struct.unpack("<H", data)[0]

    def u32(self, addr):
        data = self.read_bytes(addr, 4)
        return struct.unpack("<I", data)[0]

    def u64(self, addr):
        data = self.read_bytes(addr, 8)
        return struct.unpack("<Q", data)[0]

    def ptr(self, addr):
        return self.u64(addr)

    def rva(self, offset_hex_or_int):
        """Converte um offset RVA em endereco absoluto da memoria."""
        return self.base + _to_int(offset_hex_or_int)

    def is_alive(self):
        """Verifica se o processo ainda esta ativo e responsivo para leitura."""
        if not self.base:
            return False
        try:
            self.u32(self.base)
            return True
        except Exception:
            return False

    def heap_regions(self, lo=None, hi=None):
        """Enumera regioes de memoria legiveis do processo."""
        regioes = []
        if self._ensure_native_attached():
            max_c = 10000
            addrs = (ctypes.c_uint64 * max_c)()
            sizes = (ctypes.c_uint64 * max_c)()
            n = self._bridge_dylib.fmsh_get_regions(addrs, sizes, max_c)
            for i in range(n):
                a = addrs[i]
                s = sizes[i]
                if lo is not None and a < lo:
                    continue
                if hi is not None and (a + s) > hi:
                    continue
                regioes.append((a, s))
        return regioes

    def scan_qword(self, valor):
        """Localiza todos os enderecos da heap cujo valor de 64 bits seja igual a `valor`."""
        res = self.scan_qwords([valor])
        return res.get(valor, [])

    def scan_qwords(self, valores):
        """Varre as regioes legiveis buscando ocorrencias de múltiplos ponteiros ou valores uint64."""
        conjunto = set(_to_int(v) for v in valores)
        achados = {v: [] for v in conjunto}

        for base, size in self.heap_regions():
            try:
                chunk = self.bytes_talvez(base, size)
                if not chunk or len(chunk) < 8:
                    continue
                if np:
                    arr = np.frombuffer(chunk, dtype=np.uint64)
                    for val in conjunto:
                        idxs = np.flatnonzero(arr == val)
                        for idx in idxs:
                            achados[val].append(base + int(idx * 8))
                else:
                    for off in range(0, len(chunk) - 7, 8):
                        val = struct.unpack_from("<Q", chunk, off)[0]
                        if val in conjunto:
                            achados[val].append(base + off)
            except Exception:
                continue

        return achados

    def find_qword(self, value):
        return self.scan_qword(value)


def load_signatures(fm_version_prefix=None):
    import offsets
    data = offsets.assinaturas()
    vers = data.get("versions", {})
    if fm_version_prefix:
        for k in vers:
            if k.startswith(fm_version_prefix):
                return vers[k]
    return vers.get("26.3.2+2329565", {})
