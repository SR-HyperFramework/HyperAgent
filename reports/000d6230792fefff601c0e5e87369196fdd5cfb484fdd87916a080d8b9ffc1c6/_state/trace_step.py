import json, sys, urllib.request

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

def regs(names):
    d = call("register_get_batch", {"names": names})
    return {r["name"]: r["value"] for r in d.get("registers", [])}

n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
REG = ["eip","eax","ebx","ecx","edx","esi","edi","esp","eflags"]
for i in range(n):
    call("debug_step_into")
    r = regs(REG)
    eip = r.get("eip")
    dis = call("disassembly_at", {"address": eip, "count": 1})
    insn = dis.get("instructions",[{}])[0].get("instruction","?")
    print(f"step{i:02d} eip={eip} eax={r.get('eax')} ebx={r.get('ebx')} ecx={r.get('ecx')} edx={r.get('edx')} esi={r.get('esi')} edi={r.get('edi')} esp={r.get('esp')} | {insn}")
