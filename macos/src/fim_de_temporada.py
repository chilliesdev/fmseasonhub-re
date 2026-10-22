# Decompiled from fim_de_temporada.pyc (Python 3.14)
import datetime

ESPERA_MAXIMA = 14
MAX_LEITURAS = 5
MIN_TIMES_LIGA = 8
CATEGORIAS_DE_LIGA = (0, 1, 14)


def conjunto_da_liga(competicoes, liga_uid):
    liga = competicoes[liga_uid]['times']
    return {
        uid
        for uid, c in competicoes.items()
        if uid != liga_uid and c['categoria'] not in CATEGORIAS_DE_LIGA and (c['times'] & liga)
    }


TOLERANCIA_DEPOIS_DO_USUARIO = 30
OSCILACAO_DO_CALENDARIO = 21
ESPERA_POR_COPA = 45
UM_ANO = datetime.timedelta(days=365)
UM_DIA = datetime.timedelta(days=1)


def temporada_atual(temporadas, hoje):
    comecadas = [ano for ano, (inicio, _fim) in temporadas.items() if inicio <= hoje]
    if comecadas:
        return max(comecadas)
    return None


def liga_principal(estados, competicoes, clube_uid):
    if not clube_uid:
        return None
    minhas = [e for e in estados if clube_uid in competicoes.get(e['uid'], {}).get('times', ())]
    if minhas:
        return max(minhas, key=lambda e: (e.get('reputacao', 0), e['ultima_partida']))
    return None


def cobertas_pela_temporada_do_usuario(estados, competicoes, clube_uid, data_do_save=None, hoje=None):
    principal = liga_principal(estados, competicoes, clube_uid)
    if principal is None:
        return None, set()
    fim_do_usuario = principal['ultima_partida']
    if hoje is not None and fim_do_usuario < hoje:
        save, desde = (data_do_save or (fim_do_usuario + UM_ANO)), fim_do_usuario
    else:
        save, desde = (data_do_save or fim_do_usuario), (principal.get('fim_anterior') or (fim_do_usuario - UM_ANO))
    limite = save + datetime.timedelta(days=TOLERANCIA_DEPOIS_DO_USUARIO)
    cobertas = {e['uid'] for e in estados if e.get('inicio') and e['inicio'] > desde and e['fim'] <= limite}
    if principal.get('pais'):
        cobertas |= {e['uid'] for e in estados if e.get('pais') == principal['pais']}
    return save, cobertas


def corte_do_save_anterior(estados, competicoes, clube_uid, hoje):
    principal = liga_principal(estados, competicoes, clube_uid)
    if principal is None:
        return hoje - UM_ANO / 2
    fim_do_usuario = principal['ultima_partida']
    if fim_do_usuario < hoje:
        anterior = fim_do_usuario
    else:
        anterior = principal.get('fim_anterior') or (fim_do_usuario - UM_ANO)
    return anterior + datetime.timedelta(days=TOLERANCIA_DEPOIS_DO_USUARIO)


def estado_das_ligas(competicoes, temporadas, hoje):
    oscila = datetime.timedelta(days=OSCILACAO_DO_CALENDARIO)
    saida = []
    for uid, c in competicoes.items():
        if c['categoria'] not in CATEGORIAS_DE_LIGA or len(c['times']) < MIN_TIMES_LIGA:
            continue
        da_liga = temporadas.get(uid) or {}
        ano = temporada_atual(da_liga, hoje)
        if not ano or ano not in da_liga:
            continue
        inicio, ultima_propria = da_liga[ano]
        ultima_partida = ultima_propria
        segurada_por = []
        teto = ultima_propria + datetime.timedelta(days=ESPERA_POR_COPA)
        for copa in conjunto_da_liga(competicoes, uid):
            for c_inicio, c_fim in (temporadas.get(copa) or {}).values():
                if c_inicio <= ultima_propria and c_fim >= inicio and ultima_propria < c_fim <= teto:
                    if c_fim > ultima_partida:
                        ultima_partida = c_fim
                        segurada_por = [copa]
                    elif c_fim == ultima_partida:
                        segurada_por.append(copa)
        anterior = da_liga.get(ano - 1)
        fim_anterior = anterior[1] if anterior else None
        fim = ultima_partida
        if fim_anterior and ultima_propria < fim_anterior + UM_ANO - oscila:
            fim = max(fim, fim_anterior + UM_ANO)
        seguinte = da_liga.get(ano + 1)
        saida.append({
            'uid': uid,
            'nome': c['nome'],
            'times': (c.get('times_na_temporada') or {}).get(ano) or len(c['times']),
            'temporada': ano,
            'inicio': inicio,
            'fim': fim,
            'ultima_partida': ultima_partida,
            'inicio_da_seguinte': seguinte[0] if seguinte else (inicio + UM_ANO),
            'fim_anterior': fim_anterior,
            'reputacao': c.get('reputacao', 0),
            'pais': c.get('pais'),
            'continua': fim > ultima_partida and fim >= hoje,
            'fechada': fim < hoje,
            'dias': (fim - hoje).days,
            'segurada_por': sorted(segurada_por),
            'segurada_por_nomes': sorted(competicoes[x]['nome'] for x in segurada_por),
        })
    return saida


def ja_lida(e, ja_feitas):
    lida_em = ja_feitas.get(e['uid']) if isinstance(ja_feitas, dict) else None
    return lida_em is not None and lida_em >= e['ultima_partida']


def dona_da_data(ligas):
    if not ligas:
        return None
    return max(ligas, key=lambda e: (e['fim'], e.get('reputacao', 0)))


def motivo_da_data(ligas):
    liga = dona_da_data(ligas)
    if liga is None:
        return None
    if liga.get('continua'):
        return {'tipo': 'agenda', 'liga': liga['nome']}
    if liga.get('segurada_por_nomes'):
        return {'tipo': 'copa', 'liga': liga['nome'], 'copa': liga['segurada_por_nomes'][0]}
    return {'tipo': 'fim', 'liga': liga['nome']}


def maior_espera(ligas, data):
    if not ligas:
        return None
    e = min(ligas, key=lambda x: (x['fim'], -x.get('reputacao', 0)))
    dias = (data - e['fim']).days - 1
    if dias > 0:
        return {'liga': e['nome'], 'terminou': e['fim'], 'dias': dias}
    return None


def _datas_com_menor_espera(ligas, quantas, teto=None):
    prontas = sorted({e['fim'] + UM_DIA for e in ligas})
    quantas = max(1, min(quantas, len(prontas)))

    def espera(de, ate):
        depois_de = prontas[de - 1] if de > 0 else (datetime.date.min + UM_DIA)
        esperas = [
            (max(e['times'], 1), (prontas[ate] - e['fim'] - UM_DIA).days)
            for e in ligas
            if depois_de < e['fim'] + UM_DIA <= prontas[ate]
        ]
        if teto is not None and any(dias > teto for _clubes, dias in esperas):
            return float('inf')
        return sum(clubes * dias for clubes, dias in esperas)

    n = len(prontas)
    melhor = {(1, i): (espera(0, i), None) for i in range(n)}
    for k in range(2, quantas + 1):
        for i in range(k - 1, n):
            melhor[(k, i)] = min(
                (
                    (melhor[(k - 1, j)][0] + espera(j + 1, i), j)
                    for j in range(k - 2, i)
                ),
                key=lambda x: x[0],
            )
    datas = []
    k, i = quantas, n - 1
    while i is not None:
        datas.append(prontas[i])
        i = melhor[(k, i)][1]
        k -= 1
    return sorted(datas)


def _leituras_para_esperar_no_maximo(ligas, dias):
    prontas = sorted(e['fim'] + UM_DIA for e in ligas)
    i, n = 0, 0
    while i < len(prontas):
        limite = prontas[i] + datetime.timedelta(days=dias)
        n += 1
        while i < len(prontas) and prontas[i] <= limite:
            i += 1
    return n


def plano_de_leituras(estados, ja_feitas, hoje):
    def falta_ler(e):
        return not ja_lida(e, ja_feitas) and e['inicio_da_seguinte'] > hoje

    if not any(falta_ler(e) for e in estados):
        return []

    principal = max(estados, key=lambda e: (e.get('reputacao', 0), e['fim']))
    datas_principais = [principal['fim'] + UM_DIA]
    if datas_principais[0] <= hoje:
        datas_principais.append(datas_principais[0] + UM_ANO)

    data_da_liga = {}
    for data_principal in datas_principais:
        for e in estados:
            if e['uid'] not in data_da_liga and e['fim'] + UM_DIA <= data_principal and e['inicio_da_seguinte'] > data_principal:
                data_da_liga[e['uid']] = data_principal

    resto = [e for e in estados if e['uid'] not in data_da_liga]
    if resto:
        minimo = _leituras_para_esperar_no_maximo(resto, ESPERA_MAXIMA)
        if minimo <= MAX_LEITURAS - 1:
            datas = _datas_com_menor_espera(resto, minimo, ESPERA_MAXIMA)
        else:
            datas = _datas_com_menor_espera(resto, MAX_LEITURAS - 1)
        for e in resto:
            data_da_liga[e['uid']] = min(d for d in datas if d >= e['fim'] + UM_DIA)

    por_data = {}
    for e in estados:
        if falta_ler(e):
            por_data.setdefault(max(data_da_liga[e['uid']], hoje), []).append(e)

    return [
        {
            'data': d,
            'ligas': sorted(ligas, key=lambda x: (-x.get('reputacao', 0), x['nome'])),
            'clubes': sum(x['times'] for x in ligas),
        }
        for d, ligas in sorted(por_data.items())
    ]


def proxima_leitura(estados, ja_feitas, hoje):
    plano = plano_de_leituras(estados, ja_feitas, hoje)
    if not plano or plano[0]['data'] > hoje:
        return None
    return [e for e in plano[0]['ligas'] if e['fechada']] or None


def proximos(estados, ja_feitas, hoje):
    return plano_de_leituras(estados, ja_feitas, hoje)


PARTIDA_TEMPORADA = 48


def ler_agenda(reader):
    import struct
    import fm_reader as fr

    if fr.AGENDA_VTABLE_RVA is None or fr.VT_COMP_EDITION_RVA is None:
        return None

    iso = reader.game_date()
    if not iso:
        return None
    if isinstance(iso, datetime.date):
        hoje = iso
    else:
        hoje = datetime.date.fromisoformat(iso)

    competicoes = {}
    ponteiros = {}
    nacoes = {}

    for e in reader.enderecos_de_vtable(fr.VT_COMP_EDITION_RVA):
        comp = reader.q(e + fr.EDITION_COMP_PTR)
        if not reader.is_heap(comp):
            continue
        end = reader.q(e + fr.EDITION_TEAMS_VEC)
        beg = reader.q(e + fr.EDITION_TEAMS_VEC + 8)
        if not (reader.is_heap(beg) and end >= beg and (end - beg) % 8 == 0):
            continue
        nome = reader.fmstr(comp + fr.COMP_NAME_PTR)
        categoria = reader.u8(comp + fr.COMP_CATEGORY) & 255
        if not fr.comp_kind(nome, categoria):
            continue
        n = min((end - beg) // 8, 5000)
        if n <= 0:
            continue
        uid = reader.u32(comp + fr.COMP_UID)
        if uid not in competicoes:
            nacao = reader.q(comp + fr.COMP_NATION_PTR)
            if nacao not in nacoes:
                nacoes[nacao] = reader.fmstr(nacao + fr.NATION_NAME_PTR) if reader.is_heap(nacao) else None
            feminina = bool(reader.u8(comp + fr.COMP_IS_FEMALE)) if fr.COMP_IS_FEMALE is not None else None
            competicoes[uid] = {
                'nome': nome,
                'categoria': categoria,
                'times': set(),
                'reputacao': reader.u32(comp + fr.COMP_REPUTATION),
                'pais': (nacoes[nacao], feminina) if nacoes[nacao] else None,
            }
        c = competicoes[uid]
        for i in range(n):
            p = reader.q(beg + 8 * i)
            if reader.is_heap(p):
                tuid = reader.u32(p + fr.TEAM_UID)
                c['times'].add(tuid)
                ponteiros[tuid] = p

    tipos = [vt for vt in (fr.AGENDA_VTABLE_RVA, fr.JOGO_VTABLE_RVA) if vt is not None]
    objetos = [o for vt in tipos for o in reader.enderecos_de_vtable(vt)]
    temporadas = {}
    comp_da_etapa = {}
    times_em_jogo = {}
    ligas = {u for u, c in competicoes.items() if c['categoria'] in CATEGORIAS_DE_LIGA}

    for o in objetos:
        bloco = reader.rb(o, 80)
        if not bloco or len(bloco) < 80:
            continue
        data = fr.decode_fm_date(struct.unpack_from('<I', bloco, 76)[0])
        etapa = struct.unpack_from('<Q', bloco, 32)[0]
        ano = struct.unpack_from('<H', bloco, PARTIDA_TEMPORADA)[0]
        if not (data and reader.is_heap(etapa) and 1900 < ano < 2200):
            continue
        if etapa not in comp_da_etapa:
            comp = reader.q(etapa + 24)
            comp_da_etapa[etapa] = reader.u32(comp + 12) if reader.is_heap(comp) else None
        uid = comp_da_etapa[etapa]
        if uid not in competicoes:
            continue
        da_comp = temporadas.setdefault(uid, {})
        inicio, fim = da_comp.get(ano, (data, data))
        da_comp[ano] = (min(inicio, data), max(fim, data))
        if uid in ligas:
            vistos = times_em_jogo.setdefault(uid, {}).setdefault(ano, {})
            for lado in (8, 16):
                t = struct.unpack_from('<Q', bloco, lado)[0]
                if reader.is_heap(t) and data > vistos.get(t, datetime.date.min):
                    vistos[t] = data

    for uid, por_ano in times_em_jogo.items():
        competicoes[uid]['times_na_temporada'] = {ano: len(t) for ano, t in por_ano.items()}

    return {
        'hoje': hoje,
        'competicoes': competicoes,
        'temporadas': temporadas,
        'ponteiros': ponteiros,
        'times_em_jogo': times_em_jogo,
    }


def ponteiros_dos_clubes(agenda, ligas):
    em_jogo = agenda.get('times_em_jogo') or {}
    times = set()
    for liga in ligas:
        vistos = (em_jogo.get(liga['uid']) or {}).get(liga.get('temporada'))
        if vistos:
            times |= set(vistos)
        else:
            times |= {
                agenda['ponteiros'][u]
                for u in agenda['competicoes'][liga['uid']]['times']
                if u in agenda['ponteiros']
            }
    return list(times)
