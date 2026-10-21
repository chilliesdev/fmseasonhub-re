# Reverse Engineering Analysis Report: Architecture, UI, Database, and Analytics

**Target Application:** FM Season Hub (FMSH)  
**Binary Artifacts Analyzed:**
- PyInstaller / Executable root: `FMSH.exe`, `app_main.pyc`
- Python 3.14 Bytecode modules: `PYZ.pyz_extracted/` (`analise_perfil.pyc`, `bandeja.pyc`, `bandeja_estado.pyc`, `biblioteca_listas.pyc`, `csv_export.pyc`, `fim_de_temporada.pyc`, `idiomas.pyc`, `janela_dados.pyc`, `janela_topo.pyc`, `paths.pyc`, `sistema.pyc`, `texto.pyc`, `view_fmf.pyc`, `view_fmf_colunas.pyc`, `abrir_no_jogo.pyc`, `buscar_como.pyc`, `favoritos.pyc`, `merge_temporadas.pyc`, `navegador_do_jogo.pyc`)
- Nuitka C-compiled Python 3.14 Windows AMD64 Extensions:
  * `server.cp314-win_amd64.pyd`
  * `db.cp314-win_amd64.pyd`
  * `moneyball.cp314-win_amd64.pyd`
  * `overall.cp314-win_amd64.pyd`
  * `arquivo_partidas.cp314-win_amd64.pyd`
  * `fm_reader.cp314-win_amd64.pyd`
- Frontend SPA Bundle: `fmsh/frontend/dist/` (`index.html`, `assets/index-Cvmv7E2F.js`)
- Analytics Catalogs: `fmsh/src/moneyball_catalog.json`, `moneyball_rotulos.json`, `moneyball_siglas.json`, `presets_fabrica/*.fsh`

---

## 1. System Overview & Technology Stack

FM Season Hub is a standalone companion analytics workstation for Sports Interactive's *Football Manager* (FM24 & FM26).

```
+-------------------------------------------------------------------------------+
|                           Native OS Host (Windows)                            |
|  +-------------------------------------------------------------------------+  |
|  |                  PyWebView Desktop Multi-Window Container               |  |
|  |  +--------------------+  +---------------------+  +------------------+  |  |
|  |  | Main SPA Window    |  | Tray Flyout Window  |  | In-Game Overlay  |  |  |
|  |  | (1440x900 React)   |  | (Win32 Shell Notify)|  | (Data & Menus)   |  |  |
|  |  +---------+----------+  +----------+----------+  +--------+---------+  |  |
|  +------------|------------------------|----------------------|------------+  |
|               | DOM CustomEvents / JS  | IPC Via evaluate_js  |               |
|               v                        v                      v               |
|  +-------------------------------------------------------------------------+  |
|  |                  Embedded HTTP REST API (FastAPI + Uvicorn)             |  |
|  |  - Bound to 127.0.0.1 on dynamic open port                              |  |
|  |  - 153 Endpoints (Snapshots, Live Memory, Careers, Moneyball, DB, etc.) |  |
|  +-------------------------------------------------------------------------+  |
|                                        |                                      |
|                                        v                                      |
|  +-------------------------------------------------------------------------+  |
|  |                    Compiled Analytics & Storage Engine                  |  |
|  |  - db.pyd (SQLite3 with in-memory write buffer & ON DELETE CASCADE)     |  |
|  |  - moneyball.pyd (NumPy vectorized searchsorted percentile engine)      |  |
|  |  - overall.pyd (Truncated Z-score & Best-Fit Role Rating Matrix)        |  |
|  |  - fm_reader.pyd & arquivo_partidas.pyd (Process memory live reader)   |  |
|  +-------------------------------------------------------------------------+  |
+-------------------------------------------------------------------------------+
```

### Core Components
1. **Frontend:** React SPA bundled with Vite/Rollup. Communicates exclusively via standard asynchronous HTTP REST calls (`fetch('/api/...')`) to the local backend.
2. **Backend Server:** FastAPI ASGI application hosted via Uvicorn within `server.cp314-win_amd64.pyd`. Serves both REST JSON APIs and the SPA static bundle from `/{full_path:path}`.
3. **Windowing / Shell:** `pywebview` coupled with direct Win32 API calls via `ctypes` (`user32.dll`, `dwmapi.dll`, `gdi32.dll`, `shell32.dll`) to achieve frameless rounded windows, pill-shaped banners, floating HUDs, and system tray integration (`Shell_NotifyIconW`).
4. **Data Persistence:** Embedded SQLite 3 (`fm26_snapshots.db` / `fm24_snapshots.db`) located in the user's roaming local data directory or custom user-configured path (`db_dir`).
5. **Execution Model:** PyInstaller packaging Python 3.14 runtime with custom modules compiled via Nuitka for high-performance memory processing and reverse-engineering resistance.

---

## 2. Startup Sequence & Multi-Window Architecture

### 2.1 Startup Sequence (`app_main.py`)
1. **Single Instance Verification:**
   - Calls `_segurar_mutex()` which uses Win32 `CreateMutexW(None, False, "FMSH_SINGLE_INSTANCE_MUTEX")`.
   - If `GetLastError() == ERROR_ALREADY_EXISTS (183)`, FMSH finds existing window via `_janelas_deste_processo()`, brings it forward with `_trazer_para_frente()`, and exits immediately.
2. **Port Allocation:**
   - Calls `_free_port('127.0.0.1', 54321)`. Tests preferred port `54321`; if bound, binds to port `0` to allocate a random dynamic ephemeral loopback port.
   - Persists chosen port to disk via `_gravar_porta(port)` into `local_data_path('porta.txt')` so external game plugins (BepInEx) can locate the active server.
3. **Server Initialization:**
   - Launches a background daemon thread running `server.serve(host='127.0.0.1', port=port)`.
   - Polls `_wait_until_up(f"http://127.0.0.1:{port}/api/status", timeout=15)` until FastAPI responds with HTTP 200.
4. **Background Watcher Threads:**
   - `_iniciar_atualizador_de_plugins()`: Polls game directory and verifies BepInEx plugin integrity and updates.
   - `laco_dos_sons()`: Dedicated audio playback worker thread utilizing Win32 MCI (`winmm.dll`) for responsive feedback without UI latency.
   - `vigiar_bandeja()`: Background worker managing tray notifications, rollover reminders, and savegame sync.
5. **UI Launch:**
   - Initializes `webview.settings['ALLOW_DOWNLOADS'] = True`.
   - Creates main window `janela_principal` (1440x900, min size 960x540, maximized).
   - Starts PyWebView loop via `webview.start(ao_iniciar_o_webview, private_mode=False, storage_path=local_data_path('webview'))`.

### 2.2 Managed Windows
| Window Identifier | Function | Dimensions / Mode | Role |
| :--- | :--- | :--- | :--- |
| `principal` | `janela_principal` | 1440x900 (Maximized) | Primary React Workstation SPA |
| `caixa` | `caixinha` | Centered modal | Update application progress & splash |
| `menu_jogo` | `abrir_menu_do_jogo` | Frameless popup | In-game shortcut menu over FM client |
| `dados_jogo` | `abrir_dados_do_jogo` | Floating HUD | In-game player profile & comparison card |
| `aviso_captura` | `aviso_da_captura` | Rounded pill | Snapshot complete notification banner |
| `aviso_conexao` | `aviso_da_conexao` | Top banner | FM memory connection status indicator |
| `menu_bandeja` | `criar_janela_do_menu` | Frameless popup | System tray menu & quick actions flyout |

### 2.3 IPC & PyWebView Bridge
FMSH does **not** rely on `webview.js_api` object binding. Instead, it utilizes an asynchronous event-driven architecture:
1. **Frontend to Backend:** Asynchronous standard HTTP REST calls (`fetch('/api/...')`).
2. **Backend to Frontend:** Direct DOM execution via `janela.evaluate_js(...)`:
   - `window.dispatchEvent(new Event('fmsh-pedido-do-jogo'))`
   - `window.dispatchEvent(new CustomEvent(eventName, {detail: eventData}))`
   - `window.__fmshConectar && window.__fmshConectar()`
   - `window.__fmshMostrarPainel(lx, ly, lw, lh, pw, ph, side)`
   - `window.__fmshFecharPainel()`
   - `window.__fmshAoFechar()`
   - `window.__fmshPedirMenu()`

---

## 3. Local HTTP Server API Reference

The FastAPI backend exposes 153 endpoints categorized below:

### 3.1 Snapshots & Captures
- `GET /api/snapshots`: List all stored snapshots with metadata, club, and season dates.
- `GET /api/snapshots/{sid}`: Detailed summary of a single snapshot.
- `DELETE /api/snapshots/{sid}`: Delete snapshot (triggers SQLite foreign key cascade deletion).
- `GET /api/snapshots/{sid}/players`: List players in snapshot with pagination and basic stats.
- `GET /api/snapshots/{sid}/players/{uid}`: Full player record (profile + basic stats + advanced stats).
- `GET /api/snapshots/{sid}/players/{uid}/analise`: Advanced profile analytics (scatter data, context ratios).
- `GET /api/snapshots/{sid}/players/{uid}/percentis`: Full computed percentile vector for player.
- `GET /api/snapshots/{sid}/players/{uid}/buscar-como`: "Search Similar" attribute vector generator.
- `POST /api/snapshots/{sid}/buscar-como-receita`: Recipe generator for similar player profile filtering.
- `POST /api/capture`: Trigger memory capture of live FM process.
- `POST /api/captura/simular`: Test/mock capture pipeline.

### 3.2 Live Game & Memory Connection
- `GET /api/connect`: Probe and attach to live `fm.exe` process.
- `POST /api/disconnect`: Detach from game memory.
- `GET /api/status`: Engine status, active career, attached process PID, live memory health.
- `GET /api/live`: Real-time state of the attached FM session.
- `POST /api/refresh`: Rescan memory structures for active clubs/competitions.
- `GET /api/memoria`: Diagnostic report on process memory offsets and pointers.
- `GET /api/jogo/abrir-jogador`: Request client to navigate directly to player in FM UI.
- `GET /api/jogo/abrir-no-jogo`: In-game overlay trigger.
- `POST /api/jogo/auto-snapshot/salvar`: Auto-save scheduled snapshot on season boundary.
- `POST /api/jogo/captura`: Fast memory dump for in-game overlay display.
- `POST /api/jogo/captura-do-jogador`: Single-player deep memory extraction.
- `POST /api/jogo/conectar`: Connect shortcut triggered from in-game plugin.
- `POST /api/jogo/fechar-menu`: Close overlay menu.

### 3.3 Moneyball & Analytics
- `GET /api/moneyball`: Retrieve position catalog metadata (`moneyball_catalog.json`).
- `GET /api/moneyball/columns`: Get available derived column schema and groups.
- `GET /api/moneyball/browse`: High-performance filtered & sorted table of all players with derived metrics.
- `GET /api/moneyball/percentiles`: Retrieve distribution percentiles for selected metric pool.
- `GET /api/moneyball/export.csv`: Stream CSV export matching current active UI filter and sort criteria.
- `GET /api/search/fields`: Retrieve searchable field catalog and available operators.

### 3.4 Careers, Clubs & Rosters
- `GET /api/carreiras`: List all detected saves/careers.
- `GET /api/carreiras/ativa`: Get currently active career metadata.
- `GET /api/carreiras/{cid}`: Detailed career info and season progression timeline.
- `GET /api/carreiras/{cid}/alltime`: Career all-time aggregated player stats.
- `GET /api/carreiras/{cid}/outras-ligas`: Status of external unmanaged leagues for season rollover.
- `GET /api/carreiras/{cid}/temporadas/{sid}`: Career season link.
- `GET /api/clubs`: All clubs present in database.
- `GET /api/club_profile`: Club facilities, finances, attendance, and youth setup.
- `GET /api/myteams`: Managed club squads (Senior, Reserves, Youth teams).
- `GET /api/youth-teams`: Youth team roster and competition linkages.
- `GET /api/resumo-jogadores`: Summary counts of loaded players by status.
- `GET /api/jogadores-fora-da-captura`: Tracked players belonging to unloaded competitions.

### 3.5 Graphics & Assets
- `GET /api/club_logo/{uid}`: Retrieve club badge (from custom facepack/graphics folder).
- `GET /api/comp_logo/{uid}`: Retrieve competition trophy/logo.
- `GET /api/flag/{uid}`: Retrieve nation flag graphic.
- `GET /api/portrait/{uid}`: Retrieve player facepack cut-out portrait.

### 3.6 Shortlists & Library
- `GET /api/listas-preferenciais`: List user shortlists.
- `POST /api/listas-preferenciais`: Import or create shortlist.
- `GET /api/listas-preferenciais/{id_lista}`: Retrieve shortlist players.
- `POST /api/listas-preferenciais/{id_lista}/atualizar`: Synchronize shortlist with FM game file.
- `GET /api/favoritos/listas`: Custom user favorite categories.
- `POST /api/favoritos/listas`: Create favorite list.
- `POST /api/favoritos/listas/{id_lista}/jogadores`: Add/remove player from favorite list.
- `POST /api/favoritos/tirar-de-todas`: Remove player from all favorite lists.
- `GET /api/biblioteca`: Browse `.fmf` and `.fsh` library items.
- `GET /api/views-fm`: List Football Manager `.fmf` view files.
- `POST /api/views-fm/escolher`: Load and parse specific `.fmf` view.

### 3.7 System, Settings & Tray
- `GET /api/settings`: Read all application settings.
- `POST /api/settings`: Update settings (language, directories, sound, tray behavior).
- `POST /api/settings/overall`: Configure Overall algorithm mode (`atributos`, `misto`, `estatistica`).
- `POST /api/settings/fim-de-temporada`: Configure rollover tolerance and auto-snapshot scheduling.
- `POST /api/settings/captura-som/testar`: Play audio test cue.
- `GET /api/bandeja/menu`: Retrieve current state for tray menu.
- `POST /api/bandeja/escolher`: Execute action from tray menu.
- `POST /api/sair`: Clean shutdown sequence.

---

## 4. SQLite Database Architecture & Schema Specification

The database utilizes SQLite 3 with `PRAGMA foreign_keys = ON;` and writes via an in-memory staging mechanism (`sqlite3.connect(':memory:')`) during active game capture, flushing atomically to disk (`fm26_snapshots.db`) via `gravar_live_db()` to prevent filesystem lock contention.

### 4.1 Schema DDL

```sql
-- Snapshots Root Table
CREATE TABLE IF NOT EXISTS snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    save_name      TEXT,
    game_date      TEXT,
    in_game_season TEXT,
    scope          TEXT NOT NULL DEFAULT 'squad',  -- 'squad' | 'leagues' | 'full'
    club_uid       INTEGER,
    manager        TEXT,
    savegame_id    TEXT,
    save_file      TEXT,
    carreira_id    TEXT,
    fm_version     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    synced         INTEGER NOT NULL DEFAULT 0
);

-- Core Player Identity
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

-- Player Aggregate Season Statistics
CREATE TABLE IF NOT EXISTS player_stats (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid          INTEGER NOT NULL,

    -- Basic Match Counts & Output
    apps_total INTEGER, apps_starts INTEGER, apps_sub INTEGER, apps_complete INTEGER,
    minutes INTEGER, goals INTEGER, assists INTEGER, avg_rating REAL,
    yellow_cards INTEGER, red_cards INTEGER, man_of_the_match INTEGER,
    penalties_taken INTEGER, penalties_scored INTEGER,
    goals_conceded_gk INTEGER, clean_sheets_gk INTEGER,

    -- Advanced Moneyball Metrics
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

    -- Goalkeeper Performance
    gk_saves_held INTEGER, gk_saves_parried INTEGER, gk_saves_tipped INTEGER,
    gk_penalties_faced INTEGER, gk_penalties_saved INTEGER,
    gk_xg_faced REAL, gk_xg_shots_faced REAL,

    PRIMARY KEY (snapshot_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_stats_uid ON player_stats(uid);

-- Detailed Player Profile & Attributes (Dynamically expanded from FmReader.PROFILE_KEYS)
CREATE TABLE IF NOT EXISTS player_profile (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid         INTEGER NOT NULL,
    -- Attributes 1-20
    corners INTEGER, crossing INTEGER, dribbling INTEGER, finishing INTEGER,
    first_touch INTEGER, free_kicks INTEGER, heading INTEGER, long_shots INTEGER,
    long_throws INTEGER, marking INTEGER, passing INTEGER, penalty_taking INTEGER,
    tackling INTEGER, technique INTEGER, anticipation INTEGER, bravery INTEGER,
    composure INTEGER, concentration INTEGER, decisions INTEGER, determination INTEGER,
    flair INTEGER, leadership INTEGER, off_the_ball INTEGER, positioning INTEGER,
    teamwork INTEGER, vision INTEGER, work_rate INTEGER, acceleration INTEGER,
    agility INTEGER, balance INTEGER, jumping_reach INTEGER, natural_fitness INTEGER,
    pace INTEGER, stamina INTEGER, strength INTEGER,
    -- GK Attributes
    aerial_reach INTEGER, command_of_area INTEGER, communication INTEGER,
    eccentricity INTEGER, handling INTEGER, kicking INTEGER, one_on_ones INTEGER,
    punching INTEGER, reflexes INTEGER, rushing_out INTEGER, throwing INTEGER,
    -- Biography & Contract
    nationality TEXT, birth_date TEXT, nationality_code TEXT, loan_end TEXT,
    traits TEXT, contract_end TEXT, club_name TEXT, joined_date TEXT,
    contract_wage INTEGER, contract_squad_num INTEGER, contract_type INTEGER,
    guide_value INTEGER, transfer_value INTEGER, morale INTEGER,
    is_regen INTEGER, is_female INTEGER, is_injured INTEGER, on_loan INTEGER,
    PRIMARY KEY (snapshot_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_profile_uid ON player_profile(uid);

-- Match Logs per Player (High resolution game-by-game log)
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

-- Match Logs per Team
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

-- Calendar & Form Tracking
CREATE TABLE IF NOT EXISTS player_form (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid         INTEGER NOT NULL,
    match_date  TEXT NOT NULL,
    comp_uid    INTEGER,
    comp_name   TEXT,
    team_uid    INTEGER,
    rating      REAL,  -- NULL indicates match occurred while player was injured/benched
    PRIMARY KEY (snapshot_id, uid, match_date, comp_uid)
);
CREATE INDEX IF NOT EXISTS idx_form_uid ON player_form(snapshot_id, uid);

-- League Status Tracking
CREATE TABLE IF NOT EXISTS snapshot_ligas (
    snapshot_id    INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    comp_uid       INTEGER NOT NULL,
    nome           TEXT,
    ultima_partida TEXT,
    estado         TEXT NOT NULL,  -- 'fechada' | 'em_andamento'
    lida           INTEGER NOT NULL DEFAULT 0,
    reputacao      INTEGER,
    pais           TEXT,
    PRIMARY KEY (snapshot_id, comp_uid)
);

-- Club Profile & Facilities
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

-- Teams, Youth & Competitions
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

CREATE TABLE IF NOT EXISTS player_teams (
    snapshot_id INTEGER NOT NULL,
    player_uid  INTEGER NOT NULL,
    team_uid    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, player_uid, team_uid)
);
CREATE INDEX IF NOT EXISTS idx_pt_team ON player_teams(snapshot_id, team_uid);

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

CREATE TABLE IF NOT EXISTS youth_team_comps (
    snapshot_id INTEGER NOT NULL,
    team_uid    INTEGER NOT NULL,
    comp_uid    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, team_uid, comp_uid)
);
CREATE INDEX IF NOT EXISTS idx_ytc_comp ON youth_team_comps(snapshot_id, comp_uid);

CREATE TABLE IF NOT EXISTS comps (
    snapshot_id INTEGER NOT NULL,
    uid         INTEGER NOT NULL,
    name        TEXT,
    nation      TEXT,
    reputation  INTEGER,
    is_female   INTEGER,
    PRIMARY KEY (snapshot_id, uid)
);

CREATE TABLE IF NOT EXISTS club_leagues (
    snapshot_id INTEGER NOT NULL,
    club_uid    INTEGER NOT NULL,
    league_uid  INTEGER,
    league_name TEXT,
    club_name   TEXT,
    PRIMARY KEY (snapshot_id, club_uid)
);

CREATE TABLE IF NOT EXISTS future_transfers (
    snapshot_id   INTEGER NOT NULL,
    uid           INTEGER NOT NULL,
    dest_club_uid INTEGER,
    transfer_date TEXT,
    PRIMARY KEY (snapshot_id, uid)
);
```

### 4.2 Migrations & Schema Evolution
`db.py` contains automated schema backfills run on every startup:
1. `_ensure_column(conn, table, col, decl)`: Inspects table with `PRAGMA table_info()` and executes `ALTER TABLE {table} ADD COLUMN {col} {decl}` if missing.
2. `_backfill_club_uid(conn)`: Populates `snapshots.club_uid` for legacy snapshots by matching `snapshots.save_name` against player profiles.
3. `_backfill_carreira(conn)`: Groups unassigned snapshots into careers based on user club identity.
4. `_backfill_fm_version(conn)`: Stamps snapshots created before September 2026 as `fm_version = '26'`.

---

## 5. Moneyball Metrics & Analytics Engine

### 5.1 Catalog Structure (`moneyball_catalog.json`)
The catalog is organized into 7 tactical position groups:
- `gk`: Goalkeepers (87 metrics)
- `def`: Central Defenders (105 metrics)
- `wing`: Fullbacks & Wingbacks (101 metrics)
- `dm`: Defensive Midfielders (98 metrics)
- `b2b`: Central & Box-to-Box Midfielders (105 metrics)
- `amc`: Attacking Midfielders & Wingers (105 metrics)
- `att`: Strikers & Center Forwards (105 metrics)

Each catalog item contains:
- `key`: Unique metric ID (e.g. `def_P`, `gk_O`, `amc_AQ`)
- `col`: Original spreadsheet reference column
- `label`: Display name (e.g. `Minutos por partida`)
- `expr`: Python expression evaluated against raw fields `f[...]` and prior derived results `r[...]`
- `fmt`: Display formatting (`int`, `dec`, `pct`, `money`)
- `lowerBetter`: Boolean flag indicating whether lower numerical values represent superior performance (e.g. goals conceded, fouls committed, possession lost)

### 5.2 Expression Evaluation Engine (`moneyball.py`)
Formulas are evaluated against NumPy arrays of raw fields using helper functions:
```python
def _iferror(val, fallback=0.0):
    return np.where(np.isfinite(val), val, fallback)

def _colsum(arr, group_mask):
    return np.sum(arr[group_mask])

def _colmean(arr, group_mask, min_minutes=1):
    # Calculates position average excluding players with zero minutes
    played = group_mask & (fields['minutes'] >= min_minutes)
    return np.mean(arr[played]) if np.any(played) else 0.0
```

### 5.3 Percentile Rank Algorithm (`percentile_ranks`)
Calculates the exact mid-rank percentile rank $P \in [0, 100]$ of query values against a comparison pool:

$$P = \frac{\text{count}(x < v) + 0.5 \cdot \text{count}(x = v)}{N} \times 100$$

Vectorized via NumPy searchsorted:
```python
def percentile_ranks(pool_vals, query_vals):
    pool = np.sort(pool_vals)
    n = pool.size
    if n == 0:
        return np.full(query_vals.shape, np.nan)
    lt = np.searchsorted(pool, query_vals, side='left')
    le = np.searchsorted(pool, query_vals, side='right')
    return ((lt + le) / (2.0 * n)) * 100.0
```
*Note on `lowerBetter`:* The server calculates raw percentiles ($0 \to 100$ where larger numbers yield higher percentiles). When `lowerBetter == True`, the frontend or client inverts the score: $P_{\text{inverted}} = 100.0 - P_{\text{raw}}$.

### 5.4 Profile Analytics (`analise_perfil.pyc`)
Provides specialized scatter plot matrices and contextual ratios:
- **Volume vs Quality:** `shots/90` vs `xg/shot`
- **Distance vs Accuracy:** `distance_km/90` vs `pass_accuracy_%`
- **Progression vs Safety:** `progressive_passes/90` vs `pass_completion_%`
- **Reactive vs Proactive Defending:** `interceptions/90` vs `tackles/90`
- **Creator vs Finisher:** `xa/90` vs `npxg/90`
- **Goalkeeper Efficiency:** `shots_faced/90` vs `goals_prevented/90`

---

## 6. Overall Rating System & Role Matrices

### 6.1 Architectural Principles (`overall.pyd`)
The Overall rating is a scalar $O \in [0, 100]$ calculated across three user-selectable modes:
- `atributos`: 100% attribute rating (what the player *is*).
- `estatistica`: 100% performance rating (what the player *did*).
- `misto`: 50% attribute + 50% performance (default).

When one half is uncomputable (e.g. unsimulated leagues without detailed match logs, or players with $< 900$ minutes), the available half automatically assumes 100% weight, flagged in the UI.

### 6.2 Attribute Rating Algorithm (`anotas_atributo`)
1. **Position Group Mapping (`GRUPO`):**
   - `gk` $\to$ `gk`
   - `dc`, `sw` $\to$ `cb`
   - `dl`, `dr`, `wbl`, `wbr` $\to$ `wb`
   - `dm` $\to$ `dm`
   - `mc` $\to$ `cm`
   - `ml`, `mr`, `aml`, `amr` $\to$ `am`
   - `amc` $\to$ `cm` (or `am` based on profile)
   - `st` $\to$ `st`
2. **Missing Attribute Reweighting:**
   Attributes with value `0` denote unrevealed scouting knowledge (not zero competence). Unrevealed attributes are excluded from both numerator and denominator:
   $$W_{\text{eff}} = \frac{\sum_{i \in \text{revealed}} w_i \cdot A_i}{\sum_{i \in \text{revealed}} w_i}$$
3. **Coverage Enforcement:**
   $$\text{Coverage} = \frac{\sum_{i \in \text{revealed}} w_i}{\sum_{\text{all } i} w_i}$$
   If $\text{Coverage} < 0.70$ (`COBERTURA_MINIMA`), attribute score evaluates to `NaN`.
4. **Truncated Z-Score Scaling:**
   $$\mu \approx 9.8, \quad \sigma \approx 1.2 \quad (\text{calibrated across 247,518 FM database players})$$
   $$z = \frac{W_{\text{eff}} - \mu}{\sigma}$$
   $$\text{Score}_{\text{attr}} = \text{clamp}\left(50 + \frac{z}{3.0} \cdot 50, \ 0, \ 100\right)$$

### 6.3 Performance Rating Algorithm (`anotas_desempenho`)
1. **Minimum Participation:** Requires $\ge 900$ minutes (`MINUTOS_MINIMOS = 900`, 10 full matches). Below 900 minutes, performance rating is `None`.
2. **Best-Fit Role Evaluation:** Evaluates candidate roles for the player's group. Computes weighted sum of metric percentiles:
   $$\text{Score}_{\text{role}} = \frac{\sum_j w_j \cdot P_j}{\sum_j w_j}$$
3. **Role Selection:**
   $$\text{Score}_{\text{perf}} = \max_{r \in \text{Roles}(\text{Group})} \text{Score}_r, \quad \text{BestRole} = \arg\max_{r \in \text{Roles}(\text{Group})} \text{Score}_r$$

### 6.4 Complete Role Metric Weight Matrix

| Position Group | Role ID | Display Name (PT / EN) | Metric Keys & Weights |
| :--- | :--- | :--- | :--- |
| **GK** | `paredao` | Paredão / Shot Stopper | `g:gk_xgp`: 5.0, `ui:defesas90`: 3.0, `ug:gk_semgol`: 2.5, `ug:gk_defesas`: 2.5, `ug:gk_penaltis`: 1.0, `ui:gk_dificeis`: 1.5 |
| **GK** | `goleiro_linha` | Goleiro-linha / Sweeper Keeper | `r:progressao`: 4.0, `ug:passes`: 3.0, `ui:passes90`: 2.5, `ug:gk_xgp`: 3.0, `ui:defesas90`: 2.0 |
| **CB** | `zagueiro_agressor` | Zagueiro agressor / Ball-Winning Defender | `i:desarmedec90`: 3.0, `ug:desarmes`: 2.5, `ug:aereo`: 2.5, `ui:aereos90`: 2.5, `ui:pressoes90`: 2.0, `ui:bloqueios90`: 1.5, `ui:cortes90`: 1.5 |
| **CB** | `zagueiro_construtor` | Zagueiro construtor / Ball-Playing Defender | `r:progressao`: 4.5, `ug:passes`: 3.5, `ui:passeschave90`: 2.0, `ui:desarmes90`: 1.0, `ui:aereos90`: 1.5, `ui:cortes90`: 1.5, `ui:xa90`: 1.0 |
| **WB** | `ala_ofensivo` | Ala ofensivo / Attacking Wing-Back | `ui:xa90`: 4.5, `ui:cruzamentos`: 3.0, `ui:passeschave90`: 2.5, `ui:chances90`: 2.0, `ui:dribles90`: 1.5, `r:progressao`: 1.5, `ui:possperdida90`: 1.5 (inv) |
| **WB** | `lateral_defensivo` | Lateral defensivo / Defensive Full-Back | `i:desarmedec90`: 3.0, `ug:desarmes`: 2.5, `ui:desarmes90`: 2.5, `ui:pressoes90`: 2.5, `ui:aereos90`: 2.0, `ug:aereo`: 1.5, `ui:dist90`: 1.5, `ui:possperdida90`: 1.5 (inv) |
| **WB** | `lateral_completo` | Lateral completo / Complete Wing-Back | `ui:xa90`: 3.0, `r:progressao`: 2.5, `ui:desarmes90`: 2.5, `ui:pressoes90`: 2.0, `ui:cruzamentos`: 1.0, `ug:desarmes`: 1.5, `ui:dist90`: 1.5, `ui:possperdida90`: 1.5 (inv) |
| **DM** | `volante_destruidor` | Volante destruidor / Ball-Winning Midfielder | `i:desarmedec90`: 3.0, `ui:pressoes90`: 1.0, `ug:desarmes`: 2.5, `ui:desarmes90`: 2.5, `ui:intercep90`: 2.0, `ui:aereos90`: 1.5, `ui:dist90`: 1.5, `ui:possperdida90`: 1.5 (inv) |
| **DM** | `volante_criador` | Volante criador / Deep-Lying Playmaker | `ui:passeschave90`: 4.0, `r:progressao`: 3.5, `ui:xa90`: 3.0, `ug:passes`: 2.5, `ui:chances90`: 2.0, `ui:desarmes90`: 1.5, `ui:possperdida90`: 2.0 (inv) |
| **CM** | `box_to_box` | Box-to-box / Box-to-Box Midfielder | `ui:xg90`: 2.5, `ui:xa90`: 2.5, `ui:pressoes90`: 3.0, `r:progressao`: 2.5, `ui:desarmes90`: 2.0, `ui:dist90`: 2.5, `ui:passeschave90`: 1.5, `ui:possperdida90`: 1.5 (inv) |
| **CM** | `meia_armador` | Meia armador / Advanced Playmaker | `ui:xa90`: 5.0, `ui:passeschave90`: 4.0, `ui:chances90`: 3.0, `r:progressao`: 2.5, `ug:passes`: 2.0, `ui:dribles90`: 1.5, `ui:possperdida90`: 2.0 (inv) |
| **AM** | `meia_armador` | Meia armador / Advanced Playmaker | `ui:xa90`: 5.0, `ui:passeschave90`: 4.0, `ui:chances90`: 3.0, `r:progressao`: 2.5, `ug:passes`: 2.0, `ui:dribles90`: 1.5, `ui:possperdida90`: 2.0 (inv) |
| **AM** | `meia_goleador` | Meia goleador / Shadow Striker | `ui:xg90`: 5.0, `ui:gols90`: 2.5, `ui:chutes90`: 2.5, `ui:finalizacoes`: 2.0, `ui:chances90`: 1.0, `ui:xa90`: 1.5, `ui:possperdida90`: 1.5 (inv) |
| **AM** | `meia_completo` | Meia completo / Complete Attacking Midfielder | `ui:xg90`: 3.0, `ui:xa90`: 1.0, `ui:chances90`: 2.5, `ui:passeschave90`: 2.0, `ui:dribles90`: 1.0, `r:progressao`: 1.0, `ui:possperdida90`: 1.5 (inv) |
| **WING** | `ponta_driblador` | Ponta driblador / Winger | `ui:dribles90`: 4.0, `ui:xa90`: 3.0, `ui:cruzamentos`: 2.5, `ui:chances90`: 2.0, `ui:xg90`: 1.0, `r:progressao`: 1.5 |
| **WING** | `ponta_finalizador` | Ponta finalizador / Inside Forward | `ui:xg90`: 4.5, `ui:gols90`: 3.0, `ui:chutes90`: 2.5, `ui:finalizacoes`: 2.0, `ui:chances90`: 1.0, `ui:dribles90`: 1.5 |
| **WING** | `ponta_trabalhador` | Ponta trabalhador / Inverted Winger | `ui:pressoes90`: 3.5, `ui:dist90`: 3.0, `ui:desarmes90`: 2.5, `ui:xa90`: 2.5, `ui:cruzamentos`: 2.0, `ui:dribles90`: 1.5 |
| **ST** | `finalizador` | Finalizador / Poacher | `ui:xg90`: 5.0, `ui:gols90`: 3.0, `ui:chutes90`: 2.5, `ui:finalizacoes`: 2.5, `ui:chances90`: 2.0 |
| **ST** | `atacante_pressao` | Atacante de pressão / Pressing Forward | `ui:xg90`: 3.5, `ui:pressoes90`: 3.5, `ui:dist90`: 2.5, `ui:gols90`: 2.0, `ui:aereos90`: 1.0, `ui:chances90`: 1.5 |
| **ST** | `atacante_criativo` | Atacante criativo / Deep-Lying Forward | `ui:xa90`: 4.0, `ui:passeschave90`: 3.0, `ui:xg90`: 1.0, `ui:dribles90`: 2.5, `ui:chances90`: 2.0 |

---

## 7. Season Rollover Mechanics & View Handling

### 7.1 Season Rollover Engine (`fim_de_temporada.pyc`)
1. **League State Detection (`estado_das_ligas`):**
   - Scans competition schedule arrays (`ler_agenda(reader)`).
   - If the last official fixture date $\le$ current game date, state is `'fechada'` (completed). Otherwise `'em_andamento'` (in progress).
2. **User Season Boundary Identification (`cobertas_pela_temporada_do_usuario`):**
   - Finds the user's primary league competition UID via `liga_principal()`.
   - Obtains season end date `fim_do_usuario`.
   - Defines snapshot capture window:
     $$\text{limite} = \text{save\_date} + \text{timedelta}(\text{days}=\text{TOLERANCIA\_DEPOIS\_DO\_USUARIO})$$
   - Identifies all competitions whose season finishes between previous season cutoff and `limite`.
3. **Automated Reading Plan (`plano_de_leituras`):**
   - Computes minimum waiting schedule to batch snapshot captures when all major loaded leagues conclude, minimizing game interruption.

### 7.2 `.fmf` View Parser (`view_fmf.pyc` & `view_fmf_colunas.pyc`)
1. **Container Validation:**
   - Enforces a 2 MB maximum size limit (`_conferir_tamanho`).
   - Verifies the Football Manager container header and searches for `ViewSettingsCollectionName`.
2. **View Destination Classification (`destino_da_tela`):**
   - `squad` / `plantel`: Accepted for squad screen ("Meu time").
   - `search` / `base`: Accepted for scouting database screen ("Base").
   - `tactics` / `tatica`: Rejected (`ViewDeTatica`: "Esta view e da tela de tatica do FM, que nao existe no app").
   - `shortlist` / `lista`: Rejected (`ViewDeLista`: "Views da lista preferencial do FM nao entram no app").
3. **Column Mapping (`view_fmf_colunas.py`):**
   Maps 467 FM internal chalkboard string identifiers directly to FMSH SQLite database columns (e.g. `'chalkboard-stats-expected-goals-prevented'` $\to$ `xg_prevented_gk`, `'chalkboard-stats-interceptions-per90'` $\to$ `interceptions`, `'chalkboard-stats-distance-covered'` $\to$ `distance_km`).

---

## 8. Verification and Evidence Summary

| Analysis Target | Verification Tool / Provider | Status | Output Artifact |
| :--- | :--- | :--- | :--- |
| Frontend SPA API Endpoints | AST Regex extraction / Node.js | Complete | `rea-output/recovered-frontend/endpoints.json` (129 SPA endpoints) |
| Backend Server Routes | PE string & Symbol analysis | Complete | 153 total routes identified in `server.pyd` |
| Py3.14 Custom Bytecode | Native Python 3.14 `marshal` & `dis` | Complete | `rea-output/decompiled_pyc/*.dis.txt` (19 disassembled modules) |
| SQLite Schema & Migrations | Nuitka PE constants extraction | Complete | Exact DDL for 17 tables, indexes, and migrations documented |
| Moneyball Engine | Catalog JSON & vectorized NumPy review | Complete | Catalog keys, `percentile_ranks` searchsorted algorithm validated |
| Overall Rating Algorithm | Nuitka binary blob deserializer | Complete | 19 roles, exact weights, Z-score cutoffs, and constants confirmed |
| Rollover & `.fmf` Handling | Bytecode disassembly & analysis | Complete | State machine and view parser specifications documented |
