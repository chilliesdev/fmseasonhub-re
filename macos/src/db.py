"""Camada de persistencia SQLite (17 tabelas, schemas e snapshots).

Suporta gravacao live em memoria ou arquivo temporario e copia atomica
para o banco principal (fm26_snapshots.db).
"""

import os
import shutil
import sqlite3
import unicodedata
import paths
import settings

DB_FILE_NAME = "fm26_snapshots.db"
LIVE_SCOPE = "live"
FIM_DE_TEMPORADA_SCOPE = "fim_de_temporada"
ESCOPOS_FORA_DA_LISTA = ("live", "live_temp")
SO_TEMPORADAS = ("squad", "leagues", "full")
PREFIXO_AO_VIVO = "live_"
_LIVE_ARQUIVO = None
_DIA_DO_FM24 = 60000

SCHEMA = """
-- 1. Snapshots Root Table
CREATE TABLE IF NOT EXISTS snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    save_name      TEXT,
    game_date      TEXT,
    in_game_season TEXT,
    scope          TEXT NOT NULL DEFAULT 'squad',
    club_uid       INTEGER,
    manager        TEXT,
    savegame_id    TEXT,
    save_file      TEXT,
    carreira_id    TEXT,
    fm_version     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    synced         INTEGER NOT NULL DEFAULT 0
);

-- 2. Core Player Identity
CREATE TABLE IF NOT EXISTS players (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid          INTEGER NOT NULL,
    name_first   TEXT,
    name_last    TEXT,
    common_name  TEXT,
    full_name    TEXT,
    legal_name   TEXT,
    search_norm  TEXT,
    display_norm TEXT,
    ca           INTEGER,
    pa           INTEGER,
    height_cm    INTEGER,
    club_id      INTEGER,
    team_uid     INTEGER,
    position     TEXT,
    PRIMARY KEY (snapshot_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_players_uid ON players(uid);
CREATE INDEX IF NOT EXISTS idx_players_club ON players(snapshot_id, club_id);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(snapshot_id, team_uid);
CREATE INDEX IF NOT EXISTS idx_players_searchnorm ON players(snapshot_id, search_norm);

-- 3. Player Aggregate Season Statistics
CREATE TABLE IF NOT EXISTS player_stats (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid          INTEGER NOT NULL,
    apps_total INTEGER, apps_starts INTEGER, apps_sub INTEGER, apps_complete INTEGER,
    minutes INTEGER, goals INTEGER, assists INTEGER, avg_rating REAL,
    yellow_cards INTEGER, red_cards INTEGER, man_of_the_match INTEGER,
    penalties_taken INTEGER, penalties_scored INTEGER,
    goals_conceded_gk INTEGER, clean_sheets_gk INTEGER,
    passes_attempted INTEGER, passes_completed INTEGER, passes_progressive INTEGER,
    key_passes INTEGER, key_passes_open_play INTEGER, clear_cut_chances INTEGER,
    shots INTEGER, shots_on_target INTEGER, shots_outside_box INTEGER, shots_blocked INTEGER,
    goals_outside_box INTEGER, free_kicks_taken INTEGER, dribbles INTEGER,
    crosses_attempted INTEGER, crosses_completed INTEGER,
    crosses_open_play_attempted INTEGER, crosses_open_play_completed INTEGER,
    tackles_attempted INTEGER, tackles_completed INTEGER, tackles_key INTEGER,
    interceptions INTEGER, clearances INTEGER, blocks INTEGER,
    headers_attempted INTEGER, headers_won INTEGER, headers_lost INTEGER, headers_key INTEGER,
    fouls_committed INTEGER, fouls_won INTEGER, offsides INTEGER,
    sprints INTEGER, presses_attempted INTEGER, presses_completed INTEGER,
    distance_km REAL, possession_won INTEGER, possession_lost INTEGER,
    xg REAL, xa REAL, npxg REAL, xg_prevented_gk REAL,
    errors_leading_to_goal INTEGER, minutes_since_last_goal INTEGER,
    team_goals_for_while_in_squad INTEGER, team_goals_against_while_in_squad INTEGER,
    team_wins_while_in_squad INTEGER, team_losses_while_in_squad INTEGER,
    gk_saves_held INTEGER, gk_saves_parried INTEGER, gk_saves_tipped INTEGER,
    gk_penalties_faced INTEGER, gk_penalties_saved INTEGER,
    gk_xg_faced REAL, gk_xg_shots_faced REAL,
    PRIMARY KEY (snapshot_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_stats_uid ON player_stats(uid);

-- 4. Detailed Player Profile & Attributes
CREATE TABLE IF NOT EXISTS player_profile (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid         INTEGER NOT NULL,
    corners INTEGER, crossing INTEGER, dribbling INTEGER, finishing INTEGER,
    first_touch INTEGER, free_kicks INTEGER, heading INTEGER, long_shots INTEGER,
    long_throws INTEGER, marking INTEGER, passing INTEGER, penalty_taking INTEGER,
    tackling INTEGER, technique INTEGER, anticipation INTEGER, bravery INTEGER,
    composure INTEGER, concentration INTEGER, decisions INTEGER, determination INTEGER,
    flair INTEGER, leadership INTEGER, off_the_ball INTEGER, positioning INTEGER,
    teamwork INTEGER, vision INTEGER, work_rate INTEGER, acceleration INTEGER,
    agility INTEGER, balance INTEGER, jumping_reach INTEGER, natural_fitness INTEGER,
    pace INTEGER, stamina INTEGER, strength INTEGER,
    aerial_reach INTEGER, command_of_area INTEGER, communication INTEGER,
    eccentricity INTEGER, handling INTEGER, kicking INTEGER, one_on_ones INTEGER,
    punching INTEGER, reflexes INTEGER, rushing_out INTEGER, throwing INTEGER,
    nationality TEXT, birth_date TEXT, nationality_code TEXT, loan_end TEXT,
    traits TEXT, contract_end TEXT, club_name TEXT, joined_date TEXT,
    contract_wage INTEGER, contract_squad_num INTEGER, contract_type INTEGER,
    guide_value INTEGER, transfer_value INTEGER, morale INTEGER,
    is_regen INTEGER, is_female INTEGER, is_injured INTEGER, on_loan INTEGER,
    PRIMARY KEY (snapshot_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_profile_uid ON player_profile(uid);

-- 5. Match Logs per Player
CREATE TABLE IF NOT EXISTS player_match_stats (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid         INTEGER NOT NULL,
    match_id    INTEGER NOT NULL,
    match_date  TEXT NOT NULL,
    comp_uid    INTEGER,
    team_uid    INTEGER,
    opp_uid     INTEGER,
    home        INTEGER,
    started     INTEGER,
    minutes     INTEGER,
    rating      REAL,
    xg          REAL,
    xa          REAL,
    goals       INTEGER,
    assists     INTEGER,
    shots       INTEGER,
    shots_on_target INTEGER,
    passes_attempted INTEGER,
    passes_completed INTEGER,
    tackles_attempted INTEGER,
    tackles_completed INTEGER,
    interceptions INTEGER,
    clearances  INTEGER,
    blocks      INTEGER,
    headers_won INTEGER,
    fouls_committed INTEGER,
    possession_won INTEGER,
    possession_lost INTEGER,
    presses_completed INTEGER,
    sprints     INTEGER,
    PRIMARY KEY (snapshot_id, uid, match_id)
) WITHOUT ROWID;

-- 6. Match Logs per Team
CREATE TABLE IF NOT EXISTS team_match_stats (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    team_uid    INTEGER NOT NULL,
    match_id    INTEGER NOT NULL,
    match_date  TEXT NOT NULL,
    comp_uid    INTEGER,
    opp_uid     INTEGER,
    home        INTEGER,
    goals_for   INTEGER,
    goals_against INTEGER,
    xg_for      REAL,
    xg_against  REAL,
    shots_for   INTEGER,
    shots_against INTEGER,
    shots_on_target_for INTEGER,
    shots_on_target_against INTEGER,
    PRIMARY KEY (snapshot_id, team_uid, match_id)
) WITHOUT ROWID;

-- 7. Calendar & Form Tracking
CREATE TABLE IF NOT EXISTS player_form (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid         INTEGER NOT NULL,
    match_date  TEXT NOT NULL,
    comp_uid    INTEGER,
    comp_name   TEXT,
    team_uid    INTEGER,
    rating      REAL,
    PRIMARY KEY (snapshot_id, uid, match_date, comp_uid)
);
CREATE INDEX IF NOT EXISTS idx_form_uid ON player_form(snapshot_id, uid);

-- 8. League Status Tracking
CREATE TABLE IF NOT EXISTS snapshot_ligas (
    snapshot_id    INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    comp_uid       INTEGER NOT NULL,
    nome           TEXT,
    ultima_partida TEXT,
    estado         TEXT NOT NULL,
    lida           INTEGER NOT NULL DEFAULT 0,
    reputacao      INTEGER,
    pais           TEXT,
    PRIMARY KEY (snapshot_id, comp_uid)
);

-- 9. Club Profile & Facilities
CREATE TABLE IF NOT EXISTS club_profile (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    club_uid             INTEGER,
    name_full            TEXT,
    name_short           TEXT,
    nickname             TEXT,
    year_founded         INTEGER,
    color_fg             TEXT,
    color_bg             TEXT,
    avg_attendance       INTEGER,
    min_attendance       INTEGER,
    max_attendance       INTEGER,
    balance              INTEGER,
    transfer_budget      INTEGER,
    wage_budget          INTEGER,
    wage_total           INTEGER,
    training_facilities  INTEGER,
    youth_facilities     INTEGER,
    youth_coaching       INTEGER,
    youth_recruitment    INTEGER,
    youth_importance     INTEGER,
    supporter_loyalty    INTEGER,
    supporter_passion    INTEGER,
    PRIMARY KEY (snapshot_id)
);

-- 10. Teams
CREATE TABLE IF NOT EXISTS teams (
    snapshot_id INTEGER NOT NULL,
    team_uid    INTEGER NOT NULL,
    club_uid    INTEGER,
    team_type   INTEGER,
    label       TEXT,
    min_age     INTEGER,
    max_age     INTEGER,
    reputation  INTEGER,
    n_players   INTEGER,
    PRIMARY KEY (snapshot_id, team_uid)
);

-- 11. Player Teams
CREATE TABLE IF NOT EXISTS player_teams (
    snapshot_id INTEGER NOT NULL,
    player_uid  INTEGER NOT NULL,
    team_uid    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, player_uid, team_uid)
);
CREATE INDEX IF NOT EXISTS idx_pt_team ON player_teams(snapshot_id, team_uid);

-- 12. Youth Teams
CREATE TABLE IF NOT EXISTS youth_teams (
    snapshot_id INTEGER NOT NULL,
    team_uid    INTEGER NOT NULL,
    club_uid    INTEGER,
    club_name   TEXT,
    nation      TEXT,
    team_type   INTEGER,
    type_label  TEXT,
    is_female   INTEGER,
    n_players   INTEGER,
    escola      INTEGER,
    PRIMARY KEY (snapshot_id, team_uid)
);

-- 13. Youth Comps
CREATE TABLE IF NOT EXISTS youth_comps (
    snapshot_id INTEGER NOT NULL,
    uid         INTEGER NOT NULL,
    name        TEXT,
    name_short  TEXT,
    kind        TEXT,
    age_group   TEXT,
    nation      TEXT,
    category    INTEGER,
    reputation  INTEGER,
    is_female   INTEGER,
    PRIMARY KEY (snapshot_id, uid)
);

-- 14. Youth Team Comps
CREATE TABLE IF NOT EXISTS youth_team_comps (
    snapshot_id INTEGER NOT NULL,
    team_uid    INTEGER NOT NULL,
    comp_uid    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, team_uid, comp_uid)
);
CREATE INDEX IF NOT EXISTS idx_ytc_comp ON youth_team_comps(snapshot_id, comp_uid);

-- 15. Comps
CREATE TABLE IF NOT EXISTS comps (
    snapshot_id INTEGER NOT NULL,
    uid         INTEGER NOT NULL,
    name        TEXT,
    nation      TEXT,
    reputation  INTEGER,
    is_female   INTEGER,
    PRIMARY KEY (snapshot_id, uid)
);

-- 16. Club Leagues
CREATE TABLE IF NOT EXISTS club_leagues (
    snapshot_id INTEGER NOT NULL,
    club_uid    INTEGER NOT NULL,
    league_uid  INTEGER,
    league_name TEXT,
    club_name   TEXT,
    PRIMARY KEY (snapshot_id, club_uid)
);

-- 17. Future Transfers
CREATE TABLE IF NOT EXISTS future_transfers (
    snapshot_id   INTEGER NOT NULL,
    uid           INTEGER NOT NULL,
    dest_club_uid INTEGER,
    transfer_date TEXT,
    PRIMARY KEY (snapshot_id, uid)
);
"""


def db_file():
    """Caminho do banco: `db_dir` das configuracoes, ou a pasta de dados padrao."""
    s = settings.load()
    custom = s.get("db_dir")
    if custom and os.path.isdir(custom):
        return os.path.join(custom, DB_FILE_NAME)
    return paths.banco_padrao()


def connect(path=None):
    """Abre conexao SQLite configurada."""
    p = path or db_file()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn, table, col, decl):
    """Garante presenca de coluna no schema por introspeccao."""
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        existentes = {r[1] for r in cur.fetchall()}
        if col not in existentes:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    except Exception:
        pass


def _profile_schema():
    return ""


def _estatisticas_partida_schema():
    return ""


def _backfill_club_uid(conn):
    try:
        conn.execute("""
            UPDATE snapshots
            SET club_uid = (
                SELECT club_id FROM players
                WHERE players.snapshot_id = snapshots.id AND club_id IS NOT NULL
                LIMIT 1
            )
            WHERE club_uid IS NULL
        """)
        conn.commit()
    except Exception:
        pass


def _backfill_carreira(conn):
    try:
        conn.execute("""
            UPDATE snapshots
            SET carreira_id = 'clube:' || club_uid
            WHERE carreira_id IS NULL AND club_uid IS NOT NULL
        """)
        conn.commit()
    except Exception:
        pass


def _backfill_fm_version(conn):
    try:
        conn.execute("UPDATE snapshots SET fm_version = '26' WHERE fm_version IS NULL")
        conn.commit()
    except Exception:
        pass


def init_schema(conn):
    """Cria tabelas e indices e executa migracoes."""
    conn.executescript(SCHEMA)
    # The scanner writes every reader profile field, including positions and personality.
    from fm_reader import PROFILE_KEYS
    profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(player_profile)")}
    for column in PROFILE_KEYS:
        if column not in profile_columns:
            conn.execute(f'ALTER TABLE player_profile ADD COLUMN "{column}" INTEGER')
    _ensure_column(conn, "snapshots", "carreira_id", "TEXT")
    _ensure_column(conn, "snapshots", "fm_version", "TEXT")
    _ensure_column(conn, "snapshots", "savegame_id", "TEXT")
    _backfill_club_uid(conn)
    _backfill_carreira(conn)
    _backfill_fm_version(conn)
    conn.commit()


def init_db(path=None):
    conn = connect(path)
    try:
        init_schema(conn)
    finally:
        conn.close()


def normalize(text):
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def create_snapshot(
    conn,
    name,
    save_name=None,
    game_date=None,
    in_game_season=None,
    scope="squad",
    club_uid=None,
    manager=None,
    savegame_id=None,
    save_file=None,
    carreira_id=None,
    fm_version=None,
):
    """Insere novo snapshot e devolve seu ID gerado."""
    if not carreira_id:
        if savegame_id:
            carreira_id = f"sg:{savegame_id}"
        elif club_uid:
            carreira_id = f"clube:{club_uid}"

    cur = conn.execute(
        """
        INSERT INTO snapshots (
            name, save_name, game_date, in_game_season, scope, club_uid,
            manager, savegame_id, save_file, carreira_id, fm_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            name,
            save_name,
            game_date,
            in_game_season,
            scope,
            club_uid,
            manager,
            savegame_id,
            save_file,
            carreira_id,
            fm_version or "26",
        ),
    )
    conn.commit()
    return cur.lastrowid


def publish_capture(conn, staged, staged_sid, validate):
    """Publish a complete staged capture without changing any existing season."""
    tables = (
        "snapshots",
        "players",
        "player_stats",
        "player_profile",
        "player_form",
        "club_profile",
        "teams",
        "player_teams",
        "club_leagues",
    )
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        # Older server-created databases contain only a subset of the reader columns.
        # Apply additive schema changes inside the same transaction as the new rows.
        for table in tables:
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if not existing:
                schema = staged.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                conn.execute(schema)
            else:
                for column in staged.execute(f'PRAGMA table_info("{table}")'):
                    if column[1] not in existing:
                        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column[1]}" {column[2]}')

        snapshot = dict(staged.execute("SELECT * FROM snapshots WHERE id=?", (staged_sid,)).fetchone())
        del snapshot["id"]
        columns = ",".join(f'"{column}"' for column in snapshot)
        placeholders = ",".join("?" for _ in snapshot)
        sid = conn.execute(
            f"INSERT INTO snapshots ({columns}) VALUES ({placeholders})", tuple(snapshot.values())
        ).lastrowid
        for table in tables[1:]:
            cursor = staged.execute(f'SELECT * FROM "{table}" WHERE snapshot_id=?', (staged_sid,))
            names = [column[0] for column in cursor.description]
            snapshot_index = names.index("snapshot_id")
            columns = ",".join(f'"{column}"' for column in names)
            placeholders = ",".join("?" for _ in names)
            conn.executemany(
                f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                (tuple(sid if i == snapshot_index else value for i, value in enumerate(row))
                 for row in cursor),
            )
        validate()
    return sid


def insert_player(conn, snapshot_id, uid, data):
    """Insere dados de identidade, atributos e estatisticas de um jogador."""
    full_name = data.get("full_name") or f"{data.get('name_first', '')} {data.get('name_last', '')}".strip()
    search_norm = normalize(full_name)
    display_norm = normalize(data.get("common_name") or full_name)

    conn.execute(
        """
        INSERT OR REPLACE INTO players (
            snapshot_id, uid, name_first, name_last, common_name, full_name,
            legal_name, search_norm, display_norm, ca, pa, height_cm, club_id,
            team_uid, position
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            snapshot_id,
            uid,
            data.get("name_first"),
            data.get("name_last"),
            data.get("common_name"),
            full_name,
            data.get("legal_name"),
            search_norm,
            display_norm,
            data.get("ca"),
            data.get("pa"),
            data.get("height_cm"),
            data.get("club_id"),
            data.get("team_uid"),
            data.get("position"),
        ),
    )


def save_club(conn, snapshot_id, club_data):
    """Grava informacoes de infraestrutura e financas do clube."""
    conn.execute(
        """
        INSERT OR REPLACE INTO club_profile (
            snapshot_id, club_uid, name_full, name_short, nickname, year_founded,
            color_fg, color_bg, avg_attendance, min_attendance, max_attendance,
            balance, transfer_budget, wage_budget, wage_total, training_facilities,
            youth_facilities, youth_coaching, youth_recruitment, youth_importance,
            supporter_loyalty, supporter_passion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            snapshot_id,
            club_data.get("club_uid"),
            club_data.get("name_full"),
            club_data.get("name_short"),
            club_data.get("nickname"),
            club_data.get("year_founded"),
            club_data.get("color_fg"),
            club_data.get("color_bg"),
            club_data.get("avg_attendance"),
            club_data.get("min_attendance"),
            club_data.get("max_attendance"),
            club_data.get("balance"),
            club_data.get("transfer_budget"),
            club_data.get("wage_budget"),
            club_data.get("wage_total"),
            club_data.get("training_facilities"),
            club_data.get("youth_facilities"),
            club_data.get("youth_coaching"),
            club_data.get("youth_recruitment"),
            club_data.get("youth_importance"),
            club_data.get("supporter_loyalty"),
            club_data.get("supporter_passion"),
        ),
    )


def save_team(conn, snapshot_id, team_data):
    """Grava metadados de um time no snapshot."""
    conn.execute(
        """
        INSERT OR REPLACE INTO teams (
            snapshot_id, team_uid, club_uid, team_type, label,
            min_age, max_age, reputation, n_players
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            snapshot_id,
            team_data.get("team_uid"),
            team_data.get("club_uid"),
            team_data.get("team_type", 0),
            team_data.get("label"),
            team_data.get("min_age"),
            team_data.get("max_age"),
            team_data.get("reputation", 0),
            team_data.get("n_players", 0),
        ),
    )


def save_club_leagues(conn, snapshot_id, leagues_data):
    for item in leagues_data:
        conn.execute(
            """
            INSERT OR REPLACE INTO club_leagues (
                snapshot_id, club_uid, league_uid, league_name, club_name
            ) VALUES (?, ?, ?, ?, ?)
        """,
            (
                snapshot_id,
                item.get("club_uid"),
                item.get("league_uid"),
                item.get("league_name"),
                item.get("club_name"),
            ),
        )


def save_youth(conn, snapshot_id, youth_data):
    for yteam in youth_data.get("teams", []):
        conn.execute(
            """
            INSERT OR REPLACE INTO youth_teams (
                snapshot_id, team_uid, club_uid, club_name, nation,
                team_type, type_label, is_female, n_players, escola
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                snapshot_id,
                yteam.get("team_uid"),
                yteam.get("club_uid"),
                yteam.get("club_name"),
                yteam.get("nation"),
                yteam.get("team_type"),
                yteam.get("type_label"),
                yteam.get("is_female", 0),
                yteam.get("n_players", 0),
                yteam.get("escola", 0),
            ),
        )


def save_future_transfers(conn, snapshot_id, transfers):
    for tr in transfers:
        conn.execute(
            """
            INSERT OR REPLACE INTO future_transfers (
                snapshot_id, uid, dest_club_uid, transfer_date
            ) VALUES (?, ?, ?, ?)
        """,
            (
                snapshot_id,
                tr.get("uid"),
                tr.get("dest_club_uid"),
                tr.get("transfer_date"),
            ),
        )


def gravar_ligas(conn, snapshot_id, ligas):
    for liga in ligas:
        conn.execute(
            """
            INSERT OR REPLACE INTO snapshot_ligas (
                snapshot_id, comp_uid, nome, ultima_partida, estado, lida, reputacao, pais
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                snapshot_id,
                liga.get("comp_uid"),
                liga.get("nome"),
                liga.get("ultima_partida"),
                liga.get("estado", "em_andamento"),
                liga.get("lida", 0),
                liga.get("reputacao"),
                liga.get("pais"),
            ),
        )


def carreira_id_de(conn, snapshot_id):
    row = conn.execute(
        "SELECT carreira_id FROM snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()
    return row[0] if row else None


def fins_de_temporada_lidos(conn, carreira_id):
    rows = conn.execute(
        "SELECT id FROM snapshots WHERE carreira_id=? AND scope=?",
        (carreira_id, FIM_DE_TEMPORADA_SCOPE),
    ).fetchall()
    return [r[0] for r in rows]


def SO_TEMPORADAS_DE(conn, carreira_id):
    rows = conn.execute(
        "SELECT id FROM snapshots WHERE carreira_id=? AND scope IN ('squad', 'leagues', 'full')",
        (carreira_id,),
    ).fetchall()
    return [r[0] for r in rows]


# Live Database Support
def _pasta_ao_vivo():
    p = paths.local_data_path("live_db")
    os.makedirs(p, exist_ok=True)
    return p


def novo_arquivo_ao_vivo():
    global _LIVE_ARQUIVO
    _LIVE_ARQUIVO = os.path.join(_pasta_ao_vivo(), f"live_{os.getpid()}.db")
    return _LIVE_ARQUIVO


def arquivo_live_db():
    return _LIVE_ARQUIVO or os.path.join(_pasta_ao_vivo(), "live.db")


def connect_live():
    p = arquivo_live_db()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    init_schema(conn)
    return conn


def usar_live_db():
    return connect_live()


def gravar_live_db(origem_conn, destino_conn=None):
    """Copia todas as tabelas do banco em memoria / live para o banco permanente."""
    if destino_conn is None:
        destino_conn = connect()

    origem_conn.backup(destino_conn)
    destino_conn.commit()


def reset_live_db():
    p = arquivo_live_db()
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass


def drop_live_db():
    reset_live_db()


def limpar_leituras_ao_vivo():
    pasta = _pasta_ao_vivo()
    if os.path.isdir(pasta):
        shutil.rmtree(pasta, ignore_errors=True)
