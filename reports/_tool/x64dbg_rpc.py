#!/usr/bin/env python3
"""Minimal x64dbg MCP JSON-RPC helper over HTTP."""
import json, sys, urllib.request

URL = "http://192.168.248.169:3000/mcp"

def rpc(payload, timeout=60):
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def call_tool(name, args=None, tool_id=None):
    return rpc({
        "jsonrpc": "2.0",
        "id": tool_id if tool_id is not None else 3,
        "method": "tools/call",
        "params": {"name": name, "arguments": args or {}},
    })

def inner_text(result):
    """Extract parsed text from tools/call result.content[0].text."""
    if isinstance(result, dict) and "result" in result:
        result = result["result"]
    if isinstance(result, dict) and "content" in result:
        for item in result["content"]:
            if item.get("type") == "text":
                t = item["text"]
                try:
                    return json.loads(t)
                except Exception:
                    return t
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: x64dbg_rpc.py <tool> [json-args]", file=sys.stderr); sys.exit(2)
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    out = call_tool(name, args)
    # pretty print inner content
    parsed = inner_text(out)
    print(json.dumps(parsed, indent=2) if not isinstance(parsed, str) else parsed)
