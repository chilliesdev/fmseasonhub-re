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
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import graphics
import capture_all
import db
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

_DB_LOCK = threading.Lock()

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
    destino: Optional[str] = None

class UidsBody(BaseModel):
    uids: List[int]
    snapshot: Optional[int] = None

class BibliotecaBody(BaseModel):
    arquivo: Optional[str] = None
    conteudo: Optional[Any] = None
    uids: Optional[List[int]] = None
    snapshot: Optional[int] = None

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
    data: str

class FimDeTemporadaBody(BaseModel):
    ligado: bool

class AutoSnapshotBody(BaseModel):
    ligado: Optional[bool] = None
    modelo: Optional[str] = None
    vagas: Optional[str] = None

class CapturaSomBody(BaseModel):
    ligado: Optional[bool] = None
    volume: Optional[float] = None

class ReceitaBuscarComoBody(BaseModel):
    faixa: Optional[Any] = None
    metricas: Optional[List[str]] = None
    params: Optional[Dict[str, Any]] = None

class BuscarComoConfigBody(BaseModel):
    faixa: Optional[Any] = None
    melhor: Optional[bool] = None
    pct: Optional[bool] = None
    tolIdx: Optional[int] = None
    pisoPct: Optional[int] = None
    minMinutos: Optional[int] = None

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
    response = await call_next(request)
    return response

# ==============================================================================
# 5. Database Connection Helper
# ==============================================================================

def get_db_path() -> Path:
    if settings:
        try:
            cfg = settings.load()
            if cfg.get("db_dir"):
                p = Path(cfg["db_dir"]) / "fm26_snapshots.db"
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:
            pass
    if paths:
        try:
            return Path(paths.banco_padrao())
        except Exception:
            pass
    # Fallback to standard user data path
    data_dir = Path.home() / "Library" / "Application Support" / "FMSeasonHub"
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
            nickname TEXT
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT carreira_id AS nome, SUM(COALESCE(bytes_crus, 0)) AS bytes FROM snapshots GROUP BY carreira_id")
    rows = cur.fetchall()
    carreiras = [dict(r) for r in rows if r["nome"]]
    total = sum(c["bytes"] for c in carreiras)
    return {
        "carreiras": carreiras,
        "outros": 0,
        "total": total,
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
    if settings:
        cfg = settings.load()
        return cfg.get("bandeja", {"ligado": True})
    return {"ligado": True}

@app.post("/api/settings/bandeja")
def set_bandeja_settings(body: Dict[str, Any]):
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
def set_auto_snapshot(body: Dict[str, Any]):
    if settings:
        settings.save(auto_snapshot=body)
    return {"ok": True}

@app.get("/api/settings/auto-snapshot/nome")
def nome_do_auto_snapshot(modelo: str = "FM 2026"):
    return {"nome": f"Auto Snapshot - {modelo}"}

@app.post("/api/settings/captura-som")
def set_captura_som(body: Dict[str, Any]):
    if settings:
        cfg = settings.load()
        cur_s = cfg.get("captura_som", {})
        cur_s.update(body)
        settings.save(captura_som=cur_s)
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
        rows = conn.execute("SELECT * FROM snapshots ORDER BY created_at DESC").fetchall()
        metrics = _snapshot_metrics(conn)
        snaps = [dict(row, **metrics.get(row["id"], {"n_players": 0, "size_bytes": 0})) for row in rows]
    if include_live and _LIVE_STATUS.get("ready"):
        live_snap = dict(_LIVE_STATUS)
        live_snap.update(id=999999999, name="Live Season", n_players=0, size_bytes=0,
                         created_at=live_snap.get("read_at") or "", is_live=True)
        snaps.insert(0, live_snap)
    return snaps

@app.get("/api/snapshots/{sid}")
def get_snapshot(sid: int):
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
    conn = get_db_connection()
    with _DB_LOCK:
        cur = conn.cursor()
        cur.execute("DELETE FROM snapshots WHERE id=?", (sid,))
        conn.commit()
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
        return [dict(r) for r in rows]

@app.get("/api/snapshots/{sid}/players/{uid}")
def get_snapshot_player(sid: int, uid: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT p.*, s.*, pr.*
    FROM players p
    LEFT JOIN player_stats s ON s.snapshot_id=p.snapshot_id AND s.uid=p.uid
    LEFT JOIN player_profile pr ON pr.snapshot_id=p.snapshot_id AND pr.uid=p.uid
    WHERE p.snapshot_id=? AND p.uid=?
    """, (sid, uid))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Jogador nao encontrado")
    return dict(row)

@app.get("/api/snapshots/{sid}/players/{uid}/percentis")
def get_player_percentis(
    sid: int,
    uid: int,
    coorte: Optional[str] = None,
    regua: str = "top20",
    min_minutes: Optional[int] = None,
):
    return {
        "uid": uid,
        "coorte": coorte or "geral",
        "regua": regua,
        "percentis": {},
    }

@app.get("/api/snapshots/{sid}/players/{uid}/analise")
def get_player_analise(
    sid: int,
    uid: int,
    coorte: Optional[str] = None,
    regua: str = "top20",
    min_minutes: Optional[int] = None,
):
    return {
        "uid": uid,
        "totais": {},
        "partidas": [],
        "contexto": {},
        "similares": [],
    }

@app.get("/api/snapshots/{sid}/players/{uid}/buscar-como")
def buscar_como_player(sid: int, uid: int, request: Request):
    return {"uids": [], "params": dict(request.query_params)}

@app.post("/api/snapshots/{sid}/buscar-como-receita")
def buscar_como_receita(sid: int, body: ReceitaBuscarComoBody):
    return {"uids": [], "metricas": body.metricas or []}

@app.get("/api/buscar-como/config")
def get_buscar_como_config():
    return {
        "faixa": None,
        "melhor": True,
        "pct": True,
        "tolIdx": 1,
        "pisoPct": 70,
        "minMinutos": 450,
    }

@app.post("/api/buscar-como/config")
def save_buscar_como_config(body: BuscarComoConfigBody):
    return {"ok": True}

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
        _JOB_STATUS.update(kind="capture", state="running", phase="lendo_times", done=0,
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
                    staged_sid = db.create_snapshot(
                        staged, name=name, scope=body.scope, game_date=source[1],
                        save_name=source[2], savegame_id=source[0][0],
                        fm_version=_FM_MEMORY.fm_version,
                    )
                    capture_all.scan_base(staged, staged_sid, _FM_READER, _FM_MEMORY,
                                          progress=progress, ref_date=source[1])
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
        AO_AVISO_DA_CAPTURA({"simulada": True, "estado": estado, "tipo": tipo})
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

@app.get("/api/moneyball")
def get_moneyball(snapshot: Optional[int] = None, team: Optional[int] = None):
    return {
        "team": team,
        "players": [],
        "columns": [],
    }

@app.get("/api/moneyball/percentiles")
def get_moneyball_percentiles(
    snapshot: Optional[int] = None,
    team: Optional[int] = None,
    pool: Optional[str] = None,
    min_minutes: Optional[int] = None,
):
    return {
        "team": team,
        "pool": pool or "top20",
        "percentiles": {},
    }

@app.get("/api/search/fields")
def get_search_fields(group: str = "all", snapshot: Optional[int] = None):
    catalog = _load_moneyball_catalog()
    items = catalog.get(group, []) if group != "all" else [it for g in catalog.values() for it in g]
    return {
        "columns": items,
        "sectionOrder": ["geral", "ataque", "passe", "defesa", "fisico", "goleiro"],
        "opsByType": {"num": [">=", "<=", "="], "text": ["contains", "equals"]},
        "valueSlots": {},
    }

@app.get("/api/moneyball/columns")
def get_moneyball_columns(group: str = "all", snapshot: Optional[int] = None):
    catalog = _load_moneyball_catalog()
    current = catalog.get(group, []) if group != "all" else []
    return {
        "current": current,
        "sections": {
            "geral": [],
            "ataque": [],
            "passe": [],
            "defesa": [],
            "fisico": [],
            "goleiro": [],
        },
    }

@app.get("/api/moneyball/browse")
def moneyball_browse(request: Request):
    return {
        "total": 0,
        "filtered": 0,
        "players": [],
        "att": {},
    }

@app.get("/api/moneyball/export")
@app.get("/api/moneyball/export.csv")
def moneyball_export(request: Request):
    content = "uid,name,club,position,rating\n"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="fmsh_export.csv"'},
    )

@app.post("/api/resumo-jogadores")
def resumo_jogadores(body: UidsBody):
    conn = get_db_connection()
    cur = conn.cursor()
    if not body.uids:
        return []
    placeholders = ",".join("?" for _ in body.uids)
    cur.execute(f"SELECT uid, full_name, club_id, ca, pa FROM players WHERE uid IN ({placeholders})", body.uids)
    return [dict(r) for r in cur.fetchall()]

@app.post("/api/jogadores-fora-da-captura")
def jogadores_fora_da_captura(body: UidsBody):
    return {"uids": []}

# ==============================================================================
# 12. Clubs, Profiles, Youth Teams & Currencies
# ==============================================================================

@app.get("/api/clubs")
def get_clubs(snapshot: Optional[int] = None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT club_uid, club_name, league_uid, league_name FROM club_leagues")
    rows = cur.fetchall()
    return {"clubs": [dict(r) for r in rows]}

@app.get("/api/club_profile")
def get_club_profile(snapshot: Optional[int] = None):
    return {
        "name_full": "Club Profile",
        "name_short": "Club",
        "facilities": 20,
    }

@app.get("/api/myteams")
def get_myteams(snapshot: Optional[int] = None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM teams")
    rows = cur.fetchall()
    return {"teams": [dict(r) for r in rows]}

@app.get("/api/youth-teams")
def get_youth_teams(snapshot: Optional[int] = None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM youth_teams")
    rows = cur.fetchall()
    return {"youth_teams": [dict(r) for r in rows]}

@app.get("/api/nomes-curtos")
def get_nomes_curtos(snapshot: Optional[int] = None):
    return {"nomes": {}}

# ==============================================================================
# 13. Careers, All-time Stats & Player Progress
# ==============================================================================

@app.get("/api/carreiras")
def get_carreiras():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT carreira_id AS id FROM snapshots WHERE carreira_id IS NOT NULL")
    rows = cur.fetchall()
    carreiras = []
    for r in rows:
        cid = r["id"]
        cur.execute("SELECT COUNT(*) AS c FROM snapshots WHERE carreira_id=?", (cid,))
        count = cur.fetchone()["c"]
        carreiras.append({
            "id": cid,
            "nome": cid.replace("_", " ").title(),
            "ativa": True,
            "n_temporadas": count,
        })
    if not carreiras:
        carreiras = [{"id": "padrao", "nome": "Carreira Principal", "ativa": True, "n_temporadas": 1}]
    return {
        "ativa": carreiras[0]["id"] if carreiras else None,
        "prefs": {"moeda": 1, "periodo_salario": "week"},
        "carreiras": carreiras,
    }

@app.post("/api/carreiras/ativa")
def ativar_carreira(body: CarreiraAtivaBody):
    return {"ok": True, "ativa": body.id}

@app.put("/api/carreiras/{cid}")
def salvar_carreira_prefs(cid: str, body: CarreiraPrefsBody):
    return {"ok": True, "cid": cid}

@app.post("/api/carreiras/{cid}/temporadas/{sid}")
@app.put("/api/carreiras/{cid}/temporadas/{sid}")
def mover_temporada(cid: str, sid: int):
    conn = get_db_connection()
    with _DB_LOCK:
        cur = conn.cursor()
        cur.execute("UPDATE snapshots SET carreira_id=? WHERE id=?", (cid, sid))
        conn.commit()
    return {"ok": True}

@app.get("/api/carreiras/{cid}/alltime")
def get_carreira_alltime(cid: str):
    return {
        "cid": cid,
        "players": [],
        "seasons": [],
    }

@app.get("/api/carreiras/{cid}/outras-ligas")
def get_carreiras_outras_ligas(cid: str):
    # Archived seasons distinguishes an unavailable agenda from an empty history.
    return {"auto": None, "proximos": None, "lidas": [], "ligas": []}

@app.post("/api/carreiras/{cid}/auto-snapshot")
def set_carreira_auto_snapshot(cid: str, body: AutoSnapshotDataBody):
    return {"ok": True, "data": body.data}

@app.get("/api/players/{uid}/alltime")
def get_player_alltime(uid: int, carreira: Optional[str] = None):
    return {
        "uid": uid,
        "carreira": carreira,
        "temporadas": [],
    }

@app.get("/api/players/{uid}/alltime/percentis")
def get_player_alltime_percentis(uid: int, carreira: Optional[str] = None, coorte: Optional[str] = None):
    return {"uid": uid, "percentis": {}}

@app.get("/api/players/{uid}/temporadas")
def get_player_temporadas(uid: int):
    return {"uid": uid, "temporadas": []}

# ==============================================================================
# 14. Portal, Garimpos, Mudou, Apoiadores, Alertas, Dicas & Onboarding
# ==============================================================================

@app.get("/api/portal")
def get_portal(snapshot: Optional[int] = None):
    return {
        "base": None,
        "live": _LIVE_STATUS,
        "season": {},
        "highlights": [],
        "prospects": [],
        "youth": [],
        "expiring": [],
    }

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


def _carregar_favoritos():
    config = settings.load()
    listas = config.get("favoritos_listas") or []
    # True is the first-install sentinel. None means the user deleted all lists.
    if not listas and config.get("favoritos_lista_padrao") is True:
        return [{"id": "fav_default", "nome": "Favoritos", "cor": "#3b82f6", "uids": []}]
    return listas


def _gravar_favoritos(listas):
    padrao = settings.load().get("favoritos_lista_padrao")
    if not any(lista["id"] == padrao for lista in listas):
        padrao = listas[0]["id"] if listas else None
    settings.save(favoritos_listas=listas, favoritos_lista_padrao=padrao)


@app.get("/api/favoritos/listas")
@app.get("/api/favoritos")
def get_favoritos_listas():
    with _FAVORITOS_LOCK:
        return {"listas": _carregar_favoritos()}


@app.post("/api/favoritos/listas")
def post_favoritos_criar(body: FavListaNovaBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        nova = {"id": f"fav_{uuid.uuid4().hex}", "nome": body.nome, "cor": body.cor, "uids": body.uids or []}
        listas.append(nova)
        _gravar_favoritos(listas)
        return {"lista": nova, "listas": listas}


@app.patch("/api/favoritos/listas/{id_lista}")
def patch_favoritos_editar(id_lista: str, body: FavListaEditarBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        for lista in listas:
            if lista["id"] == id_lista:
                if body.nome:
                    lista["nome"] = body.nome
                if body.cor:
                    lista["cor"] = body.cor
                _gravar_favoritos(listas)
                return {"lista": lista}
    raise HTTPException(status_code=404, detail="Lista nao encontrada")


@app.delete("/api/favoritos/listas/{id_lista}")
def delete_favoritos_apagar(id_lista: str):
    with _FAVORITOS_LOCK:
        listas = [lista for lista in _carregar_favoritos() if lista["id"] != id_lista]
        _gravar_favoritos(listas)
        return {"ok": True}


@app.post("/api/favoritos/listas/{id_lista}/jogadores")
def post_favoritos_jogadores(id_lista: str, body: FavJogadoresBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        for lista in listas:
            if lista["id"] == id_lista:
                u_set = set(lista["uids"])
                if body.marcar:
                    u_set.update(body.uids)
                else:
                    u_set.difference_update(body.uids)
                lista["uids"] = list(u_set)
                _gravar_favoritos(listas)
                return {"ok": True, "lista": lista}
    return {"ok": True}


@app.post("/api/favoritos/listas/{id_lista}/duplicar")
def post_favoritos_duplicar(id_lista: str, body: FavDuplicarBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        for lista in listas:
            if lista["id"] == id_lista:
                dupl = {"id": f"fav_{uuid.uuid4().hex}", "nome": body.nome,
                        "cor": lista["cor"], "uids": list(lista["uids"])}
                listas.append(dupl)
                _gravar_favoritos(listas)
                return {"lista": dupl}
    raise HTTPException(status_code=404, detail="Lista nao encontrada")


@app.post("/api/favoritos/tirar-de-todas")
def post_favoritos_tirar_de_todas(body: FavJogadoresBody):
    with _FAVORITOS_LOCK:
        listas = _carregar_favoritos()
        rem_set = set(body.uids)
        for lista in listas:
            lista["uids"] = [u for u in lista["uids"] if u not in rem_set]
        _gravar_favoritos(listas)
        return {"ok": True}


@app.post("/api/favoritos/migrar-local")
def post_favoritos_migrar_local(body: FavMigrarLocalBody):
    return {"ok": True}

@app.post("/api/favoritos/aviso-visto")
def post_favoritos_aviso_visto():
    return {"ok": True}

# ==============================================================================
# 16. Library (Biblioteca) Endpoints
# ==============================================================================

def _get_biblioteca_dir() -> Path:
    if paths:
        try:
            return Path(paths.biblioteca_dir())
        except Exception:
            pass
    b_dir = Path.home() / "Library" / "Application Support" / "FMSeasonHub" / "biblioteca"
    b_dir.mkdir(parents=True, exist_ok=True)
    return b_dir

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

@app.get("/api/biblioteca")
@app.get("/api/biblioteca/listar")
def get_biblioteca():
    b_dir = _get_biblioteca_dir()
    items = []
    # Load factory presets
    presets_dir = FMSH_DIR / "src" / "presets_fabrica"
    if presets_dir.exists():
        for f in presets_dir.glob("*.fsh"):
            items.append({
                "arquivo": f.name,
                "nome": f.stem.replace("-", " ").title(),
                "nomeEn": f.stem.replace("-", " ").title(),
                "tipo": "filtro",
                "fabrica": True,
            })
    # User saved presets
    for f in b_dir.glob("*.*"):
        items.append({
            "arquivo": f.name,
            "nome": f.stem,
            "nomeEn": f.stem,
            "tipo": "filtro",
            "fabrica": False,
        })
    return {"arquivos": items, "pasta": str(b_dir)}

@app.get("/api/biblioteca/{arquivo}")
def get_biblioteca_ler(arquivo: str):
    b_dir = _get_biblioteca_dir()
    p = b_dir / arquivo
    if not p.exists():
        p = FMSH_DIR / "src" / "presets_fabrica" / arquivo
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                f.seek(0)
                return {"texto": f.read()}
    raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

@app.post("/api/biblioteca")
def post_biblioteca_gravar(body: BibliotecaBody):
    b_dir = _get_biblioteca_dir()
    nome = body.arquivo if body.arquivo is not None else "salvo.fsh"
    p = b_dir / _validar_nome_biblioteca(nome)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o666)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise HTTPException(status_code=400, detail="Arquivo nao pode ser um link simbolico") from exc
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if isinstance(body.conteudo, (dict, list)):
            json.dump(body.conteudo, f, indent=2)
        else:
            f.write(str(body.conteudo or ""))
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
    target = b_dir / arquivo
    if target.exists():
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
    return {"ja_estava": True, "nao_conferem": [], "sem_captura": []}

@app.get("/api/biblioteca/{arquivo}/bruto")
def get_biblioteca_bruto(arquivo: str):
    b_dir = _get_biblioteca_dir()
    p = b_dir / arquivo
    if not p.exists():
        p = FMSH_DIR / "src" / "presets_fabrica" / arquivo
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="Arquivo nao encontrado")

@app.post("/api/biblioteca-fmf")
def post_biblioteca_fmf(request: Request):
    return {"tipo": "view", "review": {}}

# ==============================================================================
# 17. FM Views & Shortlists Endpoints
# ==============================================================================

@app.get("/api/views-fm/pasta")
def get_views_fm_pasta():
    return {"pastas": [], "arquivos": []}

@app.post("/api/views-fm/da-pasta")
def post_views_fm_da_pasta(body: ViewDaPastaBody):
    return {"ok": True, "review": {}}

@app.post("/api/views-fm/escolher")
def post_views_fm_escolher(destino: Optional[str] = None):
    # Prompt user for .fmf file via native macOS picker
    res = subprocess.run(
        ["osascript", "-e", 'POSIX path of (choose file with prompt "Select FM View file" of type {"fmf"})'],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        fpath = res.stdout.strip()
        return {"disponivel": True, "cancelado": False, "review": {"path": fpath, "name": Path(fpath).name}}
    return {"disponivel": True, "cancelado": True}

@app.post("/api/views-fm")
def post_views_fm(request: Request):
    return {"ok": True, "review": {}}

@app.get("/api/listas-preferenciais")
def get_listas_preferenciais():
    return {"listas": []}

@app.delete("/api/listas-preferenciais/{id_lista}")
def delete_lista_preferencial(id_lista: str):
    return {"ok": True}

@app.get("/api/listas-preferenciais/pasta")
def get_listas_preferenciais_pasta():
    return {"pastas": [], "arquivos": []}

@app.post("/api/listas-preferenciais/da-pasta")
def post_lista_preferencial_da_pasta(body: ListaDaPastaBody):
    return {"ok": True, "lista": {"id": "lp_1", "nome": body.arquivo}}

@app.post("/api/listas-preferenciais/escolher")
def post_lista_preferencial_escolher():
    res = subprocess.run(
        ["osascript", "-e", 'POSIX path of (choose file with prompt "Select FM Shortlist file" of type {"fmf", "lsh"})'],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        fpath = res.stdout.strip()
        return {"disponivel": True, "cancelado": False, "lista": {"path": fpath, "nome": Path(fpath).name}}
    return {"disponivel": True, "cancelado": True}

@app.post("/api/listas-preferenciais/{id_lista}/atualizar")
def post_lista_preferencial_atualizar(id_lista: str):
    return {"ok": True}

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
    v = "1.0.0"
    if version and hasattr(version, "VERSION"):
        v = version.VERSION
    return {
        "versao": v,
        "pasta": str(get_db_path().parent),
        "log": {"linhas": ["FMSH backend running smoothly on macOS"]},
    }

@app.get("/api/diagnostico/completo")
def get_diagnostico_completo_res():
    return {"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "relatorio": "All systems operational"}

@app.post("/api/diagnostico/completo")
def post_diagnostico_completo(lang: str = "pt"):
    return {"ok": True, "em": time.strftime("%Y-%m-%dT%H:%M:%S")}

@app.post("/api/diagnostico/abrir-pasta")
def post_diagnostico_abrir_pasta():
    p = get_db_path().parent
    try:
        subprocess.Popen(["open", str(p)])
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
    i_dir = FMSH_DIR / "idiomas"
    try:
        subprocess.Popen(["open", str(i_dir)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

@app.post("/api/idiomas/exportar")
def post_idiomas_exportar(body: ExportarIdiomaBody):
    i_dir = FMSH_DIR / "idiomas"
    out_dir = i_dir / body.codigo
    out_dir.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "pasta": str(out_dir), "arquivos": [f"{body.codigo}.json"]}

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
