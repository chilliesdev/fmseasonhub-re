"""Measured career totals, using one stored capture per player and season."""

from datetime import date

import moneyball_data as data
import player_analysis


SCOPES = ('squad', 'leagues', 'full')
LATEST_FIELDS = {'minutes_since_last_goal', 'minutes_since_last_conceded'}


def season(snapshot):
    label = snapshot.get('in_game_season')
    if label:
        return label
    try:
        captured = date.fromisoformat(snapshot['game_date'][:10])
        year = captured.year - (captured.month <= 7)
        return f'{year}/{str(year + 1)[-2:]}'
    except (TypeError, ValueError, KeyError):
        # Undated captures cannot safely be combined into a season.
        return f"#{snapshot['id']}"


def load(conn, career=None, uid=None):
    """Choose the selected career and FM version before grouping any player."""
    if career is None:
        row = conn.execute("""
            SELECT s.carreira_id FROM snapshots s JOIN players p ON p.snapshot_id=s.id
            WHERE p.uid=? AND s.scope IN ('squad','leagues','full')
            ORDER BY s.game_date DESC,s.id DESC LIMIT 1
        """, (uid,)).fetchone()
        if row is None or row['carreira_id'] is None:
            raise LookupError('Jogador sem carreira armazenada')
        career = row['carreira_id']
    snapshots = [dict(row) for row in conn.execute("""
        SELECT * FROM snapshots WHERE carreira_id=? AND scope IN ('squad','leagues','full')
        ORDER BY game_date,id
    """, (career,))]
    if snapshots:
        version = snapshots[-1]['fm_version']
        snapshots = [item for item in snapshots if item['fm_version'] == version]
    fields = [row[1] for row in conn.execute('PRAGMA table_info(player_stats)')
              if row[1] not in ('snapshot_id', 'uid')]
    seasons, players, latest = {}, {}, {}
    for snapshot in snapshots:
        label = season(snapshot)
        descriptor = dict(snapshot, sid=snapshot['id'], temporada=label, is_live=False)
        seasons[label] = descriptor
        _, rows = data.load(conn, snapshot['id'])
        for row in rows:
            player_uid = row['uid']
            latest[player_uid] = row
            key = (player_uid, label)
            rank = (data.number(row.get('minutes'), -1), data.number(row.get('apps_total'), -1),
                    snapshot['game_date'] or '', snapshot['id'])
            previous = players.get(key)
            if previous is None or rank > previous[0]:
                stats = {field: row.get(field) for field in fields}
                players[key] = (rank, dict(descriptor, stats=stats))
    histories = {}
    for (player_uid, _), (_, item) in players.items():
        histories.setdefault(player_uid, []).append(item)
    aggregates = []
    for player_uid, history in sorted(histories.items()):
        row = dict(latest[player_uid])
        row.update(total([item['stats'] for item in history], fields))
        row.pop('vals', None)
        aggregates.append(row)
    return career, list(seasons.values()), histories, aggregates


def total(parts, fields):
    result = {}
    for field in fields:
        values = [data.number(part.get(field), None) for part in parts]
        if field in LATEST_FIELDS:
            result[field] = values[-1]
        elif field == 'avg_rating':
            weights = [data.number(part.get('apps_total'), None) for part in parts]
            measured = [(value, weight) for value, weight in zip(values, weights)
                        if value is not None and weight is not None and weight > 0]
            complete = all(weight is not None and weight >= 0 and
                           (weight == 0 or value is not None)
                           for value, weight in zip(values, weights))
            result[field] = (sum(value * weight for value, weight in measured) /
                             sum(weight for _, weight in measured)) if measured and complete else None
        else:
            result[field] = sum(values) if all(value is not None for value in values) else None
    return result


def composition(conn, career):
    career, seasons, _, rows = load(conn, career)
    return {'cid': career, 'players': rows, 'seasons': seasons, 'temporadas': seasons,
            'capturas': conn.execute('SELECT COUNT(*) FROM snapshots WHERE carreira_id=?',
                                     (career,)).fetchone()[0],
            'capturas_base': sum(1 for row in conn.execute(
                "SELECT scope FROM snapshots WHERE carreira_id=?", (career,)) if row[0] in SCOPES)}


def player(conn, uid, career=None):
    career, _, histories, rows = load(conn, career, uid)
    row = next((row for row in rows if row['uid'] == uid), None)
    if row is None:
        raise LookupError('Jogador nao encontrado nesta carreira')
    fields = [column[1] for column in conn.execute('PRAGMA table_info(player_stats)')
              if column[1] not in ('snapshot_id', 'uid')]
    return {'uid': uid, 'carreira': career, 'snapshot_id': row['snapshot_id'],
            'temporadas': histories[uid], 'stats': {key: row[key] for key in fields}}


def percentiles(conn, uid, career=None, coorte=None):
    career, _, _, rows = load(conn, career, uid)
    index = next((i for i, row in enumerate(rows) if row['uid'] == uid), None)
    if index is None:
        raise LookupError('Jogador nao encontrado nesta carreira')
    coorte, benchmark, minimum, mask = player_analysis.cohort(rows, index, coorte, 'top20', None)
    metrics, _ = player_analysis.player_metrics(rows, index, mask)
    if not metrics:
        raise ValueError('Jogador sem medidas armazenadas suficientes para percentis')
    return {'uid': uid, 'carreira': career, 'coorte': coorte, 'regua': benchmark,
            'min_minutes': minimum, 'n': int(mask.sum()), 'metricas': metrics,
            'percentis': {key: value['pct'] for key, value in metrics.items()}}
