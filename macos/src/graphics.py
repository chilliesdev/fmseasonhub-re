"""Indexacao e resolucao de graficos customizados do Football Manager.

Indexa escudos de clubes, logos de competicoes, bandeiras de paises e retratos de jogadores
a partir dos arquivos config.xml contidos na pasta de graficos do FM.
Suporta caminhos do macOS (~/Library/Application Support/Sports Interactive/Football Manager 26/graphics)
e do Windows (Documents/Sports Interactive/Football Manager 2026/graphics).
"""

import os
import re
import sys
import threading
import time
import paths
import settings

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")

PORTRAIT_RX = re.compile(r'from="([^"]+)"\s+to="graphics/pictures/person/(\d+)/portrait"', re.IGNORECASE)
LOGO_RX = re.compile(r'from="([^"]+)"\s+to="graphics/pictures/club/(\d+)/logo"', re.IGNORECASE)
FLAG_RX = re.compile(r'from="([^"]+)"\s+to="graphics/pictures/nation/(\d+)/flag"', re.IGNORECASE)
COMP_LOGO_RX = re.compile(r'from="([^"]+)"\s+to="graphics/pictures/comp/(\d+)/logo"', re.IGNORECASE)

_INDEX = {}
_LOGOS = {}
_COMPS = {}
_FLAGS = {}
_PORTRAITS = {}
_STATE = {
    "pronto": False,
    "indexando": False,
    "contagem": 0,
    "pasta": None,
    "erro": None,
    "indexed_at": None,
}
_TRAVA = threading.Lock()


def default_graphics_dir():
    """Diretorio padrao onde os facepacks e logos do FM ficam instalados."""
    if sys.platform == "darwin":
        candidatos = [
            os.path.expanduser("~/Library/Application Support/Sports Interactive/Football Manager 26/graphics"),
            os.path.expanduser("~/Library/Application Support/Sports Interactive/Football Manager 2026/graphics"),
            os.path.expanduser("~/Documents/Sports Interactive/Football Manager 26/graphics"),
            os.path.expanduser("~/Documents/Sports Interactive/Football Manager 2026/graphics"),
        ]
        for c in candidatos:
            if os.path.isdir(c):
                return c
        return candidatos[0]

    docs = paths.documents_dir()
    for sub in ("Football Manager 26", "Football Manager 2026"):
        cand = os.path.join(docs, "Sports Interactive", sub, "graphics")
        if os.path.isdir(cand):
            return cand

    return os.path.join(docs, "Sports Interactive", "Football Manager 2026", "graphics")


def ready():
    return bool(_STATE.get("pronto"))


def state():
    with _TRAVA:
        return dict(_STATE, dir=_STATE["pasta"], count=len(_PORTRAITS),
                    logos=len(_LOGOS), flags=len(_FLAGS), error=_STATE["erro"])


def _dentro(caminho, pasta_base):
    try:
        r_caminho = os.path.realpath(caminho)
        r_base = os.path.realpath(pasta_base)
        return r_caminho.startswith(r_base)
    except Exception:
        return False


def _resolve(uid, cache_map):
    if not uid:
        return None
    s_uid = str(uid).strip()
    return cache_map.get(s_uid)


def index_graphics(pasta=None, forcar=False):
    """Varre os config.xml UMA vez e monta o mapa de graficos em memoria."""
    global _LOGOS, _COMPS, _FLAGS, _PORTRAITS

    with _TRAVA:
        if _STATE.get("indexando"):
            return _STATE
        if _STATE.get("pronto") and not forcar:
            return _STATE
        _STATE["indexando"] = True
        _STATE["erro"] = None

    if not pasta:
        s = settings.load()
        pasta = s.get("graphics_dir") or default_graphics_dir()

    if not pasta or not os.path.isdir(pasta):
        with _TRAVA:
            _LOGOS, _COMPS, _FLAGS, _PORTRAITS = {}, {}, {}, {}
            _STATE["indexando"] = False
            _STATE["pronto"] = True
            _STATE["pasta"] = pasta
            _STATE["contagem"] = 0
            _STATE["erro"] = "pasta nao encontrada"
            _STATE["indexed_at"] = None
        return _STATE

    novos_logos = {}
    novos_comps = {}
    novas_flags = {}
    novos_portraits = {}
    total = 0

    try:
        for raiz, _, arquivos in os.walk(pasta):
            for arq in arquivos:
                if arq.lower() == "config.xml":
                    caminho_xml = os.path.join(raiz, arq)
                    try:
                        with open(caminho_xml, "r", encoding="utf-8", errors="ignore") as f:
                            conteudo = f.read()

                        # Portait
                        for ref_nome, ref_uid in PORTRAIT_RX.findall(conteudo):
                            img = os.path.join(raiz, f"{ref_nome}.png")
                            if os.path.isfile(img):
                                novos_portraits[ref_uid] = img
                                total += 1

                        # Club logo
                        for ref_nome, ref_uid in LOGO_RX.findall(conteudo):
                            img = os.path.join(raiz, f"{ref_nome}.png")
                            if os.path.isfile(img):
                                novos_logos[ref_uid] = img
                                total += 1

                        # Comp logo
                        for ref_nome, ref_uid in COMP_LOGO_RX.findall(conteudo):
                            img = os.path.join(raiz, f"{ref_nome}.png")
                            if os.path.isfile(img):
                                novos_comps[ref_uid] = img
                                total += 1

                        # Nation flag
                        for ref_nome, ref_uid in FLAG_RX.findall(conteudo):
                            img = os.path.join(raiz, f"{ref_nome}.png")
                            if os.path.isfile(img):
                                novas_flags[ref_uid] = img
                                total += 1

                    except Exception:
                        pass
    except Exception as e:
        with _TRAVA:
            _STATE["indexando"] = False
            _STATE["erro"] = str(e)
            return _STATE

    with _TRAVA:
        _LOGOS = novos_logos
        _COMPS = novos_comps
        _FLAGS = novas_flags
        _PORTRAITS = novos_portraits
        _STATE["pronto"] = True
        _STATE["indexando"] = False
        _STATE["pasta"] = pasta
        _STATE["contagem"] = total
        _STATE["indexed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    return _STATE


def reindex(pasta=None):
    return index_graphics(pasta, forcar=True)


def club_logo_file(uid):
    if not _STATE["pronto"]:
        index_graphics()
    return _resolve(uid, _LOGOS)


def comp_logo_file(uid):
    if not _STATE["pronto"]:
        index_graphics()
    return _resolve(uid, _COMPS)


def nation_flag_file(uid):
    if not _STATE["pronto"]:
        index_graphics()
    return _resolve(uid, _FLAGS)


def portrait_file(uid):
    if not _STATE["pronto"]:
        index_graphics()
    return _resolve(uid, _PORTRAITS)
