import json, sys, time
sys.path.insert(0, "C:/Users/ADMIN/HyperAgent/reports/_tool")
import x64dbg_rpc as X

def call(name, args=None, tid=370):
    return X.inner_text(X.call_tool(name, args, tool_id=tid))

def wait_paused(max_wait=2.0):
    t0=time.time()
    while time.time()-t0 < max_wait:
        st=call("debug_get_state")
        if st.get("state")=="paused":
            return st
        time.sleep(0.05)
    return st

LOG="C:/Users/ADMIN/HyperAgent/reports/_tool/step_to_entry.log"

def log(msg):
    with open(LOG,"a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

# init fresh
call("debug_init")
call("breakpoint_delete_all")
call("breakpoint_set",{"address":"0x4018A0","type":"hardware"})
call("breakpoint_set",{"address":"0x401DF8","type":"software"})
call("breakpoint_set",{"address":"0x401E42","type":"software"})
call("breakpoint_set",{"address":"0x401E81","type":"software"})
log("init+bps done")

count=0
target="?"
while count < 9000:
    st = wait_paused()
    rip = st.get("rip","?")
    if rip=="0x00000000004018A0":
        log(f"REACHED ENTRY after {count} steps")
        target="entry"
        break
    if rip=="0x0000000000401DF8":
        log(f"REACHED DECRYPTOR after {count} steps")
        target="decryptor"
        break
    if rip=="0x0000000000401E42":
        log(f"REACHED DEST-RESOLVE after {count} steps")
        target="dest"
        break
    call("debug_step_into")
    time.sleep(0.015)
    count+=1
    if count%500==0:
        log(f"step {count} rip={rip}")
else:
    log("BUDGET EXHAUSTED")
print("RESULT:", target, "steps:", count)
print("final:", json.dumps(call("debug_get_state"))[:250])
