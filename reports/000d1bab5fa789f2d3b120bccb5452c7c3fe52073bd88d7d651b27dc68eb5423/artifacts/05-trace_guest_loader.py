import json
import pathlib
import urllib.request

URL = "http://192.168.248.169:3000/mcp"
TARGET_GUEST = r"C:\Users\h26v\Desktop\000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423"
TARGET_NAME = TARGET_GUEST.split("\\")[-1].lower()
OUTPUT = pathlib.Path(r"C:\Users\ADMIN\HyperAgent\reports\000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423\artifacts\05-trace_guest_loader.json")

req_id = 0


def post(payload, timeout=60):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def raw_rpc(method, params=None, notify=False, timeout=60):
    global req_id
    payload = {"jsonrpc": "2.0", "method": method}
    if not notify:
        req_id += 1
        payload["id"] = req_id
    if params is not None:
        payload["params"] = params
    text = post(payload, timeout=timeout)
    return None if notify else json.loads(text)


def parse_content(response):
    content = response.get("result", {}).get("content", [])
    text = "".join(item.get("text", "") for item in content if item.get("type") == "text")
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"_raw": text}


def tool(name, arguments=None, timeout=60):
    return parse_content(raw_rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout))


def norm_addr(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text)
        except Exception:
            return None
    if isinstance(value, dict):
        for key in ("address", "value", "result"):
            if key in value:
                candidate = norm_addr(value[key])
                if candidate is not None:
                    return candidate
    return None


def fmt_addr(value):
    return None if value is None else f"0x{value:08X}"


def eval_expr(expression):
    data = tool("eval_expression", {"expression": expression})
    if isinstance(data, dict):
        for key in ("value", "result", "address"):
            if key in data:
                candidate = norm_addr(data[key])
                if candidate is not None:
                    return candidate
        if "_raw" in data:
            return norm_addr(data["_raw"])
    return norm_addr(data)


def mem_hex(address, size):
    if address is None:
        return b""
    data = tool("memory_read", {"address": fmt_addr(address), "size": size, "encoding": "hex"})
    raw = None
    if isinstance(data, dict):
        raw = data.get("data") or data.get("bytes") or data.get("result") or data.get("_raw")
    elif isinstance(data, str):
        raw = data
    if not isinstance(raw, str):
        return b""
    cleaned = "".join(ch for ch in raw if ch in "0123456789abcdefABCDEF")
    if len(cleaned) < 2:
        return b""
    if len(cleaned) % 2:
        cleaned = cleaned[:-1]
    try:
        return bytes.fromhex(cleaned)
    except Exception:
        return b""


def read_ascii(address, size=128):
    blob = mem_hex(address, size)
    if not blob:
        return None
    blob = blob.split(b"\x00", 1)[0]
    try:
        text = blob.decode("ascii", errors="ignore")
    except Exception:
        return None
    return text or None


def read_utf16(address, size=512):
    blob = mem_hex(address, size)
    if not blob:
        return None
    out = bytearray()
    for index in range(0, len(blob) - 1, 2):
        pair = blob[index:index + 2]
        if pair == b"\x00\x00":
            break
        out.extend(pair)
    if not out:
        return None
    try:
        text = out.decode("utf-16le", errors="ignore")
    except Exception:
        return None
    text = text.strip("\x00")
    return text or None


def symbol_at(address):
    if address is None:
        return None
    data = tool("symbol_from_address", {"address": fmt_addr(address)})
    if isinstance(data, dict):
        return data.get("symbol") or data.get("name") or data.get("_raw")
    return str(data)


def module_list():
    data = tool("module_list")
    return data.get("modules", []) if isinstance(data, dict) else []


def find_sample_module(modules):
    for module in modules:
        path = (module.get("path") or "").lower()
        name = (module.get("name") or "").lower()
        if TARGET_NAME in path or TARGET_NAME in name:
            return module
    return None


def register_batch(names):
    data = tool("register_get_batch", {"names": names})
    if isinstance(data, dict):
        if isinstance(data.get("registers"), dict):
            return data["registers"]
        return data
    return {}


trace = {
    "target_guest_path": TARGET_GUEST,
    "loader_breakpoints": {},
    "sample_module": None,
    "sample_breakpoints": {},
    "events": [],
    "errors": [],
}

try:
    trace["initialize"] = raw_rpc(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "hyperagent", "version": "1.0"},
        },
    )
    raw_rpc("notifications/initialized", {}, notify=True)
    tool("breakpoint_delete_all")
    trace["debug_init"] = tool("debug_init", {"path": TARGET_GUEST})
    trace["state_after_init"] = tool("debug_get_state")
    trace["main_after_init"] = tool("module_get_main")
    trace["threads_after_init"] = tool("thread_list")

    loader_symbols = [
        "kernel32.LoadLibraryW",
        "kernel32.LoadLibraryExW",
        "kernel32.GetProcAddress",
        "kernel32.GetModuleFileNameW",
        "kernel32.CreateMutexW",
        "kernel32.WaitForSingleObject",
        "kernel32.CreateProcessW",
        "ws2_32.inet_addr",
    ]
    loader_bp_map = {}
    for symbol in loader_symbols:
        resolved = tool("symbol_resolve", {"symbol": symbol})
        address = norm_addr(resolved)
        trace["loader_breakpoints"][symbol] = {
            "resolved": resolved,
            "address": fmt_addr(address) if address is not None else None,
        }
        if address is not None:
            tool("breakpoint_set", {"address": fmt_addr(address), "type": "software", "enabled": True})
            loader_bp_map[address] = symbol

    def collect_event(tag, run_result):
        state = tool("debug_get_state")
        modules = module_list()
        sample_module = find_sample_module(modules)
        if sample_module and trace["sample_module"] is None:
            trace["sample_module"] = sample_module
        rip = norm_addr(state.get("rip") if isinstance(state, dict) else None)
        registers = register_batch(["eip", "esp", "eax"])
        esp = norm_addr(registers.get("esp")) if isinstance(registers, dict) else None
        eax = norm_addr(registers.get("eax")) if isinstance(registers, dict) else None
        event = {
            "tag": tag,
            "run_result": run_result,
            "state": state,
            "rip": fmt_addr(rip),
            "symbol": symbol_at(rip),
            "main_module": tool("module_get_main"),
            "sample_module": sample_module,
            "details": {},
        }
        if rip in loader_bp_map:
            symbol = loader_bp_map[rip]
            event["details"]["matched_loader_breakpoint"] = symbol
            if symbol in ("kernel32.LoadLibraryW", "kernel32.LoadLibraryExW") and esp is not None:
                string_ptr = eval_expr("[esp+4]")
                event["details"]["string_ptr"] = fmt_addr(string_ptr)
                event["details"]["utf16"] = read_utf16(string_ptr, 512)
            elif symbol == "kernel32.GetProcAddress" and esp is not None:
                module_handle = eval_expr("[esp+4]")
                proc_ptr = eval_expr("[esp+8]")
                event["details"]["module_handle"] = fmt_addr(module_handle)
                event["details"]["proc_ptr"] = fmt_addr(proc_ptr)
                if proc_ptr is not None and proc_ptr < 0x10000:
                    event["details"]["proc_name"] = f"ordinal:{proc_ptr}"
                else:
                    event["details"]["proc_name"] = read_ascii(proc_ptr, 128)
            elif symbol == "kernel32.GetModuleFileNameW" and esp is not None:
                buffer_ptr = eval_expr("[esp+8]")
                event["details"]["buffer_ptr"] = fmt_addr(buffer_ptr)
                event["details"]["caller_return"] = fmt_addr(eval_expr("[esp]"))
            elif symbol == "kernel32.CreateMutexW" and esp is not None:
                name_ptr = eval_expr("[esp+0xC]")
                event["details"]["name_ptr"] = fmt_addr(name_ptr)
                event["details"]["mutex_name"] = read_utf16(name_ptr, 256)
            elif symbol == "kernel32.WaitForSingleObject" and esp is not None:
                event["details"]["handle"] = fmt_addr(eval_expr("[esp+4]"))
                event["details"]["timeout"] = fmt_addr(eval_expr("[esp+8]"))
            elif symbol == "kernel32.CreateProcessW" and esp is not None:
                app_ptr = eval_expr("[esp+4]")
                cmd_ptr = eval_expr("[esp+8]")
                event["details"]["application_name"] = read_utf16(app_ptr, 512)
                event["details"]["command_line"] = read_utf16(cmd_ptr, 512)
            elif symbol == "ws2_32.inet_addr" and esp is not None:
                string_ptr = eval_expr("[esp+4]")
                event["details"]["string_ptr"] = fmt_addr(string_ptr)
                event["details"]["ascii"] = read_ascii(string_ptr, 64)
        if eax is not None:
            event["details"]["eax"] = fmt_addr(eax)
        trace["events"].append(event)
        return event

    for index in range(10):
        run_result = tool("debug_run")
        event = collect_event(f"loader-{index + 1}", run_result)
        if trace["sample_module"] is not None:
            break
        if isinstance(event["state"], dict) and event["state"].get("state") == "stopped":
            break

    if trace["sample_module"] is not None:
        base = norm_addr(trace["sample_module"].get("base"))
        sample_rvas = {
            "DllEntryPoint": 0x12FAA,
            "ServiceMain": 0x0F3C0,
            "SvchostPushServiceGlobals": 0x0F3E0,
            "sub_6400F350": 0x0F350,
            "sub_64011630": 0x11630,
            "sub_64010690": 0x10690,
            "sub_640113F0": 0x113F0,
            "sub_64010390": 0x10390,
            "sub_640101C3": 0x101C3,
        }
        sample_bp_map = {}
        for label, rva in sample_rvas.items():
            address = base + rva
            addr_text = fmt_addr(address)
            trace["sample_breakpoints"][label] = addr_text
            tool("breakpoint_set", {"address": addr_text, "type": "software", "enabled": True})
            sample_bp_map[address] = label

        for index in range(16):
            run_result = tool("debug_run")
            state = tool("debug_get_state")
            rip = norm_addr(state.get("rip") if isinstance(state, dict) else None)
            event = {
                "tag": f"sample-{index + 1}",
                "run_result": run_result,
                "state": state,
                "rip": fmt_addr(rip),
                "symbol": symbol_at(rip),
                "main_module": tool("module_get_main"),
                "sample_module": trace["sample_module"],
                "details": {},
            }
            if rip in sample_bp_map:
                event["details"]["matched_sample_breakpoint"] = sample_bp_map[rip]
            if rip in loader_bp_map:
                event["details"]["matched_loader_breakpoint"] = loader_bp_map[rip]
            trace["events"].append(event)
            if isinstance(state, dict) and state.get("state") == "stopped":
                break
except Exception as exc:
    trace["errors"].append(repr(exc))

OUTPUT.write_text(json.dumps(trace, indent=2), encoding="utf-8")
print(json.dumps({
    "output": str(OUTPUT),
    "sample_module": trace["sample_module"],
    "sample_breakpoints": trace["sample_breakpoints"],
    "event_count": len(trace["events"]),
    "errors": trace["errors"],
}, indent=2))
