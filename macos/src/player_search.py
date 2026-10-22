"""Motor de busca e filtragem dinamica de jogadores (player search).

Avalia condicoes combinadas (AND/OR, operadores numericos e textuais) sobre vetores
NumPy com suporte a legados e payload v2.
"""

import unicodedata
import numpy as np

FIELD_OPS = {
    "field_gt",
    "field_gte",
    "field_lt",
    "field_lte",
    "field_eq",
    "field_ne",
}

NUM_OPS = {
    "gt",
    "gte",
    "lt",
    "lte",
    "eq",
    "ne",
    "between",
} | FIELD_OPS

TEXT_OPS = {
    "is",
    "is_not",
    "contains",
    "starts_with",
    "ends_with",
}

OPS_BY_TYPE = {
    "num": NUM_OPS,
    "text": TEXT_OPS,
}

VALUE_SLOTS = {
    "between": 2,
}


def _finito(val):
    try:
        f = float(val)
        return f if np.isfinite(f) else None
    except Exception:
        return None


def _dobra(s):
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def normalize_str(s):
    return _dobra(s)


def ops_for(field_type):
    return OPS_BY_TYPE.get(field_type, NUM_OPS)


def normalize(search_json=None, legacy_conds=None):
    """Aceita o payload v2 novo e o `conds=` antigo, devolvendo sempre a lista v2.

    O legado continua valendo pra SEMPRE: ele alimenta as URLs de `export.csv` que os
    beta testers ja tem salvas e o localStorage de quem nao limpou cache.
    """
    conds = []

    if isinstance(search_json, dict) and "conds" in search_json:
        bruto = search_json.get("conds", [])
    elif isinstance(search_json, list):
        bruto = search_json
    elif legacy_conds is not None:
        bruto = legacy_conds
    else:
        bruto = []

    for item in bruto:
        if not isinstance(item, dict):
            continue
        c = dict(item)
        c.setdefault("on", True)
        c.setdefault("logic", "and")
        if "col" in c and "field" not in c:
            c["field"] = c.pop("col")
        if "v2" in c and "val2" not in c:
            c["val2"] = c.pop("v2")
        conds.append(c)

    return conds


def segments(conds):
    """Divide a lista de condicoes em segmentos logicos."""
    if not conds:
        return []
    segs = []
    atual = []
    for c in conds:
        if c.get("logic") == "or" and atual:
            segs.append(atual)
            atual = [c]
        else:
            atual.append(c)
    if atual:
        segs.append(atual)
    return segs


def num_mask(arr, op, val, outro=None):
    """Mascara de um operador numerico. `outro` e a coluna do lado direito nos
    comparadores campo-a-campo.
    """
    a = np.asarray(arr, dtype=np.float64)
    n = a.shape[0]

    if op in FIELD_OPS:
        if outro is None:
            return np.zeros(n, dtype=bool)
        b = np.asarray(outro, dtype=np.float64)
        if op == "field_gt":
            return a > b
        elif op == "field_gte":
            return a >= b
        elif op == "field_lt":
            return a < b
        elif op == "field_lte":
            return a <= b
        elif op == "field_eq":
            return a == b
        elif op == "field_ne":
            return a != b
        return np.zeros(n, dtype=bool)

    v1 = _finito(val)
    if v1 is None and op != "between":
        return np.zeros(n, dtype=bool)

    if op == "gt":
        return a > v1
    elif op == "gte":
        return a >= v1
    elif op == "lt":
        return a < v1
    elif op == "lte":
        return a <= v1
    elif op == "eq":
        return a == v1
    elif op == "ne":
        return a != v1
    elif op == "between":
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            lo, hi = _finito(val[0]), _finito(val[1])
            if lo is not None and hi is not None:
                return (a >= min(lo, hi)) & (a <= max(lo, hi))
        return np.zeros(n, dtype=bool)

    return np.zeros(n, dtype=bool)


def text_mask(valores, op, alvo):
    """Avalia condicoes textuais sobre listas de strings."""
    alvo_norm = _dobra(alvo)
    res = []
    for item in valores:
        val_norm = _dobra(item)
        if op == "is":
            res.append(val_norm == alvo_norm)
        elif op == "is_not":
            res.append(val_norm != alvo_norm)
        elif op == "contains":
            res.append(alvo_norm in val_norm)
        elif op == "starts_with":
            res.append(val_norm.startswith(alvo_norm))
        elif op == "ends_with":
            res.append(val_norm.endswith(alvo_norm))
        else:
            res.append(False)
    return np.array(res, dtype=bool)


def evaluate(conds, cond_mask):
    """`conds`: lista v2 na ORDEM da tela. `cond_mask`: callable(cond) -> ndarray(bool)
    ou None (condicao invalida -> ignorada + registrada). Devolve (mask, warnings).
    """
    avisos = []
    ativas = [c for c in conds if c.get("on", True)]
    if not ativas:
        return None, avisos

    segs = segments(ativas)
    seg_mascaras = []

    for seg in segs:
        # Dentro de cada segmento o operador e AND
        parcial = None
        for c in seg:
            m = cond_mask(c)
            if m is None:
                avisos.append({"id": c.get("id"), "field": c.get("field"), "why": "unsupported"})
                continue
            if parcial is None:
                parcial = m
            else:
                parcial = parcial & m
        if parcial is not None:
            seg_mascaras.append(parcial)

    if not seg_mascaras:
        return None, avisos

    # Combina segmentos com OR
    acumulado = seg_mascaras[0]
    for m in seg_mascaras[1:]:
        acumulado = acumulado | m

    return acumulado, avisos
