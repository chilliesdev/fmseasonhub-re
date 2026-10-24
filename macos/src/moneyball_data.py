"""Stored-snapshot data shared by Moneyball browse, analytics and CSV."""

import json
import math
from datetime import date

import numpy as np

import moneyball as mb
import player_search

# Column IDs used by the shipped browse table and search builder.
ALIASES = {
    'pos': 'position', 'nat': 'nationality_code', 'club': 'club_name',
    'league': 'league_name', '_age': 'age', '_height': 'height_m',
    '_ca': 'ca', '_pa': 'pa', '_rating': 'avg_rating', 'rating': 'avg_rating',
    '_value': 'transfer_value', '_asking': 'asking_price', '_wage': 'wage',
    'contract': 'contract_end', 'birth': 'birth_date', '_lfoot': 'left_foot',
    '_rfoot': 'right_foot', '_uid': 'uid',
}


# Shipped legacy browse IDs also occur in saved quick/advanced conditions.
SEARCH_ALIASES = {
    'all_min': ('minutes', 'Minutos', 'Minutes', 'int'),
    'all_careerapps': ('all_time_appearances', 'Jogos na carreira', 'Career appearances', 'int'),
    'all_ccc': ('clear_cut_chances', 'Chances claras', 'Clear-cut chances', 'int'),
    'all_cropatt': ('crosses_open_play_attempted', 'Cruzamentos em jogo', 'Open-play crosses attempted', 'int'),
    'all_cropcmp': ('crosses_open_play_completed', 'Cruzamentos certos em jogo', 'Open-play crosses completed', 'int'),
    'all_croppct': ('crPct', 'Cruzamentos certos em jogo %', 'Open-play cross accuracy', 'pct'),
    'all_cropatt90': ('crA90', 'Cruzamentos em jogo /90', 'Open-play crosses attempted /90', 'dec2'),
    'all_cropcmp90': ('crC90', 'Cruzamentos certos em jogo /90', 'Open-play crosses completed /90', 'dec2'),
    'all_opkp90': ('opKp90', 'Passes-chave em jogo /90', 'Open-play key passes /90', 'dec2'),
    'all_tklatt': ('tackles_attempted', 'Desarmes tentados', 'Tackles attempted', 'int'),
    'all_tklpct': ('tckRawPct', 'Desarmes ganhos %', 'Tackle success', 'pct'),
    'all_xgshot': ('xg_per_shot', 'xG por finalização', 'xG per shot', 'dec2'),
}
ALIASES.update({key: metadata[0] for key, metadata in SEARCH_ALIASES.items()})
POSITION_CODES = ('gk', 'sw', 'dc', 'dr', 'dl', 'wbr', 'wbl', 'dm', 'mc', 'mr', 'ml', 'amc', 'amr', 'aml', 'st')
# The table groups differ from the analysis/cohort groups in moneyball.py.
BROWSE_GROUP_POSITIONS = {
    'gk': ('gk',), 'def': ('dc', 'sw'), 'wing': ('dr', 'dl', 'wbr', 'wbl'),
    'dm': ('dm',), 'b2b': ('mc', 'mr', 'ml'), 'amc': ('amc',), 'att': ('st', 'amr', 'aml'),
}



def search_alias_columns():
    return [{'key': key, 'label': label, 'labelEn': label_en, 'type': 'num',
             'fmt': fmt, 'section': 'geral', 'general': True}
            for key, (_, label, label_en, fmt) in SEARCH_ALIASES.items()]


def number(value, fallback=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else fallback
    except (TypeError, ValueError):
        return fallback


def _first(row, *keys):
    return next((row[key] for key in keys if row.get(key) is not None), None)


def snapshot_id(conn, selected=None, career=None):
    if selected is not None:
        return selected
    query = "SELECT id FROM snapshots WHERE scope NOT IN ('live','live_temp')"
    params = []
    if career:
        query += ' AND carreira_id=?'
        params.append(career)
    row = conn.execute(query + ' ORDER BY id DESC LIMIT 1', params).fetchone()
    return row['id'] if row else None


def table_rows(conn, table, sid):
    # Table names are internal constants, never request values.
    columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    if 'snapshot_id' not in columns or sid is None:
        return []
    return [dict(row) for row in conn.execute(f'SELECT * FROM {table} WHERE snapshot_id=?', (sid,))]


def load(conn, selected=None, career=None, groups=()):
    sid = snapshot_id(conn, selected, career)
    snapshot = conn.execute('SELECT * FROM snapshots WHERE id=?', (sid,)).fetchone()
    if not snapshot:
        return sid, []
    snapshot = dict(snapshot)
    stats = {row['uid']: row for row in table_rows(conn, 'player_stats', sid)}
    profiles = {row['uid']: row for row in table_rows(conn, 'player_profile', sid)}
    clubs = {row['club_uid']: row for row in table_rows(conn, 'club_leagues', sid)}
    club_profiles = {row['club_uid']: row for row in table_rows(conn, 'club_profile', sid)}
    comps = {row['uid']: row for row in table_rows(conn, 'comps', sid)}
    memberships = {}
    for row in table_rows(conn, 'player_teams', sid):
        memberships.setdefault(row['player_uid'], set()).add(row['team_uid'])
    rows = []
    for identity in table_rows(conn, 'players', sid):
        uid = identity['uid']
        row = {**profiles.get(uid, {}), **identity, **stats.get(uid, {})}
        row = {key: (None if isinstance(value, float) and not math.isfinite(value) else value)
               for key, value in row.items()}
        row['name'] = row.get('full_name') or row.get('common_name') or ' '.join(
            str(row.get(key) or '') for key in ('name_first', 'name_last')).strip() or str(uid)
        row['full_name'] = row['name']
        row['position'] = row.get('position') or _position(row)
        club = clubs.get(row.get('club_id'), {})
        profile = club_profiles.get(row.get('club_id'), {})
        row['club_uid'] = row.get('club_id')
        row['club_name'] = club.get('club_name') or row.get('club_name') or profile.get('name_full') or ''
        row['league_uid'] = club.get('league_uid')
        row['league_name'] = club.get('league_name') or ''
        row['_league_reputation'] = number(comps.get(row['league_uid'], {}).get('reputation'))
        row['_teams'] = sorted(memberships.get(uid, set()) | ({row['team_uid']} if row.get('team_uid') else set()))
        row['age'] = _age(row, snapshot.get('game_date'))
        row['height_m'] = number(row['height_cm']) / 100 if row.get('height_cm') else None
        row['transfer_value'] = _first(row, 'guide_value', 'value', 'transfer_value')
        row['asking_price'] = _first(profiles.get(uid, {}), 'asking', 'transfer_value')
        row['wage'] = _first(row, 'wage_weekly', 'contract_wage', 'wage')
        row['left_foot'] = _first(row, 'foot_left', 'left_foot')
        row['right_foot'] = _first(row, 'foot_right', 'right_foot')
        left, right = number(row.get('left_foot')), number(row.get('right_foot'))
        row['foot'] = ('both' if min(left, right) >= 15 else 'left' if left > right else 'right') if max(left, right) else ''
        rows.append(row)
    _derive(rows, groups)
    return sid, rows


def _age(row, game_date):
    try:
        born, today = date.fromisoformat(row['birth_date'][:10]), date.fromisoformat(game_date[:10])
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except (KeyError, TypeError, ValueError):
        return row.get('age')


def _position(row):
    positions = [(number(row.get('pos_' + pos)), pos.upper())
                 for pos in POSITION_CODES]
    score, position = max(positions, default=(0, ''))
    return position if score > 0 else ''


def _derive(rows, groups):
    if not rows:
        return
    # Catalog expressions need fields outside RAW_FIELDS (for example man_of_the_match).
    fields = set(mb.RAW_FIELDS)
    for group in groups:
        for column in mb.CATALOG.get(group, []):
            fields.update(mb.column_fields(column["key"]))
    raw = {key: np.array([number(row.get(key)) for row in rows]) for key in fields}
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        derived = mb.derive(raw)
        for group in groups:
            derived.update(mb.derive_catalog(raw, group))
    for i, row in enumerate(rows):
        row['vals'] = {key: number(values.item() if values.ndim == 0 else values[i])
                       for key, values in {**raw, **derived}.items()}
        row['vals'].update({key: value for key, value in team_metrics(row).items() if key not in row['vals']})
        row['vals'].update({key: value(row, key) for key in SEARCH_ALIASES})


def value(row, key):
    key = key.removeprefix('f.')
    key = ALIASES.get(key, key)
    return row.get(key, row['vals'].get(key))


def integer(params, key, default=None, minimum=None):
    raw = params.get(key)
    if raw is None or raw == '':
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f'{key}: expected integer') from None
    if minimum is not None and parsed < minimum:
        raise ValueError(f'{key}: must be at least {minimum}')
    return parsed


def ids(raw):
    if not raw:
        return None
    try:
        return {int(item) for item in raw.split(',') if item}
    except ValueError:
        raise ValueError('expected comma-separated IDs') from None


def select(rows, params, allowed_uids=None):
    group = params.get('group', 'all')
    positions = BROWSE_GROUP_POSITIONS.get(group)
    chosen = [row for row in rows if not positions or row['position'].lower() in positions]
    clubs, teams = ids(params.get('clubs') or params.get('club')), ids(params.get('teams') or params.get('team'))
    leagues = ids(params.get('leagues') or params.get('league'))
    uids = allowed_uids if allowed_uids is not None else ids(params.get('uids'))
    excluded = ids(params.get('exclude')) or set()
    words = player_search.normalize_str(params.get('q', '')).split()
    result = []
    for row in chosen:
        if clubs is not None and row['club_uid'] not in clubs:
            continue
        if teams is not None and not teams.intersection(row['_teams']):
            continue
        if leagues is not None and row['league_uid'] not in leagues:
            continue
        if uids is not None and row['uid'] not in uids or row['uid'] in excluded:
            continue
        if words and not all(word in player_search.normalize_str(row['name']) for word in words):
            continue
        if params.get('sex') in ('m', 'f') and bool(row.get('is_female')) != (params['sex'] == 'f'):
            continue
        result.append(row)
    for field, suffix in (('minutes', 'minutes'), ('age', 'age'), ('avg_rating', 'rating')):
        for prefix, compare in (('min', lambda a, b: a >= b), ('max', lambda a, b: a <= b)):
            key = prefix + '_' + suffix
            if key in params:
                bound = number(params[key], None)
                if bound is None:
                    raise ValueError(f'{key}: expected finite number')
                result = [row for row in result if value(row, field) is not None and compare(number(value(row, field)), bound)]
    conditions = _conditions(params)
    warnings = []
    if conditions and result:
        mask, warnings = player_search.evaluate(conditions, lambda cond: _condition_mask(result, cond))
        if mask is not None:
            result = [row for row, keep in zip(result, mask) if keep]
    return result, warnings


def _conditions(params):
    try:
        search = json.loads(params['search']) if params.get('search') else None
        legacy = json.loads(params['conds']) if params.get('conds') else None
    except (TypeError, ValueError):
        raise ValueError('invalid search JSON') from None
    if search is not None and not isinstance(search, (dict, list)) or legacy is not None and not isinstance(legacy, list):
        raise ValueError('invalid search conditions')
    if isinstance(search, dict) and not isinstance(search.get('conds', []), list):
        raise ValueError('invalid search conditions')
    return player_search.normalize(search, legacy)


def _condition_mask(rows, condition):
    key, op = condition.get('field'), condition.get('op')
    if not isinstance(key, str):
        return None
    if key == 'f.positions' and op in ('includes', 'excludes'):
        codes = condition.get('vs')
        if not isinstance(codes, list) or not codes or any(code not in POSITION_CODES for code in codes):
            return None
        threshold = number(condition.get('thr', 17), None)
        if threshold is None or not 1 <= threshold <= 20:
            raise ValueError('position threshold: expected 1 to 20')
        matches = np.array([any(
            number(row.get('pos_' + code), 20 if row['position'].lower() == code else 0) >= threshold
            for code in codes) for row in rows], dtype=bool)
        return matches if op == 'includes' else ~matches
    values = [value(row, key) for row in rows]
    if all(item is None for item in values) and key.removeprefix('f.') not in ALIASES and key.removeprefix('f.') not in mb.RAW_FIELDS:
        return None
    if op in player_search.TEXT_OPS:
        text = condition.get('vt', condition.get('val', condition.get('v')))
        if not isinstance(text, str) or not text.strip():
            return None
        return player_search.text_mask(values, op, text)
    if op not in player_search.NUM_OPS:
        return None
    numbers = [number(item, np.nan) for item in values]
    operand = condition.get('val', condition.get('v'))
    other = None
    if op in player_search.FIELD_OPS:
        rhs = condition.get('vf')
        if not isinstance(rhs, str) or not rhs.strip():
            return None
        rhs = rhs.strip()
        right_values = [value(row, rhs) for row in rows]
        if all(item is None for item in right_values) and rhs.removeprefix('f.') not in ALIASES and rhs.removeprefix('f.') not in mb.RAW_FIELDS:
            return None
        other = [number(item, np.nan) for item in right_values]
    elif op == 'between':
        bounds = operand if isinstance(operand, (list, tuple)) and len(operand) == 2 else [operand, condition.get('val2', condition.get('v2'))]
        operand = [number(bound, None) for bound in bounds]
        if any(bound is None for bound in operand):
            return None
    else:
        operand = number(operand, None)
        if operand is None:
            return None
    return player_search.num_mask(numbers, op, operand, other)


def sort_rows(rows, params):
    key = params.get('sort') or 'name'
    direction = params.get('dir', 'asc')
    if direction not in ('asc', 'desc'):
        raise ValueError('dir: expected asc or desc')
    # Stable UID tie-break and missing values last in both directions.
    ordered = sorted(rows, key=lambda row: row['uid'])
    present = [row for row in ordered if value(row, key) is not None]
    missing = [row for row in ordered if value(row, key) is None]
    def sort_key(row):
        item = value(row, key)
        return (0, float(item)) if isinstance(item, (int, float)) else (1, player_search.normalize_str(item))
    return sorted(present, key=sort_key, reverse=direction == 'desc') + missing


def percentiles(rows, queries, pool='save', min_minutes=0, team_columns=False):
    if pool not in ('save', 'pos', 'filtered', 'top20', 'top5'):
        raise ValueError('invalid percentile pool')
    eligible = [row for row in rows if number(row.get('minutes')) >= min_minutes]
    if pool in ('top20', 'top5'):
        leagues = {}
        for row in eligible:
            if row['league_uid'] is not None:
                leagues[row['league_uid']] = row['_league_reputation']
        top = set(sorted(leagues, key=lambda uid: (-leagues[uid], uid))[:int(pool[3:])])
        eligible = [row for row in eligible if row['league_uid'] in top]
    result = {}
    team_values = {row['uid']: team_metrics(row) for row in rows + queries} if team_columns else {}
    def metric(row, key):
        return team_values.get(row['uid'], {}).get(key, value(row, key))
    # Values stay in ascending rank order. The client applies lowerBetter once.
    for position in {row['position'] for row in queries} if pool == 'pos' else {None}:
        reference = [row for row in eligible if position is None or row['position'] == position]
        targets = [row for row in queries if position is None or row['position'] == position]
        if not reference:
            continue
        keys = set().union(*(row['vals'] for row in reference)) | set(ALIASES)
        for key in keys:
            ranks = mb.percentile_ranks([number(metric(row, key), np.nan) for row in reference],
                                        [number(metric(row, key), np.nan) for row in targets])
            for row, rank in zip(targets, ranks):
                if math.isfinite(rank) and math.isfinite(number(metric(row, key), np.nan)):
                    result.setdefault(str(row['uid']), {})[key] = float(rank)
    return result


def _n(row, key):
    return number(row.get(key))


def _per90(total, minutes):
    return total * 90 / minutes if minutes > 0 else 0.0


def _ratio(numerator, denominator):
    return numerator / denominator if denominator > 0 else 0.0


def team_metrics(row):
    """Numeric column IDs from the shipped My team table."""
    minutes = _n(row, 'minutes')
    n = lambda key: _n(row, key)
    per90 = lambda total: _per90(total, minutes)
    passing_wide = n('passes_attempted') - n('passes_completed')
    open_crosses, open_completed = n('crosses_open_play_attempted'), n('crosses_open_play_completed')
    set_crosses, set_completed = n('crosses_attempted') - open_crosses, n('crosses_completed') - open_completed
    nonpenalty_xg = n('xg') - n('penalties_scored') * 0.79
    missed_penalties = n('penalties_taken') - n('penalties_scored')
    nonpenalty_shots = n('shots') - n('penalties_scored')
    tackles = n('tackles_attempted') + n('fouls_committed')
    actions = open_crosses + n('shots') + n('dribbles') + minutes
    sca = n('clear_cut_chances') + n('xa') + n('shots_on_target') + n('goals')
    metrics = {
        'min': minutes, 'apps': n('apps_total'), 'd90': minutes / 90,
        'minpg': _ratio(minutes, n('apps_total')), 'height': n('height_cm') / 100,
        'rating': n('avg_rating'), 'age': n('age'), 'ca': n('ca'), 'pa': n('pa'),
        'value': n('guide_value'), 'asking': n('asking_price'), 'wage': n('wage'),
        'passW': passing_wide, 'passW90': per90(passing_wide),
        'passPct': _ratio(n('passes_completed'), n('passes_attempted')),
        'passWpct': _ratio(passing_wide, n('passes_attempted')),
        'actions': actions, 'actions90': per90(actions), 'sca': sca, 'sca90': per90(sca),
        'spA': set_crosses, 'spC': set_completed, 'spPct': _ratio(set_completed, set_crosses),
        'npxg': nonpenalty_xg, 'npxg90': per90(nonpenalty_xg),
        'xgxa': n('xa') + nonpenalty_xg, 'xgxa90': per90(n('xa') + nonpenalty_xg),
        'shots': nonpenalty_shots, 'shots90': per90(nonpenalty_shots),
        'sot90': _ratio(n('shots_on_target') - missed_penalties, minutes / 90 - n('penalties_scored')),
        'sotPct': _ratio(n('shots_on_target') - missed_penalties, nonpenalty_shots),
        'conv': _ratio(n('goals') - missed_penalties, nonpenalty_shots),
        'ga': n('goals') + n('assists'), 'ga90': per90(n('goals') + n('assists')),
        'tckA': tackles, 'tckA90': per90(tackles), 'tckPct': _ratio(n('tackles_completed'), tackles),
    }
    raw_aliases = {
        'passA': 'passes_attempted', 'passC': 'passes_completed', 'keyP': 'key_passes',
        'lost': 'possession_lost', 'crA': 'crosses_open_play_attempted', 'crC': 'crosses_open_play_completed',
        'xa': 'xa', 'goals': 'goals', 'ast': 'assists', 'hdrA': 'headers_attempted',
        'hdrW': 'headers_won', 'tckW': 'tackles_completed', 'fouls': 'fouls_committed',
        'errs': 'errors_leading_to_goal', 'dist': 'distance_km', 'drb': 'dribbles',
        'lfoot': 'left_foot', 'rfoot': 'right_foot', 'uid': 'uid', 'morale': 'morale',
        'intlApps': 'intl_apps', 'intlGoals': 'intl_goals', 'u21Apps': 'u21_apps', 'u21Goals': 'u21_goals',
        'xg': 'xg', 'shotsAll': 'shots', 'sotAll': 'shots_on_target', 'gob': 'goals_outside_box',
        'fkShots': 'free_kicks_taken', 'pens': 'penalties_taken', 'pensG': 'penalties_scored',
        'ccc': 'clear_cut_chances', 'prog': 'passes_progressive', 'crAll': 'crosses_attempted',
        'crAllC': 'crosses_completed', 'tckRaw': 'tackles_attempted', 'tckKey': 'tackles_key',
        'pressA': 'presses_attempted', 'pressC': 'presses_completed', 'foulsWon': 'fouls_won',
        'yellow': 'yellow_cards', 'red': 'red_cards',
    }
    metrics.update({key: n(field) for key, field in raw_aliases.items()})
    for key in ('passA', 'passC', 'keyP', 'lost', 'crA', 'crC', 'xa', 'goals', 'ast',
                'hdrA', 'hdrW', 'tckW', 'fouls', 'errs', 'dist', 'drb', 'shotsAll', 'sotAll', 'prog'):
        metrics[key + '90'] = per90(metrics[key])
    for key, numerator, denominator in (
        ('crPct', 'crosses_open_play_completed', 'crosses_open_play_attempted'),
        ('hdrPct', 'headers_won', 'headers_attempted'), ('xgShot', 'xg', 'shots'),
        ('sotAllPct', 'shots_on_target', 'shots'), ('convAll', 'goals', 'shots'),
        ('crAllPct', 'crosses_completed', 'crosses_attempted'),
        ('tckRawPct', 'tackles_completed', 'tackles_attempted'),
    ):
        metrics[key] = _ratio(n(numerator), n(denominator))
    for key, field in (('npxgFm90', 'npxg'), ('shotsOut90', 'shots_outside_box'),
                       ('opKp90', 'key_passes_open_play'), ('int90', 'interceptions')):
        metrics[key] = per90(n(field))
    return metrics
