# Decompiled from buscar_como.pyc (Python 3.14) with macOS adaptations
import numpy as np

import analise_perfil as an
import moneyball as mb

MIN_METRICAS = 3
MAX_METRICAS = 6
FORA_PADRAO = 2
FORA_MAXIMO = 4
LIMITE_PADRAO = 500

CANDIDATAS = {
    'att': ('xg90', 'npxg90', 'sh90', 'sot90', 'g90', 'conv', 'xa90', 'kp90', 'dr90', 'aerpct'),
    'amc': ('xa90', 'kp90', 'ccc90', 'dr90', 'xg90', 'sh90', 'pp90', 'crc90', 'acc', 'npxg90'),
    'wing': ('crc90', 'kp90', 'xa90', 'dr90', 'pp90', 'tkw90', 'itc90', 'prc90', 'pw90', 'acc'),
    'dm': ('pw90', 'tkw90', 'itc90', 'prc90', 'pp90', 'acc', 'pa90', 'aerpct', 'clrblk90', 'kp90'),
    'b2b': ('pw90', 'pp90', 'kp90', 'tkw90', 'itc90', 'prc90', 'acc', 'dr90', 'xg90', 'xa90'),
    'def': ('tkw90', 'itc90', 'clrblk90', 'hw90', 'aerpct', 'prc90', 'pw90', 'pp90', 'acc', 'pa90'),
    'gk': ('gksv', 'gkxgp', 'gkcs', 'gkpen', 'gksf90', 'gkxgf90', 'ga90', 'gkheld', 'gkpas'),
}

PRODUCAO = {
    'att': ('xg90', 'npxg90', 'g90', 'sot90', 'conv', 'xa90', 'ccc90', 'a90', 'kp90'),
    'amc': ('xg90', 'g90', 'sot90', 'xa90', 'ccc90', 'a90', 'kp90', 'acc', 'pw90'),
    'wing': ('xa90', 'ccc90', 'crc90', 'kp90', 'xg90', 'g90', 'a90', 'acc', 'pw90'),
    'dm': ('pw90', 'tkw90', 'itc90', 'prc90', 'aerpct', 'hw90', 'clrblk90', 'acc', 'pp90'),
    'b2b': ('pw90', 'tkw90', 'itc90', 'xa90', 'kp90', 'xg90', 'acc', 'pp90', 'prc90'),
    'def': ('tkw90', 'itc90', 'clrblk90', 'hw90', 'aerpct', 'pw90', 'acc', 'prc90', 'pp90'),
    'gk': ('gksv', 'gkxgp', 'gkcs', 'gkpen', 'ga90'),
}

COMPORTAMENTO = {
    'att': ('sh90', 'shout_pct', 'dr90', 'kp90', 'pp90', 'pa90', 'pra90', 'spr90', 'hw90', 'fw90', 'fc90', 'pl90', 'tkw90'),
    'amc': ('sh90', 'shout_pct', 'dr90', 'kp90', 'pp90', 'progShare', 'pa90', 'cra90', 'pra90', 'spr90', 'fw90', 'fc90', 'tkw90', 'itc90', 'pl90', 'pw90'),
    'wing': ('cra90', 'dr90', 'pp90', 'pa90', 'sh90', 'shout_pct', 'spr90', 'pra90', 'tkw90', 'itc90', 'fc90', 'fw90', 'pl90'),
    'dm': ('pa90', 'pp90', 'progShare', 'pra90', 'fc90', 'pl90', 'spr90', 'dr90', 'sh90', 'kp90', 'cra90', 'fw90'),
    'b2b': ('pa90', 'pp90', 'progShare', 'dr90', 'sh90', 'pra90', 'spr90', 'fc90', 'pl90', 'cra90', 'kp90', 'fw90'),
    'def': ('pa90', 'pp90', 'progShare', 'pra90', 'fc90', 'pl90', 'spr90', 'cra90', 'dr90', 'fw90'),
    'gk': ('gkheld', 'gkpas', 'gksf90', 'gkxgf90'),
}

OBJETIVOS = ('', 'reposicao', 'estilo')


def _candidatas_do_objetivo(coorte, objetivo):
    if objetivo == 'reposicao':
        return PRODUCAO[coorte]
    if objetivo == 'estilo':
        return COMPORTAMENTO[coorte]
    return CANDIDATAS[coorte]


def grupo_da_posicao(pos):
    for g, ps in mb.GROUP_POSITIONS.items():
        if g != 'all' and pos in ps:
            return g
    return None


def coorte_da_posicao(pos):
    for g, ps in mb.COHORT_POSITIONS.items():
        if g != 'all' and pos in ps:
            return g
    return None


def _tabela_de_metricas(coorte):
    if coorte == 'gk':
        return an.METRICAS_GK, an.CAMPOS_GK
    return an.METRICAS, an.CAMPOS


def _cortar(campos, mascara, nomes):
    return {k: np.asarray(campos[k], dtype=float)[mascara] for k in nomes}


def _um(campos, idx, nomes):
    return {k: np.asarray([float(campos[k][idx])]) for k in nomes}


def executar(campos, meta, idx, params, validade=None):
    tol = float(params.get('tol', 20.0))
    modo = params.get('modo', 'faixa')
    if modo not in ('faixa', 'melhor', 'pct'):
        raise ValueError('modo desconhecido')
    objetivo = params.get('objetivo') or ''
    if objetivo not in OBJETIVOS:
        raise ValueError('objetivo desconhecido')
    fora = max(0, min(FORA_MAXIMO, int(params.get('fora', FORA_PADRAO))))
    min_minutes = int(params.get('min_minutes', 900))
    limite = int(params.get('limite', LIMITE_PADRAO))

    pos_arr = np.asarray(meta['pos'])
    fixa = params.get('ref')
    if fixa:
        idxs = []
        idx = None
        coorte = fixa.get('coorte')
        grupo = fixa.get('grupo')
        pos_ref = str(fixa.get('posicao') or '')
        if coorte not in CANDIDATAS or grupo not in mb.GROUP_POSITIONS or grupo == 'all':
            raise ValueError('receita com posicao desconhecida')
    else:
        idxs = [int(idx)] if np.isscalar(idx) else [int(i) for i in idx]
        if not (1 <= len(idxs) <= 3):
            raise ValueError('de 1 a 3 jogadores de referencia')
        idx = idxs[0]
        if len({coorte_da_posicao(str(pos_arr[i])) for i in idxs}) != 1:
            raise ValueError('as referencias sao de posicoes diferentes')
        pos_ref = str(pos_arr[idx])
        coorte = coorte_da_posicao(pos_ref)
        grupo = grupo_da_posicao(pos_ref)
        if coorte is None or grupo is None:
            raise ValueError('posicao sem coorte de comparacao')

    posicoes = set(mb.COHORT_POSITIONS[coorte]) & set(mb.GROUP_POSITIONS[grupo])
    metricas_tab, nomes_campos = _tabela_de_metricas(coorte)

    minutos = np.asarray(campos['minutes'], dtype=float)
    mascara = np.isin(pos_arr, list(posicoes)) & (minutos >= min_minutes)
    indices_pool = np.nonzero(mascara)[0]

    pool = _cortar(campos, mascara, nomes_campos)
    eus = [_um(campos, i, nomes_campos) for i in idxs]

    if idxs:
        ref_minutos = float(min(minutos[i] for i in idxs))
    else:
        ref_minutos = float(fixa.get('minutos') or min_minutes)

    valores = {}
    elegivel = {}
    meu = {}
    meu_ok = {}
    percentil = {}
    mediana = {}

    candidatas = [k for k in _candidatas_do_objetivo(coorte, objetivo) if k in metricas_tab]

    for k in candidatas:
        fn, ele, menos = metricas_tab[k]
        v = np.asarray(fn(pool), dtype=float)
        if ele is not None:
            e = np.asarray(ele(pool), dtype=bool)
        else:
            e = np.ones(v.shape, dtype=bool)

        e &= np.isfinite(v)
        if validade is not None:
            e &= np.asarray(validade[k], dtype=bool)[mascara]

        if fixa:
            m = float((fixa.get('valores') or {}).get(k, 0.0))
            ok = k in (fixa.get('valores') or {})
        else:
            m = float(np.mean([np.asarray(fn(eu), dtype=float)[0] for eu in eus]))
            ok = True if ele is None else all(bool(ele(eu)[0]) for eu in eus)

        ok = ok and np.isfinite(m)
        if validade is not None and idxs:
            ok = ok and all(bool(validade[k][i]) for i in idxs)
        base = v[e]
        valores[k] = v
        elegivel[k] = e
        meu[k] = m
        meu_ok[k] = ok
        percentil[k] = an._percentil(base, m, menos) if base.size else 0.0
        mediana[k] = float(np.median(base)) if base.size else 0.0

    possiveis = [k for k in candidatas if meu_ok[k] and abs(meu[k]) > 1e-9]
    pedidas = params.get('metricas') or []
    if any(k not in possiveis for k in pedidas):
        raise ValueError('metricas selecionadas sem medidas ou amostra suficientes')

    def p_bruto(k):
        if metricas_tab[k][2]:
            return 100.0 - percentil[k]
        return percentil[k]

    if pedidas:
        ligadas = pedidas[:MAX_METRICAS]
    elif objetivo == 'estilo':
        ligadas = sorted(possiveis, key=lambda k: -abs(p_bruto(k) - 50.0))[:MAX_METRICAS]
    else:
        ligadas = sorted(possiveis, key=lambda k: -percentil[k])[:MAX_METRICAS]

    if len(ligadas) < MIN_METRICAS:
        raise ValueError('a referencia tem menos de 3 metricas com amostra')

    n = len(ligadas)
    dif = np.empty((n, indices_pool.size))
    cabe = np.empty((n, indices_pool.size), dtype=bool)

    for j, k in enumerate(ligadas):
        menos = metricas_tab[k][2]
        if modo == 'pct':
            base = valores[k][elegivel[k]]
            if base.size:
                p_pool = np.asarray(mb.percentile_ranks(base, valores[k]), dtype=float)
            else:
                p_pool = np.zeros(indices_pool.size)
            if menos:
                p_pool = 100.0 - p_pool
            d = np.abs(p_pool - percentil[k])
            ok = (d <= tol / 2.0)
        else:
            assinada = ((valores[k] - meu[k]) / abs(meu[k])) * 100.0
            d = np.abs(assinada)
            if modo == 'melhor':
                if menos:
                    ok = (assinada <= tol)
                else:
                    ok = (assinada >= -tol)
                if objetivo == 'reposicao':
                    if menos:
                        d = np.maximum(0.0, assinada)
                    else:
                        d = np.maximum(0.0, -assinada)
            else:
                ok = (d <= tol)
        cabe[j] = ok & elegivel[k]
        dif[j] = np.where(elegivel[k], np.minimum(d, 100.0), 100.0)

    dentro = cabe.sum(axis=0)
    passou = (n - dentro) <= fora
    # An out-of-range allowance cannot replace a missing measurement.
    passou &= np.logical_and.reduce([elegivel[k] for k in ligadas])
    passou &= ~np.isin(indices_pool, idxs)

    ca = np.asarray(meta['ca'], dtype=float)[indices_pool]
    piso = float(params.get('piso_ca', 0) or 0)
    if piso > 0:
        if fixa:
            ca_ref = float(fixa.get('ca') or 0)
        else:
            ca_ref = float(np.mean([meta['ca'][i] for i in idxs]))
        if np.isfinite(ca_ref):
            passou &= (ca >= (ca_ref * piso / 100.0))

    if params.get('ca_max'):
        if fixa:
            ca_ref = float(fixa.get('ca') or 0)
        else:
            ca_ref = float(np.mean([meta['ca'][i] for i in idxs]))
        if np.isfinite(ca_ref):
            passou &= (ca <= (ca_ref * float(params['ca_max']) / 100.0))

    if params.get('salario_ate_dele'):
        if fixa:
            sal_ref = float(fixa['salario']) if fixa.get('salario') is not None else None
        else:
            vs = [float(meta['wage'][i]) for i in idxs if np.isfinite(meta['wage'][i])]
            sal_ref = float(np.mean(vs)) if vs else None
        if sal_ref:
            w = np.asarray(meta['wage'], dtype=float)[indices_pool]
            passou &= (np.isfinite(w) & (w <= sal_ref))

    if params.get('valor_max') is not None:
        v = np.asarray(meta['value'], dtype=float)[indices_pool]
        passou &= (np.isfinite(v) & (v <= float(params['valor_max'])))

    pe = params.get('pe') or ''
    if pe:
        if pe == 'igual':
            alvo_pe = str(fixa.get('pe') or '') if fixa else str(meta['foot'][idx])
        else:
            alvo_pe = pe
        passou &= (np.asarray(meta['foot'])[indices_pool] == alvo_pe)

    if params.get('idade_max') is not None:
        passou &= (np.asarray(meta['age'], dtype=float)[indices_pool] <= float(params['idade_max']))

    if params.get('contrato_ate'):
        ct = np.asarray(meta['contract'])[indices_pool]
        passou &= np.array([c > '1901' and c <= params['contrato_ate'] for c in ct])

    if params.get('ligas') is not None:
        passou &= np.isin(np.asarray(meta['league_uid'])[indices_pool], list(params['ligas']))

    if params.get('excluir_clube'):
        passou &= (np.asarray(meta['club_uid'])[indices_pool] != int(params['excluir_clube']))

    semelhanca = np.maximum(0.0, 100.0 - dif.mean(axis=0))
    escolhidos = np.nonzero(passou)[0]

    if objetivo == 'reposicao':
        valor_pool = np.asarray(meta['value'], dtype=float)[indices_pool]
        valor_pool = np.where(np.isfinite(valor_pool), valor_pool, np.inf)
        ordem = escolhidos[np.lexsort((valor_pool[escolhidos], -np.round(semelhanca[escolhidos])))]
    else:
        ordem = escolhidos[np.argsort(-semelhanca[escolhidos], kind='stable')]

    uids_todos = np.asarray(meta['uid'])[indices_pool][ordem]

    if fixa:
        ref_dict = {
            'uid': 0,
            'nome': str(fixa.get('nome') or ''),
            'nomes': [str(fixa.get('nome') or '')],
            'uids': [],
            'n_refs': 0,
            'posicao': pos_ref,
            'grupo': grupo,
            'coorte': coorte,
            'idade': int(fixa.get('idade') or 0),
            'ca': int(fixa.get('ca') or 0),
            'pa': int(fixa.get('pa') or 0),
            'valor': float(fixa['valor']) if fixa.get('valor') is not None else None,
            'salario': float(fixa['salario']) if fixa.get('salario') is not None else None,
            'pe': str(fixa.get('pe') or ''),
            'nota': float(fixa['nota']) if fixa.get('nota') is not None else None,
            'clube': '',
            'minutos': int(ref_minutos),
            'amostra_curta': False,
            'receita': True,
        }
    else:
        ref_dict = {
            'uid': int(meta['uid'][idx]),
            'nome': ' + '.join(str(meta['name'][i]) for i in idxs),
            'nomes': [str(meta['name'][i]) for i in idxs],
            'uids': [int(meta['uid'][i]) for i in idxs],
            'n_refs': len(idxs),
            'posicao': pos_ref,
            'grupo': grupo,
            'coorte': coorte,
            'idade': (lambda vs: int(round(float(np.mean(vs)))) if vs else 0)([float(meta['age'][i]) for i in idxs if np.isfinite(meta['age'][i])]),
            'ca': (lambda v: int(round(v)) if np.isfinite(v) else 0)(float(np.mean([meta['ca'][i] for i in idxs]))),
            'pa': (lambda v: int(round(v)) if np.isfinite(v) else 0)(float(np.mean([meta['pa'][i] for i in idxs]))),
            'valor': (lambda vs: float(np.mean(vs)) if len(vs) else None)([float(meta['value'][i]) for i in idxs if np.isfinite(meta['value'][i])]),
            'salario': (lambda vs: float(np.mean(vs)) if len(vs) else None)([float(meta['wage'][i]) for i in idxs if np.isfinite(meta['wage'][i])]),
            'pe': str(meta['foot'][idx]),
            'nota': (lambda vs: float(np.mean(vs)) if len(vs) else None)([float(meta['rating'][i]) for i in idxs if np.isfinite(meta['rating'][i])]),
            'clube': str(meta['club'][idx]) if len(idxs) == 1 else '',
            'minutos': int(ref_minutos),
            'amostra_curta': ref_minutos < min_minutes,
        }

    return {
        'referencia': ref_dict,
        'valores': [[round(float(valores[k][o]), 4) for k in ligadas] for o in ordem[:limite]],
        'metricas': [
            {
                'chave': k,
                'v': round(meu[k], 4),
                'p': round(percentil[k], 1),
                'menos': bool(metricas_tab[k][2]),
                'alto': bool(p_bruto(k) >= 50.0),
                'p_bruto': round(p_bruto(k), 1),
                'mediana': round(mediana[k], 4),
                'ligada': k in ligadas,
                'faixa': [
                    round(meu[k] * (1 - tol / 100.0), 4),
                    round(meu[k] * (1 + tol / 100.0), 4),
                ],
            }
            for k in sorted(possiveis, key=lambda k: (-abs(p_bruto(k) - 50.0) if objetivo == 'estilo' else -percentil[k]))
        ],
        'ligadas': ligadas,
        'objetivo': objetivo,
        'tol': tol,
        'modo': modo,
        'fora': fora,
        'dentro_minimo': max(0, n - fora),
        'n_pool': int(indices_pool.size),
        'total': int(escolhidos.size),
        'uids': [int(u) for u in uids_todos[:limite]],
        'semelhanca': [round(float(s), 1) for s in semelhanca[ordem][:limite]],
    }
