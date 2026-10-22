"""Subprocesso de isolamento para extracao de memoria ao vivo (Live Scan).

Executa a leitura direta da memoria em um processo filho efemero para que 100% da
memoria heap alocada pelo CPython seja devolvida ao sistema operacional (macOS) ao finalizar.
Comunica progresso e status com o processo principal via multiprocessing.Queue.
"""

import os
import sys
import time
import multiprocessing
from datetime import date

from fm_memory import FmMemory, FmNotRunning, _log
from fm_reader import FmReader
import capture_all
import db


def _preparar_leitura_viva(reader, mem):
    """Verifica e inicializa estruturas previas para a leitura."""
    if not reader.save_loaded():
        raise FmNotRunning("Football Manager nao possui savegame aberto.")
    return True


def _ler_ao_vivo(game_date, arquivo, fila):
    """Corpo do processo da leitura. Conversa com o app pela `fila`."""
    try:
        if fila:
            fila.put({"phase": "conectando", "ready": False})

        mem = FmMemory()
        reader = FmReader(mem)

        _preparar_leitura_viva(reader, mem)

        gd = reader.game_date()
        data_iso = gd.isoformat() if gd else (game_date or date.today().isoformat())
        sname = reader.save_name() or "Jogo Salvo"

        if fila:
            fila.put({
                "phase": "preparando_base",
                "game_date": data_iso,
                "save_name": sname,
                "ready": False
            })

        conn = db.usar_live_db()
        db.init_schema(conn)

        sid = db.create_snapshot(
            conn,
            name="Live Database",
            save_name=sname,
            game_date=data_iso,
            scope="live",
            fm_version=mem.fm_version,
        )

        def report_prog(done, total, phase="lendo"):
            if fila:
                fila.put({
                    "phase": phase,
                    "done": done,
                    "total": total,
                    "ready": False
                })

        total = capture_all.scan_base(conn, sid, reader, mem, progress=report_prog, ref_date=data_iso)
        conn.commit()

        if fila:
            fila.put({
                "phase": "fim",
                "ready": True,
                "total": total,
                "game_date": data_iso,
                "save_name": sname,
                "snapshot_id": sid,
            })
    except Exception as e:
        _log(f"leitura ao vivo falhou: {e}")
        if fila:
            fila.put({
                "phase": "erro",
                "erro": str(e),
                "ready": False
            })


def rodar_no_filho(game_date, arquivo, fila):
    """Funcao alvo chamada pelo multiprocessing.Process no processo isolado."""
    try:
        _ler_ao_vivo(game_date, arquivo, fila)
    except Exception as e:
        if fila:
            fila.put({"phase": "erro", "erro": str(e), "ready": False})


def iniciar_leitura_viva(game_date=None, arquivo=None):
    """Dispara a leitura em segundo plano em processo separado."""
    ctx = multiprocessing.get_context("spawn")
    fila = ctx.Queue()
    p = ctx.Process(target=rodar_no_filho, args=(game_date, arquivo, fila))
    p.daemon = True
    p.start()
    return p, fila
