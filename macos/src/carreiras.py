"""Agrupamento de snapshots em carreiras e persistencia de preferencias por carreira.

Cada carreira reune temporadas do mesmo savegame ou clube, com nome, clube atual
e configuracoes particulares (colunas visiveis, filtros, favoritos).
"""

import sqlite3
import threading
import settings

CHAVES_PREFS = (
    "nome",
    "moeda",
    "periodo_salario",
    "colunas",
    "filtros",
    "ordenacao",
    "favoritos",
    "overall_modo",
    "buscar_como",
)
SO_TEMPORADAS = ("squad", "leagues", "full")
_PREFS_LOCK = threading.Lock()


class Carreira:
    def __init__(self, id_carreira, nome=None, clube_uid=None, savegame_id=None):
        self.id = id_carreira
        self.nome = nome or id_carreira
        self.clube_uid = clube_uid
        self.savegame_id = savegame_id
        self.snapshots = []

    def to_dict(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "clube_uid": self.clube_uid,
            "savegame_id": self.savegame_id,
            "snapshots": self.snapshots,
        }


def _prefs_vazias():
    return {k: None for k in CHAVES_PREFS}


def _guardadas(cid):
    s = settings.load()
    carreiras = s.get("carreiras") or {}
    return carreiras.get(cid) or {}


def prefs(cid=None, conn=None):
    """Retorna as preferencias guardadas para a carreira `cid` (ou a ativa)."""
    if not cid:
        cid = ativa_id(conn)
    if not cid:
        return _prefs_vazias()
    guardadas = _guardadas(cid)
    res = _prefs_vazias()
    res.update(guardadas)
    return res


def gravar_prefs(cid, **campos):
    """Grava so o que veio; o que nao veio fica como estava."""
    if not cid:
        return
    with _PREFS_LOCK:
        s = settings.load()
        carreiras = dict(s.get("carreiras") or {})
        atual = dict(carreiras.get(cid) or {})
        for k, v in campos.items():
            if k in CHAVES_PREFS:
                atual[k] = v
        carreiras[cid] = atual
        settings.save(carreiras=carreiras)


def ativa_id(conn=None):
    """Retorna o ID da carreira ativa guardada em settings ou infere do banco."""
    s = settings.load()
    ativa = s.get("carreira_ativa")
    if ativa:
        return ativa
    if conn:
        try:
            row = conn.execute(
                "SELECT carreira_id FROM snapshots WHERE carreira_id IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            pass
    return "default"


def definir_ativa(cid):
    """Define a carreira ativa nas preferencias do usuario."""
    settings.save(carreira_ativa=cid)
    return cid


def listar(conn):
    """Lista todas as carreiras existentes no banco e seus snapshots."""
    cursor = conn.execute("""
        SELECT id, name, save_name, game_date, in_game_season, scope, club_uid, manager, savegame_id, carreira_id
        FROM snapshots
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()

    mapa = {}
    for r in rows:
        cid = r[9] or f"clube:{r[6]}" if r[6] else "avulsa"
        if cid not in mapa:
            mapa[cid] = Carreira(cid, nome=r[2] or r[1], clube_uid=r[6], savegame_id=r[8])
        mapa[cid].snapshots.append({
            "id": r[0],
            "name": r[1],
            "save_name": r[2],
            "game_date": r[3],
            "in_game_season": r[4],
            "scope": r[5],
            "club_uid": r[6],
            "manager": r[7],
            "savegame_id": r[8],
            "carreira_id": cid,
        })

    return [c.to_dict() for c in mapa.values()]


def adotar_legado(conn, savegame_id=None, club_uid=None):
    """Temporada ANTIGA do mesmo clube do save aberto passa a pertencer a ele."""
    if not club_uid or not savegame_id:
        return 0

    novo = f"sg:{savegame_id}"
    antigo = f"clube:{club_uid}"

    cursor = conn.execute(
        "UPDATE snapshots SET carreira_id=? WHERE (carreira_id=? OR carreira_id IS NULL) AND club_uid=? AND savegame_id IS NULL",
        (novo, antigo, club_uid),
    )
    afetados = cursor.rowcount
    conn.commit()

    if afetados > 0:
        s = settings.load()
        carreiras = s.get("carreiras") or {}
        if antigo in carreiras and novo not in carreiras:
            carreiras[novo] = carreiras.pop(antigo)
            settings.save(carreiras=carreiras)

    return afetados


def mover_temporada(conn, snapshot_id, carreira_destino):
    """Move um snapshot especifico para outra carreira."""
    cursor = conn.execute(
        "UPDATE snapshots SET carreira_id=? WHERE id=?",
        (carreira_destino, snapshot_id),
    )
    conn.commit()
    return cursor.rowcount > 0
