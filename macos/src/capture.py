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


def resolve_manager_team(reader):
    """Obtem o ponteiro do time do treinador humano / elenco atual."""
    if hasattr(reader, "manager_team") and callable(reader.manager_team):
        team = reader.manager_team()
        if team:
            return team
    if hasattr(reader, "manager_club") and callable(reader.manager_club):
        res = reader.manager_club()
        if res and len(res) >= 2 and res[1]:
            return res[1]
    if hasattr(reader, "all_teams_with_players") and callable(reader.all_teams_with_players):
        teams = reader.all_teams_with_players()
        if teams:
            return teams[0]
    return None


def scan_squad(conn, sid, reader, team, ref_date, progress=None):
    """Le o elenco do `team` da memoria e grava no snapshot `sid` (players + stats + profile)."""
    p_sql, s_sql, f_sql, m_sql = _insert_sql(conn)

    club_uid = None
    try:
        row = conn.execute("SELECT club_uid FROM snapshots WHERE id=?", (sid,)).fetchone()
        if row and row[0]:
            club_uid = row[0]
    except Exception:
        pass

    club_ptr = None
    if hasattr(reader, "manager_club"):
        try:
            m_res = reader.manager_club()
            if m_res and len(m_res) >= 1:
                club_ptr = m_res[0]
        except Exception:
            pass
    if not club_uid and club_ptr and hasattr(reader, "u32"):
        try:
            club_uid = reader.u32(club_ptr + 0x0C)
        except Exception:
            pass

    roster = reader.roster(team)
    if not roster:
        return 0

    prows = []
    srows = []
    frows = []
    mrows = []
    ptrows = []
    total_jogadores = 0

    team_uid = None
    if hasattr(reader, "u32"):
        try:
            team_uid = reader.u32(team + 0x0C)
        except Exception:
            pass

    total_roster = len(roster)
    for idx, entrada in enumerate(roster):
        obj = reader.jogador_do_elenco(entrada)
        rows = build_player_rows(reader, obj, sid, ref_date)
        if rows:
            prow, srow, frow, mr = rows
            prows.append(prow)
            srows.append(srow)
            frows.append(frow)
            mrows.extend(mr)
            uid = prow[1]
            p_tuid = team_uid or prow[13] or uid
            ptrows.append((sid, uid, p_tuid))
            if not club_uid and prow[12]:
                club_uid = prow[12]
            total_jogadores += 1

            if len(prows) >= 2000:
                conn.executemany(p_sql, prows)
                conn.executemany(s_sql, srows)
                conn.executemany(f_sql, frows)
                if mrows:
                    conn.executemany(m_sql, mrows)
                if ptrows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO player_teams (snapshot_id, player_uid, team_uid) VALUES (?, ?, ?)",
                        ptrows,
                    )
                conn.commit()
                prows.clear()
                srows.clear()
                frows.clear()
                mrows.clear()
                ptrows.clear()

        if progress:
            progress(idx + 1, total_roster, "lendo_elenco")

    if prows:
        conn.executemany(p_sql, prows)
        conn.executemany(s_sql, srows)
        conn.executemany(f_sql, frows)
        if mrows:
            conn.executemany(m_sql, mrows)
        if ptrows:
            conn.executemany(
                "INSERT OR REPLACE INTO player_teams (snapshot_id, player_uid, team_uid) VALUES (?, ?, ?)",
                ptrows,
            )
        conn.commit()

    # Save team metadata
    t_data = None
    if hasattr(reader, "team_details"):
        try:
            t_data = reader.team_details(team, club_uid=club_uid)
        except Exception:
            pass
    if not t_data and (team_uid or ptrows or total_jogadores):
        eff_team_uid = team_uid
        if not eff_team_uid and ptrows:
            eff_team_uid = ptrows[0][2]
        if not eff_team_uid:
            row = conn.execute(
                "SELECT team_uid FROM players WHERE snapshot_id=? AND team_uid IS NOT NULL LIMIT 1",
                (sid,),
            ).fetchone()
            eff_team_uid = row[0] if row else 1
        t_data = {
            "team_uid": eff_team_uid,
            "club_uid": club_uid,
            "team_type": 0,
            "label": "First Team",
            "n_players": total_jogadores,
        }
    if t_data:
        db.save_team(conn, sid, t_data)

    # Resolve club_ptr if not provided
    if not club_ptr and hasattr(reader, "manager_club"):
        try:
            m_res = reader.manager_club()
            if m_res and len(m_res) >= 1:
                club_ptr = m_res[0]
        except Exception:
            pass

    # Save additional teams of the managed club if present
    if club_ptr and hasattr(reader, "club_teams"):
        try:
            c_teams = reader.club_teams(club_ptr)
            for ct in c_teams:
                if ct != team and hasattr(reader, "team_details"):
                    ctd = reader.team_details(ct, club_uid=club_uid)
                    if ctd:
                        db.save_team(conn, sid, ctd)
        except Exception:
            pass

    # Save club profile
    if club_ptr and hasattr(reader, "club_profile"):
        try:
            cprof = reader.club_profile(club_ptr)
            if cprof:
                if not cprof.get("club_uid") and club_uid:
                    cprof["club_uid"] = club_uid
                db.save_club(conn, sid, cprof)
        except Exception:
            pass

    if club_uid:
        conn.execute("UPDATE snapshots SET club_uid=? WHERE id=? AND club_uid IS NULL", (club_uid, sid))
        conn.commit()

    return total_jogadores


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

    c_uid = reader.u32(club + 0x0C) if club and hasattr(reader, "u32") else None
    sid = db.create_snapshot(
        conn,
        name=snapshot_name,
        save_name=save_title,
        game_date=ref_date,
        scope="squad",
        club_uid=c_uid,
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
