"""Read-only queries. Every function caps what it returns so one call cannot dump a history."""
import re

MAX_SEARCH = 20
MAX_THREAD = 100
MAX_CHATS = 100
BODY_CHARS = 400
MAX_TOTAL_CHARS = 8000


def _fts_query(q):
    words = re.findall(r"\w+", q, re.UNICODE)
    return " ".join('"%s"' % w for w in words)  # quoted tokens, implicit AND


def _chat_filter(cx, chat, include_groups):
    """Return (sql, params) restricting to a chat name (substring, diacritics-insensitive) if given."""
    sql, params = "", []
    if not include_groups:
        sql += " AND c.is_group = 0"
    if chat:
        sql += " AND c.name LIKE ? ESCAPE '\\'"
        params.append("%" + chat.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    return sql, params


def _cap(rows):
    out, total = [], 0
    for r in rows:
        total += len(r["body"]) + 40
        if total > MAX_TOTAL_CHARS:
            out.append({"note": "output cap reached; narrow the query or the date range"})
            break
        out.append(r)
    return out


def list_chats(cx, include_groups=False, limit=MAX_CHATS):
    where = "" if include_groups else "WHERE c.is_group = 0"
    rows = cx.execute(
        "SELECT c.name, c.is_group, COUNT(m.id) AS messages, MIN(m.day) AS first_day, MAX(m.day) AS last_day "
        "FROM chats c LEFT JOIN messages m ON m.chat_id = c.id %s GROUP BY c.id ORDER BY last_day DESC LIMIT ?" % where,
        (min(int(limit), MAX_CHATS),)).fetchall()
    return [dict(r) for r in rows]


def search(cx, query, chat=None, since=None, until=None, limit=10, include_groups=False):
    fts = _fts_query(query)
    if not fts:
        return []
    extra, params = _chat_filter(cx, chat, include_groups)
    if since:
        extra += " AND m.day >= ?"
        params.append(since)
    if until:
        extra += " AND m.day <= ?"
        params.append(until)
    rows = cx.execute(
        "SELECT c.name AS chat, m.ts, m.sender, substr(m.body, 1, %d) AS body "
        "FROM messages_fts f JOIN messages m ON m.id = f.rowid JOIN chats c ON c.id = m.chat_id "
        "WHERE messages_fts MATCH ? AND m.kind = 'text'%s ORDER BY rank LIMIT ?" % (BODY_CHARS, extra),
        [fts] + params + [min(int(limit), MAX_SEARCH)]).fetchall()
    return _cap([dict(r) for r in rows])


def read_thread(cx, chat, start=None, end=None, limit=50, include_groups=False):
    extra, params = _chat_filter(cx, chat, include_groups)
    if start:
        extra += " AND m.day >= ?"
        params.append(start)
    if end:
        extra += " AND m.day <= ?"
        params.append(end)
    rows = cx.execute(
        "SELECT c.name AS chat, m.ts, m.sender, m.kind, m.media_type, substr(m.body, 1, %d) AS body "
        "FROM messages m JOIN chats c ON c.id = m.chat_id WHERE 1=1%s AND m.kind != 'system' "
        "ORDER BY m.ts, m.id LIMIT ?" % (BODY_CHARS, extra),
        params + [min(int(limit), MAX_THREAD)]).fetchall()
    return _cap([dict(r) for r in rows])
