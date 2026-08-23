# Setting up HyperAgent on a new machine

You received a `HyperAgent-transfer.zip` (built by
[`scripts/package_for_transfer.ps1`](scripts/package_for_transfer.ps1)). It
contains the source code, the `resource/` tool binaries (DIE, pycdas/pycdc,
pyinstxtractor) that aren't in git, **and** the sender's live config/secrets
(`config.yaml`, VT API key) so this handoff needs zero re-entry of keys. It
does **not** contain the Python virtualenv or `.git` history — see
`PACKAGE_MANIFEST.txt` inside the zip for the exact list.

**This zip contains real API keys and VM credentials.** Treat it like a
password file: only over a private channel between you two, never attached
to a public issue/PR/repo.

You should also have received `VMRunV4.ova` as a **separate file** (it's
~35 GB, not bundled in the zip) — this is the guest VM itself, exported from
the sender's `VMRunV4` snapshot with its memory state, so it boots straight
into a ready-to-use analysis environment. See step 3 for how to import it.

## 0. Prerequisites on this machine

- Windows 10/11
- An AI coding agent already available in a terminal here (e.g. Claude Code)
  to run the prompt in step 2
- Admin rights, for the manual installs in step 3

## 1. Extract

Unzip `HyperAgent-transfer.zip` to wherever you want the project to live,
e.g. `C:\Users\<you>\HyperAgent`.

If the zip includes `dotconfig\.hyperagent\config.yaml`, copy it to
`%USERPROFILE%\.hyperagent\config.yaml` (create the `.hyperagent` folder if
needed):

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.hyperagent" | Out-Null
Copy-Item ".\dotconfig\.hyperagent\config.yaml" "$env:USERPROFILE\.hyperagent\config.yaml"
```

That file has the sender's Anthropic API key/base_url, VirusTotal key, and VM
credentials already filled in. It also has machine-specific paths (VM `.vmx`
path, `skills_root`) copied verbatim from the sender's machine — fix those if
your drive letters/username differ, or just delete `skills_root` (it defaults
to the repo's own `skill/` folder). `skill\_hyperagent-common\scripts\.env`
(VT_API_KEY), if present in the zip, needs no action — it's already in the
right place once extracted.

## 2. Prompt for the agent (automatable part)

Open a terminal in the extracted folder, start your agent there, and paste
this prompt as-is. It only covers what a script can actually do — Python venv,
package install, smoke checks. It will **not** try to install IDA Pro,
x64dbg, or VMware (those are licensed/GUI installs — step 3 below).

```text
This is the HyperAgent repo, freshly extracted on a new machine. Set up the
Python side of it:

1. Read README.md sections 3-5 (Requirements, Install, Configuration) so you
   know the current setup contract — don't assume anything from other docs
   under openwiki/, they may be stale.
2. Run `powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -InstallDev -RunTests`
   from the repo root and show me the full output.
3. If it fails, diagnose the root cause (don't just retry) and fix it —
   common causes are: Python not on PATH or older than 3.11, or a locked/
   partially-created venv/ directory from a previous attempt.
4. After bootstrap succeeds, report clearly, as a checklist:
   - Python version found and venv path used
   - whether `pip check` and the smoke import passed
   - pytest result summary (pass/fail counts)
   - which external tools bootstrap.ps1 found vs marked MISSING (vmrun,
     idalib-mcp, upx) and which stage skill directories under skill/ it found
   - whether `%USERPROFILE%\.hyperagent\config.yaml` exists and has a
     provider.api_key set (don't print the key itself)
5. Do not attempt to download or install IDA Pro, x64dbg, or VMware. Just
   tell me what's still missing for those.
```

That's it for the automatable part — it just needs the agent's judgment to
interpret bootstrap.ps1's output and fix anything broken, not blind installs
of unreviewable software.

## 3. Manual installs (do these yourself — licensed/GUI, not automatable)

| Tool | Needed for | Get it |
|---|---|---|
| IDA Pro 8.0+ (with idalib) | `02-static-pass1`, `04-static-pass2` | your existing license; run `idalib-mcp` bootstrap after install |
| x64dbg + x64dbg MCP server | `03-unpack`, `05-dynamic` | https://x64dbg.com/ — then point `HYPERAGENT_X64DBG_MCP_URL` at wherever the MCP service runs (typically inside the guest VM) |
| VMware Workstation | `05-dynamic` | your existing license — install the app itself; the guest VM comes from `VMRunV4.ova` below, not a fresh build |

None of these have a scripted install path in this repo on purpose — they're
licensed software and the guest VM is a security boundary you should build
deliberately, not something a script should silently provision. `bootstrap.ps1`
only checks whether they're already reachable.

### Importing `VMRunV4.ova`

1. Put `VMRunV4.ova` anywhere with ~40 GB free (it expands on import).
2. In VMware Workstation: **File → Open**, pick `VMRunV4.ova`, choose an
   install location, let it import. This can take a while for a 35 GB file.
3. The import already contains the `VMRunV4` snapshot state with memory
   included — first Power On resumes exactly where the sender's VM was, no
   guest boot needed.
4. Note the path VMware gives the imported `.vmx` (shown in the VM's
   settings, or find it via `vmrun list` after powering on) — you'll need it
   for `vmware.vmx_path` in step 4.
5. Confirm `vmrun` can see it: `vmrun list` should show the `.vmx` path while
   it's running.

The prep/report/summary stages and the full test suite work without any of
this — you can validate the Python install (step 2) before touching any of
these three.

## 4. Secrets and machine-specific config

If you did step 1's config.yaml copy, the Anthropic key/base_url, VT key, and
VM credentials are already live — skip straight to step 5. Otherwise (or to
override anything), env vars always win over `config.yaml`
(`hyperagent/config.py`):

- `ANTHROPIC_API_KEY` — export it in your shell before running real pipeline
  stages.
- VirusTotal key for `06-intel` — set `VT_API_KEY` / `VIRUSTOTAL_API_KEY` in
  the environment, or drop a `KEY=VALUE` line in
  `skill/_hyperagent-common/scripts/.env`.
- VM/guest credentials — `HYPERAGENT_VMX_PATH`, `HYPERAGENT_VM_SNAPSHOT`,
  `HYPERAGENT_GUEST_USER`, `HYPERAGENT_GUEST_PASSWORD`,
  `HYPERAGENT_GUEST_DESKTOP`, `HYPERAGENT_GUEST_DEBUGGER` — no defaults,
  required only for `05-dynamic`.

Either way, update `vmware.vmx_path` in `config.yaml` to the path VMware
assigned the imported `VMRunV4.ova` (step 3) — the sender's path
(`H:\VMware\WinVM\...`) almost certainly won't exist on this machine.
`vmware.snapshot_name` should stay `"VMRunV4"` since that's the snapshot
baked into the OVA; `guest_user`/`guest_password`/`guest_desktop`/
`guest_debugger` should already match what's inside the VM and don't need
changing.

## 5. Verify end to end

```powershell
.\venv\Scripts\Activate.ps1
python -m pytest hyperagent\tests\ -q
hyperagent analyze C:\path\to\a\harmless\test\sample.exe --static-only
```

If the static-only run completes and writes `reports/<sha256>/09-summary.json`,
the Python side of the install is good. Wire up steps 3-4 before trying a
full (`05-dynamic`) run.
