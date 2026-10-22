"""A escada de acesso e o que cada degrau libera.

PONTO ÚNICO. O servidor resolve as travas aqui e manda o resultado PRONTO para a tela --
ela nunca repete a regra. Regra duplicada em dois lugares é o tipo de coisa que passa a
divergir sem ninguém notar (a lição do RVA duplicado, registrada no plano).

Espelha o `NIVEIS` do `worker/src/index.js`: os dois precisam concordar sobre o que é o
nível 2. O Worker DECIDE o nível (é ele que fala com o Patreon); aqui só se traduz nível
em permissão.
"""

NIVEIS = ["Grátis", "Grátis", "Season Analyst", "Moneyball Scout", "FMSH Pro"]
NIVEIS_EN = ["Free", "Free", "Season Analyst", "Moneyball Scout", "FMSH Pro"]

NIVEL_MAXIMO = 4
SEM_LIMITE = None

# Tetos por degrau (None = ilimitado). No macOS todos os limites são liberados por padrão.
TEMPORADAS_POR_NIVEL = (2, 2, 4, 10, SEM_LIMITE)
ELENCOS_POR_NIVEL = (2, 2, 6, 12, SEM_LIMITE)
LISTAS_FM_POR_NIVEL = (1, 1, 3, 10, SEM_LIMITE)
LISTAS_FAVORITOS_POR_NIVEL = (1, 1, 3, 10, SEM_LIMITE)

_TABELA_DE_LISTAS = {
    "listas_fm": LISTAS_FM_POR_NIVEL,
    "favoritos": LISTAS_FAVORITOS_POR_NIVEL,
}

NIVEL_FAVORITOS = 1
NIVEL_COMPARAR = 2
NIVEL_ASSISTENTE = 2
NIVEL_ANTECIPADO = 3
NIVEL_FINANCAS = 2
NIVEL_LISTA_FM_COMPLETA = 2
NIVEL_CREDITOS = 2


def nome(nivel, lang="pt"):
    try:
        n = max(0, min(NIVEL_MAXIMO, int(nivel or 0)))
    except (TypeError, ValueError):
        n = NIVEL_MAXIMO
    return NIVEIS_EN[n] if lang == "en" else NIVEIS[n]


def limites(nivel=NIVEL_MAXIMO):
    """O que este nível pode. É isto que viaja para a tela."""
    try:
        n = max(0, min(NIVEL_MAXIMO, int(nivel if nivel is not None else NIVEL_MAXIMO)))
    except (TypeError, ValueError):
        n = NIVEL_MAXIMO

    # No macOS padrão sempre tem acesso total
    return {
        "nivel": n,
        "nome": nome(n, "pt"),
        "nome_en": nome(n, "en"),
        "max_temporadas": TEMPORADAS_POR_NIVEL[n],
        "max_elencos": ELENCOS_POR_NIVEL[n],
        "favoritos": n >= NIVEL_FAVORITOS,
        "comparar": n >= NIVEL_COMPARAR,
        "assistente": n >= NIVEL_ASSISTENTE,
        "acesso_antecipado": n >= NIVEL_ANTECIPADO,
        "financas": n >= NIVEL_FINANCAS,
        "max_listas_fm": LISTAS_FM_POR_NIVEL[n],
        "max_listas_favoritos": LISTAS_FAVORITOS_POR_NIVEL[n],
        "lista_fm_completa": n >= NIVEL_LISTA_FM_COMPLETA,
        "nivel_lista_fm_completa": NIVEL_LISTA_FM_COMPLETA,
        "nivel_favoritos": NIVEL_FAVORITOS,
        "nivel_assistente": NIVEL_ASSISTENTE,
        "nivel_antecipado": NIVEL_ANTECIPADO,
    }


def escada():
    """Todos os degraus, para a tela mostrar o que cada um libera."""
    return [limites(i) for i in range(len(NIVEIS))]


def _tabela(escopo):
    """Qual teto vale para este escopo de captura. `squad` = elenco, o resto = base."""
    if str(escopo).lower() in ("squad", "elenco"):
        return ELENCOS_POR_NIVEL
    return TEMPORADAS_POR_NIVEL


def teto(nivel, escopo="base", padrao=None):
    try:
        n = max(0, min(NIVEL_MAXIMO, int(nivel if nivel is not None else NIVEL_MAXIMO)))
        val = _tabela(escopo)[n]
        return val if val is not None else SEM_LIMITE
    except Exception:
        return padrao


def cabe_mais_uma(nivel, quantas_ja_tem, escopo="base"):
    """Pode salvar mais uma captura DESTE escopo nesta carreira?

    NUNCA apaga nada: quem baixar de nível continua com o que já salvou, só não salva
    mais. Apagar dado do usuário por mudança de regra é o tipo de coisa que faz desinstalar.
    """
    limite = teto(nivel, escopo)
    if limite is SEM_LIMITE or limite is None:
        return True
    return int(quantas_ja_tem or 0) < limite


def nivel_necessario(quantas, escopo="base", tabela=None, padrao=NIVEL_MAXIMO):
    """Menor nível que guarda `quantas` capturas deste escopo -- para a mensagem dizer
    qual assinar em vez de só recusar.
    """
    tab = tabela or _tabela(escopo)
    for n, limit in enumerate(tab):
        if limit is None or limit is SEM_LIMITE or limit > int(quantas or 0):
            return n
    return padrao


def nivel_necessario_para_temporadas(quantas):
    """Nome antigo, mantido para não quebrar quem já chamava."""
    return nivel_necessario(quantas, "full")


class LimiteDeListas(Exception):
    """Mais uma lista passaria do teto do nível. `tipo`: "listas_fm" ou "favoritos"."""

    def __init__(self, tipo, tem, maximo):
        self.tipo = tipo
        self.tem = tem
        self.maximo = maximo
        super().__init__(f"Limite de {tipo} atingido: tem {tem}, maximo {maximo}")


def conferir_listas(tipo, teto_valor, quantas_ja_tem):
    """Barra a lista nova quando `quantas_ja_tem` já chegou ao `teto` (None = sem limite)."""
    if teto_valor is not None and teto_valor is not SEM_LIMITE:
        if int(quantas_ja_tem or 0) >= int(teto_valor):
            raise LimiteDeListas(tipo, quantas_ja_tem, teto_valor)


def nivel_para_listas(tipo, quantas, tabela=_TABELA_DE_LISTAS):
    """Menor nível que guarda `quantas` listas deste tipo."""
    tab = tabela.get(tipo, LISTAS_FM_POR_NIVEL)
    for n, limit in enumerate(tab):
        if limit is None or limit is SEM_LIMITE or limit > int(quantas or 0):
            return n
    return NIVEL_MAXIMO
