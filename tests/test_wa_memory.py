import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from wa_memory import db, import_export, import_msgstore, queries, server  # noqa: E402

DATA = os.path.join(ROOT, "data")


def fresh():
    path = os.path.join(tempfile.mkdtemp(prefix="wa-test-"), "a.sqlite")
    cx = db.open_rw(path)
    for f, chat in (("sample_jordan.txt", "Jordan Reyes"), ("sample_camila.txt", "Camila Duarte"),
                    ("sample_book_club.txt", "Book Club")):
        import_export.import_export(cx, os.path.join(DATA, f), chat, "Sam")
    return path, cx


class ImportTests(unittest.TestCase):
    def test_date_order_detection(self):
        self.assertEqual(import_export.detect_order(import_export.parse(os.path.join(DATA, "sample_jordan.txt"))), "dmy")
        self.assertEqual(import_export.detect_order(import_export.parse(os.path.join(DATA, "sample_camila.txt"))), "mdy")

    def test_multiline_and_pm_and_media(self):
        _, cx = fresh()
        row = cx.execute("SELECT body FROM messages WHERE body LIKE 'The landlord%'").fetchone()
        self.assertIn("12 months at the same rent", row["body"])
        self.assertIn("\n", row["body"])
        t = cx.execute("SELECT ts FROM messages WHERE body LIKE '%corner table%'").fetchone()
        self.assertEqual(t["ts"], "2026-03-02 09:20:00")
        t = cx.execute("SELECT ts FROM messages WHERE body LIKE '%passport copy%'").fetchone()
        self.assertEqual(t["ts"], "2026-04-02 18:12:44")
        media = cx.execute("SELECT kind, media_type, body FROM messages WHERE kind='media' ORDER BY id").fetchall()
        self.assertEqual([(m["media_type"], m["body"]) for m in media], [("media", ""), ("image", "")])

    def test_group_detected_and_from_me(self):
        _, cx = fresh()
        groups = {r["name"] for r in cx.execute("SELECT name FROM chats WHERE is_group=1")}
        self.assertEqual(groups, {"Book Club"})
        self.assertEqual(cx.execute("SELECT COUNT(*) c FROM messages WHERE from_me=1 AND sender!='Sam'").fetchone()["c"], 0)

    def test_reimport_is_idempotent(self):
        path, cx = fresh()
        before = cx.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
        r = import_export.import_export(cx, os.path.join(DATA, "sample_jordan.txt"), "Jordan Reyes", "Sam")
        self.assertEqual(r["messages"], 0)
        self.assertEqual(cx.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"], before)


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.path, _ = fresh()
        self.cx = db.open_ro(self.path)

    def test_diacritics_insensitive_both_ways(self):
        a = queries.search(self.cx, "cafe")
        b = queries.search(self.cx, "café")
        self.assertEqual(a, b)
        self.assertEqual({r["chat"] for r in a}, {"Jordan Reyes", "Camila Duarte"})
        self.assertTrue(queries.search(self.cx, "reunion"))  # body says "reunión"

    def test_filters(self):
        self.assertEqual({r["chat"] for r in queries.search(self.cx, "cafe", chat="camila")}, {"Camila Duarte"})
        r = queries.search(self.cx, "cafe", since="2026-03-10")
        self.assertEqual({x["chat"] for x in r}, {"Camila Duarte"})

    def test_groups_hidden_unless_asked(self):
        self.assertEqual(queries.search(self.cx, "lighthouse"), [])
        self.assertTrue(queries.search(self.cx, "lighthouse", include_groups=True))
        self.assertNotIn("Book Club", [c["name"] for c in queries.list_chats(self.cx)])
        self.assertIn("Book Club", [c["name"] for c in queries.list_chats(self.cx, include_groups=True)])

    def test_thread_range_and_order(self):
        rows = queries.read_thread(self.cx, "Jordan", "2026-03-15", "2026-03-28")
        self.assertEqual([r["ts"][:10] for r in rows], sorted(r["ts"][:10] for r in rows))
        self.assertTrue(all("2026-03-15" <= r["ts"][:10] <= "2026-03-28" for r in rows))
        self.assertFalse(any(r["sender"] == "system" for r in rows))

    def test_limits_are_capped(self):
        path = os.path.join(tempfile.mkdtemp(), "big.sqlite")
        cx = db.open_rw(path)
        cid = db.add_chat(cx, "Big", 0, "t")
        for i in range(500):
            db.add_message(cx, cid, "2026-01-01 10:%02d:%02d" % (i // 60 % 60, i % 60), "A", 0, "text", "needle %d " % i + "x" * 300)
        cx.commit()
        ro = db.open_ro(path)
        self.assertLessEqual(len(queries.search(ro, "needle", limit=9999)), queries.MAX_SEARCH + 1)
        thread = queries.read_thread(ro, "Big", limit=9999)
        self.assertLessEqual(len(thread), queries.MAX_THREAD)
        self.assertLessEqual(sum(len(r.get("body", "")) for r in thread), queries.MAX_TOTAL_CHARS)
        self.assertTrue(all(len(r.get("body", "")) <= queries.BODY_CHARS for r in thread))

    def test_query_with_fts_syntax_is_harmless(self):
        self.assertEqual(queries.search(self.cx, 'cafe" OR *'), queries.search(self.cx, "cafe OR"))
        self.assertEqual(queries.search(self.cx, "***"), [])


class ReadOnlyTests(unittest.TestCase):
    def test_server_connection_cannot_write(self):
        path, _ = fresh()
        ro = db.open_ro(path)
        with self.assertRaises(sqlite3.OperationalError):
            ro.execute("DELETE FROM messages")

    def test_tools_have_no_write_or_send(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertEqual(sorted(names), ["list_chats", "read_thread", "search_messages"])
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in server.TOOLS))

    def test_package_has_no_network_send_or_crypto_code(self):
        pkg = os.path.join(ROOT, "wa_memory")
        for fn in os.listdir(pkg):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(pkg, fn), encoding="utf-8").read()
            code = re.sub(r'""".*?"""', "", src, flags=re.S)
            for bad in ("import socket", "import requests", "urllib", "http.client", "Crypto", "cryptography",
                        "crypt15", "AES", "websocket"):
                self.assertNotIn(bad, code, "%s in %s" % (bad, fn))


class ProtocolTests(unittest.TestCase):
    def run_server(self, msgs, **kw):
        path, _ = fresh()
        out = io.StringIO()
        server.serve(path, stdin=io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\n"), stdout=out, **kw)
        return [json.loads(l) for l in out.getvalue().splitlines()]

    def test_handshake_list_call(self):
        r = self.run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_messages", "arguments": {"query": "lease"}}},
        ])
        self.assertEqual([x["id"] for x in r], [1, 2, 3])  # the notification gets no reply
        self.assertIn("tools", r[0]["result"]["capabilities"])
        self.assertIn("lease", r[2]["result"]["content"][0]["text"])

    def test_unknown_tool_and_method_and_garbage(self):
        r = self.run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "send_message", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        ])
        self.assertEqual(r[0]["error"]["code"], -32602)
        self.assertEqual(r[1]["error"]["code"], -32601)
        path, _ = fresh()
        out = io.StringIO()
        server.serve(path, stdin=io.StringIO("not json\n"), stdout=out)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], -32700)

    def test_include_groups_flag(self):
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_messages", "arguments": {"query": "lighthouse"}}}
        self.assertEqual(json.loads(self.run_server([call])[0]["result"]["content"][0]["text"]), [])
        self.assertTrue(json.loads(self.run_server([call], include_groups=True)[0]["result"]["content"][0]["text"]))


class MsgstoreTests(unittest.TestCase):
    def make_source(self):
        path = os.path.join(tempfile.mkdtemp(), "msgstore.db")
        s = sqlite3.connect(path)
        s.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT);
        CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INT, subject TEXT);
        CREATE TABLE message (_id INTEGER PRIMARY KEY, chat_row_id INT, from_me INT, sender_jid_row_id INT,
                              timestamp INT, message_type INT, text_data TEXT);
        INSERT INTO jid VALUES (1,'contact-a','s.whatsapp.net'),(2,'club','g.us');
        INSERT INTO chat VALUES (1,1,NULL),(2,2,'Hiking Group');
        INSERT INTO message VALUES (1,1,0,1,1772000000000,0,'See you at the café at noon'),
                                   (2,1,1,NULL,1772000060000,0,'On my way'),
                                   (3,1,0,1,1772000120000,1,NULL),
                                   (4,2,0,1,1772000180000,0,'Trail is closed');
        """)
        s.commit()
        s.close()
        return path

    def test_import_text_media_names_and_groups(self):
        src = self.make_source()
        cx = db.open_rw(os.path.join(tempfile.mkdtemp(), "a.sqlite"))
        r = import_msgstore.import_msgstore(cx, src, {"contact-a": "Alex Chen"}, me="Sam")
        self.assertEqual(r, {"messages": 3, "chats": 1, "group_messages_skipped": 1})
        rows = cx.execute("SELECT sender, kind, media_type FROM messages ORDER BY ts").fetchall()
        self.assertEqual([(x["sender"], x["kind"]) for x in rows], [("Alex Chen", "text"), ("Sam", "text"), ("Alex Chen", "media")])
        self.assertEqual(rows[2]["media_type"], "image")
        self.assertTrue(queries.search(cx, "cafe", chat="alex"))

    def test_source_database_is_opened_read_only(self):
        src = self.make_source()
        before = os.path.getmtime(src)
        cx = db.open_rw(os.path.join(tempfile.mkdtemp(), "a.sqlite"))
        import_msgstore.import_msgstore(cx, src, include_groups=True)
        self.assertEqual(os.path.getmtime(src), before)
        s = sqlite3.connect(src)
        self.assertEqual(s.execute("SELECT COUNT(*) FROM message").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
