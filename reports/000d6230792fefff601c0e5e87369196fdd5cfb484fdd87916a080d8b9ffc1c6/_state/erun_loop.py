import json, sys, time, urllib.request

URL = "http://192.168.248.169:3000/mcp"

def rpc(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def call(name, arguments=None):
    result = rpc({"jsonrpc": "2.0", "id": 99, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}}})
    content = result.get("result", {}).get("content")
    if isinstance(content, list) and content:
        texts = [c.get("text","") for c in content if c.get("type")=="text"]
        if texts:
            out = "\n".join(texts)
            try: return json.loads(out)
            except Exception: return out
    return result.get("result", result)

def in_sample(addr):
    try:
        return 0x400000 <= int(addr, 16) < 0x470000
    except Exception:
        return False

max_iter = int(sys.argv[1]) if len(sys.argv) > 1 else 12
for i in range(max_iter):
    call("script_execute", {"command": "erun"})
    time.sleep(0.4)
    st = call("debug_get_state")
    rip = st.get("rip")
    print(f"iter{i:02d} rip={rip}")
    if in_sample(rip):
        print("REACHED SAMPLE MODULE")
        break
