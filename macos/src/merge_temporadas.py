# Decompiled from merge_temporadas.pyc (Python 3.14)
import datetime

COMPLETA = 1
COMPLETA_DOIS_CLUBES = 2
EM_ANDAMENTO = 3
JANELA_DA_CORRECAO = 365
JANELA_DA_TEMPORADA = 300
SCOPE_SALVA = 'full'
SCOPE_CORRECAO = 'fim_de_temporada'

CAMPOS_DO_ULTIMO = ('minutes_since_last_goal', 'minutes_since_last_conceded')


def _data(texto):
    return datetime.date.fromisoformat(str(texto)[:10])


def ano_da_temporada(data):
    if data.month <= 7:
        return data.year - 1
    return data.year


def rotulo(ano):
    return '%02d/%02d' % (ano % 100, (ano + 1) % 100)


def origens(conn, sid, so_uid=None):
    if so_uid is None:
        filtro, arg = ('', ())
    else:
        filtro, arg = (' AND p.uid=?', (so_uid,))

    s = conn.execute('SELECT carreira_id, game_date, scope FROM snapshots WHERE id=?', (sid,)).fetchone()
    if not s or s[2] != SCOPE_SALVA or not s[0] or not s[1]:
        return {}

    data_s, carreira = _data(s[1]), s[0]
    desde = data_s - datetime.timedelta(days=JANELA_DA_CORRECAO)

    correcoes = [
        (r[0], _data(r[1]))
        for r in conn.execute(
            'SELECT id, game_date FROM snapshots WHERE carreira_id=? AND scope=? AND game_date IS NOT NULL ORDER BY game_date DESC, id DESC',
            (carreira, SCOPE_CORRECAO),
        )
        if desde < _data(r[1]) <= data_s
    ]
    if not correcoes:
        return {}

    ids = [f for f, _d in correcoes]
    marca = ','.join('?' * len(ids))
    ligas_lidas = {
        r[0]
        for r in conn.execute(
            f'SELECT DISTINCT comp_uid FROM snapshot_ligas WHERE lida=1 AND snapshot_id IN ({marca})',
            ids,
        )
    }

    alvo = {
        r[0]
        for r in conn.execute(
            'SELECT p.uid, cl.league_uid FROM players p JOIN club_leagues cl ON cl.snapshot_id=p.snapshot_id AND cl.club_uid=p.club_id WHERE p.snapshot_id=?'
            + filtro,
            (sid,) + arg,
        )
        if r[1] in ligas_lidas
    }
    if not alvo:
        return {}

    em_f = {}
    for f, data_f in correcoes:
        for uid, clube in conn.execute(
            'SELECT uid, club_id FROM players p WHERE snapshot_id=?' + filtro,
            (f,) + arg,
        ):
            if uid in alvo and uid not in em_f:
                em_f[uid] = (f, data_f, clube)

    salvas = [
        (r[0], _data(r[1]))
        for r in conn.execute(
            'SELECT id, game_date FROM snapshots WHERE carreira_id=? AND scope=? AND game_date IS NOT NULL ORDER BY game_date DESC',
            (carreira, SCOPE_SALVA),
        )
    ]
    s0_de = {}
    for f, data_f in correcoes:
        candidatas = [x for x, d in salvas if data_f - datetime.timedelta(days=JANELA_DA_TEMPORADA) < d < data_f]
        s0_de[f] = candidatas[0] if candidatas else None

    clube_em_s0 = {}
    for s0 in {x for x in s0_de.values() if x}:
        clube_em_s0[s0] = {
            uid: (clube, jogos)
            for uid, clube, jogos in conn.execute(
                'SELECT p.uid, p.club_id, COALESCE(st.apps_total, 0) FROM players p LEFT JOIN player_stats st ON st.snapshot_id=p.snapshot_id AND st.uid=p.uid WHERE p.snapshot_id=?'
                + filtro,
                (s0,) + arg,
            )
        }

    jogou_em_s = {
        uid: jogos > 0
        for uid, jogos in conn.execute(
            'SELECT uid, COALESCE(apps_total, 0) FROM player_stats p WHERE snapshot_id=?' + filtro,
            (sid,) + arg,
        )
        if uid in alvo
    }

    saida = {}
    for uid in alvo:
        if uid not in em_f:
            if jogou_em_s.get(uid):
                saida[uid] = {'tipo': EM_ANDAMENTO, 'ano': None, 'fontes': []}
        else:
            f, data_f, clube_f = em_f[uid]
            item = {
                'tipo': COMPLETA,
                'ano': ano_da_temporada(data_f),
                'fontes': [(f, clube_f)],
            }
            s0 = s0_de.get(f)
            antes = clube_em_s0.get(s0, {}).get(uid) if s0 else None
            if antes and antes[0] != clube_f and antes[1] > 0:
                item['tipo'] = COMPLETA_DOIS_CLUBES
                item['fontes'] = [(s0, antes[0]), (f, clube_f)]
            saida[uid] = item

    return saida


def numeros(conn, origens_por_uid, campos):
    por_fonte = {}
    for uid, o in origens_por_uid.items():
        for fonte, _clube in o['fontes']:
            por_fonte.setdefault(fonte, set()).add(uid)

    lidos = {}
    sel = ', '.join(campos)
    for fonte, uids in por_fonte.items():
        marca = ','.join('?' * len(uids)) if len(uids) <= 500 else None
        if marca:
            consulta = (
                f'SELECT uid, {sel} FROM player_stats WHERE snapshot_id=? AND uid IN ({marca})',
                (fonte,) + tuple(uids),
            )
        else:
            consulta = (
                f'SELECT uid, {sel} FROM player_stats WHERE snapshot_id=?',
                (fonte,),
            )
        for linha in conn.execute(*consulta):
            if linha[0] in uids:
                lidos[(fonte, linha[0])] = dict(zip(campos, linha[1:]))

    saida = {}
    for uid, o in origens_por_uid.items():
        partes = [lidos[(f, uid)] for f, _c in o['fontes'] if (f, uid) in lidos]
        if not partes:
            continue
        soma = {}
        for campo in campos:
            valores = [p[campo] or 0 for p in partes]
            if campo in CAMPOS_DO_ULTIMO:
                soma[campo] = partes[-1][campo]
            elif campo == 'avg_rating':
                jogos = [p.get('apps_total') or 0 for p in partes]
                total = sum(jogos)
                if total:
                    soma[campo] = sum(v * j for v, j in zip(valores, jogos)) / total
                else:
                    soma[campo] = partes[-1][campo]
            else:
                soma[campo] = sum(valores)
        saida[uid] = soma

    return saida


def do_jogador(conn, sid, uid, stats):
    o = origens(conn, sid, uid).get(uid)
    if not o:
        return stats, None
    if o['tipo'] == EM_ANDAMENTO:
        return stats, {
            'tipo': o['tipo'],
            'ano': None,
            'jogos': stats.get('apps_total') or 0,
            'partes': [],
        }

    existentes = {r[1] for r in conn.execute('PRAGMA table_info(player_stats)')}
    v = numeros(conn, {uid: o}, [k for k in stats if k in existentes and k not in ('snapshot_id', 'uid')]).get(uid)
    if not v:
        return stats, None

    partes = []
    for fonte, clube in o['fontes']:
        data = conn.execute('SELECT game_date FROM snapshots WHERE id=?', (fonte,)).fetchone()
        nome = (
            conn.execute('SELECT club_name FROM club_leagues WHERE snapshot_id=? AND club_uid=?', (fonte, clube)).fetchone()
            or conn.execute('SELECT club_name FROM player_profile WHERE snapshot_id=? AND uid=?', (fonte, uid)).fetchone()
        )
        jogos = conn.execute('SELECT apps_total FROM player_stats WHERE snapshot_id=? AND uid=?', (fonte, uid)).fetchone()
        partes.append({
            'clube': nome[0] if nome else None,
            'ate': str(data[0])[:10] if data else None,
            'jogos': (jogos[0] if jogos else 0) or 0,
        })

    return dict(stats, **v), {
        'tipo': o['tipo'],
        'ano': o['ano'],
        'jogos': v.get('apps_total') or 0,
        'partes': partes,
    }


def aplicar_em_linhas(conn, sid, linhas, limite=400):
    if not linhas or len(linhas) > limite:
        return linhas
    for linha in linhas:
        campos = {k: v for k, v in linha.items() if not k.startswith('temporada_')}
        novos, origem = do_jogador(conn, sid, linha['uid'], campos)
        if not origem:
            continue
        linha.update({k: v for k, v in novos.items() if k in linha})
        linha.update(
            temporada_tipo=origem['tipo'],
            temporada_ano=origem['ano'],
            temporada_jogos=origem['jogos'],
        )
    return linhas
