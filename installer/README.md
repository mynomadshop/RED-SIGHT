# RedSight Windows installer

Everything needed to build the RedSight Desktop Windows installer, and the
first-run setup that ships inside it.

The design goal for this generation of the installer: **after running
`RedSight-Setup-<version>.exe` as Administrator, RedSight launches and works.**
Setup never stops to tell the user to go and install a dependency by hand.

## Layout

```
installer/
  RedSight.iss                  Inno Setup 6 script (wizard, components, uninstall)
  build/
    Build-Installer.ps1         stage payload -> fetch bundle -> compile -> zip
    Fetch-Bundles.ps1           download CPython 3.12 + the pip wheelhouse
  scripts/                      installed into {app}\scripts\windows
    RedSight-Common.ps1         logging, retries, downloads, process exec, PATH
    RedSight-Hardware.ps1       standalone capability scan (GPU, virtualization)
    RedSight-LmStudio.ps1       find/start LM Studio, record the endpoint and model
    RedSight-Provision.ps1      profiles, workspace, provider keys, runtime mode
    RedSight-Preflight.ps1      the dependency engine (detect / provision / verify)
    Bootstrap-RedSight.ps1      first-run orchestrator, run by the installer
    Verify-RedSightSetup.ps1    health check ("can RedSight launch right now?")
    Repair-RedSight.ps1         diagnose and repair an install that will not launch
    Start-RedSight.ps1          launcher dispatcher every shortcut points at
    Uninstall-RedSightDocker.ps1  removes containers/images, asks about volumes
  app-overlay/                  additive application modules merged into the payload
    Apply-AppOverlay.ps1        copies the modules, patches and wires the hooks
    redsight_bootstrap.py       runtime configuration, installed into each venv
    patches/lmstudio_stage115.py  appended to app/models/lmstudio.py
    app/ui/action_palette_stage114_mcp.py       MCP Servers tab in Settings
    app/ui/action_palette_stage115_lmstudio.py  LM Studio tab, probe redirection,
                                                responsiveness fixes
  tests/
    Test-RedSightSetup.ps1      cross-platform tests for the setup logic
    Test-IssScript.ps1          static checks for RedSight.iss
    test_app_overlay.py         tests for the overlay logic and runtime config
  docs/
    README.template.txt         becomes README.txt in the release zip
  legacy/
    RedSight-Setup-11.2.0.exe   previously shipped installer, used as the
                                authoritative source of the application payload
```

## Setup options

The wizard asks two things before installing anything, both informed by a
hardware scan that runs first:

1. **Setup type** - *NVIDIA GPU (CUDA local inference)* or *Laptop / PC (cloud
   AI providers)*. This decides which Python wheels are downloaded. The scan's
   recommendation is preselected, and choosing CUDA without a responding NVIDIA
   driver warns before continuing.
2. **AI provider and key** (API profile only) - LM Studio, OpenAI, Anthropic,
   Gemini, xAI or a custom OpenAI-compatible endpoint.
3. **LM Studio endpoint** (whenever a local model will be used) - the address of
   the local server, an optional model, and whether to reduce desktop animation.

It then asks for the **working folder**, which setup creates and wires into
`.env`.

Only one RedSight installation can exist on a device: when setup finds one
recorded in the registry it installs over it and skips the directory page, so a
second copy cannot be created by changing the path.

### Why the profile matters

| | CUDA profile | API / laptop profile |
| --- | --- | --- |
| PyTorch | `--index-url .../whl/cu124`, ~2.5 GB | `--index-url .../whl/cpu`, ~200 MB |
| ONNX Runtime | `onnxruntime-gpu` | `onnxruntime` |

On a machine with no working NVIDIA driver the CUDA build is not merely wasted
download - it fails to load. `PreInstalls` are installed before anything else so
the chosen torch is already satisfied when the rest of the dependency graph
resolves, and nothing pulls the default build over the top.

### Hardware detection

`RedSight-Hardware.ps1` is standalone so the Inno wizard can extract it to a
temp folder and run it before installing. It reports GPU/CUDA (via `nvidia-smi`,
not just the adapter name), chassis type, RAM, disk, Windows build and firmware
virtualization, then emits JSON for the bootstrap and INI for the wizard.

One subtlety worth knowing: `Win32_Processor.VirtualizationFirmwareEnabled`
reports **false** whenever a hypervisor is already running, because the CPU is
itself virtualized. Reading it alone would conclude that a machine already
running WSL2 cannot run WSL2, so it is OR'd with
`Win32_ComputerSystem.HypervisorPresent`.

## How RedSight reaches LM Studio

This is the part that repeatedly looked configured and was not, so it is worth
stating exactly.

The backend reads its endpoint through `app/config/settings.py`. That `Settings`
class uses `env_prefix = "RED_SIGHT_"`, and **nothing in the application calls
`load_dotenv`** - so a plain `LM_STUDIO_BASE_URL=...` line in `.env` never
reaches it. The only code that looks at that name is `LmStudioConfig`'s own
`mode="before"` validator, and it reads it from the real process environment.
With nothing there the field keeps its shipped default,
`http://host.docker.internal:1234/v1`, which resolves only inside a container.

Meanwhile the Settings dialog's "Test Connection" probes whatever URL is typed
into it, directly. So a native install could show a passing test beside a
backend that had never reached LM Studio at all.

Setup therefore records the endpoint in one machine-local file:

```
%LOCALAPPDATA%\RedSight\settings\lmstudio.json
    base_url         http://127.0.0.1:1234/v1
    model            the model a chat request names
    timeout_seconds  request timeout
    data_root        <install>\data
    runtime_mode     native | container
    ui_effects       full | reduced | off
```

and makes every consumer read it:

| Consumer | How it gets the value |
| --- | --- |
| the backend, the gateway, any `python` in a RedSight venv | `redsight_bootstrap.py` in `site-packages`, imported by a `.pth` at interpreter startup |
| `START-REDSIGHT-NATIVE.ps1` | reads it and exports it before starting anything |
| the app's own `START-REDSIGHT.ps1` | its hard-assigned `$env:LM_STUDIO_*` lines are rewritten to match |
| a containerized backend | the `LM_STUDIO_*` keys in `docker-compose.yml` are rewritten (the shipped file carries the author's own LAN address) |
| the desktop UI | Settings -> LM Studio reads and writes the same file |

Two further defects on that path are corrected by the overlay:

* **The model.** `/api/v1/chat` passes no model, and `settings.lmstudio.model_id`
  is never consulted, so the provider sent the literal id `"default"` - which
  LM Studio answers with 404. The appended patch resolves the configured model,
  or the first non-embedding model LM Studio reports as loaded.
* **The status probes.** Every probe in the UI is hardcoded to
  `http://127.0.0.1:1234`. Requests to that origin are redirected to the
  configured one, and only while the two differ.

## Which CUDA build, not just whether

A PyTorch wheel carries compiled kernels for a fixed list of GPU
architectures. Getting that list wrong does not fail at install time and does
not fail at import: `torch.cuda.is_available()` returns `True`, and the first
real operation on the device raises

```
CUDA error: no kernel image is available for execution on the device
```

The `cu124` index the installer used until 11.5.1 stops at `sm_90`, so on an
RTX 50-series card (Blackwell, `sm_120`) the whole CUDA profile was decoration.
The wheel index is now chosen from the compute capability the hardware scan
reports:

| Compute capability | Index | Requirement |
| --- | --- | --- |
| ≥ 12.0 (Blackwell, RTX 50-series) | `.../whl/cu128` | `torch>=2.7` |
| anything else, or unknown | `.../whl/cu124` | `torch` |

The version floor matters as much as the index: pip reports an
already-installed torch as satisfied, so without it a machine that once got the
wrong build would keep it through every repair run.

`Test-RsTorchCuda` then asks the question that actually matters — it compares
each device's capability against `torch.cuda.get_arch_list()` **and** runs a
real allocation on it. Setup fails the step rather than reporting success, and
the health check reports it per GPU.

## Memory, and why it showed as missing

The desktop UI does not talk to the model directly. Each chat is:

```
UI -> POST 127.0.0.1:8765/memory/build     (action/memory gateway)
   -> POST 127.0.0.1:8000/api/v1/chat      (backend -> LM Studio)
   -> POST 127.0.0.1:8765/memory/commit
```

and the memory indicator reads `127.0.0.1:8765/memory/status`. That gateway is
`redsight_actions.gateway_stage10:app` - an ASGI app, so running
`gateway_stage10.py` as a script defines it and exits without serving anything.
With the gateway down, memory reads as missing *and* no query is answered.

Setup now serves it through uvicorn and waits for `/memory/status`, and every
shortcut goes through `Start-RedSight.ps1`, which picks a launcher that starts
the gateway rather than whichever launcher happens to exist. The health check
reports the gateway separately from the backend.

## Desktop responsiveness

Three things in the shipped UI cost input latency, all of them now handled by
the overlay:

| Cause | Effect | Fix |
| --- | --- | --- |
| `LiveGpuDock.refresh` runs `subprocess.run(["nvidia-smi", ...])` on the Qt GUI thread every 1000 ms | the event loop stalls for as long as the process takes - hundreds of milliseconds on hybrid-graphics laptops | telemetry queries are served from a background sample |
| `get_lm_model()` blocks the GUI thread on an HTTP request every 10 s | a multi-second freeze whenever LM Studio is unreachable | the model list is fetched on a background thread and cached |
| `AmbientSupervisuals` repaints a translucent, full-window overlay every 50 ms | a permanent cost on integrated graphics | the cadence is budgeted (`full` / `reduced` / `off`), selectable in the wizard and in Settings |

## When it will not launch

`scripts\windows\Repair-RedSight.ps1` is the one command to reach for. It
reports first and changes nothing:

```
powershell -ExecutionPolicy Bypass -File scripts\windows\Repair-RedSight.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\Repair-RedSight.ps1 -Fix
```

It is also **Start Menu → Diagnose RedSight**. What it checks, in the order
that matters when the UI will not start:

| Area | What it answers |
| --- | --- |
| installations | how many RedSight trees exist on this device, and which one the shortcuts point at |
| shortcuts | whether the Desktop and Start Menu entries target *this* installation |
| paths | which files reference a different root, **with the offending lines** |
| workspace | whether the working directory collides with an installation |
| runtime config | the LM Studio endpoint and model the backend will actually read |
| ui | the real Command Center traceback, captured headlessly, plus the tail of the last launcher logs |
| services | the backend on 8000 and the action/memory gateway on 8765 |

`-Fix` rewrites paths, re-creates the shortcut against this installation, moves
a colliding working directory (never touching its contents), and re-installs
the runtime configuration into both virtualenvs. `-RecreateVenv` additionally
rebuilds `.venv-ui` from scratch. `-StopOtherInstances` ends a RedSight process
from a different tree that is holding port 8000 or 8765 — separate from `-Fix`
because it stops a running program.

**Always pass `-ProjectRoot` when running it from a source checkout**, and note
that it refuses to treat a checkout as an installation: rewriting install paths
inside one edits tracked files and repoints shortcuts at a tree that was never
installed.

### A leftover backend is the other common cause

`uvicorn` reporting `[Errno 10048] error while attempting to bind on address
('127.0.0.1', 8000)` means the port is already taken — normally by a backend
from an older RedSight tree. This installation's backend then exits, and the UI
talks to the old one, which is reading a different `.env`, a different data root
and possibly a different LM Studio endpoint. The diagnostics name the process
holding each port and which installation it came from.

### Two installations on one device

This is the usual reason a working install stops working. Setup refuses to
create a second one — it installs over the recorded install and skips the
directory page — but a tree that predates the installer, or one moved by hand,
is still there. The diagnostics list every tree it finds; keep one.

### Why paths get rewritten at all, and what is never rewritten

The payload carries the build machine's absolute install path, so setup
rewrites it to the real install directory. Until 11.5.2 it did that by matching
*any* drive path ending in `\RedSight` — and the working directory defaults to
`<UserProfile>\RedSight`, so the rewrite also caught the user's own workspace
and pointed it at the install root. That is what made a health check report a
file "still referencing another install path" on a working install, and what
mixed the two trees on a repair run.

Two things fix it. The build now records its source root in
`redsight-payload.json`, so the rewrite is an exact substitution rather than a
pattern. And these are never rewritten, whichever way the root was determined:

- the values of `REDSIGHT_WORKSPACE`, `REDSIGHT_WORKING_DIR`,
  `REDSIGHT_OUTPUT_DIR`, `REDSIGHT_MCP_DIR` and `RED_SIGHT_DATA_ROOT` — the
  user chose those directories
- `redsight-payload.json` itself, which holds the only record of the build root
- the setup scripts, which contain no install paths, only the code that
  computes them

A working directory that is itself a RedSight installation is now declined in
favour of `<UserProfile>\RedSight-Data`, with its existing contents untouched.

## Runtime modes

| | Container mode | Native mode |
| --- | --- | --- |
| Backend | `docker compose` (redsight + qdrant) | `scripts/start.py` in `.venv-ui` |
| Vector store | Qdrant container | Qdrant embedded, in-process |
| Requires | WSL2 + Docker Desktop | nothing beyond Python |
| Chosen when | firmware virtualization is available | it is not, or Docker is skipped |

Native mode exists because of a real failure: setup used to enable the WSL2
features and install Docker on laptops whose firmware has virtualization
switched off, leaving a machine that reboots and still cannot start the engine.
Setup now refuses that path up front, explains how to enable virtualization in
the firmware, and runs RedSight without containers instead - which works because
the application's vector store already supports `QdrantClient(path=...)` and
falls back to it when no server answers.

## What setup provisions

| Dependency | Detected by | Provisioned by |
| --- | --- | --- |
| Python 3.12 | `runtime\python`, then `py -3.12`, `python3.12`, `python`, then standard install dirs — version-gated to `3.12 <= v < 3.14` and required to import `venv`, `ensurepip`, `ssl`, `sqlite3`, `ctypes` | expanding the **bundled** official CPython (offline), else the python.org installer |
| pip / setuptools / wheel | `python -m pip` | the bundled wheelhouse (`--find-links`), offline-capable |
| `.venv-ui`, `.venv-actions` | `Scripts\python.exe` plus a real import check | `python -m venv` + `pip install` with retries |
| WSL2 | `Get-WindowsOptionalFeature` / `dism`, `wsl --status` | `dism /enable-feature`, `wsl --install --no-distribution`, `wsl --set-default-version 2` |
| Docker Desktop | `docker` on PATH, `%ProgramFiles%\Docker\Docker\Docker Desktop.exe` | downloaded from docker.com, `install --quiet --accept-license --backend=wsl-2`, user added to `docker-users` |
| Docker engine running | `docker info` | starts Docker Desktop and polls with a timeout |
| Docker images | `docker images` | `docker compose build` |
| Node.js (optional) | `node --version` | latest LTS MSI from the nodejs.org dist index |
| `.env` | file exists | copied from `.env.example` |
| Install paths | scan for `<drive>:\...\RedSight` | rewritten to the real install directory |

Everything is idempotent — re-running setup repairs rather than duplicates.

### Why a private Python runtime

The bundled interpreter is expanded to `{app}\runtime\python` and is never
registered or added to `PATH`. That makes the install deterministic and
immune to the `PYTHONPATH`/`sys.path` contamination the older bootstrap tried
to work around by stripping paths at runtime. A user who prefers their own
interpreter can tick *Use an existing Python 3.12 from PATH*.

The bundle is the official Python Software Foundation CPython build for Windows
x64, taken from [nuget.org/packages/python](https://www.nuget.org/packages/python)
— a complete relocatable distribution that includes `venv` and `ensurepip` with
a bundled pip wheel, so a virtual environment can be created with no network.
Its SHA256 is recorded in `runtime\bundle\bundle-manifest.json` at build time
and verified before use.

### Exit codes

`Bootstrap-RedSight.ps1` distinguishes "RedSight will not run" from "RedSight
runs but something optional needs attention":

| Code | Meaning |
| --- | --- |
| 0 | everything required and requested succeeded |
| 1 | a required dependency could not be provisioned |
| 2 | required parts succeeded, an optional part did not |
| 3 | a restart is required; setup resumes at the next sign-in |

Enabling the WSL2 Windows features can require a reboot. When that happens
setup registers a `RunOnce` entry so it resumes by itself, and the Inno Setup
wizard reads `rebootRequired` back out of `%LOCALAPPDATA%\RedSight\setup-summary.json`
to ask for the restart.

## Building

The Inno Setup compiler is Windows-only, so builds run on Windows (locally or
on the `windows-latest` runner via `.github/workflows/build-windows-installer.yml`).

```powershell
# from a source tree
pwsh -File installer/build/Build-Installer.ps1 -AppSource C:\src\RedSight -Version 11.5.3

# reusing the payload of the previously shipped installer
pwsh -File installer/build/Build-Installer.ps1 `
     -LegacyInstaller installer/legacy/RedSight-Setup-11.2.0.exe -Version 11.5.3
```

Useful switches:

- `-IncludeAllWheels` — pre-download every wheel for a fully offline installer
  (adds roughly a gigabyte: PySide6, torch, onnxruntime).
- `-SkipBundle` — omit the bundled runtime; setup then downloads Python.
- `-StageOnly` — build the staging tree and stop, for inspecting the payload.
- `-IsccPath` — explicit path to `ISCC.exe`.

Output lands in `dist/`: the setup exe, `SHA256SUMS-v<version>.txt`,
`manifest-v<version>.json` and `RedSightDesktopWindows<version>.zip`.

### Payload hygiene

`Build-Installer.ps1` prunes the staging tree before compiling: virtualenvs,
`__pycache__`, `node_modules`, `outputs/`, `data/runtime`,
`data/memory_exports`, `data/skills`, `redsight_remote/state`, backup snapshots
(`*.bak`, `Dockerfile.backup-*`), logs, local databases, `.env` and
`get-pip.py`. The 11.2.0 payload shipped a `Dockerfile.backup-<timestamp>`
snapshot; that class of leftover is now removed by pattern rather than by hand.

## Testing

```bash
pwsh -File installer/tests/Test-RedSightSetup.ps1   # 331 assertions
pwsh -File installer/tests/Test-IssScript.ps1       #  76 static checks
python3 installer/tests/test_app_overlay.py         #  96 assertions
```

503 assertions covering version parsing and gating, the install-path rewriter
(plain, JSON-escaped and forward-slash forms, exclusions, idempotency), `.env`
seeding, retry/backoff behaviour, process timeout and exit-code handling, the
venv import probe, bundled-Python provisioning (hash verification, tamper
refusal, absent-bundle fallback), archive expansion, hashing, the
logging/summary plumbing, LM Studio endpoint normalisation and model selection,
the runtime configuration file (BOM-free, corrupt-file tolerant) and its
environment export, the compose and launcher endpoint rewrites, the generated
native launcher (uvicorn-served gateway, health waits, no proxy on loopback),
launcher dispatch, the runtime `.pth` installation, the wizard's
one-installation-per-device guard, the PyTorch wheel index chosen per GPU
architecture and the check that proves torch can really run the installed
cards, progress reporting for long child processes, -ProjectRoot surviving the
dot-source of a script that declares its own, the refusal to treat a source
checkout as an installation, and the overlay's probe
redirection, cached sampling and effects budget. These run on Linux too, which is why they gate the
Windows build job.

The Windows job then does what unit tests cannot: it installs the freshly built
installer silently, asserts the bundled Python expanded and reports 3.12.x, that
`.venv-ui` imports `PySide6`/`qasync`/`httpx`/`pydantic`, that no build-machine
paths survive anywhere in the tree, that the health check runs, that a second
bootstrap run is idempotent, and that the uninstaller removes the virtual
environments.

Docker Desktop cannot be installed on a hosted runner (no nested
virtualisation), so the Docker and WSL2 provisioning paths are covered only for
graceful detection there; they need a real Windows machine to exercise fully.

### Compiler compatibility

`RedSight.iss` was cross-checked against the Inno Setup **6.7.0** source (the
version that built 11.2.0), not just against the docs: every `[Setup]`
directive it uses (34), every `Flags:` value (13) and every Pascal-script
function it calls (16) exists in that release, and the two `var`-parameter
signatures match exactly -
`GetSpaceOnDisk(const DriveRoot: String; const InMegabytes: Boolean; var Free, Total: Cardinal)`
and `LoadStringFromFile(const FileName: String; var S: AnsiString)`.

Worth knowing: 6.5 reworked `WizardStyle` so it now also carries the light/dark
options, but `modern` is still an accepted value, so the directive compiles on
6.3 through 6.7 alike.

## Notes and constraints

- **Docker Desktop is not bundled.** Its installer is ~1.6 GB and its licence
  restricts redistribution, so setup downloads it from Docker's official URL.
  For offline installs, drop `DockerDesktopInstaller.exe` into
  `runtime\bundle\` or `%ProgramData%\RedSight\downloads` first.
- **The installer is unsigned.** SmartScreen will warn; the release README
  explains how to verify the SHA256 instead.
- **`AppId` is unchanged** from 11.2.0, so this build upgrades an existing
  install in place rather than appearing as a second product.
- Setup requires elevation (`PrivilegesRequired=admin`) and Windows 10 2004+
  (`MinVersion=10.0.19041`), which is the floor for the WSL2 backend.
