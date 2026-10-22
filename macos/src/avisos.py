import json
import os
import time
import urllib.error
import urllib.request
import paths
import settings

LOG = paths.user_data_path('fmsh.log')


def _log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [avisos] {msg}\n")
    except OSError:
        pass


SERVICO = 'https://fmsh-acesso.marcellofelipe90.workers.dev'
CACHE = paths.local_data_path('fmsh_avisos.json')
VALIDADE = 1800
TIMEOUT = 6
MAX_RESPOSTA = 524288


def _baixar():
    from version import VERSION
    req = urllib.request.Request(
        SERVICO + '/avisos',
        headers={'User-Agent': f'FMSH/{VERSION}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            dados = json.loads(r.read(MAX_RESPOSTA).decode('utf-8'))
        lista = dados.get('avisos')
        if isinstance(lista, list):
            return lista
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
            return json.load(f)
    except (OSError, ValueError):
        return {'avisos': [], 'baixado_em': 0}


def _no_idioma(a, lang):
    if lang.startswith('pt') or not (a.get('titulo_en') or a.get('corpo_en') or a.get('link_texto_en')):
        return a
    return dict(
        a,
        titulo=a.get('titulo_en') or a.get('titulo'),
        corpo=a.get('corpo_en') or a.get('corpo'),
        link_texto=a.get('link_texto_en') or a.get('link_texto'),
    )


def listar(forcar=False, lang='pt'):
    cache = _ler_cache()
    velho = (time.time() - cache.get('baixado_em', 0)) > VALIDADE
    if forcar or velho:
        novos = _baixar()
        if novos is not None:
            cache = {'avisos': novos, 'baixado_em': time.time()}
            try:
                with open(CACHE, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False)
            except OSError as e:
                _log(f'nao consegui gravar o cache do mural: {e}')
    lidos = set(settings.load().get('avisos_lidos') or [])
    avisos = cache.get('avisos') or []
    return {
        'avisos': [
            dict(_no_idioma(a, lang), lido=str(a.get('id')) in lidos)
            for a in avisos
        ],
        'nao_lidos': sum(1 for a in avisos if str(a.get('id')) not in lidos),
        'offline': cache.get('baixado_em', 0) == 0,
    }


def marcar_lidos(lang='pt'):
    cache = _ler_cache()
    ids = [str(a.get('id')) for a in (cache.get('avisos') or []) if a.get('id')]
    lidos = set(settings.load().get('avisos_lidos') or []) | set(ids)
    settings.save(avisos_lidos=sorted(lidos)[-200:])
    return listar(lang=lang)


def limpar_cache():
    try:
        os.remove(CACHE)
    except OSError:
        pass
