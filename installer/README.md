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
    RedSight-Provision.ps1      profiles, workspace, provider keys, runtime mode
    RedSight-Preflight.ps1      the dependency engine (detect / provision / verify)
    Bootstrap-RedSight.ps1      first-run orchestrator, run by the installer
    Verify-RedSightSetup.ps1    health check ("can RedSight launch right now?")
  app-overlay/                  additive application modules merged into the payload
    Apply-AppOverlay.ps1        copies the modules and wires the launcher hook
    app/ui/action_palette_stage114_mcp.py   MCP Servers tab in Settings
  tests/
    Test-RedSightSetup.ps1      cross-platform tests for the setup logic
    Test-IssScript.ps1          static checks for RedSight.iss
    test_app_overlay.py         tests for the MCP path handling
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

It then asks for the **working folder**, which setup creates and wires into
`.env`.

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
pwsh -File installer/build/Build-Installer.ps1 -AppSource C:\src\RedSight -Version 11.3.0

# reusing the payload of the previously shipped installer
pwsh -File installer/build/Build-Installer.ps1 `
     -LegacyInstaller installer/legacy/RedSight-Setup-11.2.0.exe -Version 11.3.0
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
pwsh -File installer/tests/Test-RedSightSetup.ps1   # 137 assertions
pwsh -File installer/tests/Test-IssScript.ps1       #  45 static checks
python3 installer/tests/test_app_overlay.py         #  35 assertions
```

66 assertions covering version parsing and gating, the install-path rewriter
(plain, JSON-escaped and forward-slash forms, exclusions, idempotency), `.env`
seeding, retry/backoff behaviour, process timeout and exit-code handling, the
venv import probe, bundled-Python provisioning (hash verification, tamper
refusal, absent-bundle fallback), archive expansion, hashing and the
logging/summary plumbing. These run on Linux too, which is why they gate the
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
