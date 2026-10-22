import json
import os
import sys
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import paths

ARQUIVO_PORTA = 'porta_do_jogo.json'
RECURSO = 'abrir-jogador'
PROCESSO_DO_JOGO = 'fm.exe'
TIMEOUT = 8

_SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def arquivo_da_porta():
    return os.path.join(paths.documents_dir(), paths.APP_FOLDER_NAME, ARQUIVO_PORTA)


def _nome_do_processo(pid):
    if sys.platform == 'darwin':
        try:
            out = subprocess.check_output(['ps', '-p', str(pid), '-o', 'comm='], text=True).strip()
            return os.path.basename(out).lower()
        except Exception:
            return None
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = wintypes.HANDLE
        PROCESS_QUERY_LIMITED_INFORMATION = 4096
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            tamanho = wintypes.DWORD(1024)
            texto = ctypes.create_unicode_buffer(tamanho.value)
            if not k.QueryFullProcessImageNameW(h, 0, ctypes.byref(texto), ctypes.byref(tamanho)):
                return None
            return os.path.basename(texto.value).lower()
        finally:
            k.CloseHandle(h)
    except Exception:
        return None


def processo_e_do_jogo(pid):
    try:
        nome = _nome_do_processo(pid)
        if not nome:
            return False
        if sys.platform == 'darwin':
            return nome in ('fm', 'fm.app', 'football manager 2026', 'football manager 26') or 'fm' in nome
        return nome == PROCESSO_DO_JOGO
    except Exception:
        return False


def achar_plugin():
    try:
        with open(arquivo_da_porta(), 'r', encoding='utf-8') as f:
            dados = json.load(f)
        porta = dados['porta']
        pid = dados['pid']
        recursos = dados.get('recursos') or []
        if not (isinstance(porta, int) and not isinstance(porta, bool) and 0 < porta < 65536):
            return None
        if not (isinstance(pid, int) and not isinstance(pid, bool) and pid > 0):
            return None
        if not isinstance(recursos, list):
            return None
        if not processo_e_do_jogo(pid):
            return None
        return {
            'porta': porta,
            'pid': pid,
            'versao': str(dados.get('versao') or ''),
            'recursos': recursos,
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def liberar_foco(pid):
    if sys.platform == 'darwin':
        try:
            subprocess.run(['osascript', '-e', 'tell application "Football Manager 2026" to activate'], check=False)
        except Exception:
            pass
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(pid)
    except Exception:
        pass


def _motivo_da_resposta(corpo):
    try:
        dados = json.loads(corpo.decode('utf-8'))
        if isinstance(dados, dict):
            return dados
    except (ValueError, UnicodeDecodeError):
        pass
    return None


def abrir(uid, savegame_id=None):
    plugin = achar_plugin()
    if plugin is None:
        return {'ok': False, 'motivo': 'jogo_fechado'}
    if RECURSO not in plugin['recursos']:
        return {'ok': False, 'motivo': 'plugin_antigo'}
    consulta = {'uid': int(uid)}
    if savegame_id is not None:
        consulta['save'] = savegame_id
    url = f"http://127.0.0.1:{plugin['porta']}/abrir-jogador?{urllib.parse.urlencode(consulta)}"
    pedido = urllib.request.Request(url, data=b'', method='POST')
    liberar_foco(plugin['pid'])
    try:
        with _SEM_PROXY.open(pedido, timeout=TIMEOUT) as resposta:
            corpo = resposta.read()
        dados = _motivo_da_resposta(corpo)
        if dados is None:
            return {'ok': False, 'motivo': 'falhou_no_jogo'}
        if dados.get('ok'):
            return {'ok': True}
        return {'ok': False, 'motivo': dados.get('motivo') or 'falhou_no_jogo'}
    except urllib.error.HTTPError as erro:
        dados = _motivo_da_resposta(erro.read())
        return {'ok': False, 'motivo': (dados or {}).get('motivo') or 'falhou_no_jogo'}
    except TimeoutError:
        return {'ok': False, 'motivo': 'jogo_ocupado'}
    except (urllib.error.URLError, OSError) as erro:
        if isinstance(getattr(erro, 'reason', None), TimeoutError):
            return {'ok': False, 'motivo': 'jogo_ocupado'}
        return {'ok': False, 'motivo': 'jogo_fechado'}
