"""Leitor do arquivo de partidas e telemetria bruta (.obs) do Football Manager.

O Football Manager grava logs comprimidos com Zstandard em uma pasta temporaria
contendo notas de avaliacao e estatisticas de cada partida para todos os jogadores do save.
Suporta caminhos do macOS (~/Library/Application Support/Sports Interactive/Football Manager 26/Temporary)
e do Windows (%LOCALAPPDATA%\\Sports Interactive\\Football Manager 2026\\Temporary).
"""

import os
import struct
import sys
import zstandard as zstd

FM24 = "24"
FM26 = "26"

BLOCO = 214
NOTA_OFF = 135
ID_INTERNO_OFF = 0
ENTROU_OFF = 12
NOTA_MINIMA_PARTICIPACAO_CURTA = 6.0
MAX_ITENS_VETOR = 100000
MIN_BLOCOS_LADO = 11
DURACAO = 90
PREFIXO = "pks_"

COLUNAS_JOGADOR = (
    "id_interno",
    "minutos",
    "rating",
    "gols",
    "assistencias",
    "xg",
    "xa",
)
COLUNAS_TIME = (
    "team_uid",
    "gols",
    "xg",
    "chutes",
)


class Formato:
    def __init__(self, versao, tam_bloco=214, nota_off=135, id_off=0):
        self.versao = versao
        self.tam_bloco = tam_bloco
        self.nota_off = nota_off
        self.id_off = id_off


FORMATO_FM26 = Formato(FM26, tam_bloco=214, nota_off=135, id_off=0)
FORMATO_FM24 = Formato(FM24, tam_bloco=196, nota_off=120, id_off=0)
FORMATOS = {FM26: FORMATO_FM26, FM24: FORMATO_FM24}


def formato(versao_fm):
    v = str(versao_fm or "26").strip()
    return FORMATOS.get(v, FORMATO_FM26)


def versao_tem_arquivo(versao_fm):
    return str(versao_fm) in FORMATOS


def pasta_temporaria():
    """Diretorio onde os arquivos .obs temporarios do FM residem."""
    forcada = os.environ.get("FMSH_PASTA_TEMP_FM")
    if forcada and os.path.isdir(forcada):
        return forcada

    if sys.platform == "darwin":
        candidatos = [
            os.path.expanduser("~/Library/Application Support/Sports Interactive/Football Manager 26/Temporary"),
            os.path.expanduser("~/Library/Application Support/Sports Interactive/Football Manager 2026/Temporary"),
            os.path.expanduser("~/Library/Caches/Sports Interactive/Football Manager 26"),
        ]
        for c in candidatos:
            if os.path.isdir(c):
                return c
        return candidatos[0]

    local_app = os.environ.get("LOCALAPPDATA", "")
    for sub in ("Football Manager 2026", "Football Manager 26"):
        cand = os.path.join(local_app, "Sports Interactive", sub, "Temporary")
        if os.path.isdir(cand):
            return cand

    return os.path.join(local_app, "Sports Interactive", "Football Manager 2026", "Temporary")


def _arquivos(pasta=None):
    """Localiza todos os arquivos de match dump .obs na pasta temporaria."""
    if not pasta:
        pasta = pasta_temporaria()
    if not os.path.isdir(pasta):
        return []
    res = []
    for item in os.listdir(pasta):
        if item.endswith(".obs"):
            c = os.path.join(pasta, item)
            if os.path.isfile(c) and os.path.getsize(c) > 8:
                res.append(c)
    return res


def id_interno(bloco_or_reader, obj=None):
    """Extrai o Person Internal ID (uint32). Suporta buffer de bytes ou (reader, obj)."""
    if obj is not None:
        base = getattr(bloco_or_reader, "_person_base", 0x288)
        try:
            return bloco_or_reader.u32(obj + base + 8)
        except Exception:
            return 0
    if isinstance(bloco_or_reader, (bytes, bytearray)):
        if len(bloco_or_reader) >= 4:
            return struct.unpack_from("<I", bloco_or_reader, ID_INTERNO_OFF)[0]
    return 0


def nota(bloco_bytes):
    """Extrai a avaliacao da partida (float escala 1-10)."""
    if len(bloco_bytes) >= NOTA_OFF + 2:
        val = struct.unpack_from("<H", bloco_bytes, NOTA_OFF)[0]
        return round(val / 100.0, 2)
    return 0.0


def _minutos_em_campo(bloco_bytes):
    if len(bloco_bytes) > ENTROU_OFF:
        entrou = bloco_bytes[ENTROU_OFF]
        if entrou > 0:
            return 90
    return 0


def _lados(blocos):
    """Divide a lista de blocos da partida em mandante (home) e visitante (away)."""
    metade = len(blocos) // 2
    return blocos[:metade], blocos[metade:]


def contadores_dos_blocos(blocos, fmt=FORMATO_FM26):
    res = []
    for b in blocos:
        if len(b) >= fmt.tam_bloco:
            pid = id_interno(b)
            r = nota(b)
            mins = _minutos_em_campo(b)
            if pid > 0:
                res.append({
                    "id_interno": pid,
                    "rating": r,
                    "minutes": mins,
                })
    return res


def _calendario(blocos):
    return {}


def _float32(val):
    try:
        return float(val)
    except Exception:
        return 0.0


def ler(caminho):
    """Decomprime e analisa um arquivo .obs do Football Manager."""
    if not os.path.isfile(caminho):
        return []

    try:
        with open(caminho, "rb") as f:
            header = f.read(8)
            comprimido = f.read()

        dctx = zstd.ZstdDecompressor()
        descomprimido = dctx.decompress(comprimido, max_output_size=50000000)

        fmt = FORMATO_FM26
        tam = fmt.tam_bloco
        blocos = [
            descomprimido[i : i + tam]
            for i in range(0, len(descomprimido) - tam + 1, tam)
        ]
        return contadores_dos_blocos(blocos, fmt)
    except Exception:
        return []


def ler_tudo(pasta=None):
    """Le todos os arquivos .obs e devolve mapa agregado {id_interno: [partidas]}."""
    arqs = _arquivos(pasta)
    mapa = {}
    for a in arqs:
        partidas = ler(a)
        for p in partidas:
            pid = p["id_interno"]
            if pid not in mapa:
                mapa[pid] = []
            mapa[pid].append(p)
    return mapa
