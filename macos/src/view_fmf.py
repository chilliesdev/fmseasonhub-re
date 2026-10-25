# Decompiled from view_fmf.pyc (Python 3.14) with macOS adaptations
import glob
import json
import os
import struct

import lista_fmf
from lista_fmf import ArquivoCorrompido, ListaInvalida, NaoEhFmf

MARCA_VIEW = b'\x03\x01eiv.'
CABECALHO_VIEW = len(MARCA_VIEW) + 2 + 4
MAXIMO_COLUNAS = 400

TELAS = {
    'PlayerSearchResultsViewCollection': 'busca',
    'PlayerSearchShortlistViewCollection': 'lista',
    'FirstTeamSquadAndYouthTeamSquadCollection': 'plantel',
}

TIPOS_POR_MEMBRO = {
    '.slf': 'lista',
    '.view': 'view',
    '.pft': 'filtro',
    '.ssf': 'staff',
}


class NaoEhView(ListaInvalida):
    pass


class ViewDeTatica(ListaInvalida):
    pass


class ViewDeLista(ListaInvalida):
    pass


class ViewDeOutraTela(ListaInvalida):
    pass


def _conferir_tamanho(dados):
    if len(dados) > lista_fmf.TAMANHO_MAXIMO_ARQUIVO:
        raise ArquivoCorrompido('O arquivo e grande demais para ser uma view (limite de 2 MB).')


def tipo_do_fmf(dados: bytes) -> str | None:
    try:
        _conferir_tamanho(dados)
        extensoes = {m[1] for m in lista_fmf._ler_indice(dados)}
        return next((tipo for ext, tipo in TIPOS_POR_MEMBRO.items() if ext in extensoes), None)
    except ListaInvalida:
        return None


def ler(dados: bytes) -> dict:
    _conferir_tamanho(dados)
    membros = lista_fmf._ler_indice(dados)
    views = [m for m in membros if m[1] == '.view']
    if not views:
        raise NaoEhView('Este arquivo .fmf nao e uma view do FM.')
    _, _, deslocamento, tamanho_arquivo, tamanho_aberto = views[0]
    aberto, _ = lista_fmf._abrir_membro(dados, deslocamento, tamanho_arquivo, tamanho_aberto)
    if not aberto.startswith(MARCA_VIEW) or len(aberto) < CABECALHO_VIEW:
        raise ArquivoCorrompido('O conteudo da view nao foi reconhecido.')
    tamanho = struct.unpack_from('<I', aberto, CABECALHO_VIEW - 4)[0]
    if tamanho > len(aberto) - CABECALHO_VIEW:
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
    try:
        externo = json.loads(aberto[CABECALHO_VIEW:CABECALHO_VIEW + tamanho].decode('utf-8'))
        if not isinstance(externo, dict) or not isinstance(externo.get('ViewData'), str):
            raise ValueError('Invalid view record')
        dados_view = json.loads(externo['ViewData'])
        tabela = dados_view['m_tableConfig']
        if not isinstance(tabela, list) or not 0 < len(tabela) <= MAXIMO_COLUNAS:
            raise ValueError('Invalid view columns')
        colunas = []
        for coluna in tabela:
            if not isinstance(coluna, dict):
                raise ValueError('Invalid view column')
            identificador = coluna['m_columnID']
            if not isinstance(identificador, str) or not identificador.strip():
                raise ValueError('Invalid view column ID')
            colunas.append(identificador)
    except (ValueError, KeyError, TypeError, RecursionError) as erro:
        raise ArquivoCorrompido('O conteudo da view nao foi reconhecido.') from erro
    colecao = str(externo.get('ViewSettingsCollectionName') or '')
    if 'TacticTeamSelection' in colecao:
        raise ViewDeTatica('Esta view e da tela de tatica do FM, que nao existe no app.')
    if colecao not in TELAS:
        raise ViewDeOutraTela('Esta view e de uma tela do FM que nao existe no app.')
    return {
        'nome_interno': str(externo.get('SerialisedName') or ''),
        'tela': TELAS[colecao],
        'colunas': colunas,
    }


IDENTIDADE_BASE = (
    'pos',
    'nat',
    'club',
    'league',
    'contract',
    'foot',
    '_age',
    '_height',
    '_ca',
    '_pa',
    '_value',
    '_asking',
    '_wage',
    '_rating',
    'birth',
    '_lfoot',
    '_rfoot',
    '_uid',
)

TELA_DO_DESTINO = {'base': 'busca', 'meutime': 'plantel'}


def destino_da_tela(tela: str) -> str:
    if tela == 'lista':
        raise ViewDeLista('Views da lista preferencial do FM nao entram no app.')
    if tela == 'plantel':
        return 'meutime'
    return 'base'


def revisar(dados: bytes, nome_arquivo: str, destino: str = 'base') -> dict:
    import moneyball as mb
    import moneyball_data
    from view_fmf_colunas import EQUIVALENCIA, EQUIVALENCIA_MEUTIME

    if destino not in TELA_DO_DESTINO:
        raise ListaInvalida('Destino desconhecido.')
    lida = ler(dados)
    if destino_da_tela(lida['tela']) != destino:
        if destino == 'base':
            raise ViewDeOutraTela('Esta view e de plantel no FM: importe no Meu time.')
        else:
            raise ViewDeOutraTela('Esta view e da busca de jogadores no FM: importe na Base.')
    meutime = (destino == 'meutime')
    tabela = EQUIVALENCIA_MEUTIME if meutime else EQUIVALENCIA
    gerais = mb.general_columns_meta()
    proprias = set() if meutime else {c['key'] for c in gerais}
    catalogo = {**mb.CATALOG_BY_KEY, **{
        c['key']: c for c in moneyball_data.search_alias_columns() + gerais
    }}
    colunas = []
    contagem = {}
    usadas = set()
    for id_fm in lida['colunas']:
        regra = tabela.get(id_fm)
        estado = regra[0] if regra else 'desconhecida'
        chave = regra[1] if regra and estado in ('ok', 'nova', 'aprox') else None
        if not meutime and chave and chave != 'name' and chave not in IDENTIDADE_BASE and chave not in catalogo:
            estado, chave, motivo = 'sem', None, 'nao_le'
        elif regra and estado == 'aprox':
            motivo = regra[2]
        elif regra and estado in ('sem', 'fm'):
            motivo = regra[1]
        else:
            motivo = None
        if estado == 'atrib':
            motivo = regra[1]
        extra = bool(not meutime and bool(chave) and chave != 'name' and chave not in proprias and chave not in IDENTIDADE_BASE)
        if regra and estado == 'base':
            da_base = regra[1]
        else:
            da_base = None if meutime else chave
        coluna = catalogo.get(da_base)
        colunas.append({
            'id_fm': id_fm,
            'estado': estado,
            'chave': chave,
            'motivo': motivo,
            'extra': extra,
            'coluna': coluna,
        })
        contagem[estado] = contagem.get(estado, 0) + 1
        if chave:
            usadas.add(chave)
    if meutime:
        escondidas = []
    else:
        escondidas = [k for k in list(IDENTIDADE_BASE) + sorted(proprias) if k not in usadas]
    nome = nome_arquivo[:-4] if nome_arquivo.lower().endswith('.fmf') else nome_arquivo
    return {
        'nome': nome,
        'tela': lida['tela'],
        'destino': destino,
        'colunas': colunas,
        'escondidas': escondidas,
        'contagem': contagem,
    }


def pastas_views() -> list[dict]:
    saida = []
    for p in lista_fmf.pastas_dos_jogos():
        pasta = os.path.join(p['pasta'], 'views')
        if os.path.isdir(pasta):
            saida.append({**p, 'pasta': pasta})
    return saida


def _ler_caminho(caminho: str) -> bytes:
    if not caminho or '\0' in caminho:
        raise ListaInvalida('Nome de arquivo invalido.')
    if os.path.splitext(caminho)[1].lower() != '.fmf':
        raise NaoEhFmf('Este arquivo nao e um .fmf do Football Manager.')
    try:
        if not os.path.isfile(caminho):
            raise ListaInvalida('Nao foi possivel ler o arquivo. Ele ainda existe nesse lugar?')
        if os.path.getsize(caminho) > lista_fmf.TAMANHO_MAXIMO_ARQUIVO:
            raise ArquivoCorrompido('O arquivo e grande demais para ser uma view (limite de 2 MB).')
        with open(caminho, 'rb') as fh:
            return fh.read(lista_fmf.TAMANHO_MAXIMO_ARQUIVO + 1)
    except OSError:
        raise ListaInvalida('Nao foi possivel ler o arquivo. Ele ainda existe nesse lugar?')


def listar_pasta() -> dict:
    pastas = []
    for p in pastas_views():
        views = []
        for caminho in sorted(glob.glob(os.path.join(p['pasta'], '*')), key=lambda c: os.path.basename(c).lower()):
            if os.path.splitext(caminho)[1].lower() != '.fmf':
                continue
            arquivo = os.path.basename(caminho)
            try:
                tela = ler(_ler_caminho(caminho))['tela']
            except ViewDeTatica:
                tela = 'tatica'
            except ListaInvalida:
                continue
            views.append({
                'arquivo': arquivo,
                'nome': arquivo[:-4],
                'tela': tela,
            })
        pastas.append({**p, 'views': views})
    return {'pastas': pastas}


def ler_da_pasta(arquivo: str, jogo: str | None = None, destino: str = 'base') -> dict:
    if not arquivo or os.path.basename(arquivo) != arquivo or arquivo in ('.', '..') or '\\' in arquivo or '\0' in arquivo:
        raise ListaInvalida('Nome de arquivo invalido.')
    pasta = next((p['pasta'] for p in pastas_views() if jogo is None or p['jogo'] == str(jogo)), None)
    if not pasta:
        raise ListaInvalida('A pasta de views do Football Manager nao foi encontrada neste computador.')
    return revisar(_ler_caminho(os.path.join(pasta, arquivo)), arquivo, destino)


def ler_do_caminho(caminho: str, destino: str = 'base') -> dict:
    return revisar(_ler_caminho(caminho), os.path.basename(caminho), destino)
