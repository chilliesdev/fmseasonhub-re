"""Read-only local checks and saved reports for the Diagnostics screen."""

from collections import deque
from contextlib import closing
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import re
import sqlite3
import sys
import threading

import paths
import settings
import version

ERROR_LINE = re.compile(r"erro|error|traceback|exception|falha", re.IGNORECASE)
REPORT_LOCK = threading.Lock()


def log_path():
    # app_main.log writes here, including startup and background-thread failures.
    return Path(paths.user_data_path("fmsh.log"))


class ErrorLogHandler(logging.Handler):
    """Keep API errors in the app log; retain evidence if the disk write fails."""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.recent = deque(maxlen=200)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        text = self.format(record)
        self.recent.extend(text.splitlines())
        try:
            with log_path().open("a", encoding="utf-8") as output:
                output.write(text + "\n")
        except OSError:
            # Do not log recursively when the log itself is unavailable.
            pass


ERROR_HANDLER = ErrorLogHandler()
logging.getLogger("fmsh").addHandler(ERROR_HANDLER)


def database_status(path):
    result = {"caminho": str(path), "tamanho": 0, "existe": False, "ok": False,
              "erro": None, "integridade": None, "tabelas": [], "snapshots": None,
              "jogadores": None}
    try:
        result["tamanho"] = path.stat().st_size
        result["existe"] = True
        # Never call the application connection helper: it creates and migrates tables.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=0.25)) as conn:
            conn.execute("PRAGMA query_only=ON")
            integrity = [row[0] for row in conn.execute("PRAGMA quick_check")]
            result["integridade"] = "; ".join(integrity)
            if integrity != ["ok"]:
                raise sqlite3.DatabaseError(result["integridade"])
            result["tabelas"] = sorted(row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            for table, required, count_key in (
                ("snapshots", {"id", "name", "created_at"}, "snapshots"),
                ("players", {"snapshot_id", "uid"}, "jogadores"),
            ):
                columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
                missing = required - columns
                if missing:
                    raise sqlite3.DatabaseError(f"{table}: missing columns {', '.join(sorted(missing))}")
                result[count_key] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            result["ok"] = True
    except (OSError, sqlite3.Error) as error:
        result["erro"] = f"{type(error).__name__}: {error}"
    return result


def log_status():
    path = log_path()
    result = {"caminho": str(path), "tamanho": 0, "existe": False,
              "erro": None, "linhas": []}
    try:
        result["tamanho"] = path.stat().st_size
        result["existe"] = True
        # Bound reads even when years of application history exist.
        with path.open("rb") as source:
            offset = max(0, result["tamanho"] - 65536)
            source.seek(offset)
            if offset:
                source.readline()
            result["linhas"] = source.read(65536).decode("utf-8", errors="replace").splitlines()[-200:]
    except OSError as error:
        result["erro"] = f"{type(error).__name__}: {error}"
    ERROR_HANDLER.acquire()
    try:
        for line in ERROR_HANDLER.recent:
            if line not in result["linhas"]:
                result["linhas"].append(line)
    finally:
        ERROR_HANDLER.release()
    if result["erro"]:
        result["linhas"].append(f"ERROR reading application log: {result['erro']}")
    result["linhas"] = result["linhas"][-200:]
    result["erros"] = sum(bool(ERROR_LINE.search(line)) for line in result["linhas"])
    return result


def status(database_path, live):
    cfg = settings.load()
    return {
        "versao": version.VERSION, "empacotado": bool(getattr(sys, "frozen", False)),
        "python": platform.python_version(),
        "so": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "executavel": sys.executable, "pasta_dados": paths.user_data_path(),
        "pasta": str(database_path.parent), "banco": database_status(database_path),
        "log": log_status(), "fm_conectado": bool(live.get("ready")),
        "save": live.get("save_name"), "fm_erro": live.get("error"),
        "fm_origem": cfg.get("fm_origem"), "fm_origem_em": cfg.get("fm_origem_em"),
    }


def report_folder():
    return Path(paths.user_data_path())


def load_report():
    try:
        with (report_folder() / "diagnostico.json").open(encoding="utf-8") as source:
            result = json.load(source)
        if (isinstance(result, dict) and isinstance(result.get("texto"), str)
                and isinstance(result.get("linhas"), list) and result.get("em")):
            return result
    except (OSError, ValueError):
        pass
    return {"em": None, "arquivo": None, "texto": "", "linhas": [], "relatorio": "",
            "estado": "idle", "ok": None}


def save_report(snapshot, lang):
    """Save one measured result; GET reads this result without rerunning checks."""
    english = lang.lower().startswith("en")
    database, log = snapshot["banco"], snapshot["log"]
    ok = database["ok"] and not log["erro"] and not log["erros"] and not snapshot["fm_erro"]
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    lines = []

    def add(text, state=None):
        lines.append({"t": str(text), "e": state})

    add("FM SEASON HUB — DIAGNOSTICS" if english else "FM SEASON HUB — DIAGNÓSTICO")
    add(stamp)
    add(("Local checks passed" if ok else "Local checks found errors or unavailable evidence")
        if english else ("Verificações locais aprovadas" if ok else "Erros ou evidências indisponíveis"),
        "ok" if ok else "erro")
    add("")
    add("ENVIRONMENT" if english else "AMBIENTE")
    for label, value in (("FMSH", snapshot["versao"]), ("Python", snapshot["python"]),
                         ("OS" if english else "Sistema", snapshot["so"]),
                         ("Executable" if english else "Executável", snapshot["executavel"]),
                         ("Data" if english else "Dados", snapshot["pasta_dados"])):
        add(f"{label}: {value}")
    add(f"Football Manager: {'connected' if snapshot['fm_conectado'] else 'disconnected'}"
        if english else f"Football Manager: {'conectado' if snapshot['fm_conectado'] else 'desconectado'}")
    if snapshot["save"]:
        add(f"Save: {snapshot['save']}")
    if snapshot["fm_erro"]:
        add(snapshot["fm_erro"], "erro")
    add("")
    add("DATABASE" if english else "BANCO DE DADOS")
    add(f"{database['caminho']} ({database['tamanho']} bytes)")
    if database["erro"]:
        add(database["erro"], "erro")
    else:
        add(f"SQLite quick_check: {database['integridade']}", "ok")
        add(f"Snapshots: {database['snapshots']}; players: {database['jogadores']}")
        add(("Tables: " if english else "Tabelas: ") + ", ".join(database["tabelas"]))
    add("")
    add("APPLICATION LOG" if english else "LOG DO APLICATIVO")
    add(f"{log['caminho']} ({log['tamanho']} bytes)")
    for line in log["linhas"]:
        add(line, "erro" if ERROR_LINE.search(line) else None)
    if not log["linhas"]:
        add("Log is empty" if english else "Log vazio")
    text = "\n".join(line["t"] for line in lines)
    folder = report_folder()
    filename = f"diagnostico-{stamp.replace(':', '').replace('.', '')}.txt"
    target = folder / filename
    result = {"em": stamp, "arquivo": str(target), "texto": text, "linhas": lines,
              "relatorio": text, "estado": "complete", "ok": ok, "lang": "en" if english else "pt"}
    metadata = folder / "diagnostico.json"
    temporary = metadata.with_suffix(".json.tmp")
    try:
        target.write_text(text, encoding="utf-8")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(metadata)
    except OSError:
        target.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        raise
    return result
