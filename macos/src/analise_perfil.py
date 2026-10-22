import math
import sqlite3
import numpy as np
import moneyball as mb

MIN_CHUTES_RAZAO = 15
MIN_CHUTES_SORTE = 20
MIN_PASSES_CHAVE = 15
MIN_DESARMES = 15
MIN_PRESSOES = 30
MIN_CABECEIOS = 15
MIN_CRUZAMENTOS = 15
MIN_NO_ALVO = 8

PONTOS_DISPERSAO = 650
CAIXAS_HISTOGRAMA = 22


def _razao(a, b):
    return np.where(b > 0, a / np.maximum(b, 1e-09), 0.0)


def _p90(campo):
    def f(c):
        return _razao(c[campo], c['minutes'] / 90.0)
    return f


def _soma90(*campos):
    def f(c):
        return _razao(sum(c[x] for x in campos), c['minutes'] / 90.0)
    return f


def _pct_de(a, b):
    def f(c):
        return 100.0 * _razao(c[a], c[b])
    return f


def _metricas():
    m = {}
    m['sh90'] = (_p90('shots'), None, False)
    m['xg90'] = (_p90('xg'), None, False)
    m['g90'] = (_p90('goals'), None, False)
    m['sot90'] = (_p90('shots_on_target'), None, False)
    m['xgps'] = (lambda c: _razao(c['xg'], c['shots']), lambda c: c['shots'] >= MIN_CHUTES_RAZAO, False)
    m['prec'] = (_pct_de('shots_on_target', 'shots'), lambda c: c['shots'] >= MIN_CHUTES_RAZAO, False)
    m['conv'] = (_pct_de('goals', 'shots'), lambda c: c['shots'] >= MIN_CHUTES_RAZAO, False)
    m['convAlvo'] = (_pct_de('goals', 'shots_on_target'), lambda c: c['shots_on_target'] >= MIN_NO_ALVO, False)
    m['shout_pct'] = (_pct_de('shots_outside_box', 'shots'), lambda c: c['shots'] >= MIN_CHUTES_RAZAO, False)
    m['xa90'] = (_p90('xa'), None, False)
    m['kp90'] = (_p90('key_passes'), None, False)
    m['ccc90'] = (_p90('clear_cut_chances'), None, False)
    m['a90'] = (_p90('assists'), None, False)
    m['xaPorKp'] = (lambda c: _razao(c['xa'], c['key_passes']), lambda c: c['key_passes'] >= MIN_PASSES_CHAVE, False)
    m['aPorKp'] = (_pct_de('assists', 'key_passes'), lambda c: c['key_passes'] >= MIN_PASSES_CHAVE, False)
    m['pa90'] = (_p90('passes_attempted'), None, False)
    m['pp90'] = (_p90('passes_progressive'), None, False)
    m['acc'] = (_pct_de('passes_completed', 'passes_attempted'), None, False)
    m['progShare'] = (_pct_de('passes_progressive', 'passes_completed'), None, False)
    m['crc90'] = (_p90('crosses_completed'), None, False)
    m['cra90'] = (_p90('crosses_attempted'), None, False)
    m['crPct'] = (_pct_de('crosses_completed', 'crosses_attempted'), lambda c: c['crosses_attempted'] >= MIN_CRUZAMENTOS, False)
    m['pl90'] = (_p90('possession_lost'), None, True)
    m['pw90'] = (_p90('possession_won'), None, False)
    m['reat90'] = (_soma90('tackles_completed', 'interceptions', 'clearances', 'blocks'), None, False)
    m['prc90'] = (_p90('presses_completed'), None, False)
    m['pra90'] = (_p90('presses_attempted'), None, False)
    m['tkpct'] = (_pct_de('tackles_completed', 'tackles_attempted'), lambda c: c['tackles_attempted'] >= MIN_DESARMES, False)
    m['prpct'] = (_pct_de('presses_completed', 'presses_attempted'), lambda c: c['presses_attempted'] >= MIN_PRESSOES, False)
    m['aerpct'] = (_pct_de('headers_won', 'headers_attempted'), lambda c: c['headers_attempted'] >= MIN_CABECEIOS, False)
    m['tkw90'] = (_p90('tackles_completed'), None, False)
    m['itc90'] = (_p90('interceptions'), None, False)
    m['clrblk90'] = (_soma90('clearances', 'blocks'), None, False)
    m['hw90'] = (_p90('headers_won'), None, False)
    m['fc90'] = (_p90('fouls_committed'), None, True)
    m['fw90'] = (_p90('fouls_won'), None, False)
    m['ya90'] = (_p90('yellow_cards'), None, True)
    m['spr90'] = (_p90('sprints'), None, False)
    m['dr90'] = (_p90('dribbles'), None, False)
    m['gMenosXg10'] = (lambda c: 10.0 * _razao(c['goals'] - c['xg'], c['shots']), lambda c: c['shots'] >= MIN_CHUTES_SORTE, False)
    m['aMenosXa90'] = (lambda c: _razao(c['assists'] - c['xa'], c['minutes'] / 90.0), lambda c: c['key_passes'] >= MIN_PASSES_CHAVE, False)
    m['npxg90'] = (_p90('npxg'), None, False)
    m['dist90'] = (_p90('distance_km'), lambda c: c['distance_km'] > 0, False)
    m['minPorGol'] = (lambda c: _razao(c['minutes'], c['goals']), lambda c: c['goals'] >= 1, True)
    m['minPorChute'] = (lambda c: _razao(c['minutes'], c['shots']), lambda c: c['shots'] >= 1, True)
    return m


METRICAS = _metricas()

CAMPOS = (
    'minutes',
    'npxg',
    'distance_km',
    'goals',
    'assists',
    'shots',
    'shots_on_target',
    'shots_outside_box',
    'goals_outside_box',
    'xg',
    'xa',
    'key_passes',
    'clear_cut_chances',
    'crosses_attempted',
    'crosses_completed',
    'passes_attempted',
    'passes_completed',
    'passes_progressive',
    'dribbles',
    'tackles_attempted',
    'tackles_completed',
    'interceptions',
    'clearances',
    'blocks',
    'headers_attempted',
    'headers_won',
    'fouls_committed',
    'fouls_won',
    'yellow_cards',
    'possession_won',
    'possession_lost',
    'presses_attempted',
    'presses_completed',
    'sprints',
)

BANCO18 = (
    'g90',
    'npxg90',
    'sh90',
    'sot90',
    'conv',
    'xa90',
    'kp90',
    'ccc90',
    'crc90',
    'acc',
    'pp90',
    'dr90',
    'pl90',
    'prc90',
    'pw90',
    'tkw90',
    'aerpct',
    'dist90',
)

CAIXAS_DISTRIBUICAO = 28

SIMILARIDADE = {
    'fin': ('sh90', 'xg90', 'g90', 'sot90'),
    'cri': ('xa90', 'kp90', 'ccc90', 'crc90', 'pp90', 'a90'),
    'def': ('prc90', 'spr90', 'tkw90', 'itc90', 'hw90', 'clrblk90'),
    'geral': tuple(k for k in BANCO18 if k != 'dist90'),
}

SIMILARES_POR_ABA = 5
EXTREMOS_POR_CANTO = 3


def _extremos(x, y):
    if x.size == 0:
        return np.array([], dtype=int)
    zx = (x - x.mean()) / (x.std() or 1.0)
    zy = (y - y.mean()) / (y.std() or 1.0)
    achados = []
    for score in (zx + zy, zx - zy, -zx + zy, -zx - zy):
        achados.extend(np.argsort(-score)[:EXTREMOS_POR_CANTO].tolist())
    return np.array(sorted(set(achados)), dtype=int)


def _cortar(campos, mascara):
    return {k: np.asarray(campos[k], dtype=float)[mascara] for k in CAMPOS}


def _eu(campos, idx):
    return {k: np.asarray([float(campos[k][idx])]) for k in CAMPOS}


def _percentil(pool, valor, menos_e_melhor):
    if pool.size == 0:
        return 100.0
    p = float(mb.percentile_ranks(pool, np.asarray([valor]))[0])
    if menos_e_melhor:
        return 100.0 - p
    return p


def _posicao_no_ranking(pool, valor, menos_e_melhor):
    melhores = int((pool < valor if menos_e_melhor else pool > valor).sum())
    return melhores + 1


def calcular(campos, mascara, idx, uids):
    pool_c = _cortar(campos, mascara)
    eu_c = _eu(campos, idx)
    uids_pool = np.asarray(uids)[mascara]

    valores, meus, elegivel_pool, elegivel_eu = {}, {}, {}, {}
    metricas = {}
    for k, (fn, elegivel, menos) in METRICAS.items():
        v = np.asarray(fn(pool_c), dtype=float)
        e = np.ones(v.shape, dtype=bool) if elegivel is None else np.asarray(elegivel(pool_c), dtype=bool)
        meu = float(np.asarray(fn(eu_c), dtype=float)[0])
        ok = True if elegivel is None else bool(np.asarray(elegivel(eu_c), dtype=bool)[0])
        valores[k] = v
        elegivel_pool[k] = e
        meus[k] = meu
        base = v[e]
        metricas[k] = {
            'v': round(meu, 4),
            'ok': ok,
            'n': int(base.size),
            'p': round(_percentil(base, meu, menos), 1),
            'rank': _posicao_no_ranking(base, meu, menos),
            'mediana': round(float(np.median(base)), 4) if base.size else 0.0,
        }

    def amostra(chaves, filtro=None):
        sel = np.ones(uids_pool.shape, dtype=bool)
        for k in chaves:
            sel &= elegivel_pool[k]
        if filtro is not None:
            sel &= filtro
        todos = np.nonzero(sel)[0]
        passo = max(1, todos.size // PONTOS_DISPERSAO)
        ind = set(todos[::passo].tolist())
        if len(chaves) == 2 and todos.size:
            ind |= set(todos[_extremos(valores[chaves[0]][todos], valores[chaves[1]][todos])].tolist())
        return [
            [round(float(valores[k][i]), 3) for k in chaves] + [int(uids_pool[i])]
            for i in sorted(ind)
        ]

    def distribuicao(k):
        base = valores[k][elegivel_pool[k]]
        if base.size < 2:
            return {'caixas': [0] * CAIXAS_DISTRIBUICAO, 'min': 0.0, 'max': 1.0, 'media': 0.0}
        lo = float(base.min())
        hi = float(base.max())
        caixas, _ = np.histogram(base, bins=CAIXAS_DISTRIBUICAO, range=(lo, hi if hi > lo else lo + 1))
        return {
            'caixas': [int(x) for x in caixas],
            'min': round(lo, 4),
            'max': round(hi, 4),
            'media': round(float(base.mean()), 4),
        }

    def z(k, v):
        base = valores[k]
        sd = float(base.std()) or 1.0
        return (v - float(base.mean())) / sd

    fin_ks = ('xg90', 'sh90')
    cri_ks = ('xa90', 'kp90', 'ccc90')
    fc_pool = np.stack([
        np.mean([
            (valores[k] - valores[k].mean()) / (valores[k].std() or 1.0)
            for k in ks
        ], axis=0)
        for ks in (fin_ks, cri_ks)
    ], axis=1)
    passo = max(1, fc_pool.shape[0] // PONTOS_DISPERSAO)
    fc_ind = set(range(0, fc_pool.shape[0], passo)) | set(_extremos(fc_pool[:, 0], fc_pool[:, 1]).tolist())
    fc_pontos = [
        [round(float(fc_pool[i, 0]), 2), round(float(fc_pool[i, 1]), 2), int(uids_pool[i])]
        for i in sorted(fc_ind)
    ]
    fc_eu = [
        round(float(np.mean([z(k, meus[k]) for k in ks])), 2)
        for ks in (fin_ks, cri_ks)
    ]

    def histograma(k):
        base = valores[k][elegivel_pool[k]]
        if base.size < 2:
            return {'caixas': [0] * CAIXAS_HISTOGRAMA, 'min': 0.0, 'max': 1.0}
        lo = float(base.min())
        hi = float(base.max())
        caixas, _ = np.histogram(base, bins=CAIXAS_HISTOGRAMA, range=(lo, hi if hi > lo else lo + 1))
        return {
            'caixas': [int(x) for x in caixas],
            'min': round(lo, 3),
            'max': round(hi, 3),
        }

    def poisson_ge(feito, esperado):
        lam = max(float(esperado), 1e-09)
        return 1.0 - sum(math.exp(-lam) * (lam ** i) / math.factorial(i) for i in range(int(feito)))

    gols = int(eu_c['goals'][0])
    assist = int(eu_c['assists'][0])

    sel = elegivel_pool['shout_pct'] & elegivel_pool['prec']
    corr = 0.0
    if int(sel.sum()) > 3:
        a = valores['shout_pct'][sel]
        b = valores['prec'][sel]
        if a.std() > 0 and b.std() > 0:
            corr = float(np.corrcoef(a, b)[0, 1])

    similares = {}
    for aba, chaves in SIMILARIDADE.items():
        mu = [float(valores[k].mean()) for k in chaves]
        sd = [float(valores[k].std()) or 1.0 for k in chaves]
        zeu = np.array([(meus[k] - mu[j]) / sd[j] for j, k in enumerate(chaves)])
        zpool = np.stack([(valores[k] - mu[j]) / sd[j] for j, k in enumerate(chaves)], axis=1)
        dist = np.sqrt(((zpool - zeu) ** 2).mean(axis=1))
        dist[uids_pool == uids[idx]] = np.inf
        ordem = np.argsort(dist)[:SIMILARES_POR_ABA]
        similares[aba] = [
            {'uid': int(uids_pool[i]), 'sim': round(max(0.0, 100.0 - 22.0 * float(dist[i])), 1)}
            for i in ordem if np.isfinite(dist[i])
        ]

    return {
        'n': int(mascara.sum()),
        'metricas': metricas,
        'dispersao': {
            'volume_qualidade': amostra(('sh90', 'xgps')),
            'distancia_pontaria': amostra(('shout_pct', 'prec')),
            'progressao_seguranca': amostra(('acc', 'progShare'), pool_c['passes_attempted'] >= 200),
            'reativo_proativo': amostra(('reat90', 'prc90')),
            'posse': amostra(('pl90', 'pw90')),
            'criador_finalizador': fc_pontos,
            'geral_xg_gols': amostra(('npxg90', 'g90')),
            'geral_rem_conv': amostra(('sh90', 'conv')),
            'geral_prog_drib': amostra(('pp90', 'dr90')),
            'geral_passe': amostra(('pa90', 'acc'), pool_c['passes_attempted'] >= 200),
        },
        'distribuicao': {k: distribuicao(k) for k in BANCO18},
        'criador_finalizador_eu': fc_eu,
        'histograma': {
            'gols_menos_xg': histograma('gMenosXg10'),
            'assist_menos_xa': histograma('aMenosXa90'),
        },
        'poisson': {
            'gols': round(100.0 * poisson_ge(gols, eu_c['xg'][0])),
            'assist': round(100.0 * poisson_ge(assist, eu_c['xa'][0])),
        },
        'correlacao_distancia_pontaria': {
            'r': round(corr, 3),
            'n': int(sel.sum()),
        },
        'similares': similares,
    }


MIN_FINALIZACOES_GK = 30
MIN_DEFESAS_GK = 20
MIN_PENALTIS_GK = 3

CAMPOS_GK = (
    'minutes',
    'apps_total',
    'gk_saves_held',
    'gk_saves_parried',
    'gk_saves_tipped',
    'goals_conceded_gk',
    'gk_penalties_faced',
    'gk_penalties_saved',
    'clean_sheets_gk',
    'xg_prevented_gk',
    'gk_xg_faced',
    'passes_attempted',
    'passes_completed',
)


def _defesas(c):
    return c['gk_saves_held'] + c['gk_saves_parried'] + c['gk_saves_tipped']


def _enfrentadas(c):
    return _defesas(c) + c['goals_conceded_gk']


def _metricas_goleiro():
    enfrentou = lambda c: (_enfrentadas(c) >= MIN_FINALIZACOES_GK) & (_defesas(c) > 0)
    return {
        'gksv': (lambda c: 100.0 * _razao(_defesas(c), _enfrentadas(c)), enfrentou, False),
        'gkxgp': (_p90('xg_prevented_gk'), None, False),
        'gkcs': (_pct_de('clean_sheets_gk', 'apps_total'), None, False),
        'gkpen': (_pct_de('gk_penalties_saved', 'gk_penalties_faced'), lambda c: c['gk_penalties_faced'] >= MIN_PENALTIS_GK, False),
        'gksf90': (lambda c: _razao(_enfrentadas(c), c['minutes'] / 90.0), None, False),
        'gkxgf90': (_p90('gk_xg_faced'), None, False),
        'ga90': (_p90('goals_conceded_gk'), None, True),
        'gkheld': (lambda c: 100.0 * _razao(c['gk_saves_held'], _defesas(c)), lambda c: _defesas(c) >= MIN_DEFESAS_GK, False),
        'gkpas': (_pct_de('passes_completed', 'passes_attempted'), lambda c: c['passes_attempted'] >= 100, False),
        'gkev10': (lambda c: 10.0 * _razao(c['xg_prevented_gk'], _enfrentadas(c)), enfrentou, False),
    }


METRICAS_GK = _metricas_goleiro()
SIMILARIDADE_GK = ('gksv', 'gkxgp', 'gkcs', 'gksf90', 'gkxgf90', 'gkheld')


def calcular_goleiro(campos, mascara, idx, uids):
    pool_c = {k: np.asarray(campos[k], dtype=float)[mascara] for k in CAMPOS_GK}
    eu_c = {k: np.asarray([float(campos[k][idx])]) for k in CAMPOS_GK}
    uids_pool = np.asarray(uids)[mascara]

    valores, meus, elegivel_pool, metricas = {}, {}, {}, {}
    for k, (fn, elegivel, menos) in METRICAS_GK.items():
        v = np.asarray(fn(pool_c), dtype=float)
        e = np.ones(v.shape, dtype=bool) if elegivel is None else np.asarray(elegivel(pool_c), dtype=bool)
        meu = float(np.asarray(fn(eu_c), dtype=float)[0])
        ok = True if elegivel is None else bool(np.asarray(elegivel(eu_c), dtype=bool)[0])
        valores[k] = v
        elegivel_pool[k] = e
        meus[k] = meu
        base = v[e]
        metricas[k] = {
            'v': round(meu, 4),
            'ok': ok,
            'n': int(base.size),
            'p': round(_percentil(base, meu, menos), 1),
            'rank': _posicao_no_ranking(base, meu, menos),
            'mediana': round(float(np.median(base)), 4) if base.size else 0.0,
        }

    def amostra(chaves):
        sel = np.ones(uids_pool.shape, dtype=bool)
        for k in chaves:
            sel &= elegivel_pool[k]
        todos = np.nonzero(sel)[0]
        passo = max(1, todos.size // PONTOS_DISPERSAO)
        ind = set(todos[::passo].tolist())
        if todos.size:
            ind |= set(todos[_extremos(valores[chaves[0]][todos], valores[chaves[1]][todos])].tolist())
        return [
            [round(float(valores[k][i]), 3) for k in chaves] + [int(uids_pool[i])]
            for i in sorted(ind)
        ]

    base = valores['gkev10'][elegivel_pool['gkev10']]
    if base.size >= 2:
        lo = float(base.min())
        hi = float(base.max())
        caixas, _ = np.histogram(base, bins=CAIXAS_HISTOGRAMA, range=(lo, hi if hi > lo else lo + 1))
        hist = {
            'caixas': [int(x) for x in caixas],
            'min': round(lo, 3),
            'max': round(hi, 3),
        }
    else:
        hist = {
            'caixas': [0] * CAIXAS_HISTOGRAMA,
            'min': 0.0,
            'max': 1.0,
        }

    mu = [float(valores[k].mean()) if valores[k].size else 0.0 for k in SIMILARIDADE_GK]
    sd = [(float(valores[k].std()) or 1.0) if valores[k].size else 1.0 for k in SIMILARIDADE_GK]
    similares = []
    if uids_pool.size:
        zeu = np.array([(meus[k] - mu[j]) / sd[j] for j, k in enumerate(SIMILARIDADE_GK)])
        zpool = np.stack([(valores[k] - mu[j]) / sd[j] for j, k in enumerate(SIMILARIDADE_GK)], axis=1)
        dist = np.sqrt(((zpool - zeu) ** 2).mean(axis=1))
        dist[uids_pool == uids[idx]] = np.inf
        similares = [
            {'uid': int(uids_pool[i]), 'sim': round(max(0.0, 100.0 - 22.0 * float(dist[i])), 1)}
            for i in np.argsort(dist)[:SIMILARES_POR_ABA] if np.isfinite(dist[i])
        ]

    def distribuicao(k):
        b = valores[k][elegivel_pool[k]]
        if b.size < 2:
            return {'caixas': [0] * CAIXAS_DISTRIBUICAO, 'min': 0.0, 'max': 1.0, 'media': 0.0}
        lo = float(b.min())
        hi = float(b.max())
        caixas, _ = np.histogram(b, bins=CAIXAS_DISTRIBUICAO, range=(lo, hi if hi > lo else lo + 1))
        return {
            'caixas': [int(x) for x in caixas],
            'min': round(lo, 4),
            'max': round(hi, 4),
            'media': round(float(b.mean()), 4),
        }

    return {
        'n': int(mascara.sum()),
        'metricas': metricas,
        'distribuicao': {k: distribuicao(k) for k in METRICAS_GK},
        'totais': {k: round(float(eu_c[k][0]), 3) for k in CAMPOS_GK},
        'dispersao': {
            'trabalho_eficiencia': amostra(('gksf90', 'gksv')),
            'esperado_evitado': amostra(('gkxgf90', 'gkxgp')),
        },
        'histograma': hist,
        'similares': similares,
    }


MIN_COM_ELE = 30
DIAS_ENTRE_TEMPORADAS = 400


def janela_da_temporada(linhas, apps_total, minutos_total, selecoes=frozenset()):
    if not linhas:
        return [], 'vazia'
    ordem = sorted(linhas, key=lambda r: (r['match_date'], r['match_id']), reverse=True)
    clube = next((r['team_uid'] for r in ordem if r['team_uid'] not in selecoes), ordem[0]['team_uid'])
    doclube = [r for r in ordem if r['team_uid'] == clube]
    alvo = int(apps_total or 0)
    janela = doclube[:alvo] if alvo > 0 else doclube
    minutos = sum(int(r['minutes'] or 0) for r in janela)
    if alvo > 0 and len(janela) < alvo:
        return janela, 'parcial'
    if abs(minutos - int(minutos_total or 0)) <= 2:
        return janela, 'exata'
    return janela, 'aproximada'


def _soma(linhas, campo):
    return float(sum(r[campo] or 0 for r in linhas))


def contexto(janela):
    def resumo(linhas):
        if not linhas:
            return None
        total = _soma(linhas, 'minutes')
        mi = total or 1.0
        por90 = lambda c: round(_soma(linhas, c) * 90.0 / mi, 3)
        notas = [r['nota'] for r in linhas if r.get('nota')]
        return {
            'jogos': len(linhas),
            'min': int(total),
            'nota': round(sum(notas) / len(notas), 2) if notas else None,
            'ga90': round((_soma(linhas, 'goals') + _soma(linhas, 'assists')) * 90.0 / mi, 3),
            'sh90': por90('shots'),
            'xg90': por90('xg'),
            'g': int(_soma(linhas, 'goals')),
            'a': int(_soma(linhas, 'assists')),
            'xa90': por90('xa'),
            'kp90': por90('key_passes'),
            'prc90': por90('presses_completed'),
            'tkw90': por90('tackles_completed'),
            'itc90': por90('interceptions'),
            'spr90': por90('sprints'),
            'gs90': round(sum(r.get('gs') or 0 for r in linhas) * 90.0 / mi, 3),
            'xgc90': round(sum(r.get('xgc') or 0 for r in linhas) * 90.0 / mi, 3),
            'cs': round(100.0 * sum(1 for r in linhas if r.get('gs') == 0) / len(linhas), 1),
        }

    por_comp = {}
    for r in janela:
        por_comp.setdefault(r['comp_uid'], []).append(r)
    comps = sorted(por_comp.items(), key=lambda kv: -len(kv[1]))
    saida = {
        'casa': resumo([r for r in janela if r['home']]),
        'fora': resumo([r for r in janela if not r['home']]),
        'titular': resumo([r for r in janela if r['started']]),
        'reserva': resumo([r for r in janela if not r['started']]),
        'competicoes': [{'comp_uid': uid, **resumo(ls)} for uid, ls in comps[:3]],
    }
    resto = [r for uid, ls in comps[3:] for r in ls]
    if resto:
        saida['competicoes'].append({'comp_uid': None, **resumo(resto)})
    return saida


PESO_CAMPOS = (
    'shots',
    'shots_on_target',
    'goals',
    'xg',
    'key_passes',
    'xa',
    'passes_progressive',
    'assists',
    'clear_cut_chances',
    'crosses_completed',
    'tackles_completed',
    'interceptions',
    'presses_completed',
    'possession_won',
    'possession_lost',
    'fouls_committed',
    'sprints',
    'clearances',
    'blocks',
    'headers_won',
)


def peso_no_time(janela, times_por_partida, minutos_do_jogador):
    campos = {}
    for campo in PESO_CAMPOS:
        meu = _soma(janela, campo)
        time = sum(float((times_por_partida.get(r['match_id']) or {}).get(campo) or 0) for r in janela)
        campos[campo] = {
            'v': round(meu, 3),
            't': round(time, 3),
            'p': round(100.0 * meu / time, 2) if time > 0 else 0.0,
        }
    jogos = len(janela) or 1
    return {
        'campos': campos,
        'fatia_justa': round(100.0 * (minutos_do_jogador / (jogos * 90.0)) / 11.0, 2),
    }


def com_e_sem(janela, times_do_clube):
    if not janela:
        return None
    inicio = min(r['match_date'] for r in janela)
    minutos_por_jogo = {r['match_id']: int(r['minutes'] or 0) for r in janela}
    sem, com = [], []
    for t in times_do_clube:
        if t['match_date'] < inicio:
            continue
        m = minutos_por_jogo.get(t['match_id'])
        if m is None:
            sem.append(t)
        elif m >= MIN_COM_ELE:
            com.append(t)

    def medias(ls):
        if not ls:
            return None
        n = len(ls)
        m = lambda c: round(sum(float(t[c] or 0) for t in ls) / n, 3)
        return {
            'jogos': n,
            'gols': m('goals'),
            'xg': m('xg'),
            'chutes': m('shots'),
            'passes_chave': m('key_passes'),
            'progressivos': m('passes_progressive'),
            'gols_sofridos': m('goals_against'),
            'xg_contra': m('xg_against'),
            'chutes_sofridos': m('shots_against'),
            'vitorias': round(100.0 * sum(1 for t in ls if t['goals'] > t['goals_against']) / n, 1),
            'sem_sofrer': round(100.0 * sum(1 for t in ls if t['goals_against'] == 0) / n, 1),
        }

    return {'com': medias(com), 'sem': medias(sem)}


def peso_goleiro(janela, times_do_clube):
    if not janela:
        return None
    inicio = min(r['match_date'] for r in janela)
    do_periodo = [t for t in times_do_clube if t['match_date'] >= inicio]
    meus = {r['match_id']: int(r['minutes'] or 0) for r in janela}
    cs_time = [t for t in do_periodo if t['goals_against'] == 0]
    cs_meus = [t for t in cs_time if meus.get(t['match_id'], 0) >= MIN_COM_ELE]

    def linha(v, t):
        return {
            'v': v,
            't': t,
            'p': round(100.0 * v / t, 2) if t else 0.0,
        }

    return {
        'minutos': linha(sum(meus.values()), 90 * len(do_periodo)),
        'jogos': linha(len(janela), len(do_periodo)),
        'sem_sofrer': linha(len(cs_meus), len(cs_time)),
    }


def serie(janela, times_por_partida):
    saida = []
    for r in sorted(janela, key=lambda x: (x['match_date'], x['match_id'])):
        t = times_por_partida.get(r['match_id'])
        res = None
        if t:
            if t['goals'] > t['goals_against']:
                res = 'V'
            elif t['goals'] < t['goals_against']:
                res = 'D'
            else:
                res = 'E'
        saida.append({
            'd': r['match_date'],
            'c': r['comp_uid'],
            'o': r.get('opp_uid'),
            'casa': int(r['home'] or 0),
            'tit': int(r['started'] or 0),
            'm': int(r['minutes'] or 0),
            'n': r.get('nota'),
            'g': int(r['goals'] or 0),
            'a': int(r['assists'] or 0),
            'xg': round(float(r['xg'] or 0), 2),
            'res': res,
            'gs': r.get('gs'),
            'xgc': round(float(r['xgc']), 2) if r.get('xgc') is not None else None,
        })
    return saida


def forma_basica(conn, sid, uid, n=24):
    linhas = conn.execute(
        'SELECT match_date, comp_uid, rating FROM player_form WHERE snapshot_id=? AND uid=? AND rating IS NOT NULL ORDER BY match_date DESC LIMIT ?',
        (sid, uid, n),
    ).fetchall()
    return [{'d': r[0], 'c': r[1], 'n': r[2]} for r in reversed(linhas)]


def times_de_selecao(conn, sid):
    try:
        return frozenset(r[0] for r in conn.execute(
            'SELECT team_uid FROM youth_teams WHERE snapshot_id=? AND nation IS NOT NULL',
            (sid,),
        ))
    except sqlite3.OperationalError:
        return frozenset()


def partidas_do_jogador(conn, sid, uid, apps_total, minutos_total):
    linhas = [dict(r) for r in conn.execute(
        'SELECT * FROM player_match_stats WHERE snapshot_id=? AND uid=?',
        (sid, uid),
    )]
    if not linhas:
        return None
    janela, cobertura = janela_da_temporada(linhas, apps_total, minutos_total, times_de_selecao(conn, sid))
    if not janela:
        return None
    clube = janela[0]['team_uid']
    times = {r['match_id']: dict(r) for r in conn.execute(
        'SELECT * FROM team_match_stats WHERE snapshot_id=? AND team_uid=?',
        (sid, clube),
    )}
    notas = {(r[0], r[1]): r[2] for r in conn.execute(
        'SELECT match_date, comp_uid, rating FROM player_form WHERE snapshot_id=? AND uid=? AND rating IS NOT NULL',
        (sid, uid),
    )}
    for r in janela:
        r['nota'] = notas.get((r['match_date'], r['comp_uid']))
        t = times.get(r['match_id'])
        r['gs'] = int(t['goals_against'] or 0) if t else None
        r['xgc'] = float(t['xg_against'] or 0) if t else None
    minutos = sum(int(r['minutes'] or 0) for r in janela)
    return {
        'cobertura': cobertura,
        'jogos': len(janela),
        'jogos_da_temporada': int(apps_total or 0),
        'minutos': minutos,
        'minutos_da_temporada': int(minutos_total or 0),
        'contexto': contexto(janela),
        'peso': peso_no_time(janela, times, minutos),
        'com_e_sem': com_e_sem(janela, list(times.values())),
        'serie': serie(janela, times),
        'peso_goleiro': peso_goleiro(janela, list(times.values())),
    }
