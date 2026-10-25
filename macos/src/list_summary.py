"""Snapshot-bound contracts for the shipped Favorites/list summary panels."""

from datetime import date

import moneyball_data as data


SECTORS = {
    'gr': {'GK'}, 'def': {'SW', 'DC', 'DR', 'DL', 'WBR', 'WBL'},
    'med': {'DM', 'MC', 'MR', 'ML', 'AMC', 'AMR', 'AML'}, 'ata': {'ST'},
}


def _date(value):
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _snapshot_date(value):
    parsed = _date(value)
    return parsed if parsed and parsed.isoformat() == value else None


def _selection(conn, uids, selected):
    sid = data.snapshot_id(conn, selected)
    snapshot = conn.execute('SELECT * FROM snapshots WHERE id=?', (sid,)).fetchone()
    wanted = set(uids)
    rows = data.load(conn, sid)[1] if snapshot and wanted else []
    return dict(snapshot) if snapshot else {}, [row for row in rows if row['uid'] in wanted]


def summary(conn, uids, selected=None):
    snapshot, rows = _selection(conn, uids, selected)
    sid = snapshot.get('id')
    players = [{
        'uid': row['uid'], 'sid': sid, 'nome': row['name'],
        'idade': data.number(row.get('age'), None),
        'pa': data.number(row.get('pa'), None),
        'valor': data.number(row.get('transfer_value'), None),
    } for row in rows]
    ages = [player for player in players if player['idade'] is not None and player['idade'] >= 0]
    potentials = [player for player in players if player['pa'] is not None and player['pa'] > 0]
    values = [player for player in players if player['valor'] is not None and player['valor'] >= 0]
    bargains = [player for player in values if player['pa'] is not None and player['pa'] >= 145]
    wages = [data.number(row.get('wage'), None) for row in rows]
    wages = [wage for wage in wages if wage is not None and wage >= 0]
    today = _date(snapshot.get('game_date'))
    until = date(today.year + 1, 12, 31) if today else None
    contracts = [_date(row.get('contract_end')) for row in rows]
    nationalities = {row.get('nationality_code') or row.get('nationality') for row in rows}
    nationalities.discard(None)
    nationalities.discard('')
    return {
        'qtd': len(set(uids)), 'na_carreira': len(rows),
        'idade_media': sum(player['idade'] for player in ages) / len(ages) if ages else None,
        'valor_somado': sum(player['valor'] for player in values) if values or not rows else None,
        'salarios_semana': sum(wages) if wages or not rows else None,
        'setores': {key: sum(row['position'].upper() in positions for row in rows)
                    for key, positions in SECTORS.items()},
        'pa': potentials, 'idades': ages,
        'destaques': {
            'maior_pa': max(potentials, key=lambda player: (player['pa'], -player['uid']), default=None),
            'barato_145': min(bargains, key=lambda player: (player['valor'], player['uid']), default=None),
            'mais_valioso': max(values, key=lambda player: (player['valor'], -player['uid']), default=None),
            'contrato_ate': {'ano': until.year, 'qtd': sum(today <= end <= until for end in contracts if end)} if until else None,
            'emprestados': sum(bool(row.get('on_loan')) or bool(today and (_date(row.get('loan_end')) or date.min) >= today)
                               for row in rows),
            'nacionalidades': len(nationalities),
        },
    }


def outside_capture(conn, uids, selected=None):
    snapshot, rows = _selection(conn, uids, selected)
    missing = set(uids) - {row['uid'] for row in rows}
    found = {}
    selected_date = _snapshot_date(snapshot.get('game_date'))
    # Fallback records are explicit provenance links, never part of current aggregates.
    # Without career/date metadata, no safe cross-snapshot match can be established.
    if missing and snapshot.get('carreira_id') and selected_date:
        placeholders = ','.join('?' for _ in missing)
        candidates = conn.execute(f'''
            SELECT p.*, s.name AS source_name, s.game_date AS source_date,
                   s.fm_version AS source_version
            FROM players p JOIN snapshots s ON s.id=p.snapshot_id
            WHERE p.uid IN ({placeholders}) AND s.carreira_id=?
              AND s.scope IN ('squad','leagues','full')
              AND (s.game_date < ? OR (s.game_date=? AND s.id < ?))
            ORDER BY s.game_date DESC,s.id DESC,p.uid
        ''', [*missing, snapshot['carreira_id'], snapshot['game_date'],
              snapshot['game_date'], snapshot['id']])
        for raw in candidates:
            row = dict(raw)
            uid = row['uid']
            source_date = _snapshot_date(row['source_date'])
            if source_date is None or (source_date, row['snapshot_id']) >= (selected_date, snapshot['id']):
                continue
            if uid in found:
                continue
            profile = conn.execute('SELECT * FROM player_profile WHERE snapshot_id=? AND uid=?',
                                   (row['snapshot_id'], uid)).fetchone()
            profile = dict(profile) if profile else {}
            found[uid] = {
                'uid': uid, 'snapshot': row['snapshot_id'],
                'nome': row.get('full_name') or row.get('common_name') or ' '.join(
                    str(row.get(key) or '') for key in ('name_first', 'name_last')).strip() or str(uid),
                'posicao': row.get('position') or data._position(profile),
                'dado_de': row['source_name'] or row['source_date'],
                'versao_fm': str(row['source_version']) if row['source_version'] else None,
            }
    return {'uids': sorted(missing), 'linhas': [found[uid] for uid in sorted(found)],
            'sem_dado': len(missing) - len(found)}


def outside_rows(conn, uids, selected=None, groups=()):
    provenance = outside_capture(conn, uids, selected)['linhas']
    by_snapshot = {}
    for item in provenance:
        by_snapshot.setdefault(item['snapshot'], {})[item['uid']] = item
    result = []
    for sid, players in by_snapshot.items():
        source = conn.execute('SELECT game_date FROM snapshots WHERE id=?', (sid,)).fetchone()
        for row in data.load(conn, sid, groups=groups)[1]:
            item = players.get(row['uid'])
            if item:
                result.append({**row, 'fora': {
                    'sid': sid, 'dado_de': item['dado_de'],
                    'data_jogo': source['game_date'], 'versao_fm': item['versao_fm'],
                }})
    return result
