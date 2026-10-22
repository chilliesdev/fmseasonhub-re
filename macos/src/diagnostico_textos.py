import idiomas

_ATUAL = {'lang': 'pt'}


def usar(lang):
    _ATUAL['lang'] = (lang or 'pt').strip().lower()


def idioma_atual():
    return _ATUAL['lang']


def T(texto):
    if not texto or not texto.strip():
        return texto
    nucleo = texto.strip()
    esquerda = texto[:len(texto) - len(texto.lstrip())]
    direita = texto[len(texto.rstrip()):]
    try:
        return esquerda + idiomas.texto(_ATUAL['lang'], 'relat.' + nucleo, nucleo) + direita
    except Exception:
        return texto
