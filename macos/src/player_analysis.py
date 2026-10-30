"""Analysis of measured values in one stored snapshot.

Missing measurements stay missing. Percentiles use the existing mid-rank rule;
similarity uses the shipped search engine and its three-metric minimum.
"""

import bisect
from datetime import date
import math

import numpy as np

import analise_perfil as analysis
import buscar_como as similar
import moneyball as mb
import moneyball_data as data


PER90 = {
    'sh90': 'shots', 'xg90': 'xg', 'g90': 'goals', 'sot90': 'shots_on_target',
    'xa90': 'xa', 'kp90': 'key_passes', 'ccc90': 'clear_cut_chances', 'a90': 'assists',
    'pa90': 'passes_attempted', 'pp90': 'passes_progressive', 'crc90': 'crosses_completed',
    'cra90': 'crosses_attempted', 'pl90': 'possession_lost', 'pw90': 'possession_won',
    'prc90': 'presses_completed', 'pra90': 'presses_attempted', 'tkw90': 'tackles_completed',
    'itc90': 'interceptions', 'hw90': 'headers_won', 'fc90': 'fouls_committed',
    'fw90': 'fouls_won', 'ya90': 'yellow_cards', 'spr90': 'sprints', 'dr90': 'dribbles',
    'npxg90': 'npxg', 'dist90': 'distance_km', 'gkxgp': 'xg_prevented_gk',
    'gkxgf90': 'gk_xg_faced', 'ga90': 'goals_conceded_gk',
}
RATIOS = {
    'xgps': ('xg', 'shots'), 'prec': ('shots_on_target', 'shots'),
    'conv': ('goals', 'shots'), 'convAlvo': ('goals', 'shots_on_target'),
    'shout_pct': ('shots_outside_box', 'shots'), 'xaPorKp': ('xa', 'key_passes'),
    'aPorKp': ('assists', 'key_passes'), 'acc': ('passes_completed', 'passes_attempted'),
    'progShare': ('passes_progressive', 'passes_completed'),
    'crPct': ('crosses_completed', 'crosses_attempted'),
    'tkpct': ('tackles_completed', 'tackles_attempted'),
    'prpct': ('presses_completed', 'presses_attempted'),
    'aerpct': ('headers_won', 'headers_attempted'),
    'minPorGol': ('minutes', 'goals'), 'minPorChute': ('minutes', 'shots'),
    'gkcs': ('clean_sheets_gk', 'apps_total'),
    'gkpen': ('gk_penalties_saved', 'gk_penalties_faced'),
    'gkpas': ('passes_completed', 'passes_attempted'),
}
SAVES = ('gk_saves_held', 'gk_saves_parried', 'gk_saves_tipped')
EXTRA_FIELDS = {
    'reat90': ('minutes', 'tackles_completed', 'interceptions', 'clearances', 'blocks'),
    'clrblk90': ('minutes', 'clearances', 'blocks'),
    'gMenosXg10': ('goals', 'xg', 'shots'),
    'aMenosXa90': ('assists', 'xa', 'minutes', 'key_passes'),
    'gksv': SAVES + ('goals_conceded_gk',),
    'gksf90': SAVES + ('goals_conceded_gk', 'minutes'),
    'gkheld': SAVES,
    'gkev10': SAVES + ('goals_conceded_gk', 'xg_prevented_gk'),
}
# Preview/comparison IDs from the shipped client. Ratio values there use 0..1.
CLIENT_ALIASES = {
    'i:xg90': ('xg90', 1), 'i:convfin': ('conv', .01),
    'i:conversao': ('conv', .01), 'i:chances90': ('ccc90', 1),
    'i:passeschave90': ('kp90', 1), 'i:convpasse': ('aPorKp', .01),
    'i:cruzamentos': ('crPct', .01), 'i:duelos': ('aerpct', .01),
    'i:pressganhas': ('prpct', .01), 'i:intercep90': ('itc90', 1),
    'i:dist90': ('dist90', 1), 'g:passes': ('acc', .01),
    'g:aereo': ('aerpct', .01), 'g:desarmes': ('tkpct', .01),
    'g:progressao': ('progShare', .01), 'g:gk_defesas': ('gksv', .01),
    'g:gk_semgol': ('gkcs', .01), 'g:gk_penaltis': ('gkpen', .01),
    'g:gk_xgp': ('gkxgp', 1), 'i:sofridos90': ('ga90', 1),
    'i:passes90': ('passes_completed_per90', 1),
    'r:progressao': ('pp90', 1), 'i:posseganha90': ('pw90', 1),
    'i:possperdida90': ('pl90', 1),
    'i:desarmedec90': ('tackles_key_per90', 1),
    'i:clear90': ('clearances_per90', 1), 'i:bloqueios90': ('blocks_per90', 1),
    'i:gk_pontadedos90': ('gk_saves_tipped_per90', 1),
    'i:gk_falhas90': ('errors_leading_to_goal_per90', 1),
}


def metric_arrays(rows):
    """Return formula values and separate availability/eligibility masks."""
    fields = {key: np.array([data.number(row.get(key), np.nan) for row in rows])
              for key in set(analysis.CAMPOS + analysis.CAMPOS_GK)}
    values, valid = {}, {}
    for key, (fn, eligibility, _) in {**analysis.METRICAS, **analysis.METRICAS_GK}.items():
        required = (('minutes', PER90[key]) if key in PER90 else
                    RATIOS[key] if key in RATIOS else EXTRA_FIELDS[key])
        available = np.ones(len(rows), dtype=bool)
        for field in required:
            available &= np.isfinite(fields[field])
        if key in PER90 or key in ('reat90', 'clrblk90', 'aMenosXa90', 'gksf90'):
            available &= fields['minutes'] > 0
        if key in RATIOS:
            available &= fields[RATIOS[key][1]] > 0
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
            calculated = np.asarray(fn(fields), dtype=float)
            if eligibility is not None:
                available &= eligibility(fields)
        available &= np.isfinite(calculated)
        values[key] = np.where(available, calculated, np.nan)
        valid[key] = available
    return fields, values, valid


def load(conn, sid, uid=None):
    snapshot = conn.execute('SELECT * FROM snapshots WHERE id=?', (sid,)).fetchone()
    if snapshot is None:
        raise LookupError('Snapshot nao encontrado')
    _, rows = data.load(conn, sid)
    if uid is None:
        return dict(snapshot), rows, None
    pos = bisect.bisect_left(rows, uid, key=lambda row: row['uid'])
    if pos < len(rows) and rows[pos]['uid'] == uid:
        index = pos
    else:
        index = next((i for i, row in enumerate(rows) if row['uid'] == uid), None)
    if index is None:
        raise LookupError('Jogador nao encontrado neste snapshot')
    return dict(snapshot), rows, index


def cohort(rows, index, coorte, regua, min_minutes):
    coorte = coorte or similar.coorte_da_posicao(rows[index]['position'].lower()) or 'all'
    if coorte not in (*mb.COHORT_POSITIONS, 'all'):
        raise ValueError('coorte: posicao desconhecida')
    if regua not in ('top20', 'liga'):
        raise ValueError('regua: use top20 ou liga')
    minimum = 900 if min_minutes is None else min_minutes
    if minimum < 0:
        raise ValueError('min_minutes: deve ser zero ou positivo')
    mask = np.array([data.number(row.get('minutes'), -1) >= minimum and
                     (coorte == 'all' or row['position'].lower() in mb.COHORT_POSITIONS[coorte])
                     for row in rows])
    reference = rows[index]
    benchmark = {'tipo': regua, 'liga_uid': reference['league_uid'], 'liga_nome': reference['league_name']}
    if regua == 'liga':
        if reference['league_uid'] is None:
            raise ValueError('regua liga: jogador sem liga armazenada')
        mask &= np.array([row['league_uid'] == reference['league_uid'] for row in rows])
    else:
        leagues = {row['league_uid']: row['_league_reputation'] for row in rows if row['league_uid'] is not None}
        if leagues:
            top = set(sorted(leagues, key=lambda league: (-leagues[league], league))[:20])
            mask &= np.array([row['league_uid'] in top for row in rows])
        else:
            benchmark['efetiva'] = 'snapshot_sem_ligas'
    if not mask.any():
        raise ValueError('Sem jogadores com minutos suficientes na coorte selecionada')
    return coorte, benchmark, minimum, mask


def summaries(values, index, mask, lower_better=False):
    value = values[index]
    pool = values[mask & np.isfinite(values)]
    if not math.isfinite(value) or not pool.size:
        return None
    percentile = float(mb.percentile_ranks(pool, [value])[0])
    return {'v': round(float(value), 4), 'pct': round(percentile, 1),
            'p': round(100 - percentile if lower_better else percentile, 1),
            'ok': True, 'n': int(pool.size),
            'rank': int(np.sum(pool < value if lower_better else pool > value)) + 1,
            'mediana': round(float(np.median(pool)), 4)}


def player_metrics(rows, index, mask):
    _, values, _ = metric_arrays(rows)
    metrics = {}
    for key, array in values.items():
        lower = {**analysis.METRICAS, **analysis.METRICAS_GK}[key][2]
        summary = summaries(array, index, mask, lower)
        if summary:
            metrics[key] = summary
    # Preview aliases and raw totals also require actual finite measurements.
    minutes = np.array([data.number(row.get('minutes'), np.nan) for row in rows])
    for key in mb.RAW_FIELDS + ['tackles_key', 'errors_leading_to_goal']:
        array = np.array([data.number(row.get(key), np.nan) for row in rows])
        summary = summaries(array, index, mask)
        if summary:
            metrics[key] = summary
        if key not in ('minutes', 'apps_total', 'apps_starts', 'apps_sub', 'avg_rating'):
            with np.errstate(divide='ignore', invalid='ignore'):
                rate = np.where(minutes > 0, array * 90 / minutes, np.nan)
            values[key + '_per90'] = rate
            summary = summaries(rate, index, mask)
            if summary:
                metrics[key + '_per90'] = summary
                metrics['pizza:' + key] = summary
    for alias, (key, factor) in CLIENT_ALIASES.items():
        if key in metrics:
            summary = dict(metrics[key])
            summary['v'] = round(summary['v'] * factor, 4)
            summary['mediana'] = round(summary['mediana'] * factor, 4)
            metrics[alias] = summary
    goals = np.array([data.number(row.get('goals'), np.nan) for row in rows])
    expected = np.array([data.number(row.get('xg'), np.nan) for row in rows])
    summary = summaries(goals - expected, index, mask)
    if summary:
        metrics['i:xgover'] = summary
    saves = sum(np.array([data.number(row.get(key), np.nan) for row in rows]) for key in SAVES)
    with np.errstate(divide='ignore', invalid='ignore'):
        summary = summaries(np.where(minutes > 0, saves * 90 / minutes, np.nan), index, mask)
    if summary:
        metrics['i:defesas90'] = summary
    return metrics, values


def percentiles(conn, sid, uid, coorte=None, regua='top20', min_minutes=None):
    _, rows, index = load(conn, sid, uid)
    coorte, benchmark, minimum, mask = cohort(rows, index, coorte, regua, min_minutes)
    metrics, _ = player_metrics(rows, index, mask)
    if not metrics:
        raise ValueError('Jogador sem medidas armazenadas suficientes para percentis')
    return {'uid': uid, 'coorte': coorte, 'regua': benchmark, 'min_minutes': minimum,
            'n': int(mask.sum()), 'metricas': metrics,
            'percentis': {key: value['pct'] for key, value in metrics.items()}}


# Consumed cS chart paths and existing analysis metric IDs.
SCATTER_METRICS = {
    'volume_qualidade': ('sh90', 'xgps'),
    'progressao_seguranca': ('acc', 'progShare'),
    'reativo_proativo': ('reat90', 'prc90'),
    'posse': ('pl90', 'pw90'),
    'trabalho_eficiencia': ('gksf90', 'gksv'),
    'esperado_evitado': ('gkxgf90', 'gkxgp'),
}


def histogram(array, mask, bins, minimum=1):
    pool = array[mask & np.isfinite(array)]
    if pool.size < minimum:
        return None
    low, high = float(pool.min()), float(pool.max())
    high = high if high > low else low + 1
    counts, _ = np.histogram(pool, bins=bins, range=(low, high))
    return {'caixas': counts.tolist(), 'min': low, 'max': high, 'media': float(pool.mean())}


def scatter_points(rows, values, keys, mask):
    selected = mask.copy()
    for key in keys:
        selected &= np.isfinite(values[key])
    indices = np.flatnonzero(selected)
    if not indices.size:
        return []
    # Keep the existing extreme-point convention with a strict sample bound.
    extremes = set(analysis._extremos(values[keys[0]][indices], values[keys[1]][indices]).tolist())
    budget = max(0, analysis.PONTOS_DISPERSAO - len(extremes))
    sampled = set(np.linspace(0, len(indices) - 1, min(budget, len(indices)), dtype=int).tolist())
    chosen = sorted(extremes | sampled)
    return [[round(float(values[key][indices[i]]), 3) for key in keys] + [rows[indices[i]]['uid']]
            for i in chosen]


def goal_probability(goals, expected):
    observed, rate = data.number(goals, None), data.number(expected, None)
    if observed is None or rate is None or observed < 0 or not observed.is_integer() or rate < 0:
        return None
    if observed == 0:
        return 100
    if rate == 0:
        return 0
    # Same Poisson tail as analise_perfil.calcular. Log terms avoid overflowing
    # rate**i/factorial(i), and fsum limits cancellation in the CDF.
    count = int(observed)
    log_rate = math.log(rate)
    cdf = math.fsum(math.exp(-rate + i * log_rate - math.lgamma(i + 1)) for i in range(count))
    return round(100 * max(0, min(1, 1 - cdf)))


def analyse(conn, sid, uid, coorte=None, regua='top20', min_minutes=None):
    snapshot, rows, index = load(conn, sid, uid)
    coorte, benchmark, minimum, mask = cohort(rows, index, coorte, regua, min_minutes)
    metrics, values = player_metrics(rows, index, mask)
    player = rows[index]
    totals = {key: player[key] for key in mb.RAW_FIELDS if data.number(player.get(key), None) is not None}
    if not totals:
        raise ValueError('Jogador sem estatisticas armazenadas para analise')
    # The match payload has its own coverage flag; absent logs are not invented.
    matches = match_data(conn, sid, player)
    result = {'uid': uid, 'posicao': player['position'], 'coorte': coorte, 'regua': benchmark,
              'min_minutes': minimum, 'n': int(mask.sum()), 'totais': totals,
              'metricas': metrics, 'partidas': matches,
              'contexto': {'snapshot_id': sid, 'carreira_id': snapshot.get('carreira_id'),
                           'temporada': snapshot.get('in_game_season'), 'partidas_disponiveis': bool(matches)},
              'forma': analysis.forma_basica(conn, sid, uid),
              'nomes_times': {str(row['club_uid']): row['club_name'] for row in rows if row['club_uid']},
              'similares': {key: [] for key in analysis.SIMILARIDADE}}
    result['distribuicao'] = {}
    for key in analysis.BANCO18:
        distribution = histogram(values[key], mask, analysis.CAIXAS_DISTRIBUICAO)
        if distribution is not None:
            result['distribuicao'][key] = distribution
    result['dispersao'] = {}
    for name, keys in SCATTER_METRICS.items():
        eligible = mask.copy()
        if name == 'progressao_seguranca':
            eligible &= np.array([data.number(row.get('passes_attempted')) >= 200 for row in rows])
        result['dispersao'][name] = (scatter_points(rows, values, keys, eligible)
                                     if all(key in metrics for key in keys) else [])
    result['histograma'] = {}
    for name, key in (('gols_menos_xg', 'gMenosXg10'), ('assist_menos_xa', 'aMenosXa90')):
        distribution = histogram(values[key], mask, analysis.CAIXAS_HISTOGRAMA, minimum=2)
        if key in metrics and distribution is not None:
            result['histograma'][name] = distribution
    probability = goal_probability(player.get('goals'), player.get('xg'))
    if probability is not None:
        result['poisson'] = {'gols': probability}
    for tab, keys in analysis.SIMILARIDADE.items():
        result['similares'][tab] = analysis_peers(rows, index, mask, metrics, values, keys)
    axes = (('xg90', 'sh90'), ('xa90', 'kp90', 'ccc90'))
    if all(key in metrics for keys in axes for key in keys):
        scales = {}
        for keys in axes:
            for key in keys:
                pool = values[key][mask & np.isfinite(values[key])]
                scales[key] = (float(pool.mean()), float(pool.std()) or 1)
        def coordinate(player_index):
            return [round(float(np.mean([(values[key][player_index] - scales[key][0]) / scales[key][1]
                                         for key in keys])), 2) for keys in axes]
        result['criador_finalizador_eu'] = coordinate(index)
        candidates = mask.copy()
        for keys in axes:
            for key in keys:
                candidates &= np.isfinite(values[key])
        coordinates = np.array([coordinate(i) for i in range(len(rows))])
        result['dispersao']['criador_finalizador'] = scatter_points(
            rows, {'fin': coordinates[:, 0], 'cri': coordinates[:, 1]}, ('fin', 'cri'), candidates)
    if player['position'].lower() == 'gk':
        result['goleiro'] = {'n': int(mask.sum()), 'distribuicao': {}, 'metricas': {key: metrics[key] for key in analysis.METRICAS_GK if key in metrics},
                             'totais': totals, 'similares': analysis_peers(rows, index, mask, metrics, values, analysis.SIMILARIDADE_GK)}
        result['similares']['gk'] = result['goleiro']['similares']
        for key in analysis.METRICAS_GK:
            distribution = histogram(values[key], mask, analysis.CAIXAS_DISTRIBUICAO)
            if distribution is not None:
                result['goleiro']['distribuicao'][key] = distribution
        distribution = histogram(values['gkev10'], mask, analysis.CAIXAS_HISTOGRAMA, minimum=2)
        if 'gkev10' in metrics and distribution is not None:
            result['goleiro']['histograma'] = distribution
    return result


def analysis_peers(rows, index, mask, metrics, values, keys):
    available = [key for key in keys if key in metrics]
    if len(available) < similar.MIN_METRICAS:
        return []
    candidates = mask.copy()
    for key in available:
        candidates &= np.isfinite(values[key])
    indices = np.flatnonzero(candidates)
    if not indices.size:
        return []
    matrix = np.stack([values[key][indices] for key in available], axis=1)
    reference = np.array([values[key][index] for key in available])
    scale = matrix.std(axis=0)
    scale[scale == 0] = 1
    distance = np.sqrt(np.mean(((matrix - reference) / scale) ** 2, axis=1))
    ranked = sorted((float(dist), rows[i]['uid']) for i, dist in zip(indices, distance) if i != index)
    return [{'uid': other, 'sim': round(max(0, 100 - 22 * dist), 1)}
            for dist, other in ranked[:analysis.SIMILARES_POR_ABA]]


def match_data(conn, sid, player):
    rows = [dict(row) for row in conn.execute(
        'SELECT * FROM player_match_stats WHERE snapshot_id=? AND uid=? ORDER BY match_date,match_id',
        (sid, player['uid']))]
    if not rows:
        return None
    for row in rows:
        minutes = data.number(row.get('minutes'), None)
        row['minutes'] = minutes if minutes is not None and minutes >= 0 else None
    national_teams = analysis.times_de_selecao(conn, sid)
    rows = [row for row in rows if row['team_uid'] not in national_teams]
    if not rows:
        return None
    window, coverage = analysis.janela_da_temporada(rows, player.get('apps_total'), player.get('minutes'), national_teams)
    if any(row['minutes'] is None for row in window):
        coverage = 'parcial'
    team_rows = [dict(row) for row in conn.execute('SELECT * FROM team_match_stats WHERE snapshot_id=?', (sid,))]
    teams = {(row['team_uid'], row['match_id']): row for row in team_rows}
    series = []
    for row in sorted(window, key=lambda item: (item['match_date'], item['match_id'])):
        team = teams.get((row['team_uid'], row['match_id']), {})
        goals, against = team.get('goals_for'), team.get('goals_against')
        result = None if goals is None or against is None else 'V' if goals > against else 'D' if goals < against else 'E'
        series.append({'d': row['match_date'], 'c': row['comp_uid'], 'o': row['opp_uid'],
                       'casa': row['home'], 'tit': row['started'], 'm': row['minutes'],
                       'n': row['rating'], 'g': row['goals'], 'a': row['assists'],
                       'xg': row['xg'], 'res': result, 'gs': against, 'xgc': team.get('xg_against')})
    def context_summary(matches):
        if not matches:
            return None
        durations = [row['minutes'] for row in matches]
        known = [value for value in durations if value is not None]
        minutes = sum(known) if len(known) == len(matches) else None
        summary = {'jogos': len(matches), 'min': minutes, 'min_conhecidos': sum(known),
                   'jogos_com_minutos': len(known)}
        ratings = [data.number(row.get('rating'), None) for row in matches]
        ratings = [rating for rating in ratings if rating is not None]
        summary['nota'] = round(sum(ratings) / len(ratings), 2) if ratings else None
        for key, field in {'g': 'goals', 'a': 'assists', 'sh90': 'shots', 'xg90': 'xg',
                           'xa90': 'xa', 'kp90': 'key_passes', 'prc90': 'presses_completed',
                           'tkw90': 'tackles_completed', 'itc90': 'interceptions', 'spr90': 'sprints'}.items():
            measured = [data.number(row.get(field), None) for row in matches]
            if all(value is not None for value in measured):
                if key in ('g', 'a'):
                    summary[key] = sum(measured)
                elif minutes is not None and minutes > 0:
                    summary[key] = round(sum(measured) * 90 / minutes, 3)
        if 'g' in summary and 'a' in summary and minutes is not None and minutes > 0:
            summary['ga90'] = round((summary['g'] + summary['a']) * 90 / minutes, 3)
        for key, field in (('gs90', 'goals_against'), ('xgc90', 'xg_against')):
            measured = [data.number(teams.get((row['team_uid'], row['match_id']), {}).get(field), None)
                        for row in matches]
            if minutes is not None and minutes > 0 and all(value is not None for value in measured):
                summary[key] = round(sum(measured) * 90 / minutes, 3)
        goals_against = [data.number(teams.get((row['team_uid'], row['match_id']), {}).get('goals_against'), None)
                         for row in matches]
        if all(value is not None for value in goals_against):
            summary['cs'] = round(100 * sum(value == 0 for value in goals_against) / len(matches), 1)
        return summary
    comps = sorted({row['comp_uid'] for row in window}, key=lambda uid: (uid is None, uid or 0))
    context = {'casa': context_summary([row for row in window if row['home']]),
               'fora': context_summary([row for row in window if row['home'] == 0]),
               'titular': context_summary([row for row in window if row['started']]),
               'reserva': context_summary([row for row in window if row['started'] == 0]),
               'competicoes': [{'comp_uid': comp, **context_summary([row for row in window if row['comp_uid'] == comp])}
                               for comp in comps]}
    weights = {}
    for field in analysis.PESO_CAMPOS:
        team_field = {'goals': 'goals_for', 'xg': 'xg_for', 'shots': 'shots_for',
                      'shots_on_target': 'shots_on_target_for'}.get(field, field)
        own = [data.number(row.get(field), None) for row in window]
        team_values = [data.number(teams.get((row['team_uid'], row['match_id']), {}).get(team_field), None)
                       for row in window]
        if all(value is not None for value in own + team_values) and sum(team_values) > 0:
            weights[field] = {'v': sum(own), 't': sum(team_values),
                              'p': round(100 * sum(own) / sum(team_values), 2)}
    known_minutes = [row['minutes'] for row in window if row['minutes'] is not None]
    total_minutes = sum(known_minutes) if len(known_minutes) == len(window) else None
    return {'cobertura': coverage, 'jogos': len(window),
            'jogos_da_temporada': player.get('apps_total'), 'minutos': total_minutes,
            'minutos_da_temporada': player.get('minutes'), 'minutos_conhecidos': sum(known_minutes),
            'jogos_com_minutos': len(known_minutes), 'serie': series, 'contexto': context,
            'peso': {'campos': weights, 'fatia_justa': round(100 * total_minutes / (max(1, len(window)) * 90 * 11), 2) if total_minutes is not None else None},
            'com_e_sem': None, 'peso_goleiro': None}



NUMBER_PARAMS = {'tol': (0, 100), 'fora': (0, similar.FORA_MAXIMO), 'min_minutes': (0, 1000000),
                 'limite': (1, 5000), 'piso_ca': (0, 200), 'ca_max': (0, 200),
                 'valor_max': (0, 1e15), 'idade_max': (0, 100), 'excluir_clube': (1, 2 ** 63 - 1)}
BOOL_PARAMS = {'top20', 'contrato12', 'salario_ate_dele'}
SEARCH_PARAMS = set(NUMBER_PARAMS) | BOOL_PARAMS | {'modo', 'objetivo', 'metricas', 'mais', 'pe', 'nivel', 'ligas', 'contrato_ate'}


def search_params(params):
    unknown = set(params) - SEARCH_PARAMS
    if unknown:
        raise ValueError('Parametros desconhecidos: ' + ', '.join(sorted(unknown)))
    result = dict(params)
    for key, (low, high) in NUMBER_PARAMS.items():
        if key not in result:
            continue
        number = data.number(result[key], None)
        if isinstance(result[key], bool) or number is None or not low <= number <= high:
            raise ValueError(f'{key}: numero entre {low} e {high} necessario')
        if key in ('fora', 'min_minutes', 'limite', 'excluir_clube') and not number.is_integer():
            raise ValueError(f'{key}: numero inteiro necessario')
        result[key] = int(number) if number.is_integer() else number
    for key in BOOL_PARAMS:
        if key in result:
            if str(result[key]).lower() not in ('0', '1', 'true', 'false'):
                raise ValueError(f'{key}: use 0 ou 1')
            result[key] = str(result[key]).lower() in ('1', 'true')
    if result.get('modo', 'faixa') not in ('faixa', 'melhor', 'pct'):
        raise ValueError('modo: use faixa, melhor ou pct')
    if result.get('objetivo', '') not in similar.OBJETIVOS:
        raise ValueError('objetivo desconhecido')
    if result.get('pe', '') not in ('', 'igual', 'left', 'right', 'both'):
        raise ValueError('pe desconhecido')
    if result.get('nivel', 'ca') not in ('ca', 'overall'):
        raise ValueError('nivel: use ca ou overall')
    if result.get('nivel') == 'overall' and (result.get('piso_ca') or result.get('ca_max')):
        raise ValueError('Filtros de nivel overall sem dados suficientes; use ca')
    for key in ('metricas', 'mais', 'ligas'):
        if key in result:
            items = result[key].split(',') if isinstance(result[key], str) else result[key]
            if not isinstance(items, list) or any(isinstance(item, (dict, list, bool)) for item in items):
                raise ValueError(f'{key}: lista necessaria')
            if key == 'metricas':
                if not 1 <= len(items) <= similar.MAX_METRICAS or any(not isinstance(item, str) for item in items):
                    raise ValueError('metricas: selecione de 1 a 6 metricas suportadas')
                result[key] = list(dict.fromkeys(items))
            else:
                try:
                    result[key] = [int(item) for item in items]
                except (TypeError, ValueError):
                    raise ValueError(f'{key}: IDs inteiros necessarios') from None
                if any(item <= 0 for item in result[key]) or key == 'mais' and len(result[key]) > 2:
                    raise ValueError(f'{key}: IDs invalidos')
    if result.get('contrato_ate'):
        try:
            date.fromisoformat(result['contrato_ate'])
        except (TypeError, ValueError):
            raise ValueError('contrato_ate: data ISO necessaria') from None
    return result


def search(conn, sid, uid=None, params=None, ref=None):
    snapshot, rows, index = load(conn, sid, uid)
    params = search_params(params or {})
    if ref is not None:
        if not isinstance(ref, dict) or not isinstance(ref.get('valores'), dict):
            raise ValueError('ref.valores: receita com valores de referencia necessaria')
        if ref.get('coorte') not in similar.CANDIDATAS or ref.get('grupo') not in mb.GROUP_POSITIONS:
            raise ValueError('ref: coorte e grupo de posicao necessarios')
        if ref['coorte'] != ref['grupo']:
            raise ValueError('ref: grupo e coorte incompativeis')
        for key, value in ref['valores'].items():
            if not isinstance(key, str) or isinstance(value, bool) or data.number(value, None) is None:
                raise ValueError('ref.valores: use valores numericos finitos')
        ref = dict(ref, valores={key: float(value) for key, value in ref['valores'].items()})
        for key in ('minutos', 'idade', 'ca', 'pa', 'valor', 'salario', 'nota'):
            if ref.get(key) is not None:
                if isinstance(ref[key], bool) or data.number(ref[key], None) is None or data.number(ref[key]) < 0:
                    raise ValueError('ref.' + key + ': numero finito positivo necessario')
                ref[key] = data.number(ref[key])
        coorte = ref['coorte']
        indices = []
        params['ref'] = ref
    else:
        if index is None:
            raise ValueError('ref: receita com valores de referencia necessaria')
        indices = [index]
        for other in params.pop('mais', []):
            other_index = next((i for i, row in enumerate(rows) if row['uid'] == other), None)
            if other_index is None:
                raise ValueError('mais: jogador nao encontrado neste snapshot')
            if other_index not in indices:
                indices.append(other_index)
        coorte = similar.coorte_da_posicao(rows[index]['position'].lower())
        if coorte is None:
            raise ValueError('Posicao sem coorte de comparacao')
    candidates = set(similar._candidatas_do_objetivo(coorte, params.get('objetivo', '')))
    requested = params.get('metricas', [])
    if any(key not in candidates for key in requested) or ref and any(key not in candidates for key in ref['valores']):
        raise ValueError('metricas: IDs nao suportados para esta posicao/objetivo')
    if ref and any(key not in ref['valores'] for key in requested):
        raise ValueError('ref.valores: faltam valores para as metricas selecionadas')
    if params.pop('top20', False):
        leagues = {row['league_uid']: row['_league_reputation'] for row in rows if row['league_uid'] is not None}
        params['ligas'] = list(set(params.get('ligas', leagues)) & set(sorted(leagues, key=lambda league: (-leagues[league], league))[:20]))
    if params.pop('contrato12', False):
        try:
            current = date.fromisoformat(snapshot['game_date'])
        except (TypeError, ValueError, KeyError):
            raise ValueError('contrato12: snapshot sem data do jogo valida') from None
        try:
            until = current.replace(year=current.year + 1)
        except ValueError:
            until = current.replace(year=current.year + 1, day=28)
        params['contrato_ate'] = until.isoformat()
    if params.get('piso_ca') or params.get('ca_max'):
        levels = [ref.get('ca')] if ref else [rows[i].get('ca') for i in indices]
        if any(data.number(value, None) is None for value in levels):
            raise ValueError('Filtros de CA precisam da CA da referencia')
    if params.get('salario_ate_dele'):
        wages = [ref.get('salario')] if ref else [rows[i].get('wage') for i in indices]
        if any(data.number(value, None) is None for value in wages):
            raise ValueError('Filtro de salario precisa do salario da referencia')
    fields, _, valid = metric_arrays(rows)
    meta_keys = {'uid': 'uid', 'name': 'name', 'pos': 'position', 'ca': 'ca', 'pa': 'pa',
                 'wage': 'wage', 'value': 'transfer_value', 'age': 'age', 'rating': 'avg_rating',
                 'foot': 'foot', 'club': 'club_name', 'club_uid': 'club_uid', 'league_uid': 'league_uid',
                 'contract': 'contract_end'}
    strings = {'name', 'pos', 'foot', 'club', 'contract'}
    meta = {key: np.array([str(row.get(field) or '').lower() if key == 'pos' else str(row.get(field) or '')
                           if key in strings else data.number(row.get(field), np.nan) for row in rows])
            for key, field in meta_keys.items()}
    return similar.executar(fields, meta, indices, params, valid)
