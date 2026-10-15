"""Opt-in, read-only Ready evidence adapter for the host's ordinary agent.

WAS currently removes per-response status metadata from history. This narrowly
scoped adapter reads those markers from retained canonical message rows, while
WAS supplies the allowlist of visible ordinary-agent session IDs. No writes,
private agent stores, profiles, credentials or tool payloads are opened.
"""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

MARKER = re.compile(r'\[WIZARD_STATUS_V1\]\s*(.*?)\s*\[/WIZARD_STATUS_V1\]', re.S | re.I)
STATES = {'needs_you', 'check', 'done', 'fyi'}
ACTIVE = {'accepted', 'queued', 'running', 'waiting_for_approval', 'stopping'}


def attention(text):
    found = None
    for m in MARKER.finditer(text or ''):
        try:
            value = json.loads(m.group(1))
            if not isinstance(value, dict):
                continue
            state = str(value.get('state', '')).strip().lower().replace('-', '_').replace(' ', '_')
            state = {'needs': 'needs_you', 'needsyou': 'needs_you', 'test': 'check', 'qa': 'check'}.get(state, state)
            ask = ' '.join(str(value.get('ask') or value.get('line') or value.get('summary') or '').split())[:140]
            if state in STATES and ask:
                found = {'state': state, 'ask': ask}
                for key, limit in [('title', 100), ('subject', 40)]:
                    if value.get(key):
                        found[key] = ' '.join(str(value[key]).split())[:limit]
        except (ValueError, TypeError):
            continue
    return found


class ReadySource:
    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)

    def open(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn

    def head(self):
        with closing(self.open()) as c:
            return int(c.execute('SELECT coalesce(max(id),0) FROM messages').fetchone()[0])

    def read(self, after, limit=1000):
        with closing(self.open()) as c:
            # ID is the canonical insertion order. Compacted rows deliberately included.
            rows = c.execute('''SELECT m.id,m.session_id,m.role,m.content,m.timestamp,m.finish_reason,m.display_kind,m.tool_calls
                                FROM messages m JOIN sessions s ON s.id=m.session_id
                                WHERE m.id>? AND m.role='assistant' AND s.parent_session_id IS NULL
                                  AND coalesce(s.hidden,0)=0 AND coalesce(s.archived,0)=0
                                ORDER BY m.id LIMIT ?''', (int(after), int(limit))).fetchall()
        events = []
        for row in rows:
            r = dict(row)
            if r['display_kind'] not in (None, '', 'final') or r['tool_calls'] not in (None, '', '[]', 'null'):
                continue
            text = r['content']
            if not isinstance(text, str):
                continue
            value = attention(text)
            if value:
                events.append({'id': r['id'], 'session_id': r['session_id'], 'body': MARKER.sub('', text).strip(),
                               'attention': value, 'created': float(r['timestamp'] or 0)})
        return events, int(rows[-1]['id']) if rows else int(after), len(rows) == limit
