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
        dados_view = json.loads(externo['ViewData'])
        colunas = [str(c['m_columnID']) for c in dados_view['m_tableConfig']]
    except (ValueError, KeyError, TypeError, RecursionError) as erro:
        raise ArquivoCorrompido('O conteudo da view nao foi reconhecido.') from erro
    colecao = str(externo.get('ViewSettingsCollectionName') or '')
    if 'TacticTeamSelection' in colecao:
        raise ViewDeTatica('Esta view e da tela de tatica do FM, que nao existe no app.')
    if len(colunas) > MAXIMO_COLUNAS:
        raise ArquivoCorrompido('A view tem colunas demais.')
    return {
        'nome_interno': str(externo.get('SerialisedName') or ''),
        'tela': TELAS.get(colecao, 'busca'),
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
    if meutime:
        proprias = set()
    else:
        proprias = {c['key'] for c in mb.group_columns_meta('all')}
    colunas = []
    contagem = {}
    usadas = set()
    for id_fm in lida['colunas']:
        regra = tabela.get(id_fm)
        estado = regra[0] if regra else 'desconhecida'
        chave = regra[1] if regra and estado in ('ok', 'nova', 'aprox') else None
        if regra and estado == 'aprox':
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
        coluna = mb.columns_meta([da_base])[0] if da_base in mb.CATALOG_BY_KEY else None
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
        pasta = os.path.join(os.path.dirname(p['pasta']), 'views')
        if os.path.isdir(pasta):
            saida.append({**p, 'pasta': pasta})
    return saida


def _ler_caminho(caminho: str) -> bytes:
    if os.path.splitext(caminho)[1].lower() != '.fmf':
        raise NaoEhFmf('Este arquivo nao e um .fmf do Football Manager.')
    try:
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
        for caminho in sorted(glob.glob(os.path.join(p['pasta'], '*.fmf')), key=lambda c: os.path.basename(c).lower()):
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
    if not arquivo or os.path.basename(arquivo) != arquivo or arquivo in ('.', '..') or '\\' in arquivo:
        raise ListaInvalida('Nome de arquivo invalido.')
    pasta = next((p['pasta'] for p in pastas_views() if jogo is None or p['jogo'] == str(jogo)), None)
    if not pasta:
        raise ListaInvalida('A pasta de views do Football Manager nao foi encontrada neste computador.')
    return revisar(_ler_caminho(os.path.join(pasta, arquivo)), arquivo, destino)


def ler_do_caminho(caminho: str, destino: str = 'base') -> dict:
    return revisar(_ler_caminho(caminho), os.path.basename(caminho), destino)
