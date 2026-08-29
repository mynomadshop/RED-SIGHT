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


FIXED IN {{VERSION}} — LM STUDIO, MEMORY AND A RESPONSIVE UI
------------------------------------------------------------
Four faults reported against the previous release are fixed. All four
were in how the desktop UI, the backend and the local model server were
wired to each other, so each is described plainly below.

  * "Test Connection passes but nothing answers."
    The backend reads its LM Studio endpoint from the process
    environment. Nothing in RedSight loads .env for that setting, so the
    endpoint fell back to its built-in default of
    http://host.docker.internal:1234/v1 — an address that only exists
    inside a container. Meanwhile the Settings dialog tested whatever
    URL was typed into it, directly. A passing test could therefore sit
    next to a backend that had never reached LM Studio at all.

    Setup now records the endpoint in one file that everything reads:

        %LOCALAPPDATA%\RedSight\settings\lmstudio.json

    and installs it into the environment of the backend, the agent
    gateway and the desktop UI. A new wizard page asks for the endpoint,
    and a new Settings ▸ LM Studio tab lets you change it, detect the
    loaded models and test the connection for real.

  * "The query gets no response."
    RedSight sent every chat with the model id "default", because the
    UI passes no model and the configured one was never consulted.
    LM Studio answers 404 for a model it has not got, so nothing ever
    reached your loaded model. Requests now name the configured model,
    or the first non-embedding model LM Studio reports as loaded.

  * "Memory is missing."
    The UI reads memory from the action/memory gateway on
    127.0.0.1:8765, and each chat goes through it before and after the
    model call. That gateway has to be served by uvicorn; the launcher
    was running its module as a plain script, which starts nothing. It
    is now served properly and waited for, every shortcut goes through
    a launcher that starts it, and the health check reports it
    separately.

  * "The UI is glitchy — the cursor and clicks lag."
    Three things ran on the drawing thread: nvidia-smi was launched as
    a process once a second, an HTTP request to LM Studio blocked it
    every ten seconds, and a translucent layer covering the whole window
    repainted twenty times a second. Sampling now happens in the
    background and the animation has a budget you can choose — full,
    reduced or off — during setup and in Settings.

  * If your LM Studio runs on another machine or another port, the UI
    now reports it correctly. Its status probes were hardcoded to
    127.0.0.1:1234 and are redirected to your configured endpoint.

  * A containerized install no longer inherits the build machine's own
    LAN address for LM Studio from docker-compose.yml.

  * One installation per device. Setup installs over an existing
    RedSight rather than beside it, and no longer offers to change the
    directory when one is already present, so a machine cannot end up
    with two copies.


FIXED IN 11.5.4 - THE REGISTRY DECIDES WHICH INSTALL IS YOURS
-------------------------------------------------------------
  * Pointed at the wrong folder, the diagnostics tool used to advise
    keeping that folder and retiring the real installation, and it
    "corrected" a shortcut that was already right. Now, whatever it is
    pointed at, the installation Windows recorded wins: a mismatch is
    announced in a banner before anything else, the keep-this-one advice
    names the recorded install, and a shortcut targeting the recorded
    install is left alone.


FIXED IN 11.5.3 - THE DIAGNOSTICS TOOL IGNORED -ProjectRoot
------------------------------------------------------------
  * Repair-RedSight.ps1, the health check and the bootstrap all
    accepted -ProjectRoot and then silently discarded it. A dot-sourced
    PowerShell script's param() block runs in the caller's scope, so
    RedSight-Preflight.ps1's own -ProjectRoot reset theirs to empty and
    each fell back to guessing the directory two levels above itself.
    Run from a source checkout with -ProjectRoot pointing at the real
    installation, the repair tool therefore examined - and repaired -
    the checkout.

    All three now capture the value before dot-sourcing anything.

  * The repair tool refuses to treat a source checkout as an
    installation, and says which directory to use instead, reading it
    from the registry where possible. Rewriting install paths inside a
    checkout edits its tracked files and repoints shortcuts at a tree
    that was never installed.

  * The diagnostics now name the process holding ports 8000 and 8765 and
    which installation it was started from. A leftover backend from an
    older RedSight folder makes this one exit with

        [Errno 10048] error while attempting to bind on address
        ('127.0.0.1', 8000)

    and the UI then talks to the old backend - a different .env, a
    different data folder, possibly a different LM Studio. Re-run with
    -StopOtherInstances to free the port.


FIXED IN 11.5.2 - MIXED-UP INSTALLATIONS, AND A REPAIR TOOL
-----------------------------------------------------------
  * "Some file points to the older installation." Setup rewrites the
    build machine's path to your install directory, and it did that by
    matching any drive path ending in \RedSight. Your working directory
    defaults to <YourProfile>\RedSight - so the rewrite caught that too
    and pointed it at the install folder. A health check on a working
    install would then report a file "still referencing another install
    path", and a repair run really did mix the two folders together.

    The build now records where it was built from, so the rewrite is an
    exact substitution instead of a pattern. Your working directory,
    output folder and data folder are never rewritten, whatever their
    paths.

  * A working directory that is itself a RedSight installation is now
    declined, and <YourProfile>\RedSight-Data used instead. Nothing
    already in the folder is moved or deleted. This is what put workspace
    subfolders in among application files.

  * NEW: Start Menu -> "Diagnose RedSight". One command that reports
    everything relevant when RedSight will not start, and changes
    nothing until you ask it to:

      - every RedSight installation on the device, and which one your
        shortcuts actually point at (two installations is the usual
        reason a working install stops working)
      - which files reference a different installation, with the exact
        lines
      - whether your working directory collides with an installation
      - the LM Studio endpoint and model the backend will really read
      - the actual Command Center error, captured by starting it
        headlessly, plus the tail of the last launch logs
      - whether the backend and the action/memory gateway are answering

    Run it again with -Fix and it repairs what it found: paths,
    shortcuts, the working directory and the runtime configuration.

      powershell -ExecutionPolicy Bypass -File ^
        "<install>\scripts\windows\Repair-RedSight.ps1"
      powershell -ExecutionPolicy Bypass -File ^
        "<install>\scripts\windows\Repair-RedSight.ps1" -Fix

  * The health check now names the files it is complaining about instead
    of only counting them.


FIXED IN 11.5.1 - GPU ACCELERATION ON RTX 50-SERIES CARDS
----------------------------------------------------------
  * The CUDA setup type installed a PyTorch build that could not
    run an RTX 50-series card. A PyTorch wheel carries kernels for a
    fixed list of GPU architectures; the one being installed stopped
    two generations short of Blackwell. It imported without complaint,
    reported CUDA as available, and then failed on the first operation
    with "no kernel image is available for execution on the device" -
    so on a machine with 50-series cards the whole CUDA profile was
    decoration.

    The wheel is now chosen from the compute capability your GPUs
    report, and setup proves it works: it runs a real operation on each
    card and fails the step if any of them cannot. The health check
    reports it per GPU. If you already installed 11.5.0 on such a
    machine, re-running setup replaces the wrong build.

  * Reduced desktop animation is now the default on every machine, not
    only on machines without a discrete GPU. The cost is not the
    graphics card - the ambient layer repaints from the same thread that
    handles the mouse - so the lag was reported on a dual high-end
    desktop too. Clear the box during setup, or use Settings, to keep
    the shipped look.

  * Building the container images no longer looks like a hang. That step
    can take twenty minutes or more on a first run and used to print
    nothing at all while it worked; it now reports progress every
    minute.


ALSO FIXED IN EARLIER 11.x RELEASES
------------------------------------
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
The "RedSight" shortcut picks the right launcher for how setup
configured this machine, and will:
  1. Start Docker Desktop and the Qdrant/RedSight containers, or, in
     native mode, start the backend in-process with an embedded vector
     store and no containers at all.
  2. Start the action/memory gateway on 127.0.0.1:8765 and wait until it
     answers. The UI needs it for memory and for chat, so a failure here
     is reported rather than passed over.
  3. Put the recorded LM Studio endpoint into the environment the
     backend reads.
  4. Open the Command Center UI.

For local inference, start LM Studio and switch on its Local Server
(Developer tab), then load a model. Setup records the endpoint even when
LM Studio is not running yet, so switching it on later is enough — no
reinstall needed. To point RedSight at a different address or pick a
different model, use Settings ▸ LM Studio, which tests the endpoint and
lists the models it actually has.

If the Docker images were not built during setup, the first launch
builds them, which takes several minutes once.


TROUBLESHOOTING
---------------
Setup writes a full timestamped log and a machine-readable summary:

    %LOCALAPPDATA%\RedSight\logs\bootstrap-<timestamp>.log
    %LOCALAPPDATA%\RedSight\setup-summary.json

If RedSight will not launch, start with the diagnostics - Start Menu ->
"Diagnose RedSight". It reports what is wrong and can repair it.

To check an existing install at any time, use the Start Menu entry
"RedSight health check", or run:

    powershell -ExecutionPolicy Bypass -File ^
      "C:\Program Files\RedSight\scripts\windows\Verify-RedSightSetup.ps1"

It reports, per dependency, whether RedSight can launch right now and
what is missing if it cannot — including whether the LM Studio endpoint
reaches the backend, whether a model is loaded, and whether the
action/memory gateway is answering.

If the UI says memory is missing, the gateway did not start. Its output
is in:

    %LOCALAPPDATA%\RedSight\logs\native-gateway.err.log

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
