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


def _iferror(val, fallback=0.0):
    """Substitui NaNs e infinitos por valor de fallback seguro."""
    return np.where(np.isfinite(val), val, fallback)


def _per90(val, minutes):
    """Calcula estatistica por 90 minutos de jogo."""
    mins = np.maximum(minutes, 1)
    return _iferror((val / mins) * 90.0, 0.0)


def _pct(num, den):
    """Calcula porcentagem segura entre dois campos."""
    d = np.maximum(den, 1)
    return _iferror((num / d) * 100.0, 0.0)


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
        r["xg_per_shot"] = _iferror(f["xg"] / np.maximum(f["shots"], 1), 0.0)

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

    grp_itens = CATALOG.get(group, []) if (group and isinstance(CATALOG, dict)) else []
    for item in grp_itens:
        chave = item.get("key")
        expr = item.get("expr")
        if not chave or not expr:
            continue
        try:
            # Avalia formula segura com f e r
            val = eval(expr, {"__builtins__": None, "np": np, "_iferror": _iferror}, {"f": f, "r": r})
            r[chave] = np.asarray(val, dtype=np.float64)
        except Exception:
            r[chave] = np.zeros(len(next(iter(f.values()))), dtype=np.float64) if f else np.zeros(0)

    return r
