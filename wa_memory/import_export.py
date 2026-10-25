"""Import a chat exported from the app ("Export chat", without media) as a .txt file.

Handles the common layouts: ``12/03/2026, 14:05 - Name: text``, ``[12/03/2026, 14:05:33] Name: text``
and ``3/12/26, 2:05 PM - Name: text``. Lines that do not start with a timestamp continue the
previous message. Day-first or month-first order is detected from the file itself.
"""
import os
import re

from . import db

LINE = re.compile(
    r"^\[?(?P<a>\d{1,4})[/.\-](?P<b>\d{1,2})[/.\-](?P<c>\d{1,4}),?\s+"
    r"(?P<h>\d{1,2})[:.](?P<m>\d{2})(?:[:.](?P<s>\d{2}))?(?:\s?(?P<ap>[AaPp])\.?[Mm]\.?)?\]?\s*(?:-\s*)?(?P<rest>.*)$")
SENDER = re.compile(r"^(?P<who>[^:]{1,60}?): (?P<text>.*)$", re.S)
MEDIA = re.compile(r"^<?(?:(?P<kind>image|video|audio|sticker|gif|document)\s+omitted|media omitted)>?$", re.I)
INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮"), None)


def _clean(line):
    return line.translate(INVISIBLE).rstrip("\r\n")


def parse(path):
    """Return a list of raw dicts: a, b, c, h, m, s, sender, text."""
    raw = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = _clean(line)
            m = LINE.match(line)
            if m:
                rest = m.group("rest")
                s = SENDER.match(rest)
                h = int(m.group("h"))
                ap = (m.group("ap") or "").lower()
                if ap == "p" and h < 12:
                    h += 12
                if ap == "a" and h == 12:
                    h = 0
                raw.append({"a": int(m.group("a")), "b": int(m.group("b")), "c": int(m.group("c")),
                            "h": h, "m": int(m.group("m")), "s": int(m.group("s") or 0),
                            "sender": s.group("who") if s else None, "text": s.group("text") if s else rest})
            elif raw:
                raw[-1]["text"] += "\n" + line
    return raw


def detect_order(raw):
    """'dmy', 'mdy' or 'ymd'. Falls back to day-first when the file cannot tell."""
    if any(r["a"] > 31 for r in raw):
        return "ymd"
    if any(r["a"] > 12 for r in raw):
        return "dmy"
    if any(r["b"] > 12 for r in raw):
        return "mdy"
    return "dmy"


def to_ts(r, order):
    if order == "ymd":
        y, mo, d = r["a"], r["b"], r["c"]
    elif order == "mdy":
        mo, d, y = r["a"], r["b"], r["c"]
    else:
        d, mo, y = r["a"], r["b"], r["c"]
    if y < 100:
        y += 2000
    return "%04d-%02d-%02d %02d:%02d:%02d" % (y, mo, d, r["h"], r["m"], r["s"])


def import_export(cx, path, chat_name=None, me=None, source="export"):
    raw = parse(path)
    order = detect_order(raw)
    people = {r["sender"] for r in raw if r["sender"]}
    name = chat_name or os.path.splitext(os.path.basename(path))[0]
    chat_id = db.add_chat(cx, name, len(people) > 2, source)
    added = 0
    for r in raw:
        ts = to_ts(r, order)
        text = r["text"].strip()
        if r["sender"] is None:
            added += db.add_message(cx, chat_id, ts, "system", 0, "system", text)
            continue
        mm = MEDIA.match(text)
        if mm:
            added += db.add_message(cx, chat_id, ts, r["sender"], r["sender"] == me, "media", "",
                                    (mm.group("kind") or "media").lower())
        else:
            added += db.add_message(cx, chat_id, ts, r["sender"], r["sender"] == me, "text", text)
    cx.commit()
    return {"chat": name, "messages": added, "order": order, "is_group": len(people) > 2}
