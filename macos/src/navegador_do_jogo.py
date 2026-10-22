# Decompiled from navegador_do_jogo.pyc (Python 3.14) with macOS adaptations
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import atexit

import paths

_CANDIDATOS = (
    # macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    os.path.expanduser('~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
    os.path.expanduser('~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'),
    # Windows
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
)

_ESPERA_MAXIMA = 15.0


def _log(texto):
    try:
        with open(paths.user_data_path('fmsh.log'), 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {texto}\n")
    except Exception:
        pass


_trava = threading.Lock()
_processo = None
_porta = None
_adotado = False
_job = None


def _executavel():
    local = os.environ.get('LOCALAPPDATA', '')
    extras = (os.path.join(local, 'Google\\Chrome\\Application\\chrome.exe'),)
    for caminho in _CANDIDATOS + extras:
        if os.path.isfile(caminho):
            return caminho
    return None


def _ler_json(url, tempo=2.0):
    with urllib.request.urlopen(url, timeout=tempo) as r:
        return json.loads(r.read().decode('utf-8'))


def _vivo():
    if not _porta or (_processo is not None and _processo.poll() is not None):
        return False
    try:
        _ler_json('http://127.0.0.1:%d/json/version' % _porta, 1.0)
        return True
    except Exception:
        return False


class _PerfilEmUso(RuntimeError):
    pass


CODIGO_PERFIL_EM_USO = 21


def _lancar(exe, perfil, arquivo_da_porta, log):
    try:
        os.remove(arquivo_da_porta)
    except OSError:
        pass
    global _processo
    args = [
        exe,
        '--headless=new',
        '--remote-debugging-port=0',
        '--user-data-dir=' + perfil,
        '--no-first-run',
        '--no-default-browser-check',
        '--hide-scrollbars',
        '--mute-audio',
        '--disable-extensions',
        '--disable-component-extensions-with-background-pages',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        'about:blank',
    ]
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    _processo = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    _amarrar_ao_app(_processo, log)
    inicio = time.time()
    while time.time() - inicio < _ESPERA_MAXIMA:
        if _processo.poll() is not None:
            erro = _PerfilEmUso if _processo.returncode == CODIGO_PERFIL_EM_USO else RuntimeError
            raise erro('o navegador fechou ao abrir (codigo %s)' % _processo.returncode)
        try:
            with open(arquivo_da_porta, encoding='utf-8') as f:
                global _porta
                _porta = int(f.readline().strip())
            _ler_json('http://127.0.0.1:%d/json/version' % _porta, 1.0)
            log('navegador do jogo: %s na porta %d (%.1f s)' % (os.path.basename(exe), _porta, time.time() - inicio))
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('o navegador nao respondeu em %.0f s' % _ESPERA_MAXIMA)


def _abrir(log):
    exe = _executavel()
    if exe is None:
        raise RuntimeError('nem Edge nem Chrome instalados')
    perfil = paths.user_data_path('navegador_do_jogo')
    os.makedirs(perfil, exist_ok=True)
    arquivo_da_porta = os.path.join(perfil, 'DevToolsActivePort')
    orfao = _porta_viva(arquivo_da_porta)
    if orfao:
        global _porta, _adotado
        _porta, _adotado = orfao, True
        log(f'navegador do jogo: reutilizando processo existente na porta {orfao}')
        return
    try:
        _lancar(exe, perfil, arquivo_da_porta, log)
    except _PerfilEmUso:
        log('navegador do jogo: perfil preso por processo orfao, limpando')
        _fechar_orfao()
        _lancar(exe, perfil, arquivo_da_porta, log)


def pagina(log=_log):
    with _trava:
        if not _vivo():
            fechar()
            _abrir(log)
        abas = [a for a in _ler_json(f'http://127.0.0.1:{_porta}/json/list') if a.get('type') == 'page']
        if not abas:
            req = urllib.request.Request(f'http://127.0.0.1:{_porta}/json/new?about:blank', method='PUT')
            with urllib.request.urlopen(req, timeout=2.0) as r:
                abas = [json.loads(r.read().decode('utf-8'))]
        return abas[0]['webSocketDebuggerUrl']


def _porta_viva(arquivo_da_porta):
    try:
        with open(arquivo_da_porta, encoding='utf-8') as f:
            porta = int(f.readline().strip())
        _ler_json('http://127.0.0.1:%d/json/version' % porta, 1.0)
        return porta
    except Exception:
        return None


def _amarrar_ao_app(processo, log):
    global _job
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        if _job is None:
            class Limites(ctypes.Structure):
                _fields_ = [
                    ('PerProcessUserTimeLimit', ctypes.c_int64),
                    ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD),
                ]

            class Contadores(ctypes.Structure):
                _fields_ = [
                    ('ReadOperationCount', ctypes.c_uint64),
                    ('WriteOperationCount', ctypes.c_uint64),
                    ('OtherOperationCount', ctypes.c_uint64),
                    ('ReadTransferCount', ctypes.c_uint64),
                    ('WriteTransferCount', ctypes.c_uint64),
                    ('OtherTransferCount', ctypes.c_uint64),
                ]

            class LimitesEstendidos(ctypes.Structure):
                _fields_ = [
                    ('BasicLimitInformation', Limites),
                    ('IoInfo', Contadores),
                    ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t),
                ]

            k32.CreateJobObjectW.restype = wintypes.HANDLE
            job = k32.CreateJobObjectW(None, None)
            info = LimitesEstendidos()
            info.BasicLimitInformation.LimitFlags = 8192  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError('SetInformationJobObject falhou (%d)' % k32.GetLastError())
            _job = job
        if not k32.AssignProcessToJobObject(wintypes.HANDLE(_job), wintypes.HANDLE(int(processo._handle))):
            raise OSError('AssignProcessToJobObject falhou (%d)' % k32.GetLastError())
    except Exception as e:
        log('navegador do jogo: nao consegui amarrar ao app (%s); ele pode sobrar se o app cair' % e)


def _fechar_orfao():
    perfil = paths.user_data_path('navegador_do_jogo').replace("'", "''")
    if sys.platform == 'darwin':
        try:
            subprocess.run(['pkill', '-f', perfil], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass
    comando = "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%s*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" % perfil
    try:
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', comando],
            timeout=15,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception:
        pass


def fechar():
    global _adotado, _processo, _porta
    if _adotado:
        _fechar_orfao()
        _adotado = False
    if _processo is not None and _processo.poll() is None:
        try:
            _processo.terminate()
            _processo.wait(timeout=3)
        except Exception:
            try:
                _processo.kill()
            except Exception:
                pass
    _processo = None
    _porta = None


atexit.register(fechar)
