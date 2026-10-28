"""Motor de analise estatistica e metricas Moneyball para o Football Manager.

Carrega catalogos de formulas (moneyball_catalog.json, moneyball_rotulos.json,
moneyball_siglas.json), calcula metricas per-90 derivadas e computa
percentis exatos (mid-rank percentile ranks) sobre matrizes NumPy.
"""

import json
import os
import unicodedata
import numpy as np
import paths

POSITION_GROUPS_ORDER = ["gk", "def", "wing", "dm", "b2b", "amc", "att"]

GROUP_POSITIONS = {
    "gk": ["gk"],
    "def": ["dc", "sw"],
    "wing": ["dl", "dr", "wbl", "wbr"],
    "dm": ["dm"],
    "b2b": ["mc"],
    "amc": ["aml", "amr", "amc"],
    "att": ["st"],
}

COHORT_POSITIONS = {
    "gk": ["gk"],
    "def": ["dc", "sw"],
    "wing": ["dl", "dr", "wbl", "wbr"],
    "dm": ["dm"],
    "b2b": ["mc"],
    "amc": ["aml", "amr", "amc"],
    "att": ["st"],
}

FIELD_THEME = {
    "goleiro": [
        "clean_sheets_gk",
        "goals_conceded_gk",
        "gk_saves_held",
        "gk_saves_tipped",
        "gk_penalties_saved",
        "gk_xg_shots_faced",
        "gk_saves_parried",
        "xg_prevented_gk",
        "gk_penalties_faced",
    ],
    "aereo": ["headers_attempted", "headers_won", "headers_lost", "headers_key"],
    "defesa": [
        "tackles_attempted",
        "tackles_completed",
        "tackles_key",
        "interceptions",
        "clearances",
        "blocks",
        "possession_won",
    ],
    "finalizacao": [
        "goals",
        "shots",
        "shots_on_target",
        "xg",
        "npxg",
        "goals_outside_box",
        "shots_outside_box",
    ],
    "criacao": [
        "assists",
        "xa",
        "key_passes",
        "key_passes_open_play",
        "clear_cut_chances",
        "passes_attempted",
        "passes_completed",
        "passes_progressive",
        "crosses_attempted",
        "crosses_completed",
    ],
    "disciplina": ["fouls_committed", "fouls_won", "yellow_cards", "red_cards", "possession_lost"],
    "fisico": ["distance_km", "sprints", "presses_attempted", "presses_completed"],
}

GENERAL_CORE = [
    "apps_total",
    "apps_starts",
    "apps_sub",
    "minutes",
    "avg_rating",
    "goals",
    "assists",
    "xg",
    "xa",
]

GENERAL_LABELS = {
    "apps_total": "Jogos",
    "apps_starts": "Titular",
    "apps_sub": "Reserva",
    "minutes": "Minutos",
    "avg_rating": "Classif. Média",
    "goals": "Gols",
    "assists": "Assistências",
    "xg": "xG",
    "xa": "xA",
}

DEFAULT_VISIBLE = [
    "minutes",
    "avg_rating",
    "goals",
    "assists",
    "xg",
    "xa",
    "passes_completed",
    "tackles_completed",
]

RAW_FIELDS = [
    "minutes",
    "apps_total",
    "apps_starts",
    "apps_sub",
    "goals",
    "assists",
    "avg_rating",
    "yellow_cards",
    "red_cards",
    "penalties_taken",
    "penalties_scored",
    "passes_attempted",
    "passes_completed",
    "passes_progressive",
    "key_passes",
    "key_passes_open_play",
    "clear_cut_chances",
    "shots",
    "shots_on_target",
    "shots_outside_box",
    "shots_blocked",
    "goals_outside_box",
    "dribbles",
    "crosses_attempted",
    "crosses_completed",
    "tackles_attempted",
    "tackles_completed",
    "tackles_key",
    "interceptions",
    "clearances",
    "blocks",
    "headers_attempted",
    "headers_won",
    "headers_lost",
    "headers_key",
    "fouls_committed",
    "fouls_won",
    "sprints",
    "presses_attempted",
    "presses_completed",
    "distance_km",
    "possession_won",
    "possession_lost",
    "xg",
    "xa",
    "npxg",
    "goals_conceded_gk",
    "clean_sheets_gk",
    "xg_prevented_gk",
    "gk_saves_held",
    "gk_saves_parried",
    "gk_saves_tipped",
    "gk_penalties_faced",
    "gk_penalties_saved",
    "gk_xg_faced",
    "gk_xg_shots_faced",
]

BROWSE_RAW_FIELDS = list(RAW_FIELDS)
NEUTRAL_FIELDS = ["minutes", "apps_total", "apps_starts", "apps_sub", "distance_km"]
DUAL_GK_FIELDS = ["clean_sheets_gk", "goals_conceded_gk", "xg_prevented_gk"]
DUAL_OUTFIELD_FIELDS = ["goals", "assists", "xg", "xa"]
ANCHORS = {}

# Carrega os arquivos JSON estaticos
def _carregar_json(nome):
    caminhos = [
        paths.resource_path("src", nome),
        paths.resource_path(nome),
        os.path.join(os.path.dirname(__file__), nome),
        os.path.join(os.path.dirname(__file__), "..", "fmsh", "src", nome),
    ]
    for c in caminhos:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


CATALOG = _carregar_json("moneyball_catalog.json")
ROTULOS = _carregar_json("moneyball_rotulos.json")
CATALOG_ALIAS = _carregar_json("moneyball_siglas.json")
CATALOG_BY_KEY = {}

if isinstance(CATALOG, dict):
    for grp, itens in CATALOG.items():
        if isinstance(itens, list):
            for it in itens:
                if isinstance(it, dict) and "key" in it:
                    CATALOG_BY_KEY[it["key"]] = it

CATALOG_OCULTAS = set()
CATALOG_PATCH = {}
CATALOG_DROP = set()
FABRICATED_FALLBACKS = {5000, 5400, 100, 300, 50, 25}


def _iferror(val, fallback=0.0):
    """Substitui infinitos por valor de fallback seguro, mas preserva NaNs de estatisticas nao medidas."""
    if fallback in FABRICATED_FALLBACKS:
        fallback = np.nan
    arr = np.asarray(val, dtype=np.float64)
    return np.where(np.isnan(arr), np.nan, np.where(np.isneginf(arr) | np.isposinf(arr), fallback, arr))


def _per90(val, minutes):
    """Calcula estatistica por 90 minutos de jogo."""
    val = np.asarray(val, dtype=np.float64)
    minutes = np.asarray(minutes, dtype=np.float64)
    valid = np.isfinite(val) & np.isfinite(minutes) & (minutes > 0)
    with np.errstate(divide='ignore', invalid='ignore'):
        res = (val / minutes) * 90.0
    return np.where(valid, res, np.nan)


def _pct(num, den):
    """Calcula porcentagem segura entre dois campos."""
    num = np.asarray(num, dtype=np.float64)
    den = np.asarray(den, dtype=np.float64)
    valid = np.isfinite(num) & np.isfinite(den) & (den > 0)
    with np.errstate(divide='ignore', invalid='ignore'):
        res = (num / den) * 100.0
    return np.where(valid, res, np.nan)


def _norm_label(lbl):
    if not lbl:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(lbl))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _sigla_key(k):
    return CATALOG_ALIAS.get(k, k)


def is_general(key):
    return key in GENERAL_CORE


def column_theme(key):
    for tema, campos in FIELD_THEME.items():
        if key in campos:
            return tema
    return "geral"


def column_scope(key):
    if key.startswith("gk_"):
        return "gk"
    return "outfield"


def column_is_safe_for(key, role):
    return True


def column_fields(key):
    meta = CATALOG_BY_KEY.get(key)
    if meta and "expr" in meta:
        # Extrai nomes de campos f['...']
        import re
        return re.findall(r"f\['([a-zA-Z0-9_]+)'\]", meta["expr"])
    return [key]


def visible_columns():
    return list(DEFAULT_VISIBLE)


# General headings use shorter labels than the language-file source names.
GENERAL_LOCALE = {
    "apps_total": ("jogostotais", "Total Appearances", "Apps"),
    "apps_starts": ("jogoscomotitular", "Starting Appearances", "St Apps"),
    "apps_sub": ("entradasdobanco", "Sub Appearances", "Sub"),
    "minutes": ("minutos", "Minutes", "Mins"),
    "avg_rating": ("classifmedia", "Average Rating", "Av Rat"),
    "goals": ("gols", "Goals", "Gls"),
    "assists": ("assistencias", "Assists", "Ast"),
    "xg": ("golsesperadosxg", "Expected Goals (xG)", "xG"),
    "xa": ("assistenciasesperadasxa", "Expected Assists (xA)", "xA"),
}


def column_locale(column):
    """Attach the stable language-file key without changing stored catalog labels."""
    def normalize(label):
        return "".join(c for c in _norm_label(label) if c.isalnum() or c == "%")

    key = normalize(column.get("label"))
    key = normalize(ROTULOS.get(key, column.get("label")))
    return {**column, "tkey": key}


def general_columns_meta():
    return [
        {"key": key, "label": GENERAL_LABELS[key],
         "tkey": GENERAL_LOCALE[key][0], "labelEn": GENERAL_LOCALE[key][1],
         "shortEn": GENERAL_LOCALE[key][2],
         "fmt": "rating" if key == "avg_rating" else "dec2" if key in {"xg", "xa"} else "int",
         "general": True, "section": "geral", "type": "num"}
        for key in GENERAL_CORE
    ]


def group_columns_meta(group):
    itens = CATALOG.get(group, []) if isinstance(CATALOG, dict) else []
    return itens


def columns_meta(keys=None):
    if keys is None:
        return CATALOG
    res = []
    for k in keys:
        if k in CATALOG_BY_KEY:
            res.append(CATALOG_BY_KEY[k])
    return res


def percentile_ranks(pool_vals, query_vals):
    """Calcula percentis mid-rank P = (count(x < v) + 0.5 * count(x == v)) / N * 100."""
    p_arr = np.asarray(pool_vals, dtype=np.float64)
    q_arr = np.asarray(query_vals, dtype=np.float64)

    validos = p_arr[np.isfinite(p_arr)]
    n = validos.size
    if n == 0:
        return np.full(q_arr.shape, np.nan, dtype=np.float64)

    pool = np.sort(validos)
    lt = np.searchsorted(pool, q_arr, side="left")
    le = np.searchsorted(pool, q_arr, side="right")
    return ((lt + le) / (2.0 * n)) * 100.0


def derive(raw_dict, position_group=None):
    """Calcula metricas basicas e derivadas de um conjunto de vetores de jogadores."""
    f = {k: np.asarray(v, dtype=np.float64) for k, v in raw_dict.items()}
    mins = f.get("minutes", np.zeros(1, dtype=np.float64))

    r = {}
    r["minutes"] = mins
    for k in ("goals", "assists", "xg", "xa", "shots", "passes_completed", "tackles_completed", "interceptions"):
        if k in f:
            r[k] = f[k]
            r[f"{k}_per90"] = _per90(f[k], mins)

    if "xg" in f and "shots" in f:
        shots = f["shots"]
        valid = np.isfinite(f["xg"]) & np.isfinite(shots) & (shots > 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            res = f["xg"] / shots
        r["xg_per_shot"] = np.where(valid, res, np.nan)

    if "passes_completed" in f and "passes_attempted" in f:
        r["pass_accuracy_pct"] = _pct(f["passes_completed"], f["passes_attempted"])

    if "tackles_completed" in f and "tackles_attempted" in f:
        r["tackle_success_pct"] = _pct(f["tackles_completed"], f["tackles_attempted"])

    return r


def derive_extra(derived_dict):
    return derived_dict


def derive_catalog(raw_dict, group=None):
    """Avalia o catalogo completo de formulas para o grupo posicional especificado."""
    f = {k: np.asarray(v, dtype=np.float64) for k, v in raw_dict.items()}
    r = {}

    mins = f.get("minutes")
    has_mins = (mins is not None) and (np.asarray(mins) > 0) & np.isfinite(np.asarray(mins))

    grp_itens = CATALOG.get(group, []) if (group and isinstance(CATALOG, dict)) else []
    for item in grp_itens:
        chave = item.get("key")
        expr = item.get("expr")
        if not chave or not expr:
            continue
        try:
            # Avalia formula segura com f e r
            val = eval(expr, {"__builtins__": None, "np": np, "_iferror": _iferror}, {"f": f, "r": r})
            arr = np.asarray(val, dtype=np.float64)
        except Exception:
            arr = np.full(len(next(iter(f.values()))), np.nan, dtype=np.float64) if f else np.zeros(0)

        lbl = item.get("label", "")
        is_rate = (
            "Minutos pra" in lbl
            or "Minutos por" in lbl
            or "pra um gol" in lbl
            or "pra 1 gol" in lbl
            or "pra uma" in lbl
            or "pra um" in lbl
            or "/90" in lbl
            or "/ 90" in lbl
            or chave in {
                "b2b_BB", "amc_V", "att_X", "gk_P", "def_AF",
                "b2b_AH", "att_BW", "amc_CH", "amc_CI", "att_CI", "att_CH",
                "att_CF", "att_CG", "att_BX", "att_BY", "b2b_AI",
                "dm_AG", "dm_AH", "b2b_DF", "amc_BR", "wing_BQ", "wing_BR",
                "amc_BV", "amc_BW", "gk_BD", "gk_BE", "gk_BF"
            }
        )

        if is_rate:
            if mins is not None:
                arr = np.where(has_mins, arr, np.nan)

            if chave in {"b2b_AH", "att_BW", "amc_CH", "att_BX", "att_BY", "amc_CI"}:
                shots = f.get("shots", np.zeros_like(arr))
                goals = f.get("goals", np.zeros_like(arr))
                valid = np.isfinite(shots) & (shots > 0) & np.isfinite(goals) & (goals > 0)
                arr = np.where(valid, arr, np.nan)
            elif chave in {"b2b_BB", "amc_V", "att_X", "gk_P", "def_AF"}:
                pom = f.get("man_of_the_match")
                if pom is None and "gk_O" in r:
                    pom = r["gk_O"]
                if pom is None and "b2b_BA" in r:
                    pom = r["b2b_BA"]
                if pom is None and "amc_U" in r:
                    pom = r["amc_U"]
                if pom is None and "att_W" in r:
                    pom = r["att_W"]
                if pom is not None:
                    valid_pom = np.isfinite(pom) & (pom > 0)
                    arr = np.where(valid_pom, arr, np.nan)
                else:
                    arr = np.full_like(arr, np.nan)
            elif chave == "att_CI":
                contrib = r.get("att_AB")
                if contrib is None:
                    g = f.get("goals")
                    a = f.get("assists")
                    if g is not None and a is not None:
                        contrib = g + a
                if contrib is not None:
                    valid_contrib = np.isfinite(contrib) & (contrib > 0)
                    arr = np.where(valid_contrib, arr, np.nan)
                else:
                    arr = np.full_like(arr, np.nan)
            elif chave == "att_CH":
                goals = f.get("goals", np.zeros_like(arr))
                valid_goals = np.isfinite(goals) & (goals > 0)
                arr = np.where(valid_goals, arr, np.nan)
            elif chave in {"att_CF", "att_CG"}:
                shots = f.get("shots" if chave == "att_CF" else "shots_on_target", np.zeros_like(arr))
                valid_shots = np.isfinite(shots) & (shots > 0)
                arr = np.where(valid_shots, arr, np.nan)
            elif chave in {"dm_AG", "dm_AH"}:
                fouls = f.get("fouls_committed", np.zeros_like(arr))
                cards = f.get("yellow_cards", np.zeros_like(arr))
                if chave == "dm_AH":
                    cards = cards + f.get("red_cards", np.zeros_like(arr))
                valid_fc = np.isfinite(fouls) & (fouls > 0) & np.isfinite(cards) & (cards > 0)
                arr = np.where(valid_fc, arr, np.nan)
            elif chave in {"b2b_DF", "amc_BR"}:
                kp = f.get("key_passes", np.zeros_like(arr))
                ast = f.get("assists", np.zeros_like(arr))
                valid_ka = np.isfinite(kp) & (kp > 0) & np.isfinite(ast) & (ast > 0)
                arr = np.where(valid_ka, arr, np.nan)
            elif chave in {"wing_BR", "amc_BV"}:
                kp = f.get("key_passes", np.zeros_like(arr))
                valid_kp = np.isfinite(kp) & (kp > 0)
                arr = np.where(valid_kp, arr, np.nan)

        r[chave] = arr

    return r
