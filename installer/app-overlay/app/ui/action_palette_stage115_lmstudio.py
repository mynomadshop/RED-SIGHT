"""RedSight Stage 11.5 - LM Studio wiring, and a UI that stays responsive.

Four defects in the shipped desktop build are corrected here. All four are
installed by monkey-patching from :func:`install`, so no existing module
changes and a failure in any one of them cannot stop the UI from starting.

1. The LM Studio endpoint is unreachable from the backend
   ``LmStudioConfig.base_url`` defaults to
   ``http://host.docker.internal:1234/v1``, which resolves only inside a
   container, and nothing exports the real endpoint into the process
   environment. Setup now records the endpoint in
   ``%LOCALAPPDATA%\\RedSight\\settings\\lmstudio.json``; this module exposes it
   in Settings so it can be changed, tested and re-applied without editing
   files.

2. Every status probe in the UI is hardcoded to ``http://127.0.0.1:1234``
   An LM Studio on another port, or on another machine on the LAN, therefore
   always reads as offline no matter what Settings says - which is exactly the
   contradiction of a passing connection test beside a connection error.
   Rather than rewrite each of those call sites, requests aimed at the shipped
   default origin are redirected to the configured one, and only while the two
   differ.

3. ``nvidia-smi`` is run on the Qt GUI thread once a second
   ``LiveGpuDock.refresh`` calls ``subprocess.run(["nvidia-smi", ...])`` from a
   one-second QTimer, and ``get_lm_model`` blocks the same thread on an HTTP
   request every ten seconds. Each of those stalls the event loop, which is
   felt directly as late cursor movement and late clicks. Sampling now happens
   on a background thread and the GUI thread is served from the last sample.

4. A translucent full-window overlay repaints twenty times a second
   ``AmbientSupervisuals`` covers the whole main window with a translucent,
   antialiased layer on a 50 ms timer, and ``VoiceOrb`` runs at 33 ms. On
   integrated graphics that is a large, permanent cost for decoration. The
   cadence is now budgeted, and the budget is selectable in Settings.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# The origin the shipped UI probes are hardcoded to.
DEFAULT_LM_ORIGIN = "http://127.0.0.1:1234"

EFFECT_LEVELS = ("full", "reduced", "off")

# Ambient layer / voice orb timer intervals in milliseconds, per budget.
_EFFECT_INTERVALS = {
    "full": (50, 33),
    "reduced": (200, 66),
    "off": (0, 100),
}

_NVIDIA_QUERY_MARKER = "--query-gpu"

_state: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Stored configuration
# ---------------------------------------------------------------------------


def runtime():
    """The ``redsight_bootstrap`` module, or ``None`` if setup did not install it.

    Setup copies it into each RedSight virtualenv's ``site-packages``. Its
    absence is not fatal: everything here then falls back to the shipped
    defaults.
    """
    module = _state.get("runtime")
    if module is None:
        try:
            import redsight_bootstrap

            module = redsight_bootstrap
        except Exception:
            module = False
        _state["runtime"] = module
    return module or None


def configured_base_url() -> str:
    """The configured OpenAI-compatible base URL, e.g. ``http://host:1234/v1``."""
    module = runtime()
    if module is None:
        return os.environ.get("LM_STUDIO_BASE_URL") or (DEFAULT_LM_ORIGIN + "/v1")
    try:
        return module.base_url()
    except Exception:
        return DEFAULT_LM_ORIGIN + "/v1"


def configured_origin() -> str:
    """The scheme, host and port of the configured endpoint, with no path."""
    url = configured_base_url()
    marker = "://"
    index = url.find(marker)
    if index < 0:
        return DEFAULT_LM_ORIGIN
    rest = url[index + len(marker) :]
    host = rest.split("/", 1)[0]
    return url[:index] + marker + host


def configured_model() -> str:
    module = runtime()
    if module is None:
        return os.environ.get("LM_STUDIO_MODEL", "")
    try:
        return module.model_id()
    except Exception:
        return ""


def save_configuration(**values: Any) -> str:
    """Persist endpoint settings and mirror them into this process."""
    module = runtime()
    if module is None:
        raise RuntimeError(
            "RedSight's runtime configuration module is missing. "
            "Run 'Repair RedSight setup' from the Start Menu."
        )
    path = module.save_config(values)
    module.apply_environment(override=True)
    _state.pop("effective_origin", None)
    return str(path)


# ---------------------------------------------------------------------------
# 1. nvidia-smi sampling, off the GUI thread
# ---------------------------------------------------------------------------


class _NvidiaSampler:
    """Runs the telemetry query on its own thread and keeps the last result.

    A GUI-thread caller is served from the stored sample, so the event loop is
    never blocked on a process launch. Sampling stops for good once nvidia-smi
    turns out to be absent, rather than paying for a failed spawn forever.
    """

    def __init__(self, interval: float = 2.0) -> None:
        self.interval = max(0.5, float(interval))
        self._lock = threading.Lock()
        self._result: subprocess.CompletedProcess | None = None
        self._argv: list[str] | None = None
        self._thread: threading.Thread | None = None
        self._available = True

    # -- sampling ---------------------------------------------------------

    def _run(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return _original_subprocess_run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )

    def _loop(self) -> None:
        while self._available:
            time.sleep(self.interval)
            with self._lock:
                argv = list(self._argv or [])
            if not argv:
                continue
            try:
                result = self._run(argv, timeout=8.0)
            except FileNotFoundError:
                self._available = False
                return
            except Exception:
                continue
            with self._lock:
                self._result = result

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="redsight-gpu-sampler", daemon=True
        )
        self._thread.start()

    # -- GUI-thread entry point -------------------------------------------

    def sample(self, argv: list[str]) -> subprocess.CompletedProcess:
        with self._lock:
            self._argv = list(argv)
            cached = self._result

        if cached is not None:
            return cached

        # Cold cache: one synchronous read, with a short timeout so even the
        # first paint cannot hang, then the background thread takes over.
        result = self._run(list(argv), timeout=4.0)
        with self._lock:
            self._result = result
        self._ensure_thread()
        return result


_original_subprocess_run = subprocess.run


def _is_nvidia_telemetry(argv: Any) -> bool:
    if isinstance(argv, (str, bytes)):
        return False
    try:
        parts = [str(part) for part in argv]
    except Exception:
        return False
    if not parts:
        return False
    # Split on both separators rather than trusting os.path: the same check has
    # to hold when this module is exercised off Windows.
    program = parts[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if program not in ("nvidia-smi", "nvidia-smi.exe"):
        return False
    return any(_NVIDIA_QUERY_MARKER in part for part in parts[1:])


def install_gpu_sampling(interval: float = 2.0) -> bool:
    """Serve nvidia-smi telemetry queries from a background sample."""
    if _state.get("gpu_sampling"):
        return False

    sampler = _NvidiaSampler(interval=interval)

    def patched_run(*args: Any, **kwargs: Any):
        argv = args[0] if args else kwargs.get("args")
        if _is_nvidia_telemetry(argv):
            try:
                return sampler.sample(list(argv))
            except Exception:
                # Fall through to the real call so behaviour never gets worse.
                pass
        return _original_subprocess_run(*args, **kwargs)

    subprocess.run = patched_run
    _state["gpu_sampling"] = sampler
    return True


# ---------------------------------------------------------------------------
# 2. LM Studio probes: configured endpoint, cached, never blocking
# ---------------------------------------------------------------------------


class _CachedResponse:
    """Enough of an ``http.client.HTTPResponse`` for the UI's status probes.

    ``get_lm_model`` uses ``urlopen`` as a context manager and hands the result
    to ``json.load``, so read/close/context-manager behaviour is all that is
    needed.
    """

    def __init__(self, body: bytes, url: str, status: int = 200) -> None:
        self._buffer = io.BytesIO(body)
        self.url = url
        self.status = status
        self.code = status
        self.headers = {"Content-Type": "application/json"}

    def read(self, amount: int | None = None) -> bytes:
        return self._buffer.read() if amount is None else self._buffer.read(amount)

    def readline(self, *args: Any) -> bytes:
        return self._buffer.readline(*args)

    def __iter__(self):
        return iter(self._buffer)

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def info(self):
        return self.headers

    def close(self) -> None:
        self._buffer.close()

    def __enter__(self) -> "_CachedResponse":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        self.close()
        return False


_original_urlopen = urllib.request.urlopen


def effective_url(url: str) -> str:
    """Redirect a request aimed at the shipped default LM Studio origin.

    Only the hardcoded ``http://127.0.0.1:1234`` origin is redirected, and only
    while the configured endpoint differs from it. Everything else - the
    backend, Qdrant, the actions gateway - is untouched.
    """
    text = str(url)
    if not text.startswith(DEFAULT_LM_ORIGIN):
        return text
    origin = _state.get("effective_origin")
    if origin is None:
        origin = configured_origin()
        _state["effective_origin"] = origin
    if not origin or origin == DEFAULT_LM_ORIGIN:
        return text
    return origin + text[len(DEFAULT_LM_ORIGIN) :]


def is_lm_models_url(url: str) -> bool:
    """True only for the LM Studio model list, at either origin."""
    text = str(url).rstrip("/")
    if not text.endswith("/models"):
        return False
    origin = _state.get("effective_origin")
    if origin is None:
        origin = configured_origin()
        _state["effective_origin"] = origin
    return text.startswith(DEFAULT_LM_ORIGIN) or (bool(origin) and text.startswith(origin))


class _ModelsProbe:
    """Keeps the LM Studio model list fresh on a background thread."""

    def __init__(self, interval: float = 10.0) -> None:
        self.interval = max(2.0, float(interval))
        self._lock = threading.Lock()
        self._body: bytes | None = None
        self._error: BaseException | None = None
        self._url = ""
        self._thread: threading.Thread | None = None

    def _fetch(self, url: str, timeout: float) -> bytes:
        with _original_urlopen(url, timeout=timeout) as response:
            return response.read()

    def _loop(self) -> None:
        while True:
            time.sleep(self.interval)
            with self._lock:
                url = self._url
            if not url:
                continue
            try:
                body = self._fetch(url, timeout=6.0)
            except BaseException as exc:  # noqa: BLE001 - reported, not raised
                with self._lock:
                    self._body = None
                    self._error = exc
                continue
            with self._lock:
                self._body = body
                self._error = None

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="redsight-lmstudio-probe", daemon=True
        )
        self._thread.start()

    def open(self, url: str, timeout: float | None) -> _CachedResponse:
        with self._lock:
            self._url = url
            body = self._body
            error = self._error

        if body is not None:
            return _CachedResponse(body, url)
        if error is not None:
            self._ensure_thread()
            raise error

        # Cold cache: read it once here, keeping the caller's timeout but never
        # letting it exceed a couple of seconds on the GUI thread.
        limit = 2.0 if timeout is None else min(float(timeout), 2.0)
        try:
            body = self._fetch(url, timeout=limit)
        except BaseException as exc:  # noqa: BLE001
            with self._lock:
                self._error = exc
            self._ensure_thread()
            raise
        with self._lock:
            self._body = body
            self._error = None
        self._ensure_thread()
        return _CachedResponse(body, url)


def install_lm_probe(interval: float = 10.0) -> bool:
    """Point LM Studio status probes at the configured endpoint and cache them."""
    if _state.get("lm_probe"):
        return False

    probe = _ModelsProbe(interval=interval)

    def patched_urlopen(url: Any, *args: Any, **kwargs: Any):
        target = url if isinstance(url, str) else getattr(url, "full_url", None)
        if isinstance(target, str):
            redirected = effective_url(target)
            # Only LM Studio's own model list is cached. Another service that
            # happens to expose /models must be left completely alone.
            if is_lm_models_url(redirected):
                timeout = kwargs.get("timeout")
                if timeout is None and args:
                    # urlopen(url, data, timeout)
                    timeout = args[1] if len(args) > 1 else None
                try:
                    return probe.open(redirected, timeout)
                except (urllib.error.URLError, OSError):
                    raise
                except Exception:
                    pass
            if redirected != target:
                if isinstance(url, str):
                    url = redirected
                else:
                    try:
                        url.full_url = redirected
                    except Exception:
                        pass
        return _original_urlopen(url, *args, **kwargs)

    urllib.request.urlopen = patched_urlopen
    _state["lm_probe"] = probe
    return True


def install_httpx_redirect() -> bool:
    """Redirect the httpx-based status probes to the configured endpoint too.

    The diagnostics tab and the status dashboard build their check lists from
    inline ``http://127.0.0.1:1234/...`` literals, so the redirect has to sit
    below them rather than in their call sites.
    """
    if _state.get("httpx_redirect"):
        return False
    try:
        import httpx
    except Exception:
        return False

    original_request = httpx.Client.request
    original_arequest = httpx.AsyncClient.request

    def patched_request(self, method: str, url: Any, *args: Any, **kwargs: Any):
        return original_request(self, method, _redirect_httpx_url(url), *args, **kwargs)

    async def patched_arequest(self, method: str, url: Any, *args: Any, **kwargs: Any):
        return await original_arequest(
            self, method, _redirect_httpx_url(url), *args, **kwargs
        )

    httpx.Client.request = patched_request
    httpx.AsyncClient.request = patched_arequest
    _state["httpx_redirect"] = True
    return True


def _redirect_httpx_url(url: Any) -> Any:
    if isinstance(url, str):
        return effective_url(url)
    text = str(url)
    redirected = effective_url(text)
    if redirected == text:
        return url
    try:
        return type(url)(redirected)
    except Exception:
        return redirected


# ---------------------------------------------------------------------------
# 3. A visual-effects budget
# ---------------------------------------------------------------------------


def effect_level() -> str:
    """``full``, ``reduced`` or ``off`` - ``reduced`` unless told otherwise."""
    raw = str(os.environ.get("REDSIGHT_UI_EFFECTS") or "").strip().lower()
    if raw in EFFECT_LEVELS:
        return raw
    module = runtime()
    if module is not None:
        try:
            stored = str(module.load_config().get("ui_effects") or "").strip().lower()
            if stored in EFFECT_LEVELS:
                return stored
        except Exception:
            pass
    return "reduced"


def _retime(widget: Any, interval_ms: int) -> None:
    """Re-time a widget's animation timer, or stop it and hide the widget."""
    timer = getattr(widget, "timer", None)
    if timer is None:
        return
    if interval_ms <= 0:
        timer.stop()
        try:
            widget.hide()
        except Exception:
            pass
        return
    timer.setInterval(int(interval_ms))


def install_effect_budget(level: str | None = None) -> dict[str, Any]:
    """Budget the ambient layer and the voice orb repaint cadence.

    Both classes start their own QTimer in ``__init__``, so the interval is
    adjusted straight after construction. At ``off`` the ambient layer is
    stopped and hidden: it is decoration, and it is the single most expensive
    thing on screen because it is translucent and covers the whole window.
    """
    report: dict[str, Any] = {"level": level or effect_level(), "patched": []}
    if _state.get("effect_budget"):
        report["patched"] = list(_state["effect_budget"])
        return report

    ambient_ms, orb_ms = _EFFECT_INTERVALS.get(report["level"], _EFFECT_INTERVALS["reduced"])
    if report["level"] == "full":
        _state["effect_budget"] = []
        return report

    try:
        from app.ui import action_palette_stage110 as s110
    except Exception:
        report["error"] = "app.ui.action_palette_stage110 is not importable"
        return report

    patched: list[str] = []
    for name, interval in (("AmbientSupervisuals", ambient_ms), ("VoiceOrb", orb_ms)):
        cls = getattr(s110, name, None)
        if cls is None or getattr(cls, "_rs115_retimed", False):
            continue

        original_init = cls.__init__

        def make_init(original: Any, interval_ms: int):
            def patched_init(self, *args: Any, **kwargs: Any):
                original(self, *args, **kwargs)
                try:
                    _retime(self, interval_ms)
                except Exception:
                    pass

            return patched_init

        cls.__init__ = make_init(original_init, interval)
        cls._rs115_retimed = True
        patched.append(f"{name}@{interval}ms" if interval > 0 else f"{name}=off")

    report["patched"] = patched
    _state["effect_budget"] = patched
    return report


# ---------------------------------------------------------------------------
# 4. The LM Studio settings tab
# ---------------------------------------------------------------------------


class _EndpointWorker(QThread):
    """Talks to LM Studio off the GUI thread. Reports models or an error."""

    completed = Signal(bool, object)

    def __init__(self, base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_url = base_url

    def run(self) -> None:  # pragma: no cover - exercised through the UI
        url = self._base_url.rstrip("/") + "/models"
        try:
            with _original_urlopen(url, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:
            self.completed.emit(False, f"{type(exc).__name__}: {exc}")
            return
        models = []
        for entry in payload.get("data", []) if isinstance(payload, dict) else []:
            if isinstance(entry, dict) and entry.get("id"):
                models.append(str(entry["id"]))
        self.completed.emit(True, models)


class LmStudioTab(QWidget):
    """Endpoint, model and effects budget, with a real connection test."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _EndpointWorker | None = None

        layout = QVBoxLayout(self)

        intro = QLabel(
            "RedSight's backend reads the endpoint below. The desktop UI's own "
            "status probes are redirected to it as well, so a server on another "
            "port or another machine is reported correctly."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9FAAB6;")
        layout.addWidget(intro)

        form = QFormLayout()

        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setClearButtonEnabled(True)
        self.endpoint_edit.setPlaceholderText("http://127.0.0.1:1234/v1")
        form.addRow("Endpoint", self.endpoint_edit)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        form.addRow("Model", self.model_combo)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setSuffix(" s")
        form.addRow("Request timeout", self.timeout_spin)

        self.effects_combo = QComboBox()
        self.effects_combo.addItem("Reduced - calmer animation (recommended)", "reduced")
        self.effects_combo.addItem("Full - as shipped", "full")
        self.effects_combo.addItem("Off - no ambient animation", "off")
        form.addRow("Visual effects", self.effects_combo)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.detect_button = QPushButton("Detect models")
        self.test_button = QPushButton("Test connection")
        buttons.addWidget(self.detect_button)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#9FAAB6;")
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.detect_button.clicked.connect(lambda: self._probe(detect=True))
        self.test_button.clicked.connect(lambda: self._probe(detect=False))

        self._load()

    # -- state ------------------------------------------------------------

    def _load(self) -> None:
        module = runtime()
        config = {}
        if module is not None:
            try:
                config = module.load_config()
            except Exception:
                config = {}

        self.endpoint_edit.setText(str(config.get("base_url") or configured_base_url()))
        model = str(config.get("model") or configured_model())
        if model:
            self.model_combo.addItem(model)
            self.model_combo.setCurrentText(model)
        self.timeout_spin.setValue(int(config.get("timeout_seconds") or 180))

        level = str(config.get("ui_effects") or effect_level())
        index = self.effects_combo.findData(level)
        self.effects_combo.setCurrentIndex(index if index >= 0 else 0)

        if module is None:
            self.status.setText(
                "RedSight's runtime configuration module is missing, so changes "
                "here cannot be saved. Run 'Repair RedSight setup' from the "
                "Start Menu."
            )
            for widget in (self.endpoint_edit, self.model_combo, self.timeout_spin,
                           self.effects_combo, self.detect_button, self.test_button):
                widget.setEnabled(False)
        else:
            self.status.setText(f"Configuration file: {module.CONFIG_PATH}")

    # -- probing ----------------------------------------------------------

    def _probe(self, detect: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        endpoint = self._normalized_endpoint()
        if not endpoint:
            QMessageBox.warning(self, "LM Studio", "Enter an endpoint first.")
            return

        self.detect_button.setEnabled(False)
        self.test_button.setEnabled(False)
        self.status.setText(f"Contacting {endpoint} ...")

        worker = _EndpointWorker(endpoint, self)
        worker.completed.connect(lambda ok, payload: self._probe_finished(ok, payload, detect))
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _probe_finished(self, ok: bool, payload: object, detect: bool) -> None:
        self._worker = None
        self.detect_button.setEnabled(True)
        self.test_button.setEnabled(True)

        if not ok:
            self.status.setText(f"LM Studio did not answer: {payload}")
            QMessageBox.warning(
                self,
                "LM Studio",
                "LM Studio did not answer.\n\n"
                f"{payload}\n\n"
                "Open LM Studio, switch on its local server under Developer, "
                "then test again.",
            )
            return

        models = [str(item) for item in (payload if isinstance(payload, list) else [])]
        if detect:
            current = self.model_combo.currentText().strip()
            self.model_combo.clear()
            for model in models:
                self.model_combo.addItem(model)
            if current and current in models:
                self.model_combo.setCurrentText(current)
            elif models:
                self.model_combo.setCurrentIndex(0)

        if models:
            self.status.setText(
                f"Connected. {len(models)} model(s) loaded: " + ", ".join(models[:6])
            )
        else:
            self.status.setText(
                "Connected, but LM Studio has no model loaded. Load one in LM "
                "Studio, then choose Detect models."
            )

    def _normalized_endpoint(self) -> str:
        module = runtime()
        text = self.endpoint_edit.text()
        if module is None:
            return str(text or "").strip()
        try:
            return module.normalize_base_url(text)
        except Exception:
            return str(text or "").strip()

    # -- called by the dialog's Save & Apply -------------------------------

    def apply(self) -> None:
        module = runtime()
        if module is None:
            return
        endpoint = self._normalized_endpoint()
        if not endpoint:
            raise RuntimeError("The LM Studio endpoint cannot be empty.")

        path = save_configuration(
            base_url=endpoint,
            model=self.model_combo.currentText().strip(),
            timeout_seconds=int(self.timeout_spin.value()),
            ui_effects=str(self.effects_combo.currentData() or "reduced"),
        )
        self.endpoint_edit.setText(endpoint)
        self.status.setText(
            f"Saved to {path}. Restart RedSight for the backend to pick this up."
        )


def _add_tab(dialog: Any) -> None:
    tab = LmStudioTab(dialog)
    dialog._rs115_lmstudio_tab = tab
    # Sit before Diagnostics, which is conventionally last.
    index = max(dialog.tabs.count() - 1, 0)
    dialog.tabs.insertTab(index, tab, "LM Studio")


def install_settings_tab() -> bool:
    """Add the LM Studio tab to the Advanced Settings dialog. Idempotent."""
    from app.ui import action_palette_stage106 as s106

    cls = s106.AdvancedSettingsDialog
    if getattr(cls, "_rs115_installed", False):
        return False

    original_init = cls.__init__
    original_apply = getattr(cls, "_apply", None)

    def patched_init(self, window, *args: Any, **kwargs: Any):
        original_init(self, window, *args, **kwargs)
        try:
            _add_tab(self)
        except Exception:
            import traceback

            traceback.print_exc()

    def patched_apply(self, *args: Any, **kwargs: Any):
        tab = getattr(self, "_rs115_lmstudio_tab", None)
        if tab is not None:
            try:
                tab.apply()
            except Exception:
                import traceback

                traceback.print_exc()
        if original_apply is not None:
            return original_apply(self, *args, **kwargs)
        return None

    cls.__init__ = patched_init
    if original_apply is not None:
        cls._apply = patched_apply
    cls._rs115_installed = True
    return True


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def install() -> dict[str, Any]:
    """Install every Stage 11.5 fix. Never raises."""
    report: dict[str, Any] = {}

    module = runtime()
    if module is not None:
        try:
            # What matters in a log is the endpoint the process will actually
            # use, not which variables this call happened to be the first to
            # set - the .pth normally sets them all before install() runs, so
            # reporting newly-applied keys reads as an empty list and looks
            # like a failure.
            module.apply_environment()
            report["environment"] = {
                key: os.environ.get(key, "")
                for key in ("LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL", "REDSIGHT_UI_EFFECTS")
            }
        except Exception as exc:
            report["environment_error"] = str(exc)
    else:
        report["environment_error"] = "redsight_bootstrap is not importable"

    for name, action in (
        ("gpu_sampling", install_gpu_sampling),
        ("lm_probe", install_lm_probe),
        ("httpx_redirect", install_httpx_redirect),
        ("effect_budget", install_effect_budget),
        ("settings_tab", install_settings_tab),
    ):
        try:
            report[name] = action()
        except Exception as exc:
            report[name] = f"{type(exc).__name__}: {exc}"

    report["endpoint"] = configured_base_url()
    report["model"] = configured_model()
    return report
