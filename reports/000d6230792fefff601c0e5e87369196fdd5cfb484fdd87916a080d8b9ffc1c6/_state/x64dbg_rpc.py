import json, sys, urllib.request

URL = "http://192.168.248.169:3000/mcp"

def rpc(payload):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))

def call(name, arguments=None):
    payload = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    result = rpc(payload)
    # unwrap content[0].text if present
    content = result.get("result", {}).get("content")
    if isinstance(content, list) and content:
        texts = []
        for c in content:
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
        if texts:
            out = "\n".join(texts)
            try:
                return json.loads(out)
            except Exception:
                return out
    if "error" in result:
        return {"rpc_error": result["error"]}
    return result.get("result", result)

def main():
    cmd = sys.argv[1]
    if cmd == "initialize":
        print(json.dumps(rpc({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "hyperagent", "version": "1.0"}},
        })))
    elif cmd == "list_tools":
        print(json.dumps(rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})))
    else:
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(call(name, args), indent=2))

if __name__ == "__main__":
    main()
