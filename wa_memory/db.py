"""SQLite schema with an FTS5 index that ignores diacritics ("cafe" finds "café")."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  is_group INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL REFERENCES chats(id),
  ts TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM:SS', local time as exported
  day TEXT NOT NULL,             -- 'YYYY-MM-DD'
  sender TEXT NOT NULL,
  from_me INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL,            -- text | media | system
  media_type TEXT,               -- only the kind of media, never the file
  body TEXT NOT NULL DEFAULT '',
  uniq TEXT NOT NULL UNIQUE      -- hash that makes re-imports idempotent
);
CREATE INDEX IF NOT EXISTS ix_messages_chat_ts ON messages(chat_id, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  body, sender, tokenize = 'unicode61 remove_diacritics 2'
);
"""


def open_rw(path):
    cx = sqlite3.connect(path)
    cx.row_factory = sqlite3.Row
    cx.executescript(SCHEMA)
    return cx


def open_ro(path):
    """The server opens the archive read-only at the SQLite level."""
    cx = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def add_chat(cx, name, is_group, source):
    cx.execute("INSERT OR IGNORE INTO chats(name, is_group, source) VALUES (?,?,?)", (name, int(is_group), source))
    return cx.execute("SELECT id FROM chats WHERE name=?", (name,)).fetchone()["id"]


def add_message(cx, chat_id, ts, sender, from_me, kind, body, media_type=None):
    import hashlib
    uniq = hashlib.sha1(("%d|%s|%s|%s" % (chat_id, ts, sender, body)).encode("utf-8")).hexdigest()
    cur = cx.execute(
        "INSERT OR IGNORE INTO messages(chat_id, ts, day, sender, from_me, kind, media_type, body, uniq) "
        "VALUES (?,?,?,?,?,?,?,?,?)", (chat_id, ts, ts[:10], sender, int(from_me), kind, media_type, body, uniq))
    if cur.rowcount:
        cx.execute("INSERT INTO messages_fts(rowid, body, sender) VALUES (?,?,?)", (cur.lastrowid, body, sender))
    return cur.rowcount
