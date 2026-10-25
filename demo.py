"""One-command demo: import three invented chat exports, then talk to the MCP server over stdio.

    python demo.py
"""
import json
import os
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(tempfile.mkdtemp(prefix="wa-demo-"), "archive.sqlite")


def cli(*args):
    p = subprocess.run([sys.executable, "-m", "wa_memory", "--db", DB] + list(args), cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        raise SystemExit(p.stderr)
    return p.stdout.strip()


print("== import ==")
for name, chat in (("sample_jordan.txt", "Jordan Reyes"), ("sample_camila.txt", "Camila Duarte"),
                   ("sample_book_club.txt", "Book Club")):
    print(cli("import-export", os.path.join(ROOT, "data", name), "--chat", chat, "--me", "Sam"))

requests = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_chats", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_messages", "arguments": {"query": "cafe"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "read_thread", "arguments": {
        "chat": "Jordan", "start": "2026-03-15", "end": "2026-03-28"}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "send_message", "arguments": {"to": "x", "text": "hi"}}},
]
p = subprocess.run([sys.executable, "-m", "wa_memory", "--db", DB, "serve"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                   input="\n".join(json.dumps(r) for r in requests) + "\n")
replies = {r["id"]: r for r in map(json.loads, p.stdout.splitlines())}

print("\n== tools/list ==")
print(", ".join(t["name"] for t in replies[2]["result"]["tools"]), "(no tool writes or sends)")
print("\n== list_chats (the group chat is hidden by default) ==")
print(replies[3]["result"]["content"][0]["text"])
print("\n== search_messages query='cafe' (matches 'café' too) ==")
print(replies[4]["result"]["content"][0]["text"])
print("\n== read_thread chat='Jordan' 2026-03-15..2026-03-28 ==")
print(replies[5]["result"]["content"][0]["text"])
print("\n== tools/call send_message ==")
print(replies[6]["error"]["message"])
