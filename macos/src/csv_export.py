import math
from decimal import Decimal, ROUND_FLOOR

_HALF = Decimal('0.5')

PROFILES = {
    'excel-br': {'delim': ';', 'bom': True, 'loc': 'pt'},
    'intl': {'delim': ',', 'bom': False, 'loc': 'en'},
}

DEFAULT_PROFILE = 'excel-br'

EMPTY = ''

_COMPACT = [
    (1000.0, {'pt': '\xa0mil', 'en': 'K'}),
    (1000000.0, {'pt': '\xa0M', 'en': 'M'}),
    (1000000000.0, {'pt': '\xa0BI', 'en': 'B'}),
]


def _dec_sep(loc):
    if loc == 'pt':
        return ','
    return '.'


def _group_sep(loc):
    if loc == 'pt':
        return '.'
    return ','


def _round_half_up(x, places):
    scale = 10 ** places
    y = x * scale
    n = math.floor(y)
    frac = y - n
    if abs(frac - 0.5) < 1e-09:
        d = Decimal(x) * scale
        n = int(d.to_integral_value(rounding=ROUND_FLOOR))
        if d - n >= _HALF:
            return (n + 1) / scale
        return n / scale
    if frac > 0.5:
        return (n + 1) / scale
    return n / scale


def _num(x, places, loc, grouping=False):
    trim = places < 0
    places = abs(places)
    d = _round_half_up(float(x), places)
    if d == 0:
        d = 0.0
    if grouping:
        s = f'{d:,.{places}f}'
    else:
        s = f'{d:.{places}f}'
    if trim and '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s.replace(',', '\x00').replace('.', _dec_sep(loc)).replace('\x00', _group_sep(loc))


def compact_money(v, loc, symbol):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return EMPTY
    if v != v or v in (float('inf'), float('-inf')) or v <= 0:
        return EMPTY
    pick = -1
    for i, (scale, _) in enumerate(_COMPACT):
        if abs(v) >= scale:
            pick = i
    if pick < 0:
        return f'{symbol} {_num(v, -1, loc)}'
    scale, suffix = _COMPACT[pick]
    n = _round_half_up(v / scale, 1)
    if n >= 1000 and pick + 1 < len(_COMPACT):
        scale, suffix = _COMPACT[pick + 1]
        n = _round_half_up(v / scale, 1)
    return f'{symbol} {_num(n, -1, loc)}{suffix[loc]}'


def fmt_value(v, fmt, loc, symbol='£'):
    if fmt in ('txt', 'pos'):
        if v is None:
            return EMPTY
        return str(v)
    if v is None:
        return EMPTY
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if v != v or v in (float('inf'), float('-inf')):
        return EMPTY
    if fmt == 'int':
        return _num(v, 0, loc, grouping=True)
    if fmt == 'dec':
        return _num(v, 2, loc)
    if fmt == 'dec1':
        return _num(v, 1, loc)
    if fmt == 'rating':
        if v:
            return _num(v, 2, loc)
        return EMPTY
    if fmt == 'pct':
        return _num(v * 100, 1, loc) + '%'
    if fmt == 'money':
        return compact_money(v, loc, symbol)
    return _num(v, 2, loc)


def _is_number(s):
    body = s.lstrip('-').replace('.', '').replace(',', '').replace('%', '')
    return body.isdigit()


def csv_cell(value, delim):
    if value is None:
        s = ''
    else:
        s = str(value)
    if s[:1] in ('=', '+', '@', '\t', '\r') or (s[:1] == '-' and not _is_number(s)):
        s = "'" + s
    if delim in s or '"' in s or '\n' in s or '\r' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def csv_line(values, delim):
    return delim.join(csv_cell(v, delim) for v in values) + '\r\n'
