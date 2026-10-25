"""A Model Context Protocol server over stdio (newline-delimited JSON-RPC 2.0), standard library only.

Three tools, all read-only: list_chats, search_messages, read_thread. There is no tool that writes
to the archive or sends anything, the database is opened with SQLite's read-only mode, and the
process never opens a network connection.
"""
import json
import sys

from . import db, queries

PROTOCOL = "2024-11-05"

TOOLS = [
    {"name": "list_chats",
     "description": "List imported chats with message counts and date range. Group chats are hidden unless the server was started with --include-groups.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": queries.MAX_CHATS}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "search_messages",
     "description": "Full-text search over message text, ignoring accents and case. Optional chat name filter and YYYY-MM-DD date range.",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string"}, "chat": {"type": "string"}, "since": {"type": "string"},
         "until": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": queries.MAX_SEARCH}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "read_thread",
     "description": "Read one chat in time order between two YYYY-MM-DD dates (inclusive).",
     "inputSchema": {"type": "object", "required": ["chat"], "properties": {
         "chat": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": queries.MAX_THREAD}}},
     "annotations": {"readOnlyHint": True}},
]


class Server:
    def __init__(self, db_path, include_groups=False):
        self.cx = db.open_ro(db_path)
        self.include_groups = include_groups

    def call_tool(self, name, args):
        if name == "list_chats":
            return queries.list_chats(self.cx, self.include_groups, args.get("limit", queries.MAX_CHATS))
        if name == "search_messages":
            return queries.search(self.cx, args["query"], args.get("chat"), args.get("since"), args.get("until"),
                                  args.get("limit", 10), self.include_groups)
        if name == "read_thread":
            return queries.read_thread(self.cx, args["chat"], args.get("start"), args.get("end"),
                                       args.get("limit", 50), self.include_groups)
        raise KeyError(name)

    def handle(self, msg):
        """One JSON-RPC message in, a response dict (or None for notifications) out."""
        mid, method = msg.get("id"), msg.get("method", "")
        if mid is None:  # notification
            return None

        def ok(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        def err(code, text):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

        if method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion", PROTOCOL)
            return ok({"protocolVersion": ver, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "wa-memory", "version": "0.1.0"}})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            p = msg.get("params") or {}
            try:
                data = self.call_tool(p.get("name"), p.get("arguments") or {})
            except KeyError as e:
                return err(-32602, "unknown tool or missing argument: %s" % e)
            except Exception as e:  # a bad query must not kill the server
                return ok({"content": [{"type": "text", "text": "error: %s" % e}], "isError": True})
            return ok({"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}]})
        return err(-32601, "method not found: " + method)


def serve(db_path, include_groups=False, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    server = Server(db_path, include_groups)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = server.handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
