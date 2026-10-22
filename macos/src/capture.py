"""Capturer: le o elenco do clube do usuario direto da memoria do FM26 e grava
um snapshot nomeado no SQLite local (identity + stats + profile).
Requer o FM aberto com um save carregado.
"""

import os
import sys
import time

from fm_memory import FmMemory, FmNotRunning
from fm_reader import FmReader
from capture_all import build_player_rows, _insert_sql, gravar_arquivo_partidas
import db


def scan_squad(conn, sid, reader, team, ref_date):
    """Le o elenco do `team` da memoria e grava no snapshot `sid` (players + stats + profile)."""
    p_sql, s_sql, f_sql, m_sql = _insert_sql(conn)

    roster = reader.roster(team)
    if not roster:
        return 0

    prows = []
    srows = []
    frows = []
    mrows = []

    for entrada in roster:
        obj = reader.jogador_do_elenco(entrada)
        rows = build_player_rows(reader, obj, sid, ref_date)
        if not rows:
            continue
        prow, srow, frow, mr = rows
        prows.append(prow)
        srows.append(srow)
        frows.append(frow)
        mrows.extend(mr)

    if prows:
        conn.executemany(p_sql, prows)
        conn.executemany(s_sql, srows)
        conn.executemany(f_sql, frows)
        if mrows:
            conn.executemany(m_sql, mrows)
        conn.commit()

    return len(prows)


def capture(snapshot_name):
    """Executa a captura completa do elenco do treinador humano."""
    mem = FmMemory()
    reader = FmReader(mem)

    if not reader.save_loaded():
        raise FmNotRunning("Nenhum save carregado no Football Manager.")

    mgr = reader.human_manager()
    club, team, club_full, club_short = reader.manager_club()

    if not club or not team:
        print("[erro] Nao consegui localizar o clube do treinador. Save carregado?")
        return None

    if mgr:
        print(f"Treinador : {mgr.get('full_name', 'Treinador')}")
    print(f"Clube     : {club_full} ({club_short})")

    gd = reader.game_date()
    ref_date = gd.isoformat() if gd else "2026-07-01"
    save_title = reader.save_name() or "Jogo Salvo"

    conn = db.connect()
    db.init_schema(conn)

    sid = db.create_snapshot(
        conn,
        name=snapshot_name,
        save_name=save_title,
        game_date=ref_date,
        scope="squad",
        club_uid=reader.u32(club + 0x0C) if club else None,
        manager=mgr.get("full_name") if mgr else None,
        fm_version=mem.fm_version,
    )

    n_gravados = scan_squad(conn, sid, reader, team, ref_date)
    if n_gravados == 0:
        print("[erro] Roster vazio.")
        return None

    print(f"Gravados  : {n_gravados} jogadores no snapshot #{sid}")
    print(f"Banco     : {db.db_file()}")
    return sid


if __name__ == "__main__":
    nome = sys.argv[1] if len(sys.argv) > 1 else "Meu Elenco"
    capture(nome)
