"""Read-only trial scorecard; never reads private agent files or message contents."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import time


def duration(value):
    match = re.fullmatch(r'(\d+)([hmd])', value)
    if not match:
        raise argparse.ArgumentTypeError('Use e.g. 24h, 30m, 7d')
    return int(match[1]) * {'m': 60, 'h': 3600, 'd': 86400}[match[2]]


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def scorecard(database, lite_database, since):
    with readonly(database) as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute('SELECT * FROM front_desk_receipts WHERE created>=? ORDER BY id', (since,))]
    coordinators = [r for r in rows if r['kind'] == 'coordinator']
    dispatches = [r for r in rows if r['kind'] == 'dispatch']
    latencies = sorted(r['latency'] for r in coordinators)
    turns = {r['job_id'] for r in rows if r['job_id']}
    result = {'turns': len(turns), 'coordinator_calls': len(coordinators),
              'routes_per_worker': dict(Counter(r['worker'] for r in dispatches)),
              'privacy_holds': len({r['job_id'] for r in rows if r['reason'] == 'private_topic_hold'}),
              'median_latency_seconds': statistics.median(latencies) if latencies else None,
              'p95_latency_seconds': latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
              'tokens': {key: sum(r[key] for r in coordinators) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
              'errors': sum(bool(r['error']) for r in rows), 'hermes_lite_turns': None}
    try:
        with readonly(lite_database) as c:
            result['hermes_lite_turns'] = c.execute("SELECT count(*) FROM messages WHERE role='user' AND timestamp>=?", (since,)).fetchone()[0]
    except sqlite3.Error as exc:
        result['hermes_lite_status'] = type(exc).__name__ + ': unavailable (no message content read)'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', type=duration, default=duration('24h'))
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DATA_DIR', Path.home() / '.hermes/data/apps/wizard-manager')))
    parser.add_argument('--lite-db', type=Path, default=Path.home() / '.hermes/profiles/hermes-lite/state.db')
    args = parser.parse_args()
    try:
        print(json.dumps(scorecard(args.data_dir / 'manager.sqlite3', args.lite_db, time.time() - args.since), indent=2))
    except sqlite3.Error as exc:
        parser.exit(1, 'Trial receipts unavailable: ' + type(exc).__name__ + '\n')


if __name__ == '__main__':
    main()
