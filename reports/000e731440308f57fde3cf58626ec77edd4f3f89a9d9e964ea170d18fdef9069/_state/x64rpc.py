"""Minimal JSON-RPC client for the x64dbg MCP server over HTTP."""
import json
import sys
import urllib.request

URL = "http://192.168.248.169:3000/mcp"


def rpc(payload, timeout=30):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def call(name, args=None, timeout=30):
    res = rpc(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": name, "arguments": args or {}}},
        timeout=timeout,
    )
    content = res.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except Exception:
            return text
    return res


if __name__ == "__main__":
    init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "hyperagent", "version": "1.0"}}})
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    out = call(name, args)
    print(json.dumps(out, indent=1))
