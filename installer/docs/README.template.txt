RedSight Desktop — Windows Installer
=====================================

Version: {{VERSION}}
File:    {{SETUP_EXE}}  ({{SIZE_MB}} MB)
SHA256:  {{SHA256}}
Built:   {{BUILD_DATE}}


WHAT'S NEW IN {{VERSION}} — FULLY AUTOMATIC SETUP
--------------------------------------------------
Previous releases checked for Python and Docker and, if they were
missing, stopped and told you to go install them yourself. This release
installs and configures everything for you.

Extract the zip, right-click {{SETUP_EXE}} and choose "Run as
administrator". Setup then checks every dependency and provisions
whatever is absent:

  * Python 3.12 — a private, self-contained CPython 3.12 runtime is
    BUNDLED INSIDE THIS INSTALLER. Nothing is downloaded for it and
    nothing on your PATH is touched or overwritten. If you would rather
    use a Python 3.12 you already have, tick "Use an existing Python
    3.12 from PATH" on the setup options page.

  * pip / setuptools / wheel — installed offline from the bundled
    wheelhouse, so a fresh virtual environment works even before the
    network is reachable.

  * Virtual environments — .venv-ui (the desktop Command Center) and
    .venv-actions (the action/memory gateway) are created and their
    dependencies installed, with automatic retries on network errors.

  * WSL2 — the Microsoft-Windows-Subsystem-Linux and
    VirtualMachinePlatform Windows features are enabled and the WSL2
    kernel is updated. If Windows asks for a restart, setup says so and
    resumes by itself the next time you sign in.

  * Docker Desktop — downloaded from Docker's official site and
    installed silently, your account is added to the docker-users
    group, and the engine is started and waited for.

  * Docker images — the redsight and qdrant images are built during
    setup if you leave that component selected.

  * Node.js — optional, and only if you select it. It is needed solely
    for the WhatsApp remote utility.

  * Configuration — .env is created from .env.example, and every
    absolute path baked in on the build machine is rewritten to your
    real install directory.

Everything is idempotent: re-running setup repairs a broken install
instead of starting over.


ALSO FIXED IN THIS RELEASE
---------------------------
  * Install-path rewriting now handles JSON-escaped ("C:\\Users\\...")
    and forward-slash ("C:/Users/...") paths as well as plain ones.
    Earlier releases only matched the plain form, so paths inside JSON
    configuration files silently kept pointing at the build machine.

  * Python version validation. Earlier releases accepted any
    interpreter called "python" on PATH, including 3.11 or 3.13, and
    failed later with confusing import errors. Setup now requires
    3.12 <= version < 3.14 and verifies the interpreter can actually
    create virtual environments, so a Microsoft Store Python stub is
    rejected instead of half-working.

  * Setup now verifies that .venv-ui can import PySide6, qasync, httpx
    and pydantic before declaring success, rather than assuming pip
    succeeded.

  * Dependency installs no longer hang forever: every child process has
    a timeout, and its output is captured into the setup log.

  * The Start Menu shortcut points at powershell.exe with the launcher
    script, instead of at a .ps1 file that Windows may open in an
    editor.

  * Personal data and build leftovers are excluded from the payload
    (Dockerfile backup snapshots, *.bak files, logs, local databases,
    .env, get-pip.py).


REQUIREMENTS
------------
  * Windows 10 version 2004 (build 19041) or newer, 64-bit, or
    Windows 11.
  * Administrator rights. Setup enables Windows features and installs
    Docker Desktop, so it cannot run unelevated.
  * About 8 GB of free disk space once the Python packages and Docker
    images are in place.
  * An internet connection, unless you are installing from a prepared
    full offline bundle. The bundled Python runtime itself never needs
    the network.
  * An NVIDIA GPU is recommended (dual-GPU aware scheduling is
    supported) but not required; RedSight degrades gracefully without
    one.


INSTALLING
----------
  1. Extract this zip anywhere.
  2. Right-click {{SETUP_EXE}} → "Run as administrator".
  3. On the setup options page, choose the components you want. The
     defaults install everything, including Docker Desktop and the
     container images.
  4. Let setup run. Installing Docker Desktop and building the images
     takes a while — progress is shown, and everything is written to
     the log (see TROUBLESHOOTING).
  5. If setup reports that a restart is needed, restart. Setup resumes
     automatically when you sign back in.
  6. Use the "RedSight" shortcut on your Desktop or in the Start Menu.

Silent / unattended install:

    {{SETUP_EXE}} /VERYSILENT /SUPPRESSMSGBOXES

Core only, without Docker (useful for CI or a first look):

    {{SETUP_EXE}} /VERYSILENT /COMPONENTS="core"


ABOUT THE SECURITY WARNING
---------------------------
This installer is NOT digitally code-signed, so Windows SmartScreen and
your browser may warn about it:

    "Windows protected your PC"  /  "This file might be dangerous"

That is expected for any unsigned Windows installer; it means Windows
cannot verify the publisher through a paid code-signing certificate, not
that the file is unsafe.

  SmartScreen dialog:  click "More info", then "Run anyway".
  Edge / Chrome:       click "..." next to the download, then "Keep".

Verify the download first if you like:

    PowerShell:
      Get-FileHash .\{{SETUP_EXE}} -Algorithm SHA256

The result must equal the SHA256 at the top of this file and the value
in {{SUMS_FILE}}.


FIRST LAUNCH
-------------
The "RedSight" shortcut will:
  1. Start Docker Desktop if it is not already running.
  2. Start the Qdrant and RedSight backend containers.
  3. Connect to LM Studio's local server on 127.0.0.1:1234 if it is
     running (start LM Studio's Local Server separately for local
     inference).
  4. Start the action/memory gateway and open the Command Center UI.

If the Docker images were not built during setup, the first launch
builds them, which takes several minutes once.


TROUBLESHOOTING
---------------
Setup writes a full timestamped log and a machine-readable summary:

    %LOCALAPPDATA%\RedSight\logs\bootstrap-<timestamp>.log
    %LOCALAPPDATA%\RedSight\setup-summary.json

To check an existing install at any time, use the Start Menu entry
"RedSight health check", or run:

    powershell -ExecutionPolicy Bypass -File ^
      "C:\Program Files\RedSight\scripts\windows\Verify-RedSightSetup.ps1"

It reports, per dependency, whether RedSight can launch right now and
what is missing if it cannot.

To repair an install (safe to re-run at any time), use the Start Menu
entry "Repair RedSight setup", or run:

    powershell -ExecutionPolicy Bypass -File ^
      "C:\Program Files\RedSight\scripts\windows\Bootstrap-RedSight.ps1" ^
      -InstallDocker -EnableWsl

Setup exit codes:
    0  everything requested succeeded
    1  a required dependency could not be provisioned
    2  required parts succeeded, something optional needs attention
    3  a restart is required; setup resumes at the next sign-in


OFFLINE INSTALLS
----------------
The bundled Python runtime and packaging wheels always install without
network access. For a machine with no internet at all:

  * Tick "Offline install — never download" on the setup options page
    (or pass -OfflineOnly to Bootstrap-RedSight.ps1). Setup will then
    fail loudly rather than silently trying to reach the network.
  * Place a copy of Docker Desktop's installer, named
    DockerDesktopInstaller.exe, in the install directory's
    runtime\bundle folder, or in %ProgramData%\RedSight\downloads,
    before running setup.
  * To pre-download every Python wheel as well, run
    installer\build\Fetch-Bundles.ps1 -IncludeAllWheels on a connected
    machine and rebuild. Docker Desktop cannot be redistributed inside
    the installer, which is why it is fetched from docker.com instead.


UNINSTALLING
------------
Use "Add or Remove Programs" → RedSight → Uninstall, or the "Uninstall
RedSight" shortcut in the Start Menu group. The uninstaller asks
whether to also remove RedSight's Docker containers and images and,
separately, its stored data volumes (Qdrant vector index and chat
memory), so you can keep your data if you plan to reinstall.

The private Python runtime, the virtual environments and the setup logs
are removed with the application. Docker Desktop, WSL2 and Node.js are
left installed, since other software may rely on them.


WHAT'S IN THIS ZIP
-------------------
  {{SETUP_EXE}}          the installer (unsigned)
  {{SUMS_FILE}}          SHA256 checksum for integrity verification
  manifest-v{{VERSION}}.json   machine-readable release metadata
  README.txt                    this file


SUPPORT / MORE INFO
--------------------
https://redsight.ai
