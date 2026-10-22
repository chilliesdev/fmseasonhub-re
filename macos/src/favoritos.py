# Decompiled from favoritos.pyc (Python 3.14)
import datetime
import threading
import uuid

import limites
import settings

PALETA = (
    '#cbb668',
    '#3fc1c9',
    '#a68bf0',
    '#f27bb5',
    '#f0876a',
    '#a8d45a',
    '#8db8f2',
    '#c3ccd6',
)
NOME_MAXIMO = 80
NOME_PADRAO = 'Favoritos'
NOME_DO_NAVEGADOR = 'Favoritos (deste navegador)'

_TRAVA = threading.RLock()


def _nomes_vazios():
    return {}


nomes_das_carreiras = _nomes_vazios


def _sem_jogo(_listas):
    return {}


jogo_das_listas = _sem_jogo


class ListaNaoExiste(Exception):
    pass


def _agora():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _limpar_nome(nome, reserva=NOME_PADRAO):
    nome = ' '.join(str(nome or '').split())[:NOME_MAXIMO]
    return nome or reserva


def _cor_valida(cor):
    if isinstance(cor, str) and cor.lower() in PALETA:
        return cor
    return None


def _proxima_cor(listas):
    usadas = [x.get('cor') for x in listas]
    for cor in PALETA:
        if cor not in usadas:
            return cor
    return PALETA[len(listas) % len(PALETA)]


def _estado():
    s = settings.load()
    listas = s.get('favoritos_listas')
    return {
        'listas': [dict(x) for x in listas] if isinstance(listas, list) else [],
        'padrao': s.get('favoritos_lista_padrao'),
        'seq': int(s.get('favoritos_seq') or 0),
        'migrado': bool(s.get('favoritos_migrado')),
        'aviso': s.get('favoritos_aviso'),
        'carreiras': s.get('carreiras') if isinstance(s.get('carreiras'), dict) else {},
    }


ouvintes = []


def _gravar(e):
    settings.save(
        favoritos_listas=e['listas'],
        favoritos_lista_padrao=e['padrao'],
        favoritos_seq=e['seq'],
    )
    for ouvinte in list(ouvintes):
        try:
            ouvinte([dict(x) for x in e['listas']])
        except Exception:
            pass


def _nova(e, nome=None, cor=None, uids=(), id_lista=None):
    agora = _agora()
    if id_lista and any(x['id'] == id_lista for x in e['listas']):
        raise ValueError('id de lista repetido')
    id_final = id_lista or str(uuid.uuid4())
    lista = {
        'id': id_final,
        'nome': _limpar_nome(nome),
        'cor': _cor_valida(cor) or _proxima_cor(e['listas']),
        'uids': [],
        'entrou': {},
        'criada_em': agora,
        'atualizada_em': agora,
    }
    _acrescentar(e, lista, uids)
    e['listas'].append(lista)
    return lista


def _acrescentar(e, lista, uids):
    dentro = set(lista['uids'])
    entrou = lista.setdefault('entrou', {})
    mudou = False
    for u in uids:
        u = int(u)
        if u in dentro:
            continue
        e['seq'] += 1
        lista['uids'].append(u)
        entrou[str(u)] = e['seq']
        dentro.add(u)
        mudou = True
    if mudou:
        lista['atualizada_em'] = _agora()
    return mudou


def _tirar(lista, uids):
    fora = {int(u) for u in uids}
    antes = len(lista['uids'])
    lista['uids'] = [u for u in lista['uids'] if u not in fora]
    entrou = lista.setdefault('entrou', {})
    for u in fora:
        entrou.pop(str(u), None)
    mudou = len(lista['uids']) != antes
    if mudou:
        lista['atualizada_em'] = _agora()
    return mudou


def _achar(e, id_lista):
    for x in e['listas']:
        if x['id'] == id_lista:
            return x
    raise ListaNaoExiste(id_lista)


def _migrar(e):
    if e['listas']:
        e['migrado'] = True
        _gravar(e)
        return
    guardadas = e.get('carreiras') or {}
    try:
        nomes = nomes_das_carreiras() or {}
    except Exception:
        nomes = {}
    ordem = [cid for cid in nomes if cid in guardadas]
    resto = sorted([cid for cid in guardadas if cid not in nomes], key=lambda cid: (not str(cid).startswith('sg:'), str(cid)))
    vistos = []
    criadas = []
    for cid in ordem + resto:
        favs = (guardadas.get(cid) or {}).get('favoritos')
        if not isinstance(favs, list):
            continue
        uids = list(dict.fromkeys(int(u) for u in favs if isinstance(u, int) or str(u).isdigit()))
        if not uids or set(uids) in vistos:
            continue
        vistos.append(set(uids))
        nome_carreira = nomes.get(cid) or (guardadas.get(cid) or {}).get('nome') or cid
        lista = _nova(e, f'{NOME_PADRAO} · {nome_carreira}', None, uids)
        criadas.append({'nome': lista['nome'], 'qtd': len(uids)})
    if criadas and not e['padrao']:
        e['padrao'] = e['listas'][0]['id']
    e['migrado'] = True
    _gravar(e)


def _carregar():
    e = _estado()
    if not e['migrado']:
        _migrar(e)
    return e


def _saida(e):
    padrao = e['padrao'] if any(x['id'] == e['padrao'] for x in e['listas']) else (e['listas'][0]['id'] if e['listas'] else None)
    try:
        jogos = jogo_das_listas(e['listas']) or {}
    except Exception:
        jogos = {}
    listas = [dict(x, jogo=jogos.get(x['id'])) for x in e['listas']]
    return {
        'listas': listas,
        'padrao': padrao,
        'paleta': list(PALETA),
        'aviso': e['aviso'] or None,
    }


def estado():
    with _TRAVA:
        return _saida(_carregar())


def listas():
    return estado()['listas']


def uniao():
    vistos = {}
    for x in listas():
        for u in x['uids']:
            vistos.setdefault(u, None)
    return list(vistos)


def uids_da_lista(id_lista):
    for x in listas():
        if x['id'] == id_lista:
            return list(x['uids'])
    return None


def _garantir_padrao(e):
    if e['padrao'] and any(x['id'] == e['padrao'] for x in e['listas']):
        for x in e['listas']:
            if x['id'] == e['padrao']:
                return x
    if e['listas']:
        alvo = e['listas'][0]
    else:
        alvo = _nova(e, NOME_PADRAO, PALETA[0])
    e['padrao'] = alvo['id']
    return alvo


def criar(nome=None, cor=None, uids=(), id_lista=None, teto=None):
    with _TRAVA:
        e = _carregar()
        limites.conferir_listas('favoritos', teto, len(e['listas']))
        lista = _nova(e, nome, cor, uids, id_lista)
        if uids:
            e['padrao'] = lista['id']
        _gravar(e)
        return lista, _saida(e)


def editar(id_lista, nome=None, cor=None, esvaziar=False):
    with _TRAVA:
        e = _carregar()
        lista = _achar(e, id_lista)
        if nome is not None:
            lista['nome'] = _limpar_nome(nome, lista['nome'])
        if cor is not None and _cor_valida(cor):
            lista['cor'] = _cor_valida(cor)
        if esvaziar:
            lista['uids'] = []
            lista['entrou'] = {}
        lista['atualizada_em'] = _agora()
        _gravar(e)
        return _saida(e)


def apagar(id_lista):
    with _TRAVA:
        e = _carregar()
        antes = len(e['listas'])
        e['listas'] = [x for x in e['listas'] if x['id'] != id_lista]
        if len(e['listas']) == antes:
            raise ListaNaoExiste(id_lista)
        if e['padrao'] == id_lista:
            e['padrao'] = e['listas'][0]['id'] if e['listas'] else None
        _gravar(e)
        return _saida(e)


def duplicar(id_lista, nome=None, teto=None):
    with _TRAVA:
        e = _carregar()
        origem = _achar(e, id_lista)
        limites.conferir_listas('favoritos', teto, len(e['listas']))
        copia = _nova(e, nome or (origem['nome'] + ' (2)'), None, origem['uids'])
        _gravar(e)
        return copia, _saida(e)


def marcar(id_lista, uids, marcar_=True):
    with _TRAVA:
        e = _carregar()
        if id_lista == 'padrao':
            lista = _garantir_padrao(e)
        else:
            lista = _achar(e, id_lista)
        if marcar_:
            _acrescentar(e, lista, uids)
            e['padrao'] = lista['id']
        else:
            _tirar(lista, uids)
        _gravar(e)
        return _saida(e)


def tirar_de_todas(uids):
    with _TRAVA:
        e = _carregar()
        for lista in e['listas']:
            _tirar(lista, uids)
        _gravar(e)
        return _saida(e)


def aplicar_uniao(nova):
    with _TRAVA:
        e = _carregar()
        atual = set()
        for x in e['listas']:
            atual |= set(x['uids'])
        desejada = [int(u) for u in nova]
        alvo = _garantir_padrao(e)
        faltam = [u for u in desejada if u not in atual]
        _acrescentar(e, alvo, faltam)
        sobram = atual - set(desejada)
        if sobram:
            for x in e['listas']:
                _tirar(x, sobram)
        _gravar(e)
        return _saida(e)


def migrar_local(uids, nome=None):
    with _TRAVA:
        e = _carregar()
        atual = set()
        for x in e['listas']:
            atual |= set(x['uids'])
        faltam = [int(u) for u in uids if int(u) not in atual]
        lista = None
        if faltam:
            lista = _nova(e, nome or NOME_DO_NAVEGADOR, None, faltam)
            _gravar(e)
        return lista, _saida(e)


def aviso_visto():
    with _TRAVA:
        settings.save(favoritos_aviso=None)
        return estado()
