"""Modulo de captura completa da base de dados do Football Manager.

Varre todos os jogadores ativos no save, desempacota atributos, historico e estatisticas,
e persiste os registros estruturados no SQLite local.
"""

import os
import sys
import time
import struct
import unicodedata
from datetime import date

from fm_memory import FmMemory, FmNotRunning, _log
from fm_reader import FmReader, decode_fm_date, BASIC_KEYS, ADV_KEYS, PROFILE_KEYS
import db


_POS_MAP = {
    "pos_gk": "GK",
    "pos_sw": "SW",
    "pos_dl": "DL",
    "pos_dc": "DC",
    "pos_dr": "DR",
    "pos_dm": "DM",
    "pos_ml": "ML",
    "pos_mc": "MC",
    "pos_mr": "MR",
    "pos_aml": "AML",
    "pos_amc": "AMC",
    "pos_amr": "AMR",
    "pos_st": "ST",
    "pos_wbl": "WBL",
    "pos_wbr": "WBR",
}


def _person_base():
    return 0x288


def _vt_player():
    return 0x5492830


def _vt_player_staff():
    return 0x5498AA0


def _staff_athlete_bias():
    return -0xF8


def primary_position(prof):
    """Posicao principal = a de maior familiaridade (>=10)."""
    melhor_pos = "ST"
    melhor_val = 0
    for pos_key, rotulo in _POS_MAP.items():
        val = prof.get(pos_key, 0)
        if val is not None and val > melhor_val:
            melhor_val = val
            melhor_pos = rotulo
    return melhor_pos


def _insert_sql(conn):
    """Prepara as queries SQL de insercao em lote."""
    p_cols = (
        "snapshot_id, uid, name_first, name_last, common_name, "
        "full_name, legal_name, search_norm, display_norm, ca, pa, "
        "height_cm, club_id, team_uid, position"
    )
    p_ph = ",".join(["?"] * len(p_cols.split(",")))
    p_sql = f"INSERT OR REPLACE INTO players ({p_cols}) VALUES ({p_ph})"

    s_cols = ["snapshot_id", "uid"] + list(BASIC_KEYS) + list(ADV_KEYS)
    s_ph = ",".join(["?"] * len(s_cols))
    s_sql = f"INSERT OR REPLACE INTO player_stats ({','.join(s_cols)}) VALUES ({s_ph})"

    f_cols = ["snapshot_id", "uid"] + list(PROFILE_KEYS)
    f_ph = ",".join(["?"] * len(f_cols))
    f_sql = f"INSERT OR REPLACE INTO player_profile ({','.join(f_cols)}) VALUES ({f_ph})"

    m_sql = (
        "INSERT OR REPLACE INTO player_form "
        "(snapshot_id, uid, match_date, comp_uid, comp_name, team_uid, rating) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )

    return p_sql, s_sql, f_sql, m_sql


def build_player_rows(reader, obj, sid, ref_date, abias=0, buf=None):
    """Constroi tuplas (prow, srow, frow, mrows) prontas para gravacao no SQLite."""
    if not obj or obj < 0x10000:
        return None

    if buf is None:
        buf = reader.player_block(obj, abias)

    idt = reader.player_identity(obj, abias, buf)
    if not idt or not idt.get("uid"):
        return None

    uid = idt["uid"]
    prof = reader.player_profile(obj, abias, buf) or {}
    stats = reader.player_season_stats(obj, abias, buf) or {}
    pos = primary_position(prof)

    # Normalizacao de busca
    disp = idt.get("display_norm") or ""
    snorm = db.normalize(disp)

    # 1. prow (players)
    prow = (
        sid,
        uid,
        idt.get("name_first") or "",
        idt.get("name_last") or "",
        idt.get("common_name") or "",
        idt.get("full_name") or "",
        idt.get("legal_name") or "",
        snorm,
        disp,
        idt.get("ca", 0),
        idt.get("pa", 0),
        idt.get("height_cm", 180),
        idt.get("club_uid"),
        idt.get("team_uid"),
        pos,
    )

    # 2. srow (player_stats)
    s_vals = [sid, uid]
    for k in BASIC_KEYS:
        s_vals.append(stats.get(k, 0))
    for k in ADV_KEYS:
        s_vals.append(stats.get(k, 0))
    srow = tuple(s_vals)

    # 3. frow (player_profile)
    f_vals = [sid, uid]
    for k in PROFILE_KEYS:
        f_vals.append(prof.get(k))
    frow = tuple(f_vals)

    # 4. mrows (player_form)
    mrows = []
    form_items = reader.player_form(obj, abias)
    for m in form_items:
        mrows.append((
            sid,
            uid,
            m.get("date"),
            m.get("comp_uid"),
            m.get("comp_name"),
            m.get("team_uid"),
            m.get("rating"),
        ))

    return prow, srow, frow, mrows


def gravar_arquivo_partidas(mem, uids):
    """Complementa o snapshot com partidas do cache .obs temporario."""
    pass


def scan_base(conn, sid, reader, mem, progress=None, ref_date=None):
    """Le a base inteira da memoria e grava no snapshot sid."""
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

    # Track managed club teams
    managed_teams = set()
    if club_ptr and hasattr(reader, "club_teams"):
        try:
            managed_teams = set(reader.club_teams(club_ptr))
        except Exception:
            pass

    # Busca todos os times
    times = reader.all_teams_with_players()
    total_jogadores = 0

    prows = []
    srows = []
    frows = []
    mrows = []
    ptrows = []

    for idx, t in enumerate(times):
        t_uid = None
        if hasattr(reader, "u32"):
            try:
                t_uid = reader.u32(t + 0x0C)
            except Exception:
                pass

        # Check if t belongs to managed club
        is_managed = False
        if t in managed_teams:
            is_managed = True
        elif club_ptr and hasattr(reader, "q"):
            try:
                if reader.q(t + 0x30) == club_ptr:
                    is_managed = True
            except Exception:
                pass
        elif club_uid and hasattr(reader, "q") and hasattr(reader, "u32"):
            try:
                c_obj = reader.q(t + 0x30)
                if c_obj and reader.u32(c_obj + 0x0C) == club_uid:
                    is_managed = True
            except Exception:
                pass

        r = reader.roster(t)

        if is_managed:
            t_data = None
            if hasattr(reader, "team_details"):
                try:
                    t_data = reader.team_details(t, club_uid=club_uid)
                except Exception:
                    pass
            if not t_data and t_uid:
                t_data = {
                    "team_uid": t_uid,
                    "club_uid": club_uid,
                    "team_type": 0,
                    "label": "First Team",
                    "n_players": len(r),
                }
            if t_data:
                db.save_team(conn, sid, t_data)

        for pe in r:
            obj = reader.jogador_do_elenco(pe)
            rows = build_player_rows(reader, obj, sid, ref_date)
            if not rows:
                continue
            pr, sr, fr, mr = rows
            prows.append(pr)
            srows.append(sr)
            frows.append(fr)
            mrows.extend(mr)
            uid = pr[1]
            p_tuid = t_uid or pr[13] or uid
            ptrows.append((sid, uid, p_tuid))
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
            progress(idx + 1, len(times), "lendo_times")

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

    # Save managed club profile
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


def capture_all(snapshot_name, game_date_iso=None):
    """Captura todos os jogadores de todos os clubes e times para o banco local."""
    t0 = time.time()
    mem = FmMemory()
    reader = FmReader(mem)

    if not reader.save_loaded():
        raise FmNotRunning("Nenhum save carregado no Football Manager.")

    gd = reader.game_date()
    ref_date = gd.isoformat() if gd else (game_date_iso or "2026-07-01")
    sname = reader.save_name() or "Save Atual"

    mgr = reader.human_manager() if hasattr(reader, "human_manager") else None
    club_info = reader.manager_club() if hasattr(reader, "manager_club") else None
    club_ptr = club_info[0] if club_info and len(club_info) >= 1 else None
    club_uid = reader.u32(club_ptr + 0x0C) if club_ptr and hasattr(reader, "u32") else None

    conn = db.connect()
    db.init_schema(conn)

    sid = db.create_snapshot(
        conn,
        name=snapshot_name,
        save_name=sname,
        game_date=ref_date,
        scope="full",
        club_uid=club_uid,
        manager=mgr.get("full_name") if mgr else None,
        fm_version=mem.fm_version,
    )

    total = scan_base(conn, sid, reader, mem, ref_date=ref_date)
    conn.execute("VACUUM")
    conn.commit()

    dt = time.time() - t0
    print(f"[OK] {total} jogadores gravados no snapshot #{sid} em {dt:.1f}s")
    return sid


if __name__ == "__main__":
    nome = sys.argv[1] if len(sys.argv) > 1 else "Base Completa"
    capture_all(nome)
