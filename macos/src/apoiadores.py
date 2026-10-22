import json
import os
import time
import urllib.error
import urllib.request
import paths

LOG = paths.user_data_path('fmsh.log')


def _log(msg, quem):
    try:
        with open(LOG, 'a', encoding='utf-8') as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [{quem}] {msg}\n")
    except OSError:
        pass


SERVICO = 'https://fmsh-acesso.marcellofelipe90.workers.dev'
CACHE = paths.local_data_path('fmsh_apoiadores.json')
VALIDADE = 21600
TIMEOUT = 6
MAX_RESPOSTA = 524288

try:
    from limites import NIVEL_CREDITOS
except ImportError:
    NIVEL_CREDITOS = 1


def _baixar():
    from version import VERSION
    req = urllib.request.Request(
        f'{SERVICO}/apoiadores?nivel={NIVEL_CREDITOS}',
        headers={'User-Agent': f'FMSH/{VERSION}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            dados = json.loads(r.read(MAX_RESPOSTA).decode('utf-8'))
        nomes = dados.get('nomes')
        if isinstance(nomes, list):
            return nomes
        return []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        return None
    except Exception:
        return None


def _ler_cache():
    try:
        with open(CACHE, encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
        return None
    except Exception:
        return None


def _gravar_cache(nomes):
    try:
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump({'nomes': nomes, 'em': time.time()}, f, ensure_ascii=False)
    except OSError as e:
        _log(f'nao consegui gravar o cache: {e}', 'apoiadores')


def listar(forcar=False):
    cache = _ler_cache()
    fresco = bool(cache) and (time.time() - cache.get('em', 0) < VALIDADE)
    if fresco and not forcar:
        return {'nomes': cache['nomes'], 'offline': False}
    nomes = _baixar()
    if nomes is None:
        return {'nomes': (cache or {}).get('nomes', []), 'offline': True}
    _gravar_cache(nomes)
    return {'nomes': nomes, 'offline': False}
