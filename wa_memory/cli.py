import argparse
import json
import sys

from . import db, import_export, import_msgstore, queries, server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wa_memory")
    ap.add_argument("--db", default="wa_memory.sqlite", help="archive file (default ./wa_memory.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import-export", help="import a chat exported as .txt")
    p.add_argument("file")
    p.add_argument("--chat", help="chat name (default: the file name)")
    p.add_argument("--me", help="your name as it appears in the export")

    p = sub.add_parser("import-msgstore", help="import an already-decrypted message database (read-only)")
    p.add_argument("file")
    p.add_argument("--names", help="JSON file mapping id-part -> display name")
    p.add_argument("--me", default="Me")
    p.add_argument("--include-groups", action="store_true")

    sub.add_parser("chats", help="list chats")
    p = sub.add_parser("search", help="search from the command line")
    p.add_argument("query")
    p.add_argument("--chat")
    p = sub.add_parser("serve", help="run the MCP server on stdio")
    p.add_argument("--include-groups", action="store_true")

    a = ap.parse_args(argv)
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if a.cmd == "serve":
        server.serve(a.db, a.include_groups)
        return 0
    if a.cmd == "import-export":
        cx = db.open_rw(a.db)
        print(json.dumps(import_export.import_export(cx, a.file, a.chat, a.me)))
    elif a.cmd == "import-msgstore":
        names = json.load(open(a.names, encoding="utf-8")) if a.names else None
        cx = db.open_rw(a.db)
        print(json.dumps(import_msgstore.import_msgstore(cx, a.file, names, a.me, a.include_groups)))
    else:
        cx = db.open_ro(a.db)
        out = queries.list_chats(cx) if a.cmd == "chats" else queries.search(cx, a.query, a.chat)
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0
