import unicodedata

_TEIMOSAS = {
    'ø': 'o',
    'ı': 'i',
    'ł': 'l',
    'đ': 'd',
    'ð': 'd',
    'þ': 'th',
    'ə': 'e',
    'ħ': 'h',
    'ŋ': 'n',
    'ß': 'ss',
    'æ': 'ae',
    'œ': 'oe',
}


def sem_acento(s):
    if not s:
        return ''
    nfd = unicodedata.normalize('NFD', str(s).strip())
    base = ''.join(c for c in nfd if not unicodedata.combining(c)).lower()
    if base.isascii():
        return base
    for de, para in _TEIMOSAS.items():
        if de in base:
            base = base.replace(de, para)
    return base
