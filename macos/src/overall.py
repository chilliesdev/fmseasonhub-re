"""Sistema de avaliacao Overall do FM Season Hub (19 papeis tatica, atributos e desempenho).

Calcula notas escaladas de 0 a 100 nos modos 'atributos', 'estatistica' e 'misto',
com normalizacao por Z-score truncado para atributos e media ponderada de percentis
mid-rank para estatisticas por papel tatico.
"""

import numpy as np

MODOS = ("atributos", "estatistica", "misto")
MODO_PADRAO = "misto"
COBERTURA_MINIMA = 0.70
MINUTOS_MINIMOS = 900
Z_CORTE = 3.0
PESO_ESTATISTICA = 0.5
SEM_DADO_ESTIMADO = 50.0
ESTIMADO_SEM_DESEMPENHO = True

GRUPO = {
    "gk": "gk",
    "dc": "cb",
    "sw": "cb",
    "dl": "wb",
    "dr": "wb",
    "wbl": "wb",
    "wbr": "wb",
    "dm": "dm",
    "mc": "cm",
    "ml": "am",
    "mr": "am",
    "aml": "wing",
    "amr": "wing",
    "amc": "am",
    "st": "st",
}
GRUPO_PADRAO = "cm"

PAPEIS = {
    "gk": ["paredao", "goleiro_linha"],
    "cb": ["zagueiro_agressor", "zagueiro_construtor"],
    "wb": ["ala_ofensivo", "lateral_defensivo", "lateral_completo"],
    "dm": ["volante_destruidor", "volante_criador"],
    "cm": ["box_to_box", "meia_armador"],
    "am": ["meia_armador", "meia_goleador", "meia_completo"],
    "wing": ["ponta_driblador", "ponta_finalizador", "ponta_trabalhador"],
    "st": ["finalizador", "atacante_pressao", "atacante_criativo"],
}

ROTULO_PAPEL = {
    "paredao": "Paredão / Shot Stopper",
    "goleiro_linha": "Goleiro-linha / Sweeper Keeper",
    "zagueiro_agressor": "Zagueiro agressor / Ball-Winning Defender",
    "zagueiro_construtor": "Zagueiro construtor / Ball-Playing Defender",
    "ala_ofensivo": "Ala ofensivo / Attacking Wing-Back",
    "lateral_defensivo": "Lateral defensivo / Defensive Full-Back",
    "lateral_completo": "Lateral completo / Complete Wing-Back",
    "volante_destruidor": "Volante destruidor / Ball-Winning Midfielder",
    "volante_criador": "Volante criador / Deep-Lying Playmaker",
    "box_to_box": "Box-to-box / Box-to-Box Midfielder",
    "meia_armador": "Meia armador / Advanced Playmaker",
    "meia_goleador": "Meia goleador / Shadow Striker",
    "meia_completo": "Meia completo / Complete Attacking Midfielder",
    "ponta_driblador": "Ponta driblador / Winger",
    "ponta_finalizador": "Ponta finalizador / Inside Forward",
    "ponta_trabalhador": "Ponta trabalhador / Inverted Winger",
    "finalizador": "Finalizador / Poacher",
    "atacante_pressao": "Atacante de pressão / Pressing Forward",
    "atacante_criativo": "Atacante criativo / Deep-Lying Forward",
}

INVERSAS = {"possperdida90", "sofridos90", "gk_falhas90"}

METRICAS = {
    "paredao": {
        "gk_xgp": 5.0,
        "defesas90": 3.0,
        "gk_semgol": 2.5,
        "gk_defesas": 2.5,
        "gk_penaltis": 1.0,
        "gk_dificeis": 1.5,
    },
    "goleiro_linha": {
        "progressao": 4.0,
        "passes": 3.0,
        "passes90": 2.5,
        "gk_xgp": 3.0,
        "defesas90": 2.0,
    },
    "zagueiro_agressor": {
        "desarmedec90": 3.0,
        "desarmes": 2.5,
        "aereo": 2.5,
        "aereos90": 2.5,
        "pressoes90": 2.0,
        "bloqueios90": 1.5,
        "cortes90": 1.5,
    },
    "zagueiro_construtor": {
        "progressao": 4.5,
        "passes": 3.5,
        "passeschave90": 2.0,
        "desarmes90": 1.0,
        "aereos90": 1.5,
        "cortes90": 1.5,
        "xa90": 1.0,
    },
    "ala_ofensivo": {
        "xa90": 4.5,
        "cruzamentos": 3.0,
        "passeschave90": 2.5,
        "chances90": 2.0,
        "dribles90": 1.5,
        "progressao": 1.5,
        "possperdida90": 1.5,
    },
    "lateral_defensivo": {
        "desarmedec90": 3.0,
        "desarmes": 2.5,
        "desarmes90": 2.5,
        "pressoes90": 2.5,
        "aereos90": 2.0,
        "aereo": 1.5,
        "dist90": 1.5,
        "possperdida90": 1.5,
    },
    "lateral_completo": {
        "xa90": 3.0,
        "progressao": 2.5,
        "desarmes90": 2.5,
        "pressoes90": 2.0,
        "cruzamentos": 1.0,
        "desarmes": 1.5,
        "dist90": 1.5,
        "possperdida90": 1.5,
    },
    "volante_destruidor": {
        "desarmedec90": 3.0,
        "pressoes90": 1.0,
        "desarmes": 2.5,
        "desarmes90": 2.5,
        "intercep90": 2.0,
        "aereos90": 1.5,
        "dist90": 1.5,
        "possperdida90": 1.5,
    },
    "volante_criador": {
        "passeschave90": 4.0,
        "progressao": 3.5,
        "xa90": 3.0,
        "passes": 2.5,
        "chances90": 2.0,
        "desarmes90": 1.5,
        "possperdida90": 2.0,
    },
    "box_to_box": {
        "xg90": 2.5,
        "xa90": 2.5,
        "pressoes90": 3.0,
        "progressao": 2.5,
        "desarmes90": 2.0,
        "dist90": 2.5,
        "passeschave90": 1.5,
        "possperdida90": 1.5,
    },
    "meia_armador": {
        "xa90": 5.0,
        "passeschave90": 4.0,
        "chances90": 3.0,
        "progressao": 2.5,
        "passes": 2.0,
        "dribles90": 1.5,
        "possperdida90": 2.0,
    },
    "meia_goleador": {
        "xg90": 5.0,
        "gols90": 2.5,
        "chutes90": 2.5,
        "finalizacoes": 2.0,
        "chances90": 1.0,
        "xa90": 1.5,
        "possperdida90": 1.5,
    },
    "meia_completo": {
        "xg90": 3.0,
        "xa90": 1.0,
        "chances90": 2.5,
        "passeschave90": 2.0,
        "dribles90": 1.0,
        "progressao": 1.0,
        "possperdida90": 1.5,
    },
    "ponta_driblador": {
        "dribles90": 4.0,
        "xa90": 3.0,
        "cruzamentos": 2.5,
        "chances90": 2.0,
        "xg90": 1.0,
        "progressao": 1.5,
    },
    "ponta_finalizador": {
        "xg90": 4.5,
        "gols90": 3.0,
        "chutes90": 2.5,
        "finalizacoes": 2.0,
        "chances90": 1.0,
        "dribles90": 1.5,
    },
    "ponta_trabalhador": {
        "pressoes90": 3.5,
        "dist90": 3.0,
        "desarmes90": 2.5,
        "xa90": 2.5,
        "cruzamentos": 2.0,
        "dribles90": 1.5,
    },
    "finalizador": {
        "xg90": 5.0,
        "gols90": 3.0,
        "chutes90": 2.5,
        "finalizacoes": 2.5,
        "chances90": 2.0,
    },
    "atacante_pressao": {
        "xg90": 3.5,
        "pressoes90": 3.5,
        "dist90": 2.5,
        "gols90": 2.0,
        "aereos90": 1.0,
        "chances90": 1.5,
    },
    "atacante_criativo": {
        "xa90": 4.0,
        "passeschave90": 3.0,
        "xg90": 1.0,
        "dribles90": 2.5,
        "chances90": 2.0,
    },
}

PESOS_ATRIBUTO = {
    "gk": {
        "reflexes": 5.0,
        "handling": 4.0,
        "one_on_ones": 4.0,
        "aerial_reach": 3.5,
        "command_of_area": 3.0,
        "positioning": 3.0,
        "communication": 2.5,
        "kicking": 2.5,
        "agility": 3.0,
        "anticipation": 3.0,
        "concentration": 3.0,
        "decisions": 3.0,
    },
    "cb": {
        "tackling": 5.0,
        "marking": 4.5,
        "heading": 4.5,
        "positioning": 4.5,
        "jumping_reach": 4.0,
        "strength": 4.0,
        "anticipation": 3.5,
        "bravery": 3.5,
        "concentration": 3.5,
        "decisions": 3.5,
        "pace": 3.0,
        "stamina": 3.0,
    },
    "wb": {
        "tackling": 4.0,
        "marking": 3.5,
        "positioning": 3.5,
        "crossing": 4.0,
        "dribbling": 3.5,
        "pace": 4.5,
        "acceleration": 4.5,
        "stamina": 4.5,
        "work_rate": 4.0,
        "anticipation": 3.0,
        "teamwork": 3.5,
    },
    "dm": {
        "tackling": 4.5,
        "marking": 4.0,
        "positioning": 4.5,
        "passing": 4.0,
        "first_touch": 3.5,
        "anticipation": 4.0,
        "decisions": 4.0,
        "teamwork": 4.0,
        "work_rate": 4.0,
        "stamina": 4.0,
        "strength": 3.5,
    },
    "cm": {
        "passing": 4.5,
        "first_touch": 4.0,
        "technique": 4.0,
        "vision": 4.0,
        "decisions": 4.0,
        "anticipation": 3.5,
        "teamwork": 4.0,
        "work_rate": 4.0,
        "stamina": 4.0,
        "tackling": 3.0,
    },
    "am": {
        "passing": 4.5,
        "vision": 4.5,
        "technique": 4.5,
        "first_touch": 4.0,
        "dribbling": 4.0,
        "flair": 3.5,
        "decisions": 4.0,
        "off_the_ball": 4.0,
        "agility": 3.5,
        "composure": 3.5,
    },
    "wing": {
        "pace": 5.0,
        "acceleration": 5.0,
        "dribbling": 4.5,
        "crossing": 4.0,
        "technique": 4.0,
        "agility": 4.0,
        "flair": 3.5,
        "off_the_ball": 4.0,
        "stamina": 3.5,
    },
    "st": {
        "finishing": 5.0,
        "off_the_ball": 4.5,
        "composure": 4.5,
        "anticipation": 4.0,
        "heading": 3.5,
        "first_touch": 3.5,
        "technique": 3.5,
        "pace": 4.0,
        "acceleration": 4.0,
        "jumping_reach": 3.5,
        "strength": 3.5,
    },
}

ATRIBUTOS = set()
for p in PESOS_ATRIBUTO.values():
    ATRIBUTOS.update(p.keys())


def grupo_de(posicao):
    if not posicao:
        return GRUPO_PADRAO
    pos_limpa = str(posicao).lower().strip()
    for token in pos_limpa.replace("/", ",").split(","):
        p = token.strip()
        if p in GRUPO:
            return GRUPO[p]
    return GRUPO_PADRAO


def _limpa(val):
    try:
        f = float(val)
        return f if np.isfinite(f) else 0.0
    except Exception:
        return 0.0


def cobertura_por_papel(atributos, papel):
    """Calcula a cobertura de atributos revelados (diferentes de zero)."""
    # Encontra grupo correspondente ao papel
    grp = GRUPO_PADRAO
    for g, papeis in PAPEIS.items():
        if papel in papeis:
            grp = g
            break

    pesos = PESOS_ATRIBUTO.get(grp, {})
    total_peso = sum(pesos.values())
    if total_peso <= 0:
        return 1.0

    revelado_peso = 0.0
    for attr, peso in pesos.items():
        val = _limpa(atributos.get(attr, 0))
        if val > 0:
            revelado_peso += peso

    return revelado_peso / total_peso


def notas_atributo(atributos, grupo=None):
    """Calcula nota de atributos (0-100) via Z-score truncado."""
    grp = grupo or GRUPO_PADRAO
    pesos = PESOS_ATRIBUTO.get(grp)
    if not pesos:
        return None

    soma_pond = 0.0
    soma_pesos = 0.0
    total_pesos = sum(pesos.values())

    for attr, peso in pesos.items():
        val = _limpa(atributos.get(attr, 0))
        if val > 0:
            soma_pond += val * peso
            soma_pesos += peso

    if total_pesos <= 0 or (soma_pesos / total_pesos) < COBERTURA_MINIMA:
        return None

    w_eff = soma_pond / soma_pesos

    # Calibrado em 247.518 jogadores: mu = 9.8, sigma = 1.2
    mu = 9.8
    sigma = 1.2
    z = (w_eff - mu) / sigma
    z_clamped = max(-Z_CORTE, min(Z_CORTE, z))

    score = 50.0 + (z_clamped / Z_CORTE) * 50.0
    return round(float(np.clip(score, 0.0, 100.0)), 1)


def notas_desempenho(percentis, minutos, grupo=None):
    """Calcula nota de desempenho avaliando os papeis tatica para o grupo."""
    mins = _limpa(minutos)
    if mins < MINUTOS_MINIMOS:
        return None, None

    grp = grupo or GRUPO_PADRAO
    papeis_candidatos = PAPEIS.get(grp, [])
    if not papeis_candidatos:
        return None, None

    melhor_papel = None
    melhor_nota = -1.0

    for papel in papeis_candidatos:
        pesos = METRICAS.get(papel, {})
        soma_pond = 0.0
        soma_pesos = 0.0

        for metrica, peso in pesos.items():
            pct = percentis.get(metrica)
            if pct is not None and np.isfinite(pct):
                # Se metrica for inversa, inverte valor do percentil
                val = 100.0 - pct if metrica in INVERSAS else pct
                soma_pond += val * abs(peso)
                soma_pesos += abs(peso)

        if soma_pesos > 0:
            nota = soma_pond / soma_pesos
            if nota > melhor_nota:
                melhor_nota = nota
                melhor_papel = papel

    if melhor_nota >= 0:
        return round(float(np.clip(melhor_nota, 0.0, 100.0)), 1), melhor_papel
    return None, None


def combinar(nota_attr, nota_perf, modo=MODO_PADRAO):
    """Combina notas de atributo e desempenho segundo o modo selecionado."""
    if modo == "atributos" or nota_perf is None:
        return nota_attr
    if modo == "estatistica" or nota_attr is None:
        return nota_perf

    # Modo misto (50% atributo / 50% desempenho)
    if nota_attr is not None and nota_perf is not None:
        return round(float(0.5 * nota_attr + 0.5 * nota_perf), 1)

    return nota_attr if nota_attr is not None else nota_perf
