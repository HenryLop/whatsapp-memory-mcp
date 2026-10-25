"""Import from a message database you have ALREADY decrypted yourself.

This module only reads a plain SQLite file, opened read-only. It contains no decryption code and
does not handle backup keys. Contact names are not stored in that file, so chats are named from the
phone-number part of the chat id unless you pass a ``{"id-part": "Name"}`` JSON map.
Only text is imported; for media only its type is kept.
"""
import datetime
import sqlite3

from . import db

MEDIA_TYPES = {1: "image", 2: "audio", 3: "video", 9: "document", 13: "gif", 15: "sticker", 20: "sticker"}

SQL = """
SELECT m._id, m.from_me, m.timestamp, m.message_type, m.text_data,
       c._id AS chat_row, c.subject, j.user AS chat_user, j.server AS chat_server,
       sj.user AS sender_user
FROM message m
JOIN chat c ON c._id = m.chat_row_id
JOIN jid j ON j._id = c.jid_row_id
LEFT JOIN jid sj ON sj._id = m.sender_jid_row_id
WHERE m.timestamp > 0
ORDER BY m.timestamp
"""


def import_msgstore(cx, path, names=None, me="Me", include_groups=False):
    names = names or {}
    src = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    src.row_factory = sqlite3.Row
    added = skipped_groups = 0
    chat_ids = {}
    for r in src.execute(SQL):
        is_group = r["chat_server"] == "g.us"
        if is_group and not include_groups:
            skipped_groups += 1
            continue
        label = r["subject"] if is_group and r["subject"] else names.get(r["chat_user"], r["chat_user"])
        if label not in chat_ids:
            chat_ids[label] = db.add_chat(cx, label, is_group, "msgstore")
        ts = datetime.datetime.fromtimestamp(r["timestamp"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sender = me if r["from_me"] else names.get(r["sender_user"] or r["chat_user"], r["sender_user"] or r["chat_user"])
        mtype = r["message_type"]
        if mtype == 0 and r["text_data"]:
            added += db.add_message(cx, chat_ids[label], ts, sender, r["from_me"], "text", r["text_data"])
        elif mtype in MEDIA_TYPES:
            added += db.add_message(cx, chat_ids[label], ts, sender, r["from_me"], "media", "", MEDIA_TYPES[mtype])
    cx.commit()
    src.close()
    return {"messages": added, "chats": len(chat_ids), "group_messages_skipped": skipped_groups}
