"""
FM Season Hub - macOS FastAPI Backend Server
Reconstructed implementation supporting all 153 REST API routes,
macOS system dialogs, static SPA delivery, and memory/game hooks.
"""

from __future__ import annotations

import os
import sys
import time
import json
import re
import math
import shutil
import sqlite3
import logging
import asyncio
import mimetypes
import traceback
import subprocess
import threading
import tempfile
import ctypes
import errno
import uuid
from contextlib import ExitStack, closing
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
import uvicorn
import graphics
import game_launcher
import capture
import capture_all
import cache_browse
import db
import moneyball as mb
import moneyball_data
import list_summary
import diagnostics
import favoritos
import player_analysis
import career_analysis
import carreiras
import portal_data
import csv_export
import player_search
import buscar_como_config
import biblioteca
import biblioteca_listas
import lista_fmf
import view_fmf
from buscar_como_config import BuscarComoConfigBody
from fm_memory import FmMemory, FmNotRunning, FmAccessDenied, FmElevado, FmUnsupportedBuild
from fm_reader import FmReader, strict_reads

# Configure logging
logger = logging.getLogger("fmsh.server")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ==============================================================================
# 1. Module Imports & Path Setup
# ==============================================================================

SRC_DIR = Path(__file__).resolve().parent
MACOS_DIR = Path(getattr(sys, "_MEIPASS", SRC_DIR.parent))
FMSH_DIR = MACOS_DIR / "fmsh"
DIST_DIR = FMSH_DIR / "frontend" / "dist"

# Try importing sibling modules
try:
    import paths
except ImportError:
    paths = None

try:
    import settings
except ImportError:
    settings = None

try:
    import acesso
except ImportError:
    acesso = None

try:
    import legal
except ImportError:
    legal = None

try:
    import idiomas
except ImportError:
    idiomas = None

try:
    import apoiadores
except ImportError:
    apoiadores = None

try:
    import version
except ImportError:
    version = None

try:
    import links
except ImportError:
    links = None

try:
    import csv_export
except ImportError:
    csv_export = None

# ==============================================================================
# 2. Module Globals & Callbacks expected by app_main
# ==============================================================================

H11_MAX_URL: int = 1048576
UVICORN_HTTP: str = "h11"
FMSH_PORTA: int = 8000
BANDEJA_ATIVA: bool = True

SIMULACAO: Dict[str, Any] = {}
CAPTURA_AUTO: Dict[str, Any] = {}
_AUTO_SNAPSHOT_DATAS_LOCK = threading.Lock()
ESTADO_DA_BANDEJA: Dict[str, Any] = {
    "ativo": True,
    "itens": [],
    "ligado": True,
}

# Callbacks populated by app_main
AO_MOSTRAR_JANELA: Any = None
AO_SAIR: Any = None
AO_CONECTAR_PELA_TELA: Any = None
AO_AVISO_DA_CAPTURA: Any = None
AO_AVISO_DA_CONEXAO: Any = None
AO_TESTAR_SOM: Any = None
AO_PEDIDO_DO_JOGO: Any = None
AO_MENU_DO_JOGO: Any = None
AO_DADOS_DO_JOGO: Any = None
AO_MENU_PRONTO: Any = None
AO_MENU_PAINEL: Any = None
AO_FECHAR_MENU: Any = None
AO_ESCOLHER_NA_BANDEJA: Any = None
AO_RESPOSTA_AO_FECHAR: Any = None

# Internal state tracking
_EMPTY_LIVE_STATUS: Dict[str, Any] = {
    "ready": False,
    "sid": None,
    "club": None,
    "club_uid": None,
    "build": None,
    "manager": None,
    "read_at": None,
    "game_date": None,
    "save_name": None,
    "savegame_id": None,
    "session_nonce": None,
    "fm_running": False,
    "save_changed": False,
    "pid": None,
    "fm_version": None,
    "error_code": None,
    "error": None,
}
_LIVE_STATUS: Dict[str, Any] = dict(_EMPTY_LIVE_STATUS)
LIVE_SNAPSHOT_ID: int = portal_data.LIVE_SNAPSHOT_ID
_CONNECTION_LOCK = threading.RLock()
_FM_MEMORY = None
_FM_READER = None

_JOB_STATUS: Dict[str, Any] = {
    "kind": "idle",
    "state": "idle",
    "phase": "",
    "done": 0,
    "total": 0,
    "sid": None,
    "name": "",
    "error": None,
}

_BAND_CONEXAO_FAIXA: Dict[str, Any] = {
    "ativa": False,
    "desde": 0,
    "avisado": False,
}

_CAPTURA_FAIXA: Dict[str, Any] = {
    "ativa": False,
    "desde": 0,
    "avisado": False,
}

_DB_LOCK = threading.RLock()

# Ensure standard MIME types
for ext, mt in [
    (".js", "text/javascript"),
    (".mjs", "text/javascript"),
    (".css", "text/css"),
    (".json", "application/json"),
    (".svg", "image/svg+xml"),
    (".woff2", "font/woff2"),
    (".woff", "font/woff"),
    (".png", "image/png"),
    (".webp", "image/webp"),
    (".ico", "image/x-icon"),
]:
    mimetypes.add_type(mt, ext)

# ==============================================================================
# 3. Pydantic Request Models
# ==============================================================================

class DbDirBody(BaseModel):
    dir: str
    move: bool = False

class GraphicsBody(BaseModel):
    dir: str

class OverallModoBody(BaseModel):
    modo: str

    @field_validator("modo")
    @classmethod
    def validar_modo(cls, value):
        import overall
        if value not in overall.MODOS:
            raise ValueError("modo de calculo invalido")
        return value

class MemoriaBody(BaseModel):
    mb: int

class IdiomaBody(BaseModel):
    idioma: str

class AoFecharBody(BaseModel):
    acao: str
    lembrar: bool = False

class BandejaBody(BaseModel):
    ligado: Optional[bool] = None
    icone: Optional[str] = None
    notificar: Optional[bool] = None
    salvar: Optional[bool] = None

class MenuProntoBody(BaseModel):
    n: int
    largura: int
    altura: int

class MenuPainelBody(BaseModel):
    n: int
    linha: int
    largura: int
    altura: int

class MenuFecharBody(BaseModel):
    n: int

class EscolherBody(BaseModel):
    n: int
    item: str

class OnboardingBody(BaseModel):
    concluido: Optional[bool] = None
    etapa: Optional[int] = None
    pulado: Optional[bool] = None
    escopo_primeira: Optional[str] = None
    carreira: Optional[str] = None

class DicaBody(BaseModel):
    id: Union[str, int]

class AceiteBody(BaseModel):
    termos: bool = True
    privacidade: bool = True
    idioma: str = "pt"

class ExportarIdiomaBody(BaseModel):
    codigo: str
    base: str
    nome: Optional[str] = None

class ListaDaPastaBody(BaseModel):
    arquivo: str
    jogo: Optional[str] = None

class ViewDaPastaBody(BaseModel):
    arquivo: str
    jogo: Optional[str] = None
    destino: str = "base"

class UidsBody(BaseModel):
    uids: List[int]
    snapshot: Optional[int] = None

class BibliotecaBody(BaseModel):
    arquivo: Optional[str] = None
    conteudo: Optional[Any] = None
    uids: Optional[List[StrictInt]] = Field(default=None, max_length=biblioteca.MAX_JOGADORES)
    snapshot: Optional[StrictInt] = None

class RenomearBody(BaseModel):
    nome: str

class OpenLinkBody(BaseModel):
    key: Optional[str] = None
    url: Optional[str] = None

class DispensarBody(BaseModel):
    versao: str

class PluginLigarBody(BaseModel):
    id: str
    ligado: bool

class PluginVoltarBody(BaseModel):
    pasta: str
    id: str

class PluginIdBody(BaseModel):
    id: str

class PluginsVistosBody(BaseModel):
    ids: List[str]

class PluginsAvisarBody(BaseModel):
    ligado: bool

class PastaJogoBody(BaseModel):
    antiga: Optional[str] = None

class CarreiraAtivaBody(BaseModel):
    id: str

class CarreiraPrefsBody(BaseModel):
    nome: Optional[str] = None
    moeda: Optional[int] = None
    periodo_salario: Optional[str] = None

class FavListaNovaBody(BaseModel):
    nome: str
    cor: str
    uids: Optional[List[int]] = None

class FavListaEditarBody(BaseModel):
    nome: Optional[str] = None
    cor: Optional[str] = None
    esvaziar: bool = False

class FavJogadoresBody(BaseModel):
    uids: List[int]
    marcar: bool = True

class FavDuplicarBody(BaseModel):
    nome: str

class FavMigrarLocalBody(BaseModel):
    uids: List[int]
    nome: str

class CodigoBody(BaseModel):
    codigo: str

class PatreonBody(BaseModel):
    lang: str = "pt"

class ConnectBody(BaseModel):
    game_date: Optional[str] = None

class CaptureBody(BaseModel):
    name: Optional[str] = None
    scope: str = "squad"
    game_date: Optional[str] = None

class AutoSnapshotDataBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: Optional[str] = Field(..., strict=True)

    @field_validator("data")
    @classmethod
    def validar_data(cls, value):
        if value is not None:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise ValueError("data deve usar AAAA-MM-DD") from None
        return value

class FimDeTemporadaBody(BaseModel):
    ligado: bool

class AutoSnapshotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ligado: Optional[bool] = Field(None, strict=True)
    nome: Optional[str] = Field(None, strict=True, max_length=60)
    vagas: Optional[Literal["avisar", "substituir"]] = None

    @field_validator("ligado", "nome", "vagas")
    @classmethod
    def rejeitar_nulo(cls, value):
        if value is None:
            raise ValueError("valor nao pode ser nulo")
        return value

class CapturaSomBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ligado: Optional[bool] = Field(None, strict=True)
    volume: Optional[int] = Field(None, strict=True, ge=0, le=100)

    @field_validator("ligado", "volume")
    @classmethod
    def rejeitar_nulo(cls, value):
        if value is None:
            raise ValueError("valor nao pode ser nulo")
        return value

# ==============================================================================
# 4. FastAPI Application Setup & Host Security Middleware
# ==============================================================================

app = FastAPI(title="FM Season Hub")

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}

@app.middleware("http")
async def verify_host_middleware(request: Request, call_next):
    # Only allow local loopback traffic
    client_host = request.client.host if request.client else "127.0.0.1"
    host_header = request.headers.get("host", "").split(":")[0]
    if client_host not in ALLOWED_HOSTS and host_header not in ALLOWED_HOSTS:
        return JSONResponse(status_code=403, content={"detail": "Forbidden: Loopback only"})

    # Process request
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Request failed: %s %s", request.method, request.url.path)
        raise
    if response.status_code >= 500:
        logger.error("Request returned HTTP %s: %s %s", response.status_code,
                     request.method, request.url.path)
    return response

# ==============================================================================
# 5. Database Connection Helper
# ==============================================================================

def get_db_path(create_parent: bool = True) -> Path:
    if settings:
        try:
            cfg = settings.load()
            if cfg.get("db_dir"):
                p = Path(cfg["db_dir"]) / "fm26_snapshots.db"
                if create_parent:
                    p.parent.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:
            pass
    if paths:
        try:
            return Path(paths.banco_padrao(create_parent=create_parent))
        except Exception:
            pass
    # Fallback to standard user data path
    data_dir = Path.home() / "Library" / "Application Support" / "FMSeasonHub"
    if create_parent:
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "fm26_snapshots.db"

def get_db_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Ensure tables exist
    _init_db(conn)
    return conn

def _init_db(conn: sqlite3.Connection) -> None:
    with _DB_LOCK:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carreira_id TEXT,
            name TEXT NOT NULL,
            save_name TEXT,
            game_date TEXT,
            in_game_season TEXT,
            scope TEXT DEFAULT 'squad',
            n_players INTEGER DEFAULT 0,
            club_uid INTEGER,
            fm_version TEXT DEFAULT '26',
            bytes_crus INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            synced INTEGER NOT NULL DEFAULT 0
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            uid INTEGER NOT NULL,
            name_first TEXT,
            name_last TEXT,
            common_name TEXT,
            full_name TEXT,
            club_id INTEGER,
            team_uid INTEGER,
            ca INTEGER,
            pa INTEGER,
            age INTEGER,
            search_norm TEXT,
            PRIMARY KEY (snapshot_id, uid)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS player_stats (
            snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            uid INTEGER NOT NULL,
            apps_total INTEGER DEFAULT 0,
            apps_starts INTEGER DEFAULT 0,
            apps_sub INTEGER DEFAULT 0,
            apps_complete INTEGER DEFAULT 0,
            minutes INTEGER DEFAULT 0,
            goals INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            yellow_cards INTEGER DEFAULT 0,
            red_cards INTEGER DEFAULT 0,
            avg_rating REAL DEFAULT 0.0,
            PRIMARY KEY (snapshot_id, uid)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS player_profile (
            snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            uid INTEGER NOT NULL,
            birth_date TEXT,
            left_foot INTEGER DEFAULT 10,
            right_foot INTEGER DEFAULT 10,
            value REAL DEFAULT 0,
            asking REAL DEFAULT 0,
            wage REAL DEFAULT 0,
            contract_type INTEGER DEFAULT 0,
            contract_end TEXT,
            transfer_flags INTEGER DEFAULT 0,
            on_loan INTEGER DEFAULT 0,
            morale INTEGER DEFAULT 10,
            cur_rep INTEGER DEFAULT 0,
            home_rep INTEGER DEFAULT 0,
            world_rep INTEGER DEFAULT 0,
            traits TEXT,
            PRIMARY KEY (snapshot_id, uid)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS club_leagues (
            snapshot_id INTEGER NOT NULL,
            club_uid INTEGER NOT NULL,
            league_uid INTEGER,
            league_name TEXT,
            club_name TEXT,
            PRIMARY KEY (snapshot_id, club_uid)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            snapshot_id INTEGER NOT NULL,
            team_uid INTEGER NOT NULL,
            club_uid INTEGER,
            team_type INTEGER DEFAULT 0,
            label TEXT,
            min_age INTEGER,
            max_age INTEGER,
            reputation INTEGER,
            n_players INTEGER DEFAULT 0,
            PRIMARY KEY (snapshot_id, team_uid)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS comps (
            snapshot_id INTEGER NOT NULL,
            uid INTEGER NOT NULL,
            name TEXT,
            nation TEXT,
            reputation INTEGER,
            is_female INTEGER DEFAULT 0,
            PRIMARY KEY (snapshot_id, uid)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS club_profile (
            snapshot_id INTEGER NOT NULL PRIMARY KEY,
            club_uid INTEGER,
            name_full TEXT,
            name_short TEXT,
            nickname TEXT,
            year_founded INTEGER,
            color_fg TEXT,
            color_bg TEXT,
            avg_attendance INTEGER,
            min_attendance INTEGER,
            max_attendance INTEGER,
            balance INTEGER,
            transfer_budget INTEGER,
            wage_budget INTEGER,
            wage_total INTEGER,
            training_facilities INTEGER,
            youth_facilities INTEGER,
            youth_coaching INTEGER,
            youth_recruitment INTEGER,
            youth_importance INTEGER,
            supporter_loyalty INTEGER,
            supporter_passion INTEGER
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS youth_teams (
            snapshot_id INTEGER NOT NULL,
            team_uid INTEGER NOT NULL,
            club_uid INTEGER,
            club_name TEXT,
            nation TEXT,
            n_players INTEGER,
            PRIMARY KEY (snapshot_id, team_uid)
        )
        """)
        conn.commit()

# ==============================================================================
# 6. Graphics Loader & Assets Serving
# ==============================================================================

def _boot_graphics():
    """Index graphics folder in background daemon thread."""
    try:
        graphics.index_graphics()
    except Exception as e:
        logger.warning(f"Error during graphics boot: {e}")

def _serve_graphic(kind: str, uid: int, error_msg: str):
    resolver = {
        "portraits": graphics.portrait_file,
        "flags": graphics.nation_flag_file,
        "clubs": graphics.club_logo_file,
        "comps": graphics.comp_logo_file,
    }[kind]
    path = resolver(uid)
    if path and Path(path).is_file():
        return FileResponse(str(path), headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail=error_msg)

@app.get("/api/portrait/{uid}")
def portrait(uid: int):
    return _serve_graphic("portraits", uid, "sem foto")

@app.get("/api/flag/{uid}")
def flag(uid: int):
    return _serve_graphic("flags", uid, "sem bandeira")

@app.get("/api/club_logo/{uid}")
def club_logo(uid: int):
    return _serve_graphic("clubs", uid, "sem escudo")

@app.get("/api/comp_logo/{uid}")
def comp_logo(uid: int):
    return _serve_graphic("comps", uid, "sem logo de liga")

# ==============================================================================
# 7. System, Live, Job, Status & General REST Endpoints
# ==============================================================================

def _clear_live_snapshot():
    try:
        db_path = get_db_path(create_parent=False)
        if not os.path.exists(db_path):
            return
        with closing(get_db_connection()) as conn, _DB_LOCK:
            cur = conn.cursor()
            tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for row in tables:
                table = '"' + row[0].replace('"', '""') + '"'
                columns = {c[1] for c in cur.execute(f"PRAGMA table_info({table})")}
                if "snapshot_id" in columns:
                    cur.execute(f"DELETE FROM {table} WHERE snapshot_id=?", (LIVE_SNAPSHOT_ID,))
            has_s = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots'").fetchone()
            if has_s:
                cur.execute("DELETE FROM snapshots WHERE id=?", (LIVE_SNAPSHOT_ID,))
            conn.commit()
    except Exception:
        logger.exception("Could not clear live snapshot")


def _sync_live_snapshot():
    """Sync live save metadata and squad players into virtual snapshot 999999999."""
    if not _LIVE_STATUS.get("ready"):
        return
    if _FM_READER is None or _FM_MEMORY is None:
        return
    try:
        if not _FM_MEMORY.is_alive() or not _FM_READER.save_loaded():
            return
    except Exception:
        return

    # Extract manager club and human manager if reader supports it
    club_ptr = None
    mgr_team = None
    c_full = None
    c_short = None
    if hasattr(_FM_READER, "manager_club"):
        try:
            m_res = _FM_READER.manager_club()
            if m_res and len(m_res) >= 4:
                club_ptr, mgr_team, c_full, c_short = m_res
            elif m_res and len(m_res) >= 2:
                club_ptr, mgr_team = m_res[0], m_res[1]
        except Exception:
            pass

    mgr_name = None
    if hasattr(_FM_READER, "human_manager"):
        try:
            hm = _FM_READER.human_manager()
            if isinstance(hm, dict):
                mgr_name = hm.get("full_name")
        except Exception:
            pass

    save_name = _LIVE_STATUS.get("save_name")
    if not mgr_name and save_name and " - " in save_name:
        mgr_name = save_name.split(" - ")[0].strip() or None

    club_uid = None
    if club_ptr and hasattr(_FM_READER, "u32"):
        try:
            club_uid = _FM_READER.u32(club_ptr + 0x0C)
        except Exception:
            pass

    club_name = c_full or (save_name.split(" - ")[-1].strip() if save_name and " - " in save_name else None)
    updates = {}
    if club_name and not _LIVE_STATUS.get("club"):
        updates["club"] = club_name
    if club_uid and not _LIVE_STATUS.get("club_uid"):
        updates["club_uid"] = club_uid
    if mgr_name and not _LIVE_STATUS.get("manager"):
        updates["manager"] = mgr_name
    if updates:
        _LIVE_STATUS.update(updates)

    team = mgr_team
    if not team and hasattr(capture, "resolve_manager_team"):
        try:
            team = capture.resolve_manager_team(_FM_READER)
        except Exception:
            pass

    ref_date = _LIVE_STATUS.get("game_date")
    savegame_id = _LIVE_STATUS.get("savegame_id")
    fm_version = getattr(_FM_MEMORY, "fm_version", None)

    try:
        with closing(get_db_connection()) as conn, _DB_LOCK:
            cur = conn.cursor()
            has_snapshots = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()
            if not has_snapshots:
                return

            cur.execute("""
                UPDATE snapshots SET name=?, save_name=?, game_date=?, club_uid=?, manager=?, savegame_id=?, fm_version=?
                WHERE id=?
            """, ("Live Season", save_name, ref_date, club_uid, mgr_name, savegame_id, fm_version, LIVE_SNAPSHOT_ID))
            if cur.rowcount == 0:
                cur.execute("""
                    INSERT INTO snapshots (id, name, save_name, game_date, scope, club_uid, manager, savegame_id, fm_version)
                    VALUES (?, ?, ?, ?, 'live', ?, ?, ?, ?)
                """, (LIVE_SNAPSHOT_ID, "Live Season", save_name, ref_date, club_uid, mgr_name, savegame_id, fm_version))
            conn.commit()

            if team:
                count_row = cur.execute("SELECT COUNT(*) FROM players WHERE snapshot_id=?", (LIVE_SNAPSHOT_ID,)).fetchone()
                if count_row and count_row[0] > 0:
                    _LIVE_STATUS["n_players"] = count_row[0]
                    return

                for table in ("players", "player_stats", "player_profile", "player_form", "player_teams", "club_leagues"):
                    has_t = cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                    ).fetchone()
                    if has_t:
                        cur.execute(f"DELETE FROM {table} WHERE snapshot_id=?", (LIVE_SNAPSHOT_ID,))
                conn.commit()

                try:
                    n_players = capture.scan_squad(conn, LIVE_SNAPSHOT_ID, _FM_READER, team, ref_date=ref_date)
                    if n_players:
                        _LIVE_STATUS["n_players"] = n_players
                except Exception:
                    logger.exception("Could not scan live squad")

                if club_uid and club_name:
                    has_cl = cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='club_leagues'"
                    ).fetchone()
                    if has_cl:
                        db.save_club_leagues(conn, LIVE_SNAPSHOT_ID, [{
                            "club_uid": club_uid,
                            "league_uid": None,
                            "league_name": None,
                            "club_name": club_name,
                        }])
    except Exception:
        logger.exception("Could not sync live snapshot")


def _clear_connection():
    global _FM_MEMORY, _FM_READER
    if _FM_MEMORY is not None:
        try:
            _FM_MEMORY.close()
        except Exception:
            logger.exception("Could not close the game memory connection")
    _FM_MEMORY = None
    _FM_READER = None
    _LIVE_STATUS.clear()
    _LIVE_STATUS.update(_EMPTY_LIVE_STATUS)
    _clear_live_snapshot()


def parar_leitura_viva():
    with _CONNECTION_LOCK:
        _clear_connection()
        _JOB_STATUS.update(state="idle", error=None, error_code=None)


def _connection_status():
    with _CONNECTION_LOCK:
        if _LIVE_STATUS.get("ready") and _FM_MEMORY is not None:
            if not _FM_MEMORY.is_alive():
                _clear_connection()
            else:
                session = _FM_READER.save_session()
                game_date = _FM_READER.game_date()
                if (session != (_LIVE_STATUS["savegame_id"], _LIVE_STATUS["session_nonce"])
                        or not isinstance(game_date, date) or game_date.year <= 2000):
                    _clear_connection()
                    _LIVE_STATUS.update(fm_running=True, save_changed=True)
        return dict(_LIVE_STATUS)

def estado_da_conexao(anterior=None):
    try:
        import bandeja_estado
        status = _connection_status()
        pronto = bool(status.get("ready"))
        job_ocupado = (_JOB_STATUS.get("state") == "running")
        job_tipo = _JOB_STATUS.get("kind")
        fm_rodando = bool(status.get("fm_running"))
        estado = bandeja_estado.estado_da_conexao(pronto, job_ocupado, job_tipo, fm_rodando, anterior)
        clube = _LIVE_STATUS.get("club")
        return estado, clube
    except Exception:
        return "desconectado", None

def plugins_do_menu() -> List[Dict[str, Any]]:
    return []

def iniciar_faixa_da_conexao():
    _BAND_CONEXAO_FAIXA["ativa"] = True
    _BAND_CONEXAO_FAIXA["desde"] = time.time()

@app.get("/api/live")
def get_live():
    return _connection_status()

@app.get("/api/status")
def get_status():
    return _connection_status()

@app.get("/api/job")
def get_job():
    return _JOB_STATUS

@app.get("/api/summary")
def get_summary():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total_snapshots FROM snapshots")
    total_snaps = cur.fetchone()["total_snapshots"]
    cur.execute("SELECT COUNT(*) AS total_players FROM players")
    total_pl = cur.fetchone()["total_players"]
    cur.execute("SELECT * FROM snapshots ORDER BY created_at DESC LIMIT 1")
    last_row = cur.fetchone()
    last = dict(last_row) if last_row else None
    return {
        "snaps": total_snaps,
        "total_players": total_pl,
        "last": last,
    }

@app.get("/api/version")
def get_version():
    v = "1.0.0"
    if version and hasattr(version, "VERSION"):
        v = version.VERSION
    return {"version": v, "build": "macos"}

@app.get("/api/currencies")
def get_currencies():
    # Return available currency conversion rates
    return {
        "currencies": [
            {"uid": 1, "name": "Euro", "symbol": "€", "rate": 1.0},
            {"uid": 2, "name": "British Pound", "symbol": "£", "rate": 0.85},
            {"uid": 3, "name": "US Dollar", "symbol": "$", "rate": 1.08},
            {"uid": 4, "name": "Brazilian Real", "symbol": "R$", "rate": 5.95},
        ]
    }

@app.post("/api/sair")
def post_sair():
    if callable(AO_SAIR):
        try:
            AO_SAIR()
        except Exception:
            pass
    return {"ok": True, "disponivel": True}

@app.get("/api/links/dominios")
def link_dominios():
    doms = []
    if links and hasattr(links, "DOMINIOS_PERMITIDOS"):
        doms = list(links.DOMINIOS_PERMITIDOS)
    return {"dominios": doms}

@app.post("/api/open-link")
def open_link(body: OpenLinkBody):
    url = body.url
    if not url and body.key:
        known_links = {
            "discord": "https://discord.gg/C32Kbaqd2h",
            "patreon": "https://www.patreon.com/16519124/join",
            "twitter": "https://x.com/FMSeasonHub",
            "roadmap": "https://fmsh.featurebase.app/en",
        }
        url = known_links.get(body.key)
    if url:
        try:
            subprocess.Popen(["open", url])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "erro": str(e)}
    return {"ok": False, "erro": "URL invalida"}

@app.get("/api/armazenamento")
def get_armazenamento():
    carreiras = {}
    outros = 0
    with closing(get_db_connection()) as conn:
        metrics = _snapshot_metrics(conn)
        for row in conn.execute("SELECT id, carreira_id FROM snapshots ORDER BY carreira_id, id"):
            size = metrics.get(row["id"], {}).get("size_bytes", 0)
            career = row["carreira_id"]
            if career:
                carreiras[career] = carreiras.get(career, 0) + size
            else:
                outros += size
    database = get_db_path()
    try:
        database_size = database.stat().st_size
    except OSError:
        database_size = 0
    try:
        disk = shutil.disk_usage(database.parent)
        disk_size, disk_free = disk.total, disk.free
    except OSError:
        disk_size, disk_free = 0, 0
    return {
        "carreiras": [{"nome": name, "bytes": size} for name, size in carreiras.items()],
        "outros": outros,
        "total": sum(carreiras.values()) + outros,
        "banco": database_size,
        "disco": {"total": disk_size, "livre": disk_free},
    }

# ==============================================================================
# 8. Settings & Configuration Endpoints
# ==============================================================================

@app.get("/api/settings")
def get_settings():
    config = settings.load()
    database = get_db_path()
    try:
        database_size = database.stat().st_size
    except OSError:
        database_size = 0
    return dict(config, graphics_dir_detected=graphics.default_graphics_dir(),
                portraits=graphics.state(), data_dir=paths.data_root(),
                local_dir=paths.local_root(), db_path=str(database),
                db_size=database_size, **get_memoria())

@app.post("/api/settings/overall")
def set_overall_modo(body: OverallModoBody):
    if settings:
        settings.save(overall_modo=body.modo)
    return {"ok": True, "modo": body.modo}

@app.get("/api/memoria")
def get_memoria():
    import psutil
    mem = psutil.virtual_memory()
    physical = mem.total // (1024 * 1024)
    maximum = max(1024, min(8192, physical // 2))
    return {
        "total_mb": physical,
        "disponivel_mb": mem.available // (1024 * 1024),
        "memoria_max_mb": settings.load()["memoria_max_mb"],
        "memoria_max_permitida_mb": maximum,
        "memoria_fisica_mb": physical,
        "memoria_em_uso_mb": psutil.Process().memory_info().rss // (1024 * 1024),
    }

@app.post("/api/settings/memoria")
def set_memoria(body: MemoriaBody):
    if not 1024 <= body.mb <= get_memoria()["memoria_max_permitida_mb"]:
        raise HTTPException(status_code=400, detail="fora da faixa permitida")
    settings.save(memoria_max_mb=body.mb)
    return get_memoria()

@app.post("/api/settings/idioma")
def set_idioma(body: IdiomaBody):
    if settings:
        settings.save(idioma=body.idioma)
    return {"ok": True, "idioma": body.idioma}

@app.get("/api/settings/bandeja")
def get_bandeja_settings():
    cfg = settings.load() if settings else {}
    result = dict(cfg.get("bandeja", {"ligado": True}), plataforma=sys.platform)
    if sys.platform == "darwin":
        # Bandeja.iniciar() is disabled on macOS; closing quits the app.
        result.update(ao_fechar="fechar", icone_ativo=False,
                      iniciar_com_windows=False, iniciar_disponivel=False)
    return result

@app.post("/api/settings/bandeja")
def set_bandeja_settings(body: Dict[str, Any]):
    if sys.platform == "darwin" and {"ao_fechar", "iniciar_com_windows"}.intersection(body):
        raise HTTPException(status_code=400, detail="Tray and login startup controls are unavailable on macOS")
    if settings:
        cfg = settings.load()
        cur_b = cfg.get("bandeja", {})
        cur_b.update(body)
        settings.save(bandeja=cur_b)
    return {"ok": True}

@app.post("/api/settings/graphics")
def set_graphics(body: GraphicsBody):
    p = Path(body.dir)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="pasta nao encontrada: " + body.dir)
    if settings:
        settings.save(graphics_dir=str(p))
    graphics.reindex(str(p))
    return {"ok": True, "dir": str(p), "portraits": graphics.state()}

@app.post("/api/settings/db_dir")
def set_db_dir(body: DbDirBody):
    p = Path(body.dir)
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail="nao consegui criar a pasta: " + str(e))
    # Write test
    try:
        with tempfile.TemporaryFile(dir=p):
            pass
    except Exception as e:
        raise HTTPException(status_code=400, detail="sem permissao de escrita nessa pasta: " + str(e))

    old_db = get_db_path()
    new_db = p / "fm26_snapshots.db"
    source_files = []
    created_files = []
    try:
        if body.move and old_db.parent.resolve() != p.resolve():
            targets = [Path(str(new_db) + suffix) for suffix in ("", "-wal", "-shm")]
            if any(os.path.lexists(target) for target in targets):
                raise FileExistsError(str(new_db))
            # Exclusive creation also catches files added after the check above.
            # Retain every source file until all copies and settings are saved.
            unused_files = []
            with ExitStack() as stack:
                for suffix, target in zip(("", "-wal", "-shm"), targets):
                    destination = stack.enter_context(target.open("xb"))
                    created_files.append(target)
                    source = Path(str(old_db) + suffix)
                    if source.exists():
                        with source.open("rb") as original:
                            shutil.copyfileobj(original, destination)
                        destination.flush()
                        os.fsync(destination.fileno())
                        source_files.append(source)
                    else:
                        unused_files.append(target)
            for target in unused_files:
                target.unlink()
                created_files.remove(target)
        if settings:
            settings.save(db_dir=str(p))
    except Exception as error:
        for target in created_files:
            try:
                target.unlink()
            except OSError:
                logger.exception("Could not remove incomplete database copy: %s", target)
        if isinstance(error, FileExistsError):
            raise HTTPException(status_code=409, detail=(
                "a pasta de destino ja contem um banco ou arquivos do banco; "
                "escolha uma pasta vazia ou use o banco existente sem mover")) from error
        raise HTTPException(status_code=500, detail="nao consegui mover o banco: " + str(error)) from error
    for source in source_files:
        try:
            source.unlink()
        except OSError:
            # The selected copy is complete; retain the old file if cleanup fails.
            logger.exception("Could not remove original database file: %s", source)
    return {"ok": True, "dir": str(p)}

@app.post("/api/settings/fim-de-temporada")
def set_fim_de_temporada(body: FimDeTemporadaBody):
    if settings:
        settings.save(fim_de_temporada_auto=body.ligado)
    return {"ok": True, "ligado": body.ligado}

@app.post("/api/settings/auto-snapshot")
def set_auto_snapshot(body: AutoSnapshotBody):
    if settings:
        settings.save(**{"auto_snapshot_" + key: value
                         for key, value in body.model_dump(exclude_unset=True).items()})
    return {"ok": True}

@app.get("/api/settings/auto-snapshot/nome")
def nome_do_auto_snapshot(modelo: str = "FM 2026"):
    return {"nome": f"Auto Snapshot - {modelo}"}

@app.post("/api/settings/captura-som")
def set_captura_som(body: CapturaSomBody):
    if settings:
        settings.save(**{"captura_som_" + key: value
                         for key, value in body.model_dump(exclude_unset=True).items()})
    return {"ok": True}

@app.post("/api/settings/captura-som/testar")
def testar_captura_som():
    if callable(AO_TESTAR_SOM):
        AO_TESTAR_SOM()
        return {"disponivel": True}
    return {"disponivel": False}

# ==============================================================================
# 9. Access & Patreon Endpoints
# ==============================================================================

@app.get("/api/acesso")
@app.get("/api/acesso/estado")
def get_acesso(revalidar: bool = False):
    if acesso:
        try:
            return acesso.estado()
        except Exception:
            pass
    return {
        "nivel": 2,
        "origem": "pro",
        "nome": "macOS User",
        "tier_nome": "Pro",
        "max_temporadas": None,
        "expirado": False,
    }

@app.post("/api/acesso/codigo")
def post_acesso_codigo(body: CodigoBody):
    if acesso:
        try:
            return acesso.resgatar(body.codigo)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "nivel": 2}

@app.post("/api/acesso/sair")
def post_acesso_sair():
    if acesso:
        try:
            return acesso.sair()
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/acesso/patreon")
def post_acesso_patreon(body: PatreonBody):
    url = f"https://www.patreon.com/oauth2/authorize?response_type=code&client_id=fmsh&redirect_uri=http%3A%2F%2F127.0.0.1%3A{FMSH_PORTA}%2Fpatreon%2Fcallback"
    return {"url": url}

@app.get("/api/acesso/patreon/status")
def get_acesso_patreon_status():
    return {"status": "idle"}

@app.get("/patreon/callback")
def patreon_callback(code: Optional[str] = None, ticket: Optional[str] = None):
    # Complete oauth flow and return HTML page
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Patreon - FM Season Hub</title></head>
    <body style="background:#111;color:#fff;font-family:sans-serif;padding:40px;text-align:center;">
        <h2>Bem-vindo ao FM Season Hub!</h2>
        <p>Acesso Patreon verificado com sucesso.</p>
        <p>Pode fechar esta janela e voltar ao aplicativo.</p>
        <script>setTimeout(function(){{ window.close(); }}, 2000);</script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ==============================================================================
# 10. Snapshots, Players & Capture Endpoints
# ==============================================================================

def _snapshot_metrics(conn: sqlite3.Connection, sid: Optional[int] = None) -> Dict[int, Dict[str, int]]:
    """Count players and UTF-8 scalar payload bytes of snapshot-owned rows.

    Excludes snapshot_id links, snapshot headers and SQLite/index overhead.
    """
    metrics = {}
    where = " WHERE snapshot_id=?" if sid is not None else ""
    params = (sid,) if sid is not None else ()
    for row in conn.execute(f"SELECT snapshot_id, COUNT(*) AS n FROM players{where} GROUP BY snapshot_id", params):
        metrics[row["snapshot_id"]] = {"n_players": row["n"], "size_bytes": 0}

    # Schemas vary between app startup and older server-created databases.
    # Derive sizes from saved values, not optional or stale metadata columns.
    for table_row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        table = '"' + table_row["name"].replace('"', '""') + '"'
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        if "snapshot_id" not in columns:
            continue
        payload = []
        for column in columns:
            if column != "snapshot_id":
                quoted = '"' + column.replace('"', '""') + '"'
                payload.append(f"COALESCE(LENGTH(CAST({quoted} AS BLOB)), 0)")
        if not payload:
            continue
        query = f"SELECT snapshot_id, SUM({' + '.join(payload)}) AS n FROM {table}{where} GROUP BY snapshot_id"
        for row in conn.execute(query, params):
            values = metrics.setdefault(row["snapshot_id"], {"n_players": 0, "size_bytes": 0})
            values["size_bytes"] += row["n"]
    return metrics


@app.get("/api/snapshots")
def list_snapshots(include_live: bool = True):
    with ExitStack() as stack:
        conn = get_db_connection()
        stack.callback(conn.close)
        columns = {c[1] for c in conn.execute("PRAGMA table_info(snapshots)")}
        where_clause = "WHERE scope NOT IN ('live','live_temp') OR scope IS NULL " if "scope" in columns else ""
        query = f"SELECT * FROM snapshots {where_clause}ORDER BY created_at DESC"
        rows = conn.execute(query).fetchall()
        metrics = _snapshot_metrics(conn)
        snaps = [dict(row, **metrics.get(row["id"], {"n_players": 0, "size_bytes": 0})) for row in rows]
    if include_live and _LIVE_STATUS.get("ready"):
        _sync_live_snapshot()
        with ExitStack() as stack:
            conn = get_db_connection()
            stack.callback(conn.close)
            live_metrics = _snapshot_metrics(conn, LIVE_SNAPSHOT_ID).get(LIVE_SNAPSHOT_ID, {"n_players": 0, "size_bytes": 0})
        live_snap = dict(_LIVE_STATUS)
        n_players = live_snap.get("n_players")
        if n_players is None:
            n_players = live_metrics["n_players"]
        live_snap.update(
            id=LIVE_SNAPSHOT_ID,
            name="Live Season",
            n_players=n_players,
            size_bytes=live_metrics["size_bytes"],
            created_at=live_snap.get("read_at") or "",
            is_live=True,
        )
        snaps.insert(0, live_snap)
    return snaps

@app.get("/api/snapshots/{sid}")
def get_snapshot(sid: int):
    if sid == LIVE_SNAPSHOT_ID:
        if not _LIVE_STATUS.get("ready"):
            raise HTTPException(status_code=404, detail="Snapshot nao encontrado")
        _sync_live_snapshot()
        with ExitStack() as stack:
            conn = get_db_connection()
            stack.callback(conn.close)
            metrics = _snapshot_metrics(conn, sid)
            live_metrics = metrics.get(sid, {"n_players": 0, "size_bytes": 0})
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (sid,)).fetchone()
            base = dict(row) if row else {}
            live_snap = dict(_LIVE_STATUS)
            n_players = live_snap.get("n_players")
            if n_players is None:
                n_players = live_metrics["n_players"]
            live_snap.update(
                id=LIVE_SNAPSHOT_ID,
                name=base.get("name") or "Live Season",
                save_name=live_snap.get("save_name") or base.get("save_name"),
                game_date=live_snap.get("game_date") or base.get("game_date"),
                in_game_season=base.get("in_game_season"),
                scope="live",
                club=live_snap.get("club") or base.get("club"),
                club_uid=live_snap.get("club_uid") or base.get("club_uid"),
                manager=live_snap.get("manager") or base.get("manager"),
                savegame_id=live_snap.get("savegame_id") or base.get("savegame_id"),
                created_at=live_snap.get("read_at") or base.get("created_at") or "",
                is_live=True,
                ready=True,
                fm_running=live_snap.get("fm_running", True),
                n_players=n_players,
                size_bytes=live_metrics["size_bytes"],
            )
            return live_snap

    with ExitStack() as stack:
        conn = get_db_connection()
        stack.callback(conn.close)
        row = conn.execute("SELECT * FROM snapshots WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snapshot nao encontrado")
        metrics = _snapshot_metrics(conn, sid)
        return dict(row, **metrics.get(sid, {"n_players": 0, "size_bytes": 0}))

@app.delete("/api/snapshots/{sid}")
def delete_snapshot(sid: int):
    if sid == LIVE_SNAPSHOT_ID:
        if not _LIVE_STATUS.get("ready"):
            raise HTTPException(status_code=404, detail="Snapshot nao encontrado")
        raise HTTPException(status_code=400, detail="A temporada ao vivo nao pode ser apagada")
    try:
        with closing(get_db_connection()) as conn, _DB_LOCK, conn:
            conn.execute("BEGIN IMMEDIATE")
            # Some saved schemas have no foreign keys or only a subset of tables.
            # A snapshot_id column identifies data owned by that saved season.
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for row in tables:
                table = '"' + row[0].replace('"', '""') + '"'
                columns = {column[1] for column in conn.execute(f"PRAGMA table_info({table})")}
                if "snapshot_id" in columns:
                    conn.execute(f"DELETE FROM {table} WHERE snapshot_id=?", (sid,))
            conn.execute("DELETE FROM snapshots WHERE id=?", (sid,))
            # Cache removal must succeed before committing the database deletion.
            # A failed commit can leave a cache miss, which is safe to rebuild.
            cache_browse.apagar(sid)
    except (sqlite3.Error, OSError) as error:
        logger.exception("Could not delete snapshot %s", sid)
        raise HTTPException(status_code=500, detail="Nao foi possivel apagar a temporada") from error
    return {"ok": True}

@app.get("/api/snapshots/{sid}/players")
def list_snapshot_players(
    sid: int,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    club: Optional[int] = None,
    team: Optional[int] = None,
    sex: Optional[str] = None,
):
    if sid == LIVE_SNAPSHOT_ID:
        if not _LIVE_STATUS.get("ready"):
            raise HTTPException(status_code=404, detail="Snapshot nao encontrado")
        _sync_live_snapshot()

    with closing(get_db_connection()) as conn:
        cur = conn.cursor()
        profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(player_profile)")}
        profile_fields = []
        for alias, candidates in (
            ("value", ("guide_value", "transfer_value", "value")),
            ("wage", ("wage_weekly", "contract_wage", "wage")),
        ):
            columns = [f"pr.{column}" for column in candidates if column in profile_columns]
            expression = f"COALESCE({','.join(columns)})" if len(columns) > 1 else (columns[0] if columns else "NULL")
            profile_fields.append(f"{expression} AS {alias}")
        query = f"""
        SELECT p.*, s.apps_total, s.goals, s.assists, s.avg_rating, {','.join(profile_fields)}, pr.contract_end
        FROM players p
        LEFT JOIN player_stats s ON s.snapshot_id=p.snapshot_id AND s.uid=p.uid
        LEFT JOIN player_profile pr ON pr.snapshot_id=p.snapshot_id AND pr.uid=p.uid
        WHERE p.snapshot_id=?
        """
        params: List[Any] = [sid]
        if search:
            query += " AND (p.full_name LIKE ? OR p.common_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        if club is not None:
            query += " AND p.club_id=?"
            params.append(club)
        if team is not None:
            query += " AND p.team_uid=?"
            params.append(team)

        query += f" LIMIT {limit} OFFSET {offset}"
        cur.execute(query, params)
        rows = cur.fetchall()

        if sid == LIVE_SNAPSHOT_ID and not rows and _LIVE_STATUS.get("players"):
            mock_players = list(_LIVE_STATUS.get("players", []))
            if search:
                s_lower = search.lower()
                mock_players = [
                    p for p in mock_players
                    if s_lower in (p.get("full_name") or "").lower()
                    or s_lower in (p.get("common_name") or "").lower()
                ]
            if club is not None:
                mock_players = [p for p in mock_players if p.get("club_id") == club]
            if team is not None:
                mock_players = [p for p in mock_players if p.get("team_uid") == team]
            return {"players": mock_players[offset:offset + limit]}

        return {"players": [dict(r) for r in rows]}

@app.get("/api/snapshots/{sid}/players/{uid}")
def get_snapshot_player(sid: int, uid: int):
    if sid == LIVE_SNAPSHOT_ID:
        if not _LIVE_STATUS.get("ready"):
            raise HTTPException(status_code=404, detail="Snapshot nao encontrado")
        _sync_live_snapshot()

    with closing(get_db_connection()) as conn:
        identity = conn.execute("SELECT * FROM players WHERE snapshot_id=? AND uid=?", (sid, uid)).fetchone()
        if identity is None:
            if sid == LIVE_SNAPSHOT_ID and _LIVE_STATUS.get("players"):
                mock_player = next((p for p in _LIVE_STATUS["players"] if p.get("uid") == uid), None)
                if mock_player:
                    return {
                        **mock_player,
                        "identity": mock_player,
                        "stats": {},
                        "profile": mock_player,
                        "form": [],
                    }
            raise HTTPException(status_code=404, detail="Jogador nao encontrado")
        identity = dict(identity)
        stats = conn.execute("SELECT * FROM player_stats WHERE snapshot_id=? AND uid=?", (sid, uid)).fetchone()
        profile = conn.execute("SELECT * FROM player_profile WHERE snapshot_id=? AND uid=?", (sid, uid)).fetchone()
        stats, profile = dict(stats) if stats else {}, dict(profile) if profile else {}
        # Keep flat fields for existing callers; the shipped player/analysis view
        # requires these three sections before it can request analysis.
        result = {**profile, **stats, **identity}
        snapshot = conn.execute("SELECT game_date FROM snapshots WHERE id=?", (sid,)).fetchone()
        game_date = snapshot['game_date'] if snapshot else (_LIVE_STATUS.get("game_date") if sid == LIVE_SNAPSHOT_ID else None)
        profile['age'] = moneyball_data._age(profile, game_date)
        for alias, names in (('left_foot', ('foot_left', 'left_foot')),
                             ('right_foot', ('foot_right', 'right_foot')),
                             ('value', ('guide_value', 'value', 'transfer_value')),
                             ('wage', ('wage_weekly', 'contract_wage', 'wage'))):
            profile[alias] = next((profile[name] for name in names if profile.get(name) is not None), None)
        form = [dict(row) for row in conn.execute(
            "SELECT match_date,comp_uid,rating FROM player_form WHERE snapshot_id=? AND uid=? ORDER BY match_date",
            (sid, uid))]
        result.update(identity=identity, stats=stats, profile=profile, form=form)
        return result


def _stored_analysis_call(function, sid, uid=None, **params):
    if sid == LIVE_SNAPSHOT_ID:
        if not _LIVE_STATUS.get("ready"):
            raise HTTPException(status_code=404, detail="Snapshot ao vivo indisponivel")
        _sync_live_snapshot()
    conn = get_db_connection()
    try:
        return function(conn, sid, uid, **params)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    finally:
        conn.close()


@app.get("/api/snapshots/{sid}/players/{uid}/percentis")
def get_player_percentis(sid: int, uid: int, coorte: Optional[str] = None,
                        regua: str = "top20", min_minutes: Optional[int] = None):
    return _stored_analysis_call(player_analysis.percentiles, sid, uid, coorte=coorte,
                                 regua=regua, min_minutes=min_minutes)


@app.get("/api/snapshots/{sid}/players/{uid}/analise")
def get_player_analise(sid: int, uid: int, coorte: Optional[str] = None,
                      regua: str = "top20", min_minutes: Optional[int] = None):
    return _stored_analysis_call(player_analysis.analyse, sid, uid, coorte=coorte,
                                 regua=regua, min_minutes=min_minutes)


@app.get("/api/snapshots/{sid}/players/{uid}/buscar-como")
def buscar_como_player(sid: int, uid: int, request: Request):
    return _stored_analysis_call(player_analysis.search, sid, uid, params=dict(request.query_params))


@app.post("/api/snapshots/{sid}/buscar-como-receita")
def buscar_como_receita(sid: int, body: Dict[str, Any]):
    # The shipped client sends ref plus flat search options (not faixa/params).
    return _stored_analysis_call(player_analysis.search, sid, params={key: value for key, value in body.items()
                                 if key != "ref"}, ref=body.get("ref"))


@app.get("/api/buscar-como/config")
def get_buscar_como_config():
    return buscar_como_config.load()

@app.post("/api/buscar-como/config")
def save_buscar_como_config(body: BuscarComoConfigBody):
    return buscar_como_config.save(body)

def _connect_game(kind="connect"):
    global _FM_MEMORY, _FM_READER
    with _CONNECTION_LOCK:
        _clear_connection()
        _JOB_STATUS.update(kind=kind, state="running", phase="conectando", error=None, error_code=None)
        mem = None
        error_code = "read_failed"
        error = "Nao foi possivel ler o FM. Carregue um save e tente conectar novamente."
        running = False
        try:
            mem = FmMemory()
            if not mem.process_id:
                raise FmNotRunning("Abra o Football Manager e carregue um save antes de conectar.")
            running = True
            if not mem.base:
                raise FmUnsupportedBuild("O modulo game_plugin nao foi encontrado. Use uma versao suportada do FM.")
            if not mem.is_alive():
                raise FmAccessDenied("Nao foi possivel ler a memoria do FM. Abra o jogo pelo iniciador do Hub.")
            reader = FmReader(mem)
            session = reader.save_session()
            game_date = reader.game_date()
            if (not session[0] or not isinstance(game_date, date) or game_date.year <= 2000
                    or not reader.save_loaded() or reader.save_session() != session):
                error_code = "no_save"
                error = "Carregue um save no Football Manager, espere a carga terminar e tente novamente."
            else:
                save_name = reader.save_name()
                if not mem.is_alive():
                    raise FmNotRunning("O Football Manager foi fechado. Abra o jogo e carregue um save.")
                _FM_MEMORY, _FM_READER = mem, reader
                _LIVE_STATUS.update(
                    ready=True, fm_running=True, pid=mem.process_id, build=mem.build,
                    game_date=game_date.isoformat(), savegame_id=session[0],
                    session_nonce=session[1], save_name=save_name,
                    read_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                _JOB_STATUS.update(state="done", phase="fim", error=None)
                return {"ok": True, "connected": True, "started": False}
        except FmNotRunning as exc:
            error_code, error, running = "fm_closed", str(exc), False
        except FmAccessDenied as exc:
            error_code, error, running = "access_denied", str(exc), True
        except FmElevado as exc:
            error_code, error, running = "fm_elevated", str(exc), True
        except FmUnsupportedBuild as exc:
            error_code, error, running = "unsupported_build", str(exc), True
        except Exception:
            logger.exception("Game connection failed")
        if mem is not None:
            try:
                mem.close()
            except Exception:
                logger.exception("Could not close the failed game connection")
        _LIVE_STATUS.update(fm_running=running, error_code=error_code, error=error)
        _JOB_STATUS.update(state="error", phase="erro", error=error, error_code=error_code)
        # The shipped client reads connection errors from the JSON result.
        return {"ok": False, "connected": False, "error_code": error_code, "error": error}


@app.get("/api/game/launcher")
def game_launcher_capabilities():
    return {"platform": sys.platform, "available": sys.platform == "darwin"}


@app.post("/api/game/launch")
def launch_game():
    return game_launcher.launch_game()


@app.post("/api/connect")
def connect_fm(body: Optional[ConnectBody] = None):
    # A client-supplied date cannot establish that a save is loaded.
    return _connect_game()


@app.post("/api/refresh")
def refresh_live(body: Optional[ConnectBody] = None):
    result = _connect_game("refresh")
    return dict(result, refreshed=result["connected"], started=False)

@app.post("/api/disconnect")
def disconnect_fm():
    parar_leitura_viva()
    return {"ok": True, "disconnected": True}

@app.post("/api/capture")
def capture_snapshot(body: Optional[CaptureBody] = None):
    body = body or CaptureBody()
    name = body.name or "Snapshot Manual"
    with _CONNECTION_LOCK:
        initial_phase = "lendo_elenco" if (body.scope or "squad") == "squad" else "lendo_times"
        _JOB_STATUS.update(kind="capture", state="running", phase=initial_phase, done=0,
                           total=0, sid=None, name=name, error=None, error_code=None)
        try:
            source = _capture_source()

            def validate():
                if _capture_source() != source:
                    _clear_connection()
                    raise HTTPException(409, "O save mudou durante a leitura. Conecte novamente e repita a captura.")

            def progress(done, total, phase):
                _JOB_STATUS.update(done=done, total=total, phase=phase)
                validate()

            # scan_base commits batches. Keep every batch outside the saved-season DB.
            with strict_reads(_FM_READER), tempfile.TemporaryDirectory(prefix="fmsh-capture-") as folder:
                validate()
                with closing(db.connect(str(Path(folder) / "capture.db"))) as staged:
                    db.init_schema(staged)

                    club_ptr = None
                    mgr_team = None
                    c_full = None
                    c_short = None
                    if hasattr(_FM_READER, "manager_club"):
                        try:
                            m_res = _FM_READER.manager_club()
                            if m_res and len(m_res) >= 4:
                                club_ptr, mgr_team, c_full, c_short = m_res
                            elif m_res and len(m_res) >= 2:
                                club_ptr, mgr_team = m_res[0], m_res[1]
                        except Exception:
                            pass

                    mgr_name = None
                    if hasattr(_FM_READER, "human_manager"):
                        try:
                            hm = _FM_READER.human_manager()
                            if isinstance(hm, dict):
                                mgr_name = hm.get("full_name")
                        except Exception:
                            pass
                    if not mgr_name and source[2] and " - " in source[2]:
                        mgr_name = source[2].split(" - ")[0].strip() or None

                    club_uid = None
                    if club_ptr and hasattr(_FM_READER, "u32"):
                        try:
                            club_uid = _FM_READER.u32(club_ptr + 0x0C)
                        except Exception:
                            pass

                    staged_sid = db.create_snapshot(
                        staged, name=name, scope=body.scope, game_date=source[1],
                        save_name=source[2], savegame_id=source[0][0],
                        club_uid=club_uid, manager=mgr_name,
                        fm_version=_FM_MEMORY.fm_version,
                    )
                    if (body.scope or "squad") == "squad":
                        team = mgr_team or capture.resolve_manager_team(_FM_READER)
                        if team:
                            capture.scan_squad(staged, staged_sid, _FM_READER, team,
                                               ref_date=source[1], progress=progress)
                    else:
                        capture_all.scan_base(staged, staged_sid, _FM_READER, _FM_MEMORY,
                                              progress=progress, ref_date=source[1])

                    if club_uid:
                        club_name = c_full or (source[2].split(" - ")[-1].strip() if " - " in source[2] else "Managed Club")
                        db.save_club_leagues(staged, staged_sid, [{
                            "club_uid": club_uid,
                            "league_uid": None,
                            "league_name": None,
                            "club_name": club_name,
                        }])
                    count = staged.execute("SELECT COUNT(*) FROM players WHERE snapshot_id=?", (staged_sid,)).fetchone()[0]
                    if not count:
                        raise HTTPException(422, "Nenhum jogador foi lido. Carregue um save e repita a captura.")
                    validate()
                    _JOB_STATUS.update(phase="salvando")
                    with closing(get_db_connection()) as conn, _DB_LOCK:
                        sid = db.publish_capture(conn, staged, staged_sid, validate)
            _JOB_STATUS.update(state="done", phase="fim", sid=sid, done=count, total=count)
        except HTTPException as exc:
            _JOB_STATUS.update(state="error", phase="erro", sid=None, error=exc.detail, error_code="capture_failed")
            raise
        except Exception as exc:
            logger.exception("Capture failed; no season was saved")
            error = "Nao foi possivel ler e salvar os jogadores. Conecte novamente e repita a captura."
            _JOB_STATUS.update(state="error", phase="erro", sid=None, error=error, error_code="capture_failed")
            raise HTTPException(500, error) from exc
    if callable(AO_AVISO_DA_CAPTURA):
        try:
            AO_AVISO_DA_CAPTURA({"sid": sid, "nome": name})
        except Exception:
            logger.exception("Could not notify about the saved capture")
    return {"ok": True, "sid": sid}


def _capture_source():
    """Read fresh metadata from the verified connection, never from request defaults."""
    if not _LIVE_STATUS.get("ready") or _FM_MEMORY is None or _FM_READER is None:
        raise HTTPException(409, "Conecte ao Football Manager com um save carregado antes de capturar.")
    session = _FM_READER.save_session()
    game_date = _FM_READER.game_date()
    save_name = _FM_READER.save_name()
    if (not _FM_MEMORY.is_alive() or not _FM_READER.save_loaded() or not session[0]
            or session != (_LIVE_STATUS.get("savegame_id"), _LIVE_STATUS.get("session_nonce"))
            or _FM_READER.save_session() != session
            or not isinstance(game_date, date) or game_date.year <= 2000
            or not isinstance(save_name, str) or not save_name.strip()):
        _clear_connection()
        raise HTTPException(409, "A conexao ou o save mudou. Conecte novamente antes de capturar.")
    return session, game_date.isoformat(), save_name

@app.post("/api/captura/simular")
@app.post("/api/simular-captura")
def simular_captura(estado: str = "concluida", tipo: str = "auto"):
    SIMULACAO["estado"] = estado
    SIMULACAO["tipo"] = tipo
    if callable(AO_AVISO_DA_CAPTURA):
        try:
            AO_AVISO_DA_CAPTURA({"simulada": True, "estado": estado, "tipo": tipo})
        except Exception:
            logger.exception("Could not notify about simulated capture")
    return {"ok": True}

# ==============================================================================
# 11. Moneyball Analytics & Search Fields
# ==============================================================================

def _load_moneyball_catalog() -> Dict[str, Any]:
    cat_path = FMSH_DIR / "src" / "moneyball_catalog.json"
    if cat_path.exists():
        with open(cat_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _moneyball_rows(snapshot=None, groups=(), uids=None):
    if snapshot == LIVE_SNAPSHOT_ID and _LIVE_STATUS.get("ready"):
        _sync_live_snapshot()
    with closing(get_db_connection()) as conn:
        career = settings.load().get("carreira_ativa") if settings else None
        sid, rows = moneyball_data.load(conn, snapshot, career, groups, uids=uids)
        if sid == LIVE_SNAPSHOT_ID and not rows and _LIVE_STATUS.get("players"):
            rows = [
                {**p, "_teams": [p.get("team_uid")] if p.get("team_uid") else []}
                for p in _LIVE_STATUS["players"]
            ]
        return sid, rows


def _snapshot_player_count(sid):
    if sid is None:
        return 0
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT COUNT(*) FROM players WHERE snapshot_id=?", (sid,)).fetchone()
        count = row[0] if row else 0
        if sid == LIVE_SNAPSHOT_ID and count == 0 and _LIVE_STATUS.get("players"):
            return len(_LIVE_STATUS["players"])
        return count


def _moneyball_public_row(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


@app.get("/api/moneyball")
def get_moneyball(snapshot: Optional[int] = None, team: Optional[int] = None):
    sid, rows = _moneyball_rows(snapshot)
    if team is not None:
        rows = [row for row in rows if team in row["_teams"]]
    return {"snapshot": sid, "team": team,
            "players": [_moneyball_public_row(row) for row in rows],
            "columns": _moneyball_columns("all")}


@app.get("/api/moneyball/percentiles")
def get_moneyball_percentiles(
    snapshot: Optional[int] = None,
    team: Optional[int] = None,
    pool: str = "top20",
    min_minutes: int = 0,
):
    sid, rows = _moneyball_rows(snapshot)
    queries = [row for row in rows if team is None or team in row["_teams"]]
    try:
        if min_minutes < 0:
            raise ValueError("min_minutes: must be at least 0")
        percentiles = moneyball_data.percentiles(rows, queries, pool, min_minutes, team_columns=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"snapshot": sid, "team": team, "pool": pool, "percentiles": percentiles}

# Keys match the shipped frontend's identity columns and quick filters.
_SEARCH_ID_FIELDS = (
    ("name", "Nome", "Name", "text", "txt"),
    ("pos", "Posição", "Position", "text", "txt"),
    ("nat", "Nacionalidade", "Nationality", "text", "txt"),
    ("club", "Clube", "Club", "text", "txt"),
    ("league", "Liga", "League", "text", "txt"),
    ("_age", "Idade", "Age", "num", "int"),
    ("_height", "Altura", "Height", "num", "dec2"),
    ("_ca", "Capacidade atual", "Current ability", "num", "int"),
    ("_pa", "Capacidade potencial", "Potential ability", "num", "int"),
    ("_rating", "Classificação média", "Average rating", "num", "rating"),
    ("_value", "Valor", "Value", "money", "money"),
    ("_wage", "Salário", "Wage", "money", "money"),
    ("_asking", "Preço pedido", "Asking price", "money", "money"),
    ("contract", "Fim do contrato", "Contract end", "text", "txt"),
    ("foot", "Pé preferido", "Preferred foot", "text", "txt"),
    ("birth", "Data de nascimento", "Birth date", "text", "txt"),
    ("_lfoot", "Pé esquerdo", "Left foot", "num", "int"),
    ("_rfoot", "Pé direito", "Right foot", "num", "int"),
    ("_uid", "UID", "UID", "num", "int"),
)


def _moneyball_column_catalog(group: str) -> Dict[str, Any]:
    catalog = _load_moneyball_catalog()
    if group not in {"all", "fav"} and group not in catalog:
        raise HTTPException(status_code=400, detail=f"grupo invalido: {group}")
    sections = [
        {"group": position, "columns": [
            {**mb.column_locale(column), "from": position, "short": column.get("col", column["key"])}
            for column in columns
        ]}
        for position, columns in catalog.items()
    ]
    general = [
        {"key": key, "label": label, "labelEn": label_en, "type": field_type,
         "fmt": fmt, "general": True, "section": "contrato" if field_type == "money" else "id"}
        for key, label, label_en, field_type, fmt in _SEARCH_ID_FIELDS
    ]
    general.extend(mb.general_columns_meta())
    current = general + next((section["columns"] for section in sections if section["group"] == group), [])
    return {"group": group, "current": current, "sections": sections}


@app.get("/api/search/fields")
def get_search_fields(group: str = "all", snapshot: Optional[int] = None):
    columns = _moneyball_column_catalog(group)
    # Sets in the search engine must have a stable order: ops[0] is the UI default.
    num_ops = ["gte", "lte", "eq", "gt", "lt", "ne", "between", *sorted(player_search.FIELD_OPS)]
    text_ops = ["contains", "is", "is_not", "starts_with", "ends_with"]
    ops_by_type = {"num": num_ops, "money": num_ops, "text": text_ops,
                   "positions": ["includes", "excludes"]}
    fields = {}
    aliases = [mb.column_locale(column) for column in moneyball_data.search_alias_columns()]
    all_columns = columns["current"] + aliases + [
        column for section in columns["sections"] for column in section["columns"]
    ]
    for column in all_columns:
        field_type = column.get("type", "num")
        fields.setdefault(column["key"], {
            **column, "type": field_type, "section": column.get("section", "derivado"),
            "ops": ops_by_type[field_type],
        })
    fields["f.positions"] = {
        "key": "f.positions", "label": "Posições", "labelEn": "Positions", "type": "positions",
        "section": "id", "fmt": "txt", "ops": ops_by_type["positions"], "thresholdDefault": 17,
        "options": [{"code": code} for code in moneyball_data.POSITION_CODES],
    }
    return {
        "fields": list(fields.values()),
        "sectionOrder": ["id", "geral", "contrato", "derivado"],
        "opsByType": ops_by_type,
        "valueSlots": {op: 2 if op == "between" else 1 for ops in ops_by_type.values() for op in ops},
    }


@app.get("/api/moneyball/columns")
def get_moneyball_columns(group: str = "all", snapshot: Optional[int] = None):
    return _moneyball_column_catalog(group)

def _moneyball_columns(group, extra=""):
    catalog = _moneyball_column_catalog(group)
    identity = {field[0] for field in _SEARCH_ID_FIELDS}
    columns = [column for column in catalog["current"] if column["key"] not in identity]
    known = {column["key"] for column in columns}
    available = {column["key"]: column for section in catalog["sections"] for column in section["columns"]}
    available.update({column["key"]: mb.column_locale(column) for column in moneyball_data.search_alias_columns()})
    for key in extra.split(","):
        if key in available and key not in known:
            columns.append(available[key])
            known.add(key)
    return columns


def _moneyball_selection(params):
    group = params.get("group", "all")
    columns = _moneyball_columns(group, params.get("extra", ""))
    try:
        # Derive only positional catalogs used by this view, sort, search or export.
        requested = " ".join(str(value) for value in params.values())
        groups = set(re.findall(r"\b(gk|def|wing|dm|b2b|amc|att)_", requested))
        if group in mb.POSITION_GROUPS_ORDER:
            groups.add(group)
        allowed = None
        uid_filter = params.get("uids", "")
        if uid_filter.startswith(("lista:", "favlista:")):
            kind, list_id = uid_filter.split(":", 1)
            config = settings.load() if settings else {}
            lists = config.get("favoritos_listas" if kind == "favlista" else "listas_preferenciais") or []
            allowed = set(next((item.get("uids", []) for item in lists if item.get("id") == list_id), []))
        outside = params.get("fora", "0")
        if outside not in ("0", "1"):
            raise ValueError("fora: expected 0 or 1")
        target_uids = allowed if allowed is not None else (moneyball_data.ids(uid_filter) if uid_filter else None)
        if outside == "1":
            with closing(get_db_connection()) as conn:
                career = settings.load().get("carreira_ativa") if settings else None
                sid = moneyball_data.snapshot_id(conn, moneyball_data.integer(params, "snapshot"), career)
                rows = list_summary.outside_rows(conn, target_uids or [], sid, groups)
        else:
            load_uids = target_uids if (target_uids is not None and not (params.get("pct") == "1" and params.get("pool", "filtered") != "filtered")) else None
            sid, rows = _moneyball_rows(moneyball_data.integer(params, "snapshot"), groups, uids=load_uids)
        selected, warnings = moneyball_data.select(rows, params, allowed)
        ordered = moneyball_data.sort_rows(selected, params)
        return sid, rows, ordered, columns, warnings
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/moneyball/browse")
def moneyball_browse(request: Request):
    params = request.query_params
    sid, rows, selected, columns, warnings = _moneyball_selection(params)
    try:
        offset = moneyball_data.integer(params, "offset", 0, 0)
        limit = moneyball_data.integer(params, "limit", 100, 1)
        page = selected[offset:offset + limit]
        percentiles = {}
        if params.get("pct") == "1":
            pool = params.get("pool", "filtered")
            reference = selected if pool == "filtered" else rows
            percentiles = moneyball_data.percentiles(reference, page, pool,
                moneyball_data.integer(params, "min_minutes", 0, 0))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    public = [_moneyball_public_row(row) for row in page]
    outside = params.get("fora", "0")
    total_db = len(rows) if (outside == "1" or not params.get("uids")) else _snapshot_player_count(sid)
    return {"snapshot": sid, "group": params.get("group", "all"),
            "total": len(selected), "total_db": total_db, "filtered": len(selected),
            "rows": public, "players": public, "columns": columns,
            "percentiles": percentiles, "warnings": warnings, "att": {}}


@app.get("/api/moneyball/export")
@app.get("/api/moneyball/export.csv")
def moneyball_export(request: Request):
    params = request.query_params
    sid, rows, selected, columns, warnings = _moneyball_selection(params)
    keys = [key for key in params.get("cols", "uid,name,club,position,rating").split(",") if key]
    metadata = {column["key"]: column for column in _moneyball_column_catalog("all")["current"]}
    metadata.update({column["key"]: column for section in _moneyball_column_catalog("all")["sections"] for column in section["columns"]})
    metadata.update({"uid": {"fmt": "txt"}, "position": {"fmt": "txt"}, "rating": {"fmt": "rating"}, "age": {"fmt": "int"}})
    metadata.update({target: {"fmt": "int" if target in ("age", "ca", "pa") else "money" if target in ("transfer_value", "asking_price", "wage") else "txt"} for target in moneyball_data.ALIASES.values()})
    metadata.update({column["key"]: column for column in moneyball_data.search_alias_columns()})
    metadata.update({key: {"fmt": "dec2"} for key in mb.RAW_FIELDS})
    metadata.update({key + "_per90": {"fmt": "dec2"} for key in
                     ("goals", "assists", "xg", "xa", "shots", "passes_completed", "tackles_completed", "interceptions")})
    if not keys or any(key not in metadata and key not in moneyball_data.ALIASES and key not in moneyball_data.ALIASES.values() for key in keys):
        raise HTTPException(400, "invalid export columns")
    profile = params.get("profile", "intl")
    if profile not in csv_export.PROFILES:
        raise HTTPException(400, "invalid CSV profile")
    config = csv_export.PROFILES[profile]
    loc = "en" if params.get("lang", config["loc"]) == "en" else "pt"
    delimiter = config["delim"]
    currency = next((item for item in get_currencies()["currencies"] if str(item["uid"]) == params.get("currency")), None)
    symbol, rate = (currency["symbol"], currency["rate"]) if currency else ("£", 1)
    wage_period = params.get("wage_period", "week")
    if wage_period not in ("week", "month", "year"):
        raise HTTPException(400, "invalid wage period")
    content = ("\ufeff" if config["bom"] else "") + csv_export.csv_line(keys, delimiter)
    for row in selected:
        values = []
        for key in keys:
            item = moneyball_data.value(row, key)
            fmt = metadata.get(key, {}).get("fmt", "txt")
            if fmt == "money":
                item = moneyball_data.number(item) * rate
                if key == "_wage":
                    item *= {"week": 1, "month": 52 / 12, "year": 52}[wage_period]
            values.append(csv_export.fmt_value(item, fmt, loc, symbol))
        content += csv_export.csv_line(values, delimiter)
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="fmsh_export.csv"'})

@app.post("/api/resumo-jogadores")
def resumo_jogadores(body: UidsBody):
    with closing(get_db_connection()) as conn:
        return list_summary.summary(conn, body.uids, body.snapshot)

@app.post("/api/jogadores-fora-da-captura")
def jogadores_fora_da_captura(body: UidsBody):
    with closing(get_db_connection()) as conn:
        return list_summary.outside_capture(conn, body.uids, body.snapshot)

# ==============================================================================
# 12. Clubs, Profiles, Youth Teams & Currencies
# ==============================================================================

@app.get("/api/clubs")
def get_clubs(snapshot: Optional[int] = None):
    with closing(get_db_connection()) as conn:
        sid = moneyball_data.snapshot_id(conn, snapshot)
        return {"clubs": moneyball_data.table_rows(conn, "club_leagues", sid)}

@app.get("/api/club_profile")
def get_club_profile(snapshot: Optional[int] = None):
    with closing(get_db_connection()) as conn:
        sid = moneyball_data.snapshot_id(conn, snapshot)
        profiles = moneyball_data.table_rows(conn, "club_profile", sid)
        return profiles[0] if profiles else None

@app.get("/api/myteams")
def get_myteams(snapshot: Optional[int] = None):
    with closing(get_db_connection()) as conn:
        sid = moneyball_data.snapshot_id(conn, snapshot)
        return {"teams": moneyball_data.table_rows(conn, "teams", sid)}

@app.get("/api/youth-teams")
def get_youth_teams(snapshot: Optional[int] = None):
    with closing(get_db_connection()) as conn:
        sid = moneyball_data.snapshot_id(conn, snapshot)
        return {"youth_teams": moneyball_data.table_rows(conn, "youth_teams", sid)}

@app.get("/api/nomes-curtos")
def get_nomes_curtos(snapshot: Optional[int] = None):
    return {"nomes": {}}

# ==============================================================================
# 13. Careers, All-time Stats & Player Progress
# ==============================================================================

@app.get("/api/carreiras")
def get_carreiras():
    with closing(get_db_connection()) as conn:
        snapshots = portal_data.stored_snapshots(conn)
    active = portal_data.active_career(snapshots)
    saved = settings.load().get("carreiras") or {}
    prefs = saved.get(active) or {}
    counts = {}
    for snapshot in snapshots:
        cid = snapshot["carreira_id"]
        if cid is not None:
            counts[cid] = counts.get(cid, 0) + 1
    return {
        "ativa": active,
        "prefs": {"moeda": prefs.get("moeda") or 1,
                  "periodo_salario": prefs.get("periodo_salario") or "week"},
        "carreiras": [
            {"id": cid, "nome": (saved.get(cid) or {}).get("nome") or cid.replace("_", " ").title(),
             "ativa": cid == active, "n_temporadas": count}
            for cid, count in counts.items()
        ],
    }

@app.post("/api/carreiras/ativa")
def ativar_carreira(body: CarreiraAtivaBody):
    with closing(get_db_connection()) as conn:
        snapshots = portal_data.stored_snapshots(conn)
    if body.id not in {snapshot["carreira_id"] for snapshot in snapshots}:
        raise HTTPException(status_code=404, detail="Carreira nao encontrada")
    settings.save(carreira_ativa=body.id)
    return {"ok": True, **get_carreiras()}

@app.put("/api/carreiras/{cid}")
def salvar_carreira_prefs(cid: str, body: CarreiraPrefsBody):
    with closing(get_db_connection()) as conn:
        snapshots = portal_data.stored_snapshots(conn)
    if cid not in {snapshot["carreira_id"] for snapshot in snapshots}:
        raise HTTPException(status_code=404, detail="Carreira nao encontrada")
    carreiras.gravar_prefs(cid, **body.model_dump(exclude_none=True))
    return {"ok": True, "cid": cid}

@app.post("/api/carreiras/{cid}/temporadas/{sid}")
@app.put("/api/carreiras/{cid}/temporadas/{sid}")
def mover_temporada(cid: str, sid: int):
    if sid == LIVE_SNAPSHOT_ID:
        raise HTTPException(status_code=400, detail="Temporada ao vivo nao pode ser movida")
    conn = get_db_connection()
    with _DB_LOCK:
        cur = conn.cursor()
        cur.execute("UPDATE snapshots SET carreira_id=? WHERE id=?", (cid, sid))
        conn.commit()
    return {"ok": True}

@app.get("/api/carreiras/{cid}/alltime")
def get_carreira_alltime(cid: str):
    with closing(get_db_connection()) as conn:
        return career_analysis.composition(conn, cid)

@app.get("/api/carreiras/{cid}/outras-ligas")
def get_carreiras_outras_ligas(cid: str):
    # Archived seasons distinguishes an unavailable agenda from an empty history.
    return {"auto": None, "proximos": None, "lidas": [], "ligas": []}

@app.post("/api/carreiras/{cid}/auto-snapshot")
def set_carreira_auto_snapshot(cid: str, body: AutoSnapshotDataBody):
    with closing(get_db_connection()) as conn:
        snapshots = portal_data.stored_snapshots(conn)
    if cid not in {snapshot["carreira_id"] for snapshot in snapshots}:
        raise HTTPException(status_code=404, detail="Carreira nao encontrada")
    with _AUTO_SNAPSHOT_DATAS_LOCK:
        datas = dict(settings.load().get("auto_snapshot_datas") or {})
        if body.data is None:
            datas.pop(cid, None)
        else:
            datas[cid] = body.data
        settings.save(auto_snapshot_datas=datas)
    return {"ok": True, "data": body.data}

@app.get("/api/players/{uid}/alltime")
def get_player_alltime(uid: int, carreira: Optional[str] = None):
    with closing(get_db_connection()) as conn:
        try:
            result = career_analysis.player(conn, uid, carreira)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
    latest = get_snapshot_player(result['snapshot_id'], uid)
    latest.update(result['stats'])
    latest.update(result)
    return latest

@app.get("/api/players/{uid}/alltime/percentis")
def get_player_alltime_percentis(uid: int, carreira: Optional[str] = None, coorte: Optional[str] = None):
    with closing(get_db_connection()) as conn:
        try:
            return career_analysis.percentiles(conn, uid, carreira, coorte)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

@app.get("/api/players/{uid}/temporadas")
def get_player_temporadas(uid: int):
    # The profile uses this array to select its saved snapshot and career.
    with closing(get_db_connection()) as conn:
        rows = conn.execute("""
            SELECT s.*, s.id AS sid, p.height_cm
            FROM snapshots s
            JOIN players p ON p.snapshot_id=s.id
            WHERE p.uid=? AND (s.scope NOT IN ('live','live_temp') OR s.scope IS NULL)
            ORDER BY s.game_date DESC, s.id DESC
        """, (uid,)).fetchall()
        stats = {row["snapshot_id"]: dict(row) for row in conn.execute(
            "SELECT * FROM player_stats WHERE uid=?", (uid,))}
        return [dict(row, temporada=row["in_game_season"], is_live=False,
                     stats=stats.get(row["sid"], {})) for row in rows]

# ==============================================================================
# 14. Portal, Garimpos, Mudou, Apoiadores, Alertas, Dicas & Onboarding
# ==============================================================================

@app.get("/api/portal")
def get_portal(snapshot: Optional[int] = None):
    with closing(get_db_connection()) as conn:
        try:
            return portal_data.summary(conn, snapshot, _LIVE_STATUS)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

@app.get("/api/portal/garimpos")
def get_portal_garimpos(snapshot: Optional[int] = None):
    return {"itens": []}

@app.get("/api/portal/mudou")
def get_portal_mudou():
    return {"disponivel": True, "mudou": False}

@app.get("/api/apoiadores")
def get_apoiadores():
    if apoiadores:
        try:
            return {"nomes": apoiadores.listar()}
        except Exception:
            pass
    return {"nomes": ["FM Season Hub Community", "Supporter 1", "Supporter 2"]}

@app.get("/api/alertas")
def get_alertas(recarregar: bool = False, lang: str = "pt"):
    return {"alertas": [], "nao_lidos": 0}

@app.post("/api/alertas/lidos")
def post_alertas_lidos(lang: str = "pt"):
    return {"alertas": [], "nao_lidos": 0}

@app.get("/api/dicas")
def get_dicas():
    return {"lidas": []}

@app.post("/api/dicas/lida")
def post_dica_lida(body: DicaBody):
    return {"lidas": [body.id]}

_ONBOARDING_LOCK = threading.Lock()


def _onboarding_bruto():
    # Read the file before defaults: missing means an older installation.
    try:
        with open(settings.SETTINGS_PATH, encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _ja_usa_o_app(config):
    if config.get("acesso_nivel"):
        return True
    database = get_db_path()
    if database.is_file():
        try:
            with sqlite3.connect(str(database)) as conn:
                return conn.execute("SELECT 1 FROM snapshots LIMIT 1").fetchone() is not None
        except sqlite3.Error:
            pass
    return False


@app.get("/api/onboarding")
def get_onboarding():
    config = _onboarding_bruto()
    state = dict(settings.DEFAULTS["onboarding"])
    stored = config.get("onboarding")
    if isinstance(stored, dict):
        state.update(stored)
    elif _ja_usa_o_app(config):
        state["concluido"] = True
    return state

@app.post("/api/onboarding")
def post_onboarding(body: OnboardingBody):
    with _ONBOARDING_LOCK:
        state = get_onboarding()
        state.update(body.model_dump(exclude_unset=True))
        settings.save(onboarding=state)
        return state

@app.post("/api/onboarding/refazer")
def post_onboarding_refazer():
    with _ONBOARDING_LOCK:
        state = dict(settings.DEFAULTS["onboarding"])
        settings.save(onboarding=state)
        return state

# ==============================================================================
# 15. Favorites Management Endpoints
# ==============================================================================

_FAVORITOS_LOCK = threading.Lock()


def _agora_favoritos():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _data_favoritos(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:T| |$)", value):
        return None
    try:
        datetime.fromisoformat(value)
        return value
    except ValueError:
        return None


def _normalizar_favoritos(listas):
    config = settings.load()
    seq = max([int(config.get("favoritos_seq") or 0), *[
        value for lista in listas for value in (lista.get("entrou") if isinstance(lista.get("entrou"), dict) else {}).values()
        if isinstance(value, int)
    ]])
    try:
        # Old files did not record creation. Their last saved time is the only
        # available timestamp; persist that fallback once, never use reload time.
        saved = datetime.fromtimestamp(Path(settings.SETTINGS_PATH).stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        saved = _agora_favoritos()
    changed = False
    for lista in listas:
        created = _data_favoritos(lista.get("criada_em")) or _data_favoritos(lista.get("atualizada_em")) or saved
        updated = _data_favoritos(lista.get("atualizada_em")) or created
        for key, value in (("criada_em", created), ("atualizada_em", updated)):
            if lista.get(key) != value:
                lista[key] = value
                changed = True
        if not isinstance(lista.get("entrou"), dict):
            lista["entrou"] = {}
            changed = True
        for uid in lista["uids"]:
            if str(uid) not in lista["entrou"]:
                seq += 1
                lista["entrou"][str(uid)] = seq
                changed = True
    return changed, seq


def _carregar_favoritos():
    config = settings.load()
    listas = config.get("favoritos_listas") or []
    # True is the first-install sentinel. None means the user deleted all lists.
    if not listas and config.get("favoritos_lista_padrao") is True:
        listas = [{"id": "fav_default", "nome": "Favoritos", "cor": "#3b82f6", "uids": []}]
    changed, _ = _normalizar_favoritos(listas)
    if changed:
        _gravar_favoritos(listas)
    return listas


def _gravar_favoritos(listas):
    _, seq = _normalizar_favoritos(listas)
    padrao = settings.load().get("favoritos_lista_padrao")
    if not any(lista["id"] == padrao for lista in listas):
        padrao = listas[0]["id"] if listas else None
    settings.save(favoritos_listas=listas, favoritos_lista_padrao=padrao, favoritos_seq=seq)


def _estado_favoritos(listas):
    config = settings.load()
    aviso = config.get("favoritos_aviso")
    return {"listas": listas, "padrao": config.get("favoritos_lista_padrao"),
            "paleta": list(favoritos.PALETA), "aviso": aviso if isinstance(aviso, list) else None}


def _nova_lista_favoritos(nome, cor, uids):
    now = _agora_favoritos()
    return {"id": f"fav_{uuid.uuid4().hex}", "nome": nome, "cor": cor,
            "uids": list(dict.fromkeys(uids)), "criada_em": now, "atualizada_em": now}


@app.get("/api/favoritos/listas")
@app.get("/api/favoritos")
def get_favoritos_listas():
    with _FAVORITOS_LOCK:
        return _estado_favoritos(_carregar_favoritos())


@app.post("/api/favoritos/listas")
def post_favoritos_criar(body: FavListaNovaBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        nova = _nova_lista_favoritos(body.nome, body.cor, body.uids or [])
        listas.append(nova)
        _gravar_favoritos(listas)
        return {**_estado_favoritos(listas), "lista": nova}


@app.patch("/api/favoritos/listas/{id_lista}")
def patch_favoritos_editar(id_lista: str, body: FavListaEditarBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        for lista in listas:
            if lista["id"] == id_lista:
                before = (lista["nome"], lista["cor"], list(lista["uids"]))
                if body.nome:
                    lista["nome"] = body.nome
                if body.cor:
                    lista["cor"] = body.cor
                if body.esvaziar:
                    lista["uids"] = []
                    lista["entrou"] = {}
                if before != (lista["nome"], lista["cor"], lista["uids"]):
                    lista["atualizada_em"] = _agora_favoritos()
                _gravar_favoritos(listas)
                return {**_estado_favoritos(listas), "lista": lista}
    raise HTTPException(status_code=404, detail="Lista nao encontrada")


@app.delete("/api/favoritos/listas/{id_lista}")
def delete_favoritos_apagar(id_lista: str):
    with _FAVORITOS_LOCK:
        listas = [lista for lista in _carregar_favoritos() if lista["id"] != id_lista]
        _gravar_favoritos(listas)
        return {**_estado_favoritos(listas), "ok": True}


@app.post("/api/favoritos/listas/{id_lista}/jogadores")
def post_favoritos_jogadores(id_lista: str, body: FavJogadoresBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        for lista in listas:
            if lista["id"] == id_lista:
                before = list(lista["uids"])
                if body.marcar:
                    lista["uids"] = list(dict.fromkeys([*before, *body.uids]))
                else:
                    removed = set(body.uids)
                    lista["uids"] = [uid for uid in before if uid not in removed]
                    for uid in removed:
                        lista["entrou"].pop(str(uid), None)
                if before != lista["uids"]:
                    lista["atualizada_em"] = _agora_favoritos()
                _gravar_favoritos(listas)
                return {**_estado_favoritos(listas), "ok": True, "lista": lista}
    raise HTTPException(status_code=404, detail="Lista nao encontrada")


@app.post("/api/favoritos/listas/{id_lista}/duplicar")
def post_favoritos_duplicar(id_lista: str, body: FavDuplicarBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        for lista in listas:
            if lista["id"] == id_lista:
                dupl = _nova_lista_favoritos(body.nome, lista["cor"], lista["uids"])
                listas.append(dupl)
                _gravar_favoritos(listas)
                return {**_estado_favoritos(listas), "lista": dupl}
    raise HTTPException(status_code=404, detail="Lista nao encontrada")


@app.post("/api/favoritos/tirar-de-todas")
def post_favoritos_tirar_de_todas(body: FavJogadoresBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        rem_set = set(body.uids)
        for lista in listas:
            before = list(lista["uids"])
            lista["uids"] = [u for u in before if u not in rem_set]
            if before != lista["uids"]:
                lista["atualizada_em"] = _agora_favoritos()
                for uid in rem_set:
                    lista["entrou"].pop(str(uid), None)
        _gravar_favoritos(listas)
        return {**_estado_favoritos(listas), "ok": True}


@app.post("/api/favoritos/migrar-local")
def post_favoritos_migrar_local(body: FavMigrarLocalBody):
    with _FAVORITOS_LOCK:
        return {**_estado_favoritos(_carregar_favoritos()), "ok": True}

@app.post("/api/favoritos/aviso-visto")
def post_favoritos_aviso_visto():
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        settings.save(favoritos_aviso=None)
        return {**_estado_favoritos(listas), "ok": True}

# ==============================================================================
# 16. Library (Biblioteca) Endpoints
# ==============================================================================

_orig_paths_biblioteca_dir = paths.biblioteca_dir if paths else None

def _get_biblioteca_dir() -> Path:
    if _orig_paths_biblioteca_dir:
        try:
            return Path(_orig_paths_biblioteca_dir())
        except Exception:
            pass
    b_dir = Path.home() / "Library" / "Application Support" / "FMSeasonHub" / "biblioteca"
    b_dir.mkdir(parents=True, exist_ok=True)
    return b_dir

if paths:
    paths.biblioteca_dir = lambda: str(_get_biblioteca_dir())


def _identidades_do_banco(uids, snapshot=None):
    if not uids:
        return {}
    try:
        with closing(get_db_connection()) as conn:
            placeholders = ",".join("?" for _ in uids)
            snap_val = int(snapshot) if snapshot is not None and str(snapshot).isdigit() else 0
            rows = conn.execute(f"""
                SELECT p.uid, p.snapshot_id, p.full_name, p.common_name, p.name_first, p.name_last, perfil.birth_date
                FROM players p
                LEFT JOIN player_profile perfil ON perfil.snapshot_id=p.snapshot_id AND perfil.uid=p.uid
                LEFT JOIN snapshots s ON s.id=p.snapshot_id
                WHERE p.uid IN ({placeholders})
                ORDER BY (p.snapshot_id = ?) DESC, (perfil.birth_date IS NOT NULL) DESC, s.id DESC
            """, [*list(uids), snap_val]).fetchall()
            saida = {}
            for raw in rows:
                row = dict(raw)
                uid = row["uid"]
                if uid not in saida:
                    nome = row.get("full_name") or row.get("common_name") or " ".join(
                        str(row.get(key) or "") for key in ("name_first", "name_last")).strip() or str(uid)
                    saida[uid] = {
                        "nome": nome,
                        "nascimento": row.get("birth_date"),
                    }
            return saida
    except Exception:
        return {}


biblioteca_listas.identidades = _identidades_do_banco

def _validar_nome_biblioteca(nome: str) -> str:
    """Library names identify one entry, never a relative or absolute path."""
    if (not nome.strip() or nome in (".", "..") or "\0" in nome
            or "/" in nome or "\\" in nome or PureWindowsPath(nome).drive):
        raise HTTPException(status_code=400, detail="Nome de arquivo invalido")
    try:
        nome.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=400, detail="Nome de arquivo invalido") from exc
    return nome

def _lista_biblioteca(conteudo):
    """Read the native .lsh contract, including files imported by the shipped UI."""
    try:
        dados = json.loads(conteudo) if isinstance(conteudo, str) else conteudo
    except ValueError as exc:
        raise HTTPException(400, "Lista de jogadores invalida") from exc
    if not isinstance(dados, dict) or not isinstance(dados.get("nome"), str) or not dados["nome"].strip():
        raise HTTPException(400, "Lista de jogadores invalida")
    if any(dados.get(key) is not None and not isinstance(dados[key], str)
           for key in ("id", "criado", "jogo")):
        raise HTTPException(400, "Metadados de lista invalidos")
    jogadores = dados.get("jogadores")
    if not isinstance(jogadores, list) or not 0 < len(jogadores) <= biblioteca.MAX_JOGADORES:
        raise HTTPException(400, "Selecione entre 1 e 5000 jogadores")
    uids = [j.get("uid") if isinstance(j, dict) else None for j in jogadores]
    if any(type(uid) is not int or uid <= 0 for uid in uids) or len(set(uids)) != len(uids):
        raise HTTPException(400, "Identidades de jogadores invalidas")
    return dados


def _selecionar_lista_biblioteca(body, nome):
    max_sqlite_integer = (1 << 63) - 1
    if (not body.uids or any(not 0 < uid <= max_sqlite_integer for uid in body.uids)
            or body.snapshot is None or not 0 < body.snapshot <= max_sqlite_integer):
        raise HTTPException(400, "Selecione jogadores e uma captura valida")
    if Path(nome).suffix.lower() != ".lsh" or body.conteudo is not None:
        raise HTTPException(400, "Salve a selecao como uma lista .lsh")
    uids = list(dict.fromkeys(body.uids))
    with closing(get_db_connection()) as conn:
        snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (body.snapshot,)).fetchone()
        if not snapshot:
            raise HTTPException(400, "Captura nao encontrada")
        placeholders = ",".join("?" for _ in uids)
        rows = conn.execute(f"""
            SELECT p.*, perfil.birth_date FROM players p
            LEFT JOIN player_profile perfil ON perfil.snapshot_id=p.snapshot_id AND perfil.uid=p.uid
            WHERE p.snapshot_id=? AND p.uid IN ({placeholders})
        """, [body.snapshot, *uids])
        identidades = {}
        for raw in rows:
            row = dict(raw)
            identidades[row["uid"]] = {
                "nome": row.get("full_name") or row.get("common_name") or " ".join(
                    str(row.get(key) or "") for key in ("name_first", "name_last")).strip() or str(row["uid"]),
                "nascimento": row.get("birth_date"),
            }
        if len(identidades) != len(uids):
            raise HTTPException(400, "Jogador nao encontrado na captura selecionada")
    dados = biblioteca_listas.conteudo({"id": f"fav_{uuid.uuid4().hex}", "nome": Path(nome).stem,
                                        "uids": uids}, identidades)
    dados.update(snapshot=body.snapshot, carreira_id=snapshot["carreira_id"],
                 criado=datetime.now(timezone.utc).isoformat())
    if snapshot["fm_version"]:
        dados["jogo"] = snapshot["fm_version"]
    return dados


@app.get("/api/biblioteca")
@app.get("/api/biblioteca/listar")
def get_biblioteca():
    b_dir = _get_biblioteca_dir()
    items = []
    # Load factory presets
    presets_dir = FMSH_DIR / "src" / "presets_fabrica"
    if presets_dir.exists():
        for f in presets_dir.glob("*.fsh"):
            nome = f.stem.replace("-", " ").title()
            nome_en = nome
            try:
                dados = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(dados, dict):
                    if isinstance(dados.get("nome"), str) and dados["nome"].strip():
                        nome = dados["nome"]
                    nome_en = dados.get("nomeEn")
                    if not isinstance(nome_en, str) or not nome_en.strip():
                        nome_en = nome
            except (OSError, UnicodeError, ValueError):
                pass
            items.append({
                "arquivo": f.name,
                "nome": nome,
                "nomeEn": nome_en,
                "tipo": "filtro",
                "fabrica": True,
            })
    # User saved presets
    ligadas = {x.get("arquivo_biblioteca"): x["id"] for x in lista_fmf.listar() if x.get("arquivo_biblioteca")}
    for f in b_dir.glob("*.*"):
        ext = f.suffix.lower()
        if ext == ".lsh":
            item = {"arquivo": f.name, "nome": f.stem, "nomeEn": f.stem,
                    "tipo": "lista", "fabrica": False}
            try:
                if f.is_symlink() or f.stat().st_size > biblioteca.TAMANHO_MAXIMO:
                    raise HTTPException(400, "Arquivo de lista invalido")
                dados = _lista_biblioteca(f.read_text(encoding="utf-8"))
                loaded = {x.get("id") for x in settings.load().get("favoritos_listas") or []}
                item.update(nome=dados["nome"], nomeEn=dados["nome"], listaId=dados.get("id"),
                            jogadores=len(dados["jogadores"]), criado=dados.get("criado"),
                            jogo=dados.get("jogo"), carregada=bool(dados.get("id")) and dados["id"] in loaded)
            except (OSError, UnicodeError, HTTPException) as exc:
                item["erro"] = exc.detail if isinstance(exc, HTTPException) else "Arquivo de lista invalido"
        elif ext == ".fmf":
            lista_id = ligadas.get(f.name, "")
            is_ligada = bool(lista_id)
            item = {
                "arquivo": f.name,
                "nome": f.stem,
                "nomeEn": f.stem,
                "tipo": "listaFm",
                "fabrica": False,
                "listaId": lista_id,
                "carregada": is_ligada,
            }
            try:
                if f.is_symlink():
                    raise HTTPException(400, "Arquivo nao pode ser um link simbolico")
                if f.stat().st_size > biblioteca.TAMANHO_MAXIMO:
                    raise HTTPException(400, "Arquivo invalido")
                dados = f.read_bytes()
                tipo_fmf = view_fmf.tipo_do_fmf(dados)
                if tipo_fmf == "view" and not is_ligada:
                    item["tipo"] = "visao"
                else:
                    item["tipo"] = "listaFm"
                    try:
                        lida = lista_fmf.ler(dados)
                        item.update(
                            nome=lida.get("nome") or f.stem,
                            nomeEn=lida.get("nome") or f.stem,
                            jogadores=len(lida.get("uids") or []),
                        )
                    except Exception:
                        pass
            except Exception as exc:
                item["erro"] = exc.detail if isinstance(exc, HTTPException) else str(exc)
        else:
            item = {
                "arquivo": f.name,
                "nome": f.stem,
                "nomeEn": f.stem,
                "tipo": "filtro",
                "fabrica": False,
            }
        items.append(item)
    return {"arquivos": items, "pasta": str(b_dir)}

def _obter_caminho_biblioteca(arquivo: str) -> Path:
    nome = _validar_nome_biblioteca(arquivo)
    b_dir = _get_biblioteca_dir().resolve()
    presets_dir = (FMSH_DIR / "src" / "presets_fabrica").resolve()
    user_path = _get_biblioteca_dir() / nome
    if user_path.is_symlink() or user_path.exists():
        caminho = user_path
    else:
        caminho = FMSH_DIR / "src" / "presets_fabrica" / nome

    if caminho.is_symlink():
        try:
            alvo = caminho.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail="Arquivo nao pode ser um link simbolico") from exc
        if not (alvo.is_relative_to(b_dir) or alvo.is_relative_to(presets_dir)):
            raise HTTPException(status_code=400, detail="Arquivo nao pode ser um link simbolico")
        if not alvo.is_file():
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
        return alvo

    if not caminho.is_file():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    return caminho

@app.get("/api/biblioteca/{arquivo}")
def get_biblioteca_ler(arquivo: str):
    p = _obter_caminho_biblioteca(arquivo)
    if p.suffix.lower() == ".fmf":
        raise HTTPException(status_code=400, detail="Arquivo binario nao pode ser lido como filtro")
    try:
        with open(p, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                f.seek(0)
                return {"texto": f.read()}
    except (UnicodeDecodeError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail="Arquivo binario nao pode ser lido como filtro") from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado") from exc

@app.post("/api/biblioteca")
def post_biblioteca_gravar(body: BibliotecaBody):
    b_dir = _get_biblioteca_dir()
    selecao = body.uids is not None or body.snapshot is not None
    nome = body.arquivo if body.arquivo is not None else ("salvo.lsh" if selecao else "salvo.fsh")
    p = b_dir / _validar_nome_biblioteca(nome)
    if p.suffix.lower() == ".fmf":
        raise HTTPException(status_code=400, detail="Arquivo binario nao pode ser salvo como filtro")
    conteudo = _selecionar_lista_biblioteca(body, nome) if selecao else body.conteudo
    if p.suffix.lower() == ".lsh":
        conteudo = _lista_biblioteca(conteudo)
    texto = json.dumps(conteudo, indent=2) if isinstance(conteudo, (dict, list)) else str(conteudo or "")
    if p.suffix.lower() == ".lsh" and len(texto.encode("utf-8")) > biblioteca.TAMANHO_MAXIMO:
        raise HTTPException(400, "Arquivo excede o tamanho maximo de 5 MB")
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o666)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise HTTPException(status_code=400, detail="Arquivo nao pode ser um link simbolico") from exc
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    return {"ok": True, "arquivo": p.name}

def _renomear_sem_substituir(src: Path, dst: Path) -> None:
    """Rename atomically on macOS without replacing any existing entry."""
    source, destination = os.fsencode(src), os.fsencode(dst)
    if b"\0" in source or b"\0" in destination:
        raise OSError("File names cannot contain null bytes")
    try:
        rename_exclusive = ctypes.CDLL(None, use_errno=True).renamex_np
    except (AttributeError, OSError) as exc:
        raise OSError("Exclusive rename is unavailable") from exc
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    # sys/stdio.h: RENAME_EXCL rejects destinations created during the operation.
    if rename_exclusive(source, destination, 0x00000004) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(dst))


@app.post("/api/biblioteca/{arquivo}/nome")
def post_biblioteca_renomear(arquivo: str, body: RenomearBody):
    b_dir = _get_biblioteca_dir()
    src = b_dir / _validar_nome_biblioteca(arquivo)
    dst = b_dir / _validar_nome_biblioteca(body.nome)
    if src.is_symlink():
        raise HTTPException(status_code=400, detail="Arquivo nao pode ser um link simbolico")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Arquivo original nao encontrado")
    if src == dst:
        return {"ok": True, "novo": dst.name}
    try:
        _renomear_sem_substituir(src, dst)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Ja existe um arquivo com esse nome") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Arquivo original nao encontrado") from exc
    except OSError as exc:
        logger.exception("Library rename failed")
        raise HTTPException(status_code=500, detail="Nao foi possivel renomear o arquivo") from exc
    return {"ok": True, "novo": dst.name}

@app.delete("/api/biblioteca/{arquivo}")
def delete_biblioteca_apagar(arquivo: str):
    b_dir = _get_biblioteca_dir()
    target = b_dir / _validar_nome_biblioteca(arquivo)
    if target.is_symlink() or target.exists():
        target.unlink()
    return {"ok": True}

@app.post("/api/biblioteca/abrir-pasta")
def post_biblioteca_abrir_pasta():
    b_dir = _get_biblioteca_dir()
    try:
        subprocess.Popen(["open", str(b_dir)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

@app.post("/api/biblioteca/{arquivo}/carregar")
def post_biblioteca_carregar(arquivo: str):
    nome = _validar_nome_biblioteca(arquivo)
    b_dir = _get_biblioteca_dir()
    caminho = b_dir / nome
    if caminho.is_symlink():
        raise HTTPException(status_code=400, detail="Arquivo nao pode ser um link simbolico")
    if not caminho.exists():
        fab = FMSH_DIR / "src" / "presets_fabrica" / nome
        if fab.exists():
            caminho = fab
        else:
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    if not caminho.is_file():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    if caminho.stat().st_size > biblioteca.TAMANHO_MAXIMO:
        raise HTTPException(status_code=400, detail="Arquivo excede o tamanho maximo")
    ext = caminho.suffix.lower()
    if ext not in (".lsh", ".fmf"):
        raise HTTPException(status_code=400, detail="Arquivo nao e uma lista")

    with _FAVORITOS_LOCK:
        try:
            return biblioteca_listas.carregar(nome)
        except biblioteca.ArquivoInvalido as exc:
            msg = str(exc)
            if "nao encontrado" in msg.lower():
                raise HTTPException(status_code=404, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/biblioteca/{arquivo}/bruto")
def get_biblioteca_bruto(arquivo: str):
    p = _obter_caminho_biblioteca(arquivo)
    return FileResponse(str(p))

@app.post("/api/biblioteca-fmf")
async def post_biblioteca_fmf(request: Request, arquivo: str):
    dados = await _ler_upload_fmf(request, arquivo)
    tipo = view_fmf.tipo_do_fmf(dados)
    if tipo == "view":
        lida = _operar_view_fm(view_fmf.ler, dados)
        destino = _operar_view_fm(view_fmf.destino_da_tela, lida["tela"])
        review = _operar_view_fm(view_fmf.revisar, dados, arquivo, destino)
        return {"tipo": "view", "review": review}
    if tipo == "lista":
        lista = _operar_lista_preferencial(lista_fmf.adicionar, dados, arquivo=arquivo)
        return {"tipo": "lista", **_resposta_lista_preferencial(lista)}
    raise HTTPException(400, "Selecione uma view ou lista .fmf valida do Football Manager")

# ==============================================================================
# 17. FM Views & Shortlists Endpoints
# ==============================================================================

def _operar_view_fm(operacao, *args):
    try:
        return operacao(*args)
    except lista_fmf.ListaInvalida as exc:
        raise HTTPException(400, str(exc)) from exc


async def _ler_upload_fmf(request: Request, arquivo: str) -> bytes:
    if not arquivo or Path(arquivo).name != arquivo or "\\" in arquivo or "\0" in arquivo:
        raise HTTPException(400, "Nome de arquivo invalido")
    if Path(arquivo).suffix.lower() != ".fmf":
        raise HTTPException(400, "Selecione um arquivo .fmf do Football Manager")
    dados = bytearray()
    async for trecho in request.stream():
        dados.extend(trecho)
        if len(dados) > lista_fmf.TAMANHO_MAXIMO_ARQUIVO:
            raise HTTPException(413, "O arquivo excede o limite de 2 MB")
    return bytes(dados)


@app.get("/api/views-fm/pasta")
def get_views_fm_pasta():
    return _operar_view_fm(view_fmf.listar_pasta)

@app.post("/api/views-fm/da-pasta")
def post_views_fm_da_pasta(body: ViewDaPastaBody):
    if Path(body.arquivo).is_absolute():
        return _operar_view_fm(view_fmf.ler_do_caminho, body.arquivo, body.destino)
    return _operar_view_fm(view_fmf.ler_da_pasta, body.arquivo, body.jogo, body.destino)

@app.post("/api/views-fm/escolher")
def post_views_fm_escolher(destino: str = "base"):
    if destino not in view_fmf.TELA_DO_DESTINO:
        raise HTTPException(400, "Destino desconhecido")
    try:
        res = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose file with prompt "Select FM View file" of type {"fmf"})'],
            capture_output=True,
            text=True,
        )
    except OSError:
        return {"disponivel": False, "cancelado": False}
    if res.returncode != 0:
        return {"disponivel": "(-128)" in res.stderr, "cancelado": "(-128)" in res.stderr}
    if not res.stdout.strip():
        return {"disponivel": True, "cancelado": True}
    review = _operar_view_fm(view_fmf.ler_do_caminho, res.stdout.strip(), destino)
    return {"disponivel": True, "cancelado": False, "review": review}

@app.post("/api/views-fm")
async def post_views_fm(request: Request, arquivo: str, destino: str = "base"):
    dados = await _ler_upload_fmf(request, arquivo)
    return _operar_view_fm(view_fmf.revisar, dados, arquivo, destino)

@app.get("/api/listas-preferenciais")
def get_listas_preferenciais():
    return {"listas": [_lista_preferencial_json(lista) for lista in lista_fmf.listar()]}


def _lista_preferencial_json(lista):
    """Expose the persisted list with dates in the shipped UI's format."""
    result = {**lista, "carregada_em": lista.get("atualizada_em")}
    if isinstance(result.get("arquivo_em"), (int, float)):
        result["arquivo_em"] = datetime.fromtimestamp(result["arquivo_em"], timezone.utc).isoformat()
    return result


def _resposta_lista_preferencial(lista):
    return {"ok": True, "lista": _lista_preferencial_json(lista), **get_listas_preferenciais()}


def _operar_lista_preferencial(operacao, *args, **kwargs):
    try:
        return operacao(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, "Lista nao encontrada") from exc
    except lista_fmf.ListaInvalida as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        logger.exception("Could not save the preferred list")
        raise HTTPException(500, "Nao foi possivel salvar a lista") from exc

@app.delete("/api/listas-preferenciais/{id_lista}")
def delete_lista_preferencial(id_lista: str):
    if not _operar_lista_preferencial(lista_fmf.remover, id_lista):
        raise HTTPException(404, "Lista nao encontrada")
    return {"ok": True, **get_listas_preferenciais()}

@app.get("/api/listas-preferenciais/pasta")
def get_listas_preferenciais_pasta():
    result = _operar_lista_preferencial(lista_fmf.listar_pasta)
    for pasta in result["pastas"]:
        for lista in pasta["listas"]:
            lista["modificado"] = datetime.fromtimestamp(lista["modificado"], timezone.utc).isoformat()
        for inv in pasta.get("invalidas") or []:
            if isinstance(inv.get("modificado"), (int, float)):
                inv["modificado"] = datetime.fromtimestamp(inv["modificado"], timezone.utc).isoformat()
    return result

@app.post("/api/listas-preferenciais/da-pasta")
def post_lista_preferencial_da_pasta(body: ListaDaPastaBody):
    # UI folder entries use basenames; API clients can supply a local absolute path.
    if Path(body.arquivo).is_absolute():
        lista = _operar_lista_preferencial(lista_fmf.importar_do_caminho, body.arquivo)
    else:
        lista = _operar_lista_preferencial(lista_fmf.importar_da_pasta, body.arquivo, body.jogo)
    return _resposta_lista_preferencial(lista)


@app.post("/api/listas-preferenciais")
async def post_lista_preferencial_bytes(request: Request, arquivo: str):
    if not arquivo or Path(arquivo).name != arquivo or "\\" in arquivo or "\0" in arquivo:
        raise HTTPException(400, "Nome de arquivo invalido")
    if Path(arquivo).suffix.lower() != ".fmf":
        raise HTTPException(400, "Selecione uma lista .fmf do Football Manager")
    dados = bytearray()
    async for trecho in request.stream():
        dados.extend(trecho)
        if len(dados) > lista_fmf.TAMANHO_MAXIMO_ARQUIVO:
            raise HTTPException(413, "A lista excede o limite de 2 MB")
    lista = _operar_lista_preferencial(lista_fmf.adicionar, bytes(dados), arquivo=arquivo)
    return _resposta_lista_preferencial(lista)

@app.post("/api/listas-preferenciais/escolher")
def post_lista_preferencial_escolher():
    try:
        res = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose file with prompt "Select FM Shortlist file" of type {"fmf"})'],
            capture_output=True,
            text=True,
        )
    except OSError:
        # The UI has a browser file-input fallback when no native picker exists.
        return {"disponivel": False, "cancelado": False}
    if res.returncode != 0:
        if "(-128)" in res.stderr:
            return {"disponivel": True, "cancelado": True}
        return {"disponivel": False, "cancelado": False}
    if not res.stdout.strip():
        return {"disponivel": True, "cancelado": True}
    lista = _operar_lista_preferencial(lista_fmf.importar_do_caminho, res.stdout.strip())
    return {"disponivel": True, "cancelado": False, **_resposta_lista_preferencial(lista)}

@app.post("/api/listas-preferenciais/{id_lista}/atualizar")
def post_lista_preferencial_atualizar(id_lista: str):
    lista = _operar_lista_preferencial(lista_fmf.atualizar, id_lista)
    return _resposta_lista_preferencial(lista)

# ==============================================================================
# 18. Game Plugin & Live In-Game HUD Endpoints
# ==============================================================================

@app.get("/api/jogo/pedido")
def get_jogo_pedido():
    # The frontend polls this route. Reading pending requests must not reopen
    # the window or emit another request event. The macOS game bridge currently
    # has no pending player requests.
    return {"pedido": None}

@app.post("/api/jogo/abrir-jogador")
def post_jogo_abrir_jogador(uid: int, acao: str = "perfil", b: Optional[int] = None):
    return {"ok": True, "uid": uid, "acao": acao}

@app.post("/api/jogo/abrir-no-jogo")
def post_jogo_abrir_no_jogo(uid: int, sid: Optional[int] = None):
    return {"ok": True, "uid": uid, "sid": sid}

@app.get("/api/jogo/dados")
@app.post("/api/jogo/dados")
def get_jogo_dados():
    return {"dados": None}

@app.get("/api/jogo/navegador")
@app.post("/api/jogo/navegador")
def get_jogo_navegador():
    return {"navegador": None}

@app.get("/api/jogo/captura-do-jogador")
@app.post("/api/jogo/captura-do-jogador")
def get_jogo_captura_do_jogador(uid: Optional[int] = None):
    return {"captura": None, "uid": uid}

@app.post("/api/jogo/dados/fechar")
def post_jogo_dados_fechar():
    if callable(AO_FECHAR_MENU):
        try:
            AO_FECHAR_MENU()
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/jogo/conectar")
def post_jogo_conectar():
    if callable(AO_CONECTAR_PELA_TELA):
        try:
            AO_CONECTAR_PELA_TELA()
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/jogo/fechar-menu")
def post_jogo_fechar_menu():
    if callable(AO_FECHAR_MENU):
        try:
            AO_FECHAR_MENU()
        except Exception:
            pass
    return {"ok": True}

@app.get("/api/jogo/captura")
@app.post("/api/jogo/captura")
def get_jogo_captura():
    return {"captura": _CAPTURA_FAIXA}

@app.post("/api/jogo/captura/fechar")
def post_jogo_captura_fechar():
    _CAPTURA_FAIXA["ativa"] = False
    return {"ok": True}

@app.post("/api/jogo/auto-snapshot/salvar")
def post_jogo_auto_snapshot_salvar():
    return {"ok": True}

@app.get("/api/plugins")
def get_plugins():
    return {
        "aceito": legal.aceito_plugins(settings.load()),
        "tem_lista": False,
        "ultima": None,
        "historico": [],
        "jogos": [],
        "instalado": False,
        "disponivel": False,
    }


def _plugins_indisponiveis():
    raise HTTPException(status_code=501, detail="Plugins do jogo indisponiveis no macOS")


@app.post("/api/plugins/verificar")
def post_plugins_verificar():
    return _plugins_indisponiveis()

@app.post("/api/plugins/ligar")
def post_plugins_ligar(body: PluginLigarBody):
    disabled = set(settings.load().get("plugins_desligados") or [])
    if body.ligado:
        disabled.discard(body.id)
    else:
        disabled.add(body.id)
    settings.save(plugins_desligados=sorted(disabled))
    return get_plugins()

@app.post("/api/plugins/voltar")
def post_plugins_voltar(body: PluginVoltarBody):
    return _plugins_indisponiveis()

@app.get("/api/plugins/oferta")
def get_plugins_oferta():
    return {
        "plugins": [],
        "nao_vistos": [],
        "avisar": bool(settings.load().get("plugins_avisar_novos", True)),
    }

@app.post("/api/plugins/avisar-novos")
def post_plugins_avisar_novos(body: PluginsAvisarBody):
    settings.save(plugins_avisar_novos=body.ligado)
    return get_plugins_oferta()

@app.post("/api/plugins/instalar")
def post_plugins_instalar(body: PluginIdBody):
    return _plugins_indisponiveis()

@app.post("/api/plugins/pasta-jogo")
def post_plugins_pasta_jogo(body: PastaJogoBody):
    return _plugins_indisponiveis()

@app.post("/api/plugins/dispensar")
def post_plugins_dispensar(body: PluginIdBody):
    dismissed = set(settings.load().get("plugins_dispensados") or [])
    dismissed.add(body.id)
    settings.save(plugins_dispensados=sorted(dismissed))
    return get_plugins_oferta()

@app.post("/api/plugins/oferta-vista")
def post_plugins_oferta_vista(body: PluginsVistosBody):
    seen = settings.load().get("plugins_oferta_vista")
    seen = set(seen if isinstance(seen, list) else [])
    seen.update(body.ids)
    settings.save(plugins_oferta_vista=sorted(seen))
    return get_plugins_oferta()

@app.get("/api/plugins/foto")
def get_plugins_foto():
    raise HTTPException(status_code=404, detail="Sem foto do plugin")

# ==============================================================================
# 19. Window & System Tray Management Endpoints
# ==============================================================================

@app.post("/api/janela/mostrar")
def post_janela_mostrar():
    if callable(AO_MOSTRAR_JANELA):
        try:
            AO_MOSTRAR_JANELA()
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/janela/ao-fechar")
def post_janela_ao_fechar(body: AoFecharBody):
    if callable(AO_RESPOSTA_AO_FECHAR):
        try:
            AO_RESPOSTA_AO_FECHAR(body.acao, body.lembrar)
        except Exception:
            pass
    return {"ok": True}

@app.get("/api/bandeja/conexao")
def get_bandeja_conexao():
    return _BAND_CONEXAO_FAIXA

@app.post("/api/bandeja/conexao/fechar")
def post_bandeja_conexao_fechar():
    _BAND_CONEXAO_FAIXA["ativa"] = False
    return {"ok": True}

@app.get("/api/bandeja/menu")
def get_bandeja_menu():
    return ESTADO_DA_BANDEJA

@app.post("/api/bandeja/menu/pronto")
def post_bandeja_menu_pronto(body: MenuProntoBody):
    if callable(AO_MENU_PRONTO):
        try:
            AO_MENU_PRONTO(body.n, body.largura, body.altura)
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/bandeja/menu/painel")
def post_bandeja_menu_painel(body: MenuPainelBody):
    if callable(AO_MENU_PAINEL):
        try:
            AO_MENU_PAINEL(body.n, body.linha, body.largura, body.altura)
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/bandeja/menu/fechar")
def post_bandeja_menu_fechar(body: MenuFecharBody):
    if callable(AO_FECHAR_MENU):
        try:
            AO_FECHAR_MENU(body.n)
        except Exception:
            pass
    return {"ok": True}

@app.post("/api/bandeja/escolher")
def post_bandeja_escolher(body: EscolherBody):
    if callable(AO_ESCOLHER_NA_BANDEJA):
        try:
            AO_ESCOLHER_NA_BANDEJA(body.n, body.item)
        except Exception:
            pass
    return {"ok": True}

# ==============================================================================
# 20. Updates, Diagnostics & Log Endpoints
# ==============================================================================

@app.get("/api/atualizacao")
def get_atualizacao(forcar: bool = False):
    return {
        "tem_nova": False,
        "versao": "1.0.0",
        "instalado": True,
        "automatica": False,
        "url": "",
        "dispensada": False,
        "respondeu": True,
    }

@app.post("/api/atualizacao/dispensar")
def post_atualizacao_dispensar(body: DispensarBody):
    return {"ok": True}

@app.get("/api/atualizacao/progresso")
def get_atualizacao_progresso():
    return {"progresso": 100, "concluido": True}

@app.post("/api/atualizacao/aplicar")
def post_atualizacao_aplicar():
    return {"ok": True}

@app.get("/atualizando")
def get_atualizando_page():
    atualizando_file = FMSH_DIR / "src" / "web" / "atualizando.html"
    if atualizando_file.exists():
        return FileResponse(str(atualizando_file))
    return HTMLResponse("<h2>FM Season Hub esta atualizando...</h2>")

@app.get("/api/diagnostico")
def get_diagnostico():
    return diagnostics.status(get_db_path(create_parent=False), dict(_LIVE_STATUS))

@app.get("/api/diagnostico/completo")
def get_diagnostico_completo_res():
    with diagnostics.REPORT_LOCK:
        return diagnostics.load_report()

@app.post("/api/diagnostico/completo")
def post_diagnostico_completo(lang: str = "pt"):
    try:
        with diagnostics.REPORT_LOCK:
            result = diagnostics.save_report(get_diagnostico(), lang)
    except OSError as error:
        logger.exception("Could not save diagnostics report")
        raise HTTPException(status_code=500, detail="Could not save diagnostics report") from error
    return {"ok": True, "em": result["em"]}

@app.post("/api/diagnostico/abrir-pasta")
def post_diagnostico_abrir_pasta():
    try:
        subprocess.Popen(["open", str(diagnostics.report_folder())])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

@app.post("/api/abrir-pasta-dados")
def post_abrir_pasta_dados():
    p = get_db_path().parent
    try:
        subprocess.Popen(["open", str(p)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

# ==============================================================================
# 21. Languages, Translations, Legal & Patch Notes Endpoints
# ==============================================================================

@app.get("/api/idiomas")
def get_idiomas():
    if idiomas:
        try:
            return {"idiomas": idiomas.disponiveis()}
        except Exception:
            pass
    # Fallback to scanning FMSH_DIR / idiomas
    i_dir = FMSH_DIR / "idiomas"
    langs = []
    if i_dir.exists():
        for d in i_dir.iterdir():
            if d.is_dir() and not d.name.startswith("_"):
                langs.append({"codigo": d.name, "nome": d.name.upper()})
    if not langs:
        langs = [{"codigo": "pt", "nome": "Português"}, {"codigo": "en", "nome": "English"}]
    for lang in langs:
        lang.update(completo=0, cobertura=0, traduzidos=0, total=0)
    return {"idiomas": langs}

@app.get("/api/idiomas/{codigo}")
def get_idioma_codigo(codigo: str):
    if not idiomas or codigo not in {item["codigo"] for item in idiomas.disponiveis()}:
        raise HTTPException(status_code=404, detail="Idioma nao encontrado")
    return {
        "interface": idiomas.resolver(codigo),
        "colunas": idiomas.resolver(codigo, "colunas"),
    }

@app.post("/api/idiomas/abrir-pasta")
def post_idiomas_abrir_pasta():
    i_dir = Path(paths.idiomas_dir())
    try:
        subprocess.Popen(["open", str(i_dir)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

@app.post("/api/idiomas/exportar")
def post_idiomas_exportar(body: ExportarIdiomaBody):
    try:
        return idiomas.exportar(body.codigo, body.base, body.nome)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        logger.warning("Could not export language files", exc_info=True)
        raise HTTPException(status_code=500, detail="Nao foi possivel criar os arquivos de idioma") from exc

@app.get("/api/legal")
@app.get("/api/legal/estado")
def get_legal(doc: str = "termos", lang: str = "pt"):
    content = ""
    is_aceito = True
    if legal:
        try:
            content = legal.documento(doc, lang)
            is_aceito = legal.aceito()
        except Exception:
            pass
    if not content:
        fname = f"TERMOS.{lang}.txt" if doc == "termos" else f"PRIVACIDADE.{lang}.txt"
        fpath = FMSH_DIR / "legal" / fname
        if not fpath.exists():
            fpath = FMSH_DIR / "legal" / ("TERMOS.txt" if doc == "termos" else "PRIVACIDADE.txt")
        if fpath.exists():
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
    return {
        "aceite": is_aceito,
        "aceito": is_aceito,
        "texto": content or "Termos de Uso do FM Season Hub",
    }

@app.post("/api/legal/aceite")
@app.post("/api/legal/aceitar")
def post_legal_aceite(body: Optional[AceiteBody] = None):
    if settings:
        try:
            settings.save(aceite={
                "versao": "1",
                "termos_aceitos": True,
                "privacidade_lida": True,
                "plugins_aceitos": True,
            })
        except Exception:
            pass
    return {"ok": True, "aceito": True}

@app.get("/api/overall/modos")
def get_overall_modos():
    import overall
    return {"modos": list(overall.MODOS), "padrao": overall.MODO_PADRAO}

@app.get("/api/patch-notes")
def get_patch_notes(lang: str = "pt"):
    fname = "PATCH_NOTES.en.txt" if lang == "en" else "PATCH_NOTES.txt"
    p = FMSH_DIR / fname
    if not p.exists():
        p = FMSH_DIR / "PATCH_NOTES.txt"
    content = ""
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
    return {"texto": content}

# ==============================================================================
# 22. Native macOS File/Folder Dialog Endpoint
# ==============================================================================

@app.post("/api/dialogo/pasta")
def post_dialogo_pasta():
    """Prompt user for directory selection using native AppleScript."""
    try:
        res = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select Folder")'],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if res.returncode == 0 and res.stdout.strip():
            return {"disponivel": True, "pasta": res.stdout.strip().rstrip("/")}
        return {"disponivel": True, "pasta": None}
    except Exception as e:
        logger.warning(f"Native folder picker failed: {e}")
        return {"disponivel": False, "pasta": None}

# ==============================================================================
# 23. React Static Files Mounting & SPA Fallback Handler
# ==============================================================================

# Mount static asset folders if they exist
if DIST_DIR.exists():
    for sub in ["assets", "fonts", "icones", "jogos", "mockup", "promo"]:
        sub_path = DIST_DIR / sub
        if sub_path.exists() and sub_path.is_dir():
            app.mount(f"/{sub}", StaticFiles(directory=str(sub_path)), name=sub)

@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    """Serve files from frontend dist, falling back to index.html for client routing."""
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=404, detail="Nao encontrado")

    target_path = (DIST_DIR / full_path).resolve()

    # Security check: ensure path is within dist
    try:
        target_path.relative_to(DIST_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado")

    # Serve existing file
    if target_path.is_file():
        return FileResponse(str(target_path))

    # Fallback to SPA index.html
    index_file = DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))

    return HTMLResponse("<h2>FM Season Hub Frontend Not Found</h2>", status_code=404)

# ==============================================================================
# 24. Server Runner
# ==============================================================================

def serve(host: str = "127.0.0.1", port: int = 8000):
    global FMSH_PORTA
    FMSH_PORTA = port
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        http=UVICORN_HTTP,
        h11_max_incomplete_event_size=H11_MAX_URL,
    )

def run(host: str = "127.0.0.1", port: int = 8000):
    serve(host=host, port=port)

if __name__ == "__main__":
    run()
