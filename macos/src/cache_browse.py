"""Cache persistente em disco para browse de jogadores e dados calculados.

Guarda matrizes NumPy binarias (.npy), JSONs e arrays u8 para carregamento ultra-rapido
na interface sem sobrecarregar o banco SQLite em tempo de execucao.
"""

import json
import os
import shutil
import numpy as np
import paths


def _raiz():
    p = paths.local_data_path("cache_browse")
    os.makedirs(p, exist_ok=True)
    return p


def pasta(snapshot_id):
    """Caminho da subpasta de cache para um snapshot especifico."""
    p = os.path.join(_raiz(), str(snapshot_id))
    os.makedirs(p, exist_ok=True)
    return p


def esta_pronto(snapshot_id):
    """Verifica se os arquivos essenciais de cache ja foram gerados para o snapshot."""
    p = pasta(snapshot_id)
    return os.path.isfile(os.path.join(p, "browse.json")) or os.path.isfile(
        os.path.join(p, "matrix.npy")
    )


def _le_texto(caminho):
    if os.path.isfile(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _grava_texto(caminho, texto):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)


_salva_texto = _grava_texto


def _salva_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)


def _salva_npy(caminho, arr):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    np.save(caminho, arr)


def _cabe_em_float32(arr):
    return np.ascontiguousarray(arr, dtype=np.float32)


def _matriz(dados):
    if isinstance(dados, np.ndarray):
        return dados
    return np.array(dados)


def _u8_caminhos(snapshot_id):
    p = pasta(snapshot_id)
    return os.path.join(p, "u8_matrix.npy"), os.path.join(p, "u8_keys.json")


def ler_u8(snapshot_id):
    p_npy, p_keys = _u8_caminhos(snapshot_id)
    if os.path.isfile(p_npy) and os.path.isfile(p_keys):
        try:
            arr = np.load(p_npy)
            with open(p_keys, "r", encoding="utf-8") as f:
                keys = json.load(f)
            return arr, keys
        except Exception:
            pass
    return None, None


def gravar_u8(snapshot_id, arr, keys):
    p_npy, p_keys = _u8_caminhos(snapshot_id)
    _salva_npy(p_npy, np.ascontiguousarray(arr, dtype=np.uint8))
    _salva_json(p_keys, keys)


def ler(snapshot_id):
    """Le dados de browse em cache."""
    p = pasta(snapshot_id)
    p_json = os.path.join(p, "browse.json")
    if os.path.isfile(p_json):
        try:
            with open(p_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def gravar(snapshot_id, dados):
    """Grava dados de browse no cache."""
    p = pasta(snapshot_id)
    p_json = os.path.join(p, "browse.json")
    _salva_json(p_json, dados)


def ler_overall(snapshot_id):
    """Le avaliacoes overall cacheadas para o snapshot."""
    p = pasta(snapshot_id)
    p_ov = os.path.join(p, "overall.json")
    if os.path.isfile(p_ov):
        try:
            with open(p_ov, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def gravar_overall(snapshot_id, dados):
    """Grava avaliacoes overall cacheadas para o snapshot."""
    p = pasta(snapshot_id)
    p_ov = os.path.join(p, "overall.json")
    _salva_json(p_ov, dados)


def apagar(snapshot_id):
    """Exclui toda a pasta de cache do snapshot."""
    p = os.path.join(_raiz(), str(snapshot_id))
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
        return True
    return False


def podar_orfaos(snapshots_validos):
    """Remove pastas de cache de snapshots que ja foram apagados do banco de dados."""
    validos = {str(s) for s in snapshots_validos}
    raiz = _raiz()
    if not os.path.isdir(raiz):
        return
    for item in os.listdir(raiz):
        caminho = os.path.join(raiz, item)
        if os.path.isdir(caminho) and item not in validos:
            shutil.rmtree(caminho, ignore_errors=True)
