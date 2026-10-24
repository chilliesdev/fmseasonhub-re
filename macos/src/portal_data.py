"""Portal summaries from saved seasons, independent of the game connection."""

import career_analysis
import settings


LIVE_SNAPSHOT_ID = 999999999  # Virtual snapshot ID returned by /api/snapshots.


def stored_snapshots(conn):
    return [dict(row) for row in conn.execute("""
        SELECT * FROM snapshots WHERE scope IN ('squad','leagues','full')
        ORDER BY game_date DESC,id DESC
    """)]


def active_career(snapshots):
    selected = settings.load().get('carreira_ativa')
    if selected in {row['carreira_id'] for row in snapshots}:
        return selected
    return snapshots[0]['carreira_id'] if snapshots else None


def summary(conn, selected, live):
    snapshots = stored_snapshots(conn)
    connected = bool(live.get('ready')) and selected in (None, LIVE_SNAPSHOT_ID)
    if selected is not None and selected != LIVE_SNAPSHOT_ID:
        base = next((row for row in snapshots if row['id'] == selected), None)
        if base is None:
            raise LookupError('Snapshot nao encontrado')
        career = base['carreira_id']
    else:
        if selected == LIVE_SNAPSHOT_ID and not connected:
            raise LookupError('Snapshot ao vivo indisponivel')
        career = active_career(snapshots)
        base = None
    seasons = [row for row in snapshots if row['carreira_id'] == career]
    if base is None:
        base = seasons[0] if seasons else None
    highlights = []
    if base is not None:
        base = dict(base, is_live=False)
        base['n_players'] = conn.execute(
            'SELECT COUNT(*) FROM players WHERE snapshot_id=?', (base['id'],)).fetchone()[0]
        highlights = [dict(row) for row in conn.execute("""
            SELECT p.uid,COALESCE(p.full_name,p.common_name,CAST(p.uid AS TEXT)) AS full_name,
                   s.avg_rating
            FROM players p JOIN player_stats s ON s.snapshot_id=p.snapshot_id AND s.uid=p.uid
            WHERE p.snapshot_id=? AND s.avg_rating IS NOT NULL
              AND (? IS NULL OR p.club_id=?)
            ORDER BY s.avg_rating DESC,p.uid LIMIT 3
        """, (base['id'], base['club_uid'], base['club_uid']))]
    season = {'label': career_analysis.season(base), 'days_left': None} if base else {}
    if connected:
        # Live status supplies connection metadata; stored captures remain separate.
        season = ({'label': career_analysis.season(dict(live, id=LIVE_SNAPSHOT_ID)),
                   'days_left': None} if live.get('game_date') else {})
    return {
        'connected': connected,
        'live': dict(live),
        'seasons': len(seasons),
        'total_seasons': len(snapshots),
        'carreira_id': career,
        'base': base,
        'ultima': base,
        'season': season,
        'game_date': live.get('game_date') if connected else (base or {}).get('game_date'),
        **{key: live.get(key) if connected else None
           for key in ('club', 'club_uid', 'manager', 'read_at')},
        'highlights': highlights if not connected else [],
        'prospects': [],
        'youth': {'n': 0, 'avg_ca': None},
        'expiring': None,
    }
