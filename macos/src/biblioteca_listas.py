# Decompiled from biblioteca_listas.pyc (Python 3.14)
import os
import re
import threading
import time
import unicodedata

import biblioteca
import paths
import version


def _sem_identidades(_uids):
    return {}


identidades = _sem_identidades
familias = _sem_identidades


def jogo_unanime(uids, por_uid):
    vistos = {por_uid[u] for u in uids if u in por_uid}
    if len(vistos) == 1:
        return vistos.pop()
    return None


_TRAVA = threading.RLock()
_escrito = {}


def _log(msg):
    try:
        with open(paths.user_data_path('fmsh.log'), 'a', encoding='utf-8') as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [listas na Biblioteca] {msg}\n")
    except Exception:
        pass


def _nome_de_arquivo(nome):
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', str(nome or '')).strip(' .')[:80]
    return f"{limpo or 'lista'}.lsh"


def _lsh_por_id():
    pasta = paths.biblioteca_dir()
    saida = {}
    try:
        nomes = sorted(os.listdir(pasta))
    except OSError:
        return saida
    for nome in nomes:
        caminho = os.path.join(pasta, nome)
        if not (nome.lower().endswith('.lsh') and biblioteca._cabe(caminho)):
            continue
        try:
            with open(caminho, encoding='utf-8') as fh:
                dados = biblioteca.ler_texto(fh.read(), '.lsh')
        except (OSError, biblioteca.ArquivoInvalido):
            continue
        if dados.get('id'):
            saida.setdefault(dados['id'], nome)
    return saida


def conteudo(lista, ident):
    if len(lista['uids']) > biblioteca.MAX_JOGADORES:
        raise ValueError(f"'{lista['nome']}' tem mais de {biblioteca.MAX_JOGADORES} jogadores")
    jogadores = []
    for u in lista['uids']:
        info = ident.get(u) or {}
        item = {'uid': u}
        for k, v in info.items():
            if v is not None:
                item[k] = v
        jogadores.append(item)
    dados = {
        'id': lista['id'],
        'nome': lista['nome'],
        'app_versao': version.VERSION,
        'jogadores': jogadores,
    }
    if re.fullmatch(r'#[0-9a-fA-F]{6}', lista.get('cor') or ''):
        dados['cor'] = lista['cor']
    jogo = jogo_unanime(lista['uids'], familias(lista['uids']) if lista['uids'] else {})
    if jogo:
        dados['jogo'] = jogo
    return biblioteca.conferir(dados, '.lsh')


def _gravar(arquivo, dados):
    import json
    destino = os.path.join(paths.biblioteca_dir(), arquivo)
    temporario = destino + '.tmp'
    with open(temporario, 'w', encoding='utf-8') as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1)
    os.replace(temporario, destino)


def espelhar_favoritos(listas):
    with _TRAVA:
        por_id = None
        for lista in listas:
            marca = (lista['nome'], lista.get('cor'), tuple(lista['uids']))
            if _escrito.get(lista['id']) == marca:
                continue
            try:
                if por_id is None:
                    por_id = _lsh_por_id()
                dados = conteudo(lista, identidades(lista['uids']) if lista['uids'] else {})
                arquivo = por_id.get(lista['id']) or biblioteca._nome_livre(_nome_de_arquivo(lista['nome']))
                _gravar(arquivo, dados)
                _escrito[lista['id']] = marca
                por_id[lista['id']] = arquivo
            except Exception as erro:
                _log(f"falhou ao gravar '{lista['nome']}': {erro!r}")


def espelhar_tudo():
    import favoritos
    import lista_fmf
    with _TRAVA:
        _escrito.clear()
    espelhar_favoritos(favoritos.listas())
    try:
        lista_fmf.espelhar_existentes()
    except Exception as erro:
        _log(f'falhou ao copiar as listas do FM: {erro!r}')


def situacao(itens):
    import favoritos
    import lista_fmf
    ids_favoritos = {x['id'] for x in favoritos.listas()}
    ligadas = {x.get('arquivo_biblioteca'): x['id'] for x in lista_fmf.listar() if x.get('arquivo_biblioteca')}
    for item in itens:
        if item.get('erro'):
            continue
        if item.get('tipo') == 'lista':
            item['carregada'] = bool(item.get('listaId')) and item['listaId'] in ids_favoritos
        elif item.get('tipo') == 'listaFm':
            item['listaId'] = ligadas.get(item['arquivo'], '')
            item['carregada'] = bool(item['listaId'])


def _normal(texto):
    return (
        unicodedata.normalize('NFKD', str(texto or ''))
        .encode('ascii', 'ignore')
        .decode()
        .casefold()
        .strip()
    )


def _confere(do_arquivo, local):
    n1 = (do_arquivo.get('nascimento') or '')[:10]
    n2 = (local.get('nascimento') or '')[:10]
    if n1 and n2:
        return n1 == n2
    a = _normal(do_arquivo.get('nome')).split()
    b = _normal(local.get('nome')).split()
    if not a or not b:
        return True
    return set(a) <= set(b) or set(b) <= set(a) or (a[0] == b[0] and a[-1] == b[-1])


def carregar(arquivo, teto_fm=None, teto_favoritos=None):
    arquivo = biblioteca.nome_seguro(arquivo)
    ext = os.path.splitext(arquivo)[1].lower()
    if ext == '.lsh':
        return _carregar_lsh(arquivo, teto_favoritos)
    if ext == '.fmf':
        return _carregar_fmf(arquivo, teto_fm)
    raise biblioteca.ArquivoInvalido('este arquivo nao e uma lista')


def _carregar_lsh(arquivo, teto=None):
    import favoritos
    caminho = os.path.join(paths.biblioteca_dir(), arquivo)
    if not os.path.isfile(caminho):
        c_fab = os.path.join(biblioteca._pasta_fabrica(), biblioteca.nome_seguro(arquivo))
        if not os.path.isfile(c_fab):
            raise biblioteca.ArquivoInvalido('arquivo nao encontrado')
    dados = biblioteca.ler(arquivo)
    if isinstance(dados, (bytes, bytearray)):
        import json
        try:
            dados = json.loads(dados.decode('utf-8'))
        except Exception as e:
            raise biblioteca.ArquivoInvalido(str(e))
    elif isinstance(dados, str):
        import json
        try:
            dados = json.loads(dados)
        except Exception as e:
            raise biblioteca.ArquivoInvalido(str(e))
    if not isinstance(dados, dict):
        raise biblioteca.ArquivoInvalido('formato de lista invalido')
    id_arquivo = dados.get('id') or ''
    nome_lista = dados.get('nome') or os.path.splitext(arquivo)[0]
    ja = next((x for x in favoritos.listas() if (id_arquivo and x['id'] == id_arquivo)
               or (not id_arquivo and x.get('nome') == nome_lista)), None)
    if ja:
        return {
            'destino': 'favoritos',
            'id': ja['id'],
            'ja_estava': True,
            'importados': len(ja['uids']),
            'nao_conferem': [],
            'sem_captura': 0,
        }
    jogadores = dados.get('jogadores')
    if not isinstance(jogadores, list):
        raise biblioteca.ArquivoInvalido('formato de lista invalido')
    uids = [j['uid'] for j in jogadores if isinstance(j, dict) and 'uid' in j]
    snapshot = dados.get('snapshot')
    try:
        locais = identidades(uids, snapshot=snapshot) if uids else {}
    except TypeError:
        locais = identidades(uids) if uids else {}
    aceitos = []
    nao_conferem = []
    sem_captura = 0
    for j in jogadores:
        if not isinstance(j, dict) or 'uid' not in j:
            continue
        local = locais.get(j['uid'])
        if not local:
            sem_captura += 1
            aceitos.append(j['uid'])
        elif _confere(j, local):
            aceitos.append(j['uid'])
        else:
            nao_conferem.append(j.get('nome') or str(j['uid']))
    lista, _ = favoritos.criar(
        nome_lista,
        dados.get('cor'),
        aceitos,
        id_lista=id_arquivo or None,
        teto=teto,
    )
    return {
        'destino': 'favoritos',
        'id': lista['id'],
        'ja_estava': False,
        'importados': len(aceitos),
        'nao_conferem': nao_conferem,
        'sem_captura': sem_captura,
    }


def _carregar_fmf(arquivo, teto=None):
    import lista_fmf
    ja = next((x for x in lista_fmf.listar() if x.get('arquivo_biblioteca') == arquivo), None)
    if ja:
        return {
            'destino': 'lista',
            'id': ja['id'],
            'ja_estava': True,
            'importados': len(ja['uids']),
            'nao_conferem': [],
            'sem_captura': 0,
        }
    caminho = os.path.join(paths.biblioteca_dir(), arquivo)
    if not os.path.isfile(caminho):
        raise biblioteca.ArquivoInvalido('arquivo nao encontrado')
    try:
        dados, modificado = lista_fmf._ler_arquivo(caminho)
        nova = lista_fmf.adicionar(
            dados,
            origem=arquivo,
            arquivo_em=caminho,
            arquivo_biblioteca=arquivo,
            sem_substituir=True,
            teto=teto,
        )
    except lista_fmf.ListaInvalida as e:
        raise biblioteca.ArquivoInvalido(str(e))
    return {
        'destino': 'lista',
        'id': nova['id'],
        'ja_estava': False,
        'importados': len(nova['uids']),
        'nao_conferem': [],
        'sem_captura': 0,
    }
