"""Bounded, read-only retrieval through WAS's visible conversation API.

WAS does not expose the upstream full-text search route. Do not bypass it: page
its projected history, rank excerpts locally, and report incomplete coverage.
No persistent transcript cache, tools, embeddings, or private-agent requests.
"""
import re
import math
import time
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from urllib.error import HTTPError, URLError

DIAGNOSTIC_LIMIT = 8


def failure_detail(exc, elapsed=None):
    """Bounded metadata only: never expose response bodies, URLs or credentials."""
    cause = exc.reason if isinstance(exc, URLError) else exc
    kind = ('http_error' if isinstance(exc, HTTPError) else
            'timeout' if isinstance(cause, (TimeoutError, socket.timeout)) else
            'invalid_response' if isinstance(exc, (ValueError, KeyError, TypeError)) else 'transport_error')
    detail = {'kind': kind, 'exception': type(exc).__name__[:80]}
    if isinstance(exc, HTTPError):
        detail['http_status'] = exc.code
    if elapsed is not None:
        detail['elapsed_ms'] = round(max(0, elapsed) * 1000)
    return detail

PAGE_SIZE = 500
THREAD_LIMIT = 96
PAGE_LIMIT = 128
PAGES_PER_THREAD = 4
LOOKUP_SECONDS = 15
STOP = set('a an and are as at be been but by can could did do does for from had has have he her here how i if in is it its me my of on or our please she so that the their them there these they this those to was we were what when where which who why will with would you your find thread threads chat chats status work asked looking hello hi hey thanks thank'.split())
STOP.update('another app build create finished hit instead integrated interface just let like message new not out question reply scratch screen send text told'.split())


def terms_for(text):
    terms = set(re.findall(r'[^\W_]{3,}', text.lower())) - STOP
    # Vocabulary bridges, not thread IDs/titles or evidence invented by the model.
    if terms & {'voice', 'dictation', 'transcription', 'transcribe'}:
        terms.update(('voice', 'dictation', 'transcription', 'transcribe'))
    if terms & {'tab', 'tabs'}:
        terms.update(('tab', 'tabs'))
    return sorted(terms)[:40]


def should_lookup(text):
    """Read prior work for lookup/status, not for greetings or fresh handoffs."""
    return bool(re.search(r'\b(?:threads?|chats?|status|progress|where|find|locate|search|earlier|previous|asked|remember|requests?|finished|integrated|built|done|happened|missing|exists?)\b|\bwhat(?:[’\']s| is)? about\b|went through', text, re.I))


def visible(s):
    return (isinstance(s, dict) and isinstance(s.get('id'), str)
            and bool(s['id']) and not s.get('parent_session_id')
            and not s.get('hidden') and not s.get('archived')
            and not s.get('private') and not s.get('is_private')
            and (s.get('agent') or {}).get('id', 'hermes') == 'hermes'
            and (s.get('agent') or {}).get('privacy', 'standard') == 'standard')


def revalidate(sessions, request, was):
    """Recheck only selected exact IDs, not another expensive global snapshot."""
    deadline = time.monotonic() + 12
    checked, failed = [], 0
    def read(s):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('visibility budget')
        p = request(f'{was}/api/sessions/{quote(s["id"], safe="")}', timeout=min(4, left))
        current = p.get('session')
        if not isinstance(current, dict) or current.get('id') != s['id']:
            raise ValueError('invalid session detail')
        return {**s, **current} if visible(current) else None
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix='manager-visibility') as pool:
        for start in range(0, len(sessions), 6):
            if time.monotonic() >= deadline:
                failed += len(sessions) - start
                break
            for future in [pool.submit(read, s) for s in sessions[start:start + 6]]:
                try:
                    result = future.result()
                    if result:
                        checked.append(result)
                except Exception:
                    failed += 1
    return checked, failed


def retrieve(sessions, terms, request, was, clean, deadline=None):
    """Return evidence and explicit coverage; never claim a negative is proven.

    Latest pages arrive in chronological order. Advance by pagination.returned,
    NOT len(data): WAS removes internal rows after upstream pagination.
    """
    deadline = deadline or time.monotonic() + LOOKUP_SECONDS
    allowed = {s['id']: s for s in sessions if visible(s)}
    def matches(text):
        words = set(re.findall(r'[^\W_]{3,}', text.lower()))
        return set(terms) & words

    ranked = sorted(allowed.values(), key=lambda s: len(matches(
        str(s.get('title') or '') + ' ' + clean((s.get('latest_message') or {}).get('content')))), reverse=True)
    # Interleave semantic hints and recency so generic/misleading titles cannot
    # crowd out content-only candidates before their histories have been read.
    candidates = {}
    for a, b in zip(ranked, allowed.values()):
        for s in (a, b):
            if len(candidates) < THREAD_LIMIT:
                candidates[s['id']] = s
    states = {sid: {'offset': 0, 'pages': 0, 'done': False, 'failed': False, 'attempts': 0,
                    'matches': {}, 'recent': {}} for sid in candidates}
    pages = 0
    diagnostics = []
    def read(sid):
        started = time.monotonic()
        states[sid]['attempts'] += 1
        try:
            left = deadline - started
            if left <= 0:
                raise TimeoutError('lookup budget')
            states[sid]['timeout_ms'] = round(min(4, left) * 1000)
            return request(f'{was}/api/sessions/{quote(sid, safe="")}/messages'
                           f'?order=latest&limit={PAGE_SIZE}&offset={states[sid]["offset"]}'
                           '&include_compacted=true&view=wizard', timeout=min(4, left))
        finally:
            states[sid]['elapsed'] = time.monotonic() - started

    with ThreadPoolExecutor(max_workers=6, thread_name_prefix='manager-lookup') as pool:
        # One page per candidate before deepening. Failed/malformed pages do not
        # become empty histories. A fixed page/time budget bounds slow services.
        for depth in range(PAGES_PER_THREAD):
            pending = [sid for sid, st in states.items() if not st['done'] and not st['failed']]
            if depth:
                pending.sort(key=lambda sid: max((len(x['terms']) for x in states[sid]['matches'].values()), default=0), reverse=True)
            for start in range(0, len(pending), 6):
                if pages >= PAGE_LIMIT or time.monotonic() >= deadline:
                    break
                batch = pending[start:start + min(6, PAGE_LIMIT - pages)]
                futures = [(sid, pool.submit(read, sid)) for sid in batch]
                pages += len(batch)
                for sid, future in futures:
                    st = states[sid]
                    try:
                        p = future.result()
                        data, pagination = p['data'], p['pagination']
                        returned = pagination['returned']
                        if (not isinstance(data, list) or not isinstance(returned, int)
                                or isinstance(returned, bool) or not len(data) <= returned <= PAGE_SIZE
                                or pagination.get('offset') != st['offset']
                                or pagination.get('order') != 'latest'):
                            raise ValueError('invalid history page')
                        st['pages'] += 1
                        st['offset'] += returned
                        st['done'] = returned < PAGE_SIZE
                        for row in data:
                            if (not isinstance(row, dict) or row.get('role') not in ('user', 'assistant')
                                    or (row.get('role') == 'assistant' and row.get('shareable') is False)
                                    or row.get('tool_call_id')
                                    or row.get('tool_calls') or row.get('hidden')
                                    or row.get('display_kind') not in (None, '', 'final', 'commentary')):
                                continue
                            text = clean(row.get('content'))[:24000]
                            if not text or row.get('id') is None:
                                continue
                            ident = str(row['id'])
                            hit = matches(text)
                            item = {'message_id': ident, 'role': row['role'],
                                    'timestamp': row.get('timestamp'), 'text': text[:1000]}
                            if depth == 0:
                                st['recent'][ident] = item
                                if len(st['recent']) > 2:
                                    del st['recent'][next(iter(st['recent']))]
                            if hit:
                                # Anchor a bounded excerpt at the first keyword,
                                # instead of truncating away a buried request.
                                first = min(m.start() for m in re.finditer(r'[^\W_]{3,}', text.lower()) if m.group() in hit)
                                begin = max(0, first - 200)
                                item['text'] = ('…' if begin else '') + text[begin:begin + 1400]
                                item['terms'] = sorted(hit)
                                st['matches'][ident] = item
                        st['matches'] = dict(sorted(st['matches'].items(), key=lambda pair:
                            (len(pair[1]['terms']), pair[1]['role'] == 'user'), reverse=True)[:8])
                    except Exception as exc:
                        st['failed'] = True
                        if len(diagnostics) < DIAGNOSTIC_LIMIT:
                            diagnostics.append({'session_id': sid, 'offset': st['offset'],
                                'request_timeout_ms': st.get('timeout_ms', 0),
                                **failure_detail(exc, st.get('elapsed', 0))})
            if pages >= PAGE_LIMIT or time.monotonic() >= deadline:
                break
    # Rare topic words matter more than vocabulary shared by many coding chats.
    # Count document frequency, not repeated occurrences in verbose transcripts.
    frequency = {term: sum(any(term in r['terms'] for r in st['matches'].values())
                           for st in states.values()) for term in terms}
    def score(item):
        return sum(1 / math.sqrt(max(1, frequency[t])) for t in item['terms']) * (1.2 if item['role'] == 'user' else 1)
    for st in states.values():
        st['matches'] = dict(sorted(st['matches'].items(), key=lambda pair: score(pair[1]), reverse=True)[:3])
    hits = sorted(((sid, st) for sid, st in states.items() if st['matches']),
                  key=lambda pair: max(score(x) for x in pair[1]['matches'].values()), reverse=True)[:12]
    evidence = {sid: {'excerpts': list(st['matches'].values()),
                      'recent_messages': list(st['recent'].values())} for sid, st in hits}
    complete = len(states) == len(allowed) and all(st['done'] and not st['failed'] for st in states.values())
    return evidence, {'state': 'bounded' if not complete else 'searched',
                      'method': 'WAS projected message history; lexical vocabulary bridges',
                      'terms': terms, 'visible_threads': len(allowed),
                      'threads_read': sum(st['pages'] > 0 for st in states.values()),
                      'pages_read': sum(st['pages'] for st in states.values()),
                      'failed_threads': sum(st['failed'] for st in states.values()),
                      'failure_scope': 'history_retrieval_not_task_execution',
                      'failure_diagnostics': diagnostics,
                      'failure_diagnostics_omitted': max(0, sum(st['failed'] for st in states.values()) - len(diagnostics)),
                      'unattempted_threads': len(allowed) - sum(st['attempts'] > 0 for st in states.values()),
                      'time_budget_exhausted': time.monotonic() >= deadline,
                      'page_budget_exhausted': pages >= PAGE_LIMIT,
                      'history_coverage_complete': complete,
                      # Even a complete lexical pass is not semantic proof of absence.
                      'absence_proven': False}
