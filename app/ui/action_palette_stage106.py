r"""RedSight Stage 10.6 - durable, provider-optional desktop settings.

This module is the base Settings surface extended by the Stage 11.4 MCP and
Stage 11.5 LM Studio overlays.  It deliberately treats "not configured" as a
valid state: the Command Center must open before a user has an API key or a
running local model server.

Provider metadata is stored in ``%LOCALAPPDATA%\RedSight\settings`` using the
same schema as ``RedSight-Provision.ps1``.  Secrets are encrypted with Windows
DPAPI for the current user and are never written to the repository, shown back
in the UI, or placed on a command line.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


SETTINGS_DIR = _local_app_data() / "RedSight" / "settings"
PROVIDER_CONFIG = SETTINGS_DIR / "provider.json"
PROVIDER_SECRETS = SETTINGS_DIR / "provider-secrets.json"
RUNTIME_CONFIG = SETTINGS_DIR / "lmstudio.json"
LOG_DIR = _local_app_data() / "RedSight" / "logs"

PROVIDER_LABELS: tuple[tuple[str, str], ...] = (
    ("Not configured", "none"),
    ("LM Studio (local)", "lmstudio"),
    ("OpenAI", "openai"),
    ("Anthropic Claude", "anthropic"),
    ("Google Gemini", "gemini"),
    ("Grok (xAI)", "xai"),
    ("OpenRouter", "openrouter"),
    ("Groq", "groq"),
    ("Mistral AI", "mistral"),
    ("Together AI", "together"),
    ("DeepSeek", "deepseek"),
    ("Cerebras", "cerebras"),
    ("Custom OpenAI-compatible", "custom"),
)
PROVIDERS = tuple(slug for _, slug in PROVIDER_LABELS)
PROVIDER_DEFAULT_MODELS = {
    "none": "",
    "lmstudio": "",
    "openai": "gpt-5.6-terra",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-3.8-flash",
    "xai": "grok-4.6",
    "openrouter": "openai/gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-small-latest",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "deepseek": "deepseek-chat",
    "cerebras": "llama-3.3-70b",
    "custom": "",
}
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "xai": "https://api.x.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "deepseek": "https://api.deepseek.com",
    "cerebras": "https://api.cerebras.ai/v1",
    "custom": "",
}
PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "custom": "REDSIGHT_CUSTOM_API_KEY",
}


def _atomic_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def _normalise_url(value: str, label: str) -> str:
    candidate = str(value or "").strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be a complete http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain a username or password.")
    return candidate


def provider_defaults() -> dict[str, Any]:
    return {
        "version": 2,
        "active_provider": "none",
        "models": dict(PROVIDER_DEFAULT_MODELS),
        "base_urls": dict(PROVIDER_BASE_URLS),
        "custom_base_url": "",
    }


def load_provider_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load provider metadata; missing/corrupt state is safely unconfigured."""
    target = Path(path) if path else PROVIDER_CONFIG
    result = provider_defaults()
    stored = _read_json(target)

    active = str(stored.get("active_provider") or "none").strip().lower()
    result["active_provider"] = active if active in PROVIDERS else "none"

    models = stored.get("models")
    if isinstance(models, dict):
        for provider in PROVIDERS:
            if models.get(provider) is not None:
                result["models"][provider] = str(models[provider]).strip()

    stored_urls = stored.get("base_urls")
    if isinstance(stored_urls, dict):
        for provider in PROVIDER_BASE_URLS:
            candidate = str(stored_urls.get(provider) or "").strip()
            if candidate:
                try:
                    result["base_urls"][provider] = _normalise_url(
                        candidate, f"{provider} provider URL"
                    )
                except ValueError:
                    pass
    # v1 compatibility: the custom URL lived at the top level.
    legacy_custom = str(stored.get("custom_base_url") or "").strip()
    if legacy_custom:
        try:
            result["base_urls"]["custom"] = _normalise_url(
                legacy_custom, "Custom provider URL"
            )
        except ValueError:
            pass
    result["custom_base_url"] = result["base_urls"].get("custom", "")
    return result


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte)))


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), pointer), buffer


def protect_secret(value: str) -> str:
    """Encrypt a secret with CurrentUser DPAPI and return base64 ciphertext."""
    if os.name != "nt":
        raise RuntimeError("API keys can only be stored by this Windows build using DPAPI.")
    raw = str(value).encode("utf-8")
    incoming, keepalive = _blob(raw)
    outgoing = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = (
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    )
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptProtectData(
        ctypes.byref(incoming), None, None, None, None, 0x01, ctypes.byref(outgoing)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(outgoing.pbData, outgoing.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        del keepalive
        kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def unprotect_secret(value: str) -> str:
    """Decrypt CurrentUser DPAPI ciphertext. Invalid state returns no secret."""
    if os.name != "nt" or not value:
        return ""
    try:
        raw = base64.b64decode(value, validate=True)
        incoming, keepalive = _blob(raw)
        outgoing = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptUnprotectData.argtypes = (
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        )
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        if not crypt32.CryptUnprotectData(
            ctypes.byref(incoming), None, None, None, None, 0x01, ctypes.byref(outgoing)
        ):
            return ""
        try:
            return ctypes.string_at(outgoing.pbData, outgoing.cbData).decode("utf-8")
        finally:
            del keepalive
            kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))
    except (ValueError, OSError, UnicodeError):
        return ""


def load_secret_store(path: Path | str | None = None) -> dict[str, str]:
    target = Path(path) if path else PROVIDER_SECRETS
    stored = _read_json(target)
    return {
        str(key): str(value)
        for key, value in stored.items()
        if str(key) in PROVIDERS and isinstance(value, str) and value
    }


def configured_secret(provider: str, path: Path | str | None = None) -> str:
    return unprotect_secret(load_secret_store(path).get(str(provider), ""))


def has_stored_secret(provider: str, path: Path | str | None = None) -> bool:
    return bool(load_secret_store(path).get(str(provider)))


def save_provider_config(
    config: dict[str, Any],
    *,
    api_key: str | None = None,
    clear_secret: bool = False,
    config_path: Path | str | None = None,
    secrets_path: Path | str | None = None,
) -> Path:
    """Persist provider metadata and optionally replace/remove one secret.

    ``api_key=None`` means keep the existing key.  An explicit
    ``clear_secret=True`` removes it.  That distinction prevents opening and
    saving Settings from accidentally erasing a working credential.
    """
    target = Path(config_path) if config_path else PROVIDER_CONFIG
    secret_target = Path(secrets_path) if secrets_path else PROVIDER_SECRETS
    normalised = provider_defaults()

    active = str(config.get("active_provider") or "none").strip().lower()
    if active not in PROVIDERS:
        raise ValueError(f"Unknown AI provider: {active}")
    normalised["active_provider"] = active

    supplied_models = config.get("models")
    if isinstance(supplied_models, dict):
        for provider in PROVIDERS:
            if supplied_models.get(provider) is not None:
                normalised["models"][provider] = str(supplied_models[provider]).strip()

    supplied_urls = config.get("base_urls")
    if isinstance(supplied_urls, dict):
        for provider in PROVIDER_BASE_URLS:
            candidate = str(supplied_urls.get(provider) or "").strip()
            if candidate:
                normalised["base_urls"][provider] = _normalise_url(
                    candidate, f"{provider} provider URL"
                )
    custom = str(
        normalised["base_urls"].get("custom")
        or config.get("custom_base_url")
        or ""
    ).strip()
    if active == "custom" or custom:
        custom = _normalise_url(custom, "Custom provider URL")
    normalised["base_urls"]["custom"] = custom
    normalised["custom_base_url"] = custom
    _atomic_json(target, normalised)

    if clear_secret or (api_key is not None and api_key.strip()):
        store = load_secret_store(secret_target)
        if clear_secret:
            store.pop(active, None)
        else:
            store[active] = protect_secret(api_key.strip())
        _atomic_json(secret_target, store)

    return target


def load_runtime_config(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path else RUNTIME_CONFIG
    stored = _read_json(target)
    return {
        "version": 1,
        "data_root": str(stored.get("data_root") or ""),
        "runtime_mode": str(stored.get("runtime_mode") or "").lower(),
        "auto_start": bool(stored.get("auto_start", True)),
    }


def save_runtime_config(
    updates: dict[str, Any], path: Path | str | None = None
) -> Path:
    """Update runtime fields while preserving the Stage 11.5 LM settings."""
    target = Path(path) if path else RUNTIME_CONFIG
    payload = _read_json(target)
    if not payload:
        payload = {
            "version": 1,
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "",
            "timeout_seconds": 180,
            "ui_effects": "reduced",
        }
    for key in ("data_root", "runtime_mode", "auto_start"):
        if key in updates:
            payload[key] = updates[key]
    payload["version"] = 1
    return _atomic_json(target, payload)


def apply_provider_environment(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Mirror a saved provider choice into this process without requiring it."""
    current = config or load_provider_config()
    active = str(current.get("active_provider") or "none")
    model = str(current.get("models", {}).get(active) or "")
    applied = {
        "REDSIGHT_ACTIVE_PROVIDER": active,
        "REDSIGHT_PROVIDER_MODEL": model,
    }
    if active in PROVIDER_KEY_ENV:
        applied["RED_SIGHT_PLATFORM__MODE"] = "cloud_allowed"
        applied["RED_SIGHT_ROUTING__CLOUD_FALLBACK"] = "true"
        key = configured_secret(active)
        if key:
            applied[PROVIDER_KEY_ENV[active]] = key
    base_url = str(current.get("base_urls", {}).get(active) or "").strip()
    if base_url:
        applied[f"REDSIGHT_{active.upper()}_BASE_URL"] = base_url
        if active == "custom":
            applied["REDSIGHT_CUSTOM_BASE_URL"] = base_url
    for key, value in applied.items():
        os.environ[key] = value
    return applied


def _lm_endpoint() -> str:
    raw = _read_json(RUNTIME_CONFIG)
    return str(raw.get("base_url") or "http://127.0.0.1:1234/v1").rstrip("/")


def _probe_url(provider: str, configured_base_url: str) -> str:
    if provider == "lmstudio":
        base = _lm_endpoint()
    elif configured_base_url:
        base = _normalise_url(configured_base_url, f"{provider} provider URL")
    else:
        base = PROVIDER_BASE_URLS[provider]
    return base.rstrip("/") + "/models"


def probe_provider(
    provider: str,
    api_key: str = "",
    custom_base_url: str = "",
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Perform a bounded, read-only provider connection test."""
    if provider == "none":
        return False, "No provider is selected. RedSight can still open and be configured later."
    if provider not in PROVIDERS:
        return False, "Unknown provider."
    if provider in PROVIDER_KEY_ENV and provider != "custom" and not api_key:
        return False, "No API key is configured for this provider."

    headers = {"Accept": "application/json", "User-Agent": "RedSight/11.6"}
    if provider not in {"anthropic", "gemini", "none", "lmstudio"} and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif provider == "gemini":
        headers["x-goog-api-key"] = api_key

    try:
        request = urllib.request.Request(
            _probe_url(provider, custom_base_url), headers=headers, method="GET"
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
        entries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entries, list) and isinstance(payload, dict):
            entries = payload.get("models")
        count = len(entries) if isinstance(entries, list) else 0
        return True, f"Connected successfully; {count} model(s) reported."
    except urllib.error.HTTPError as exc:
        return False, f"Provider returned HTTP {exc.code}. Check the key and selected endpoint."
    except Exception as exc:
        return False, f"Connection failed: {type(exc).__name__}: {exc}"


class _ProviderProbe(QThread):
    completed = Signal(bool, str)

    def __init__(
        self,
        provider: str,
        api_key: str,
        custom_base_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.api_key = api_key
        self.custom_base_url = custom_base_url

    def run(self) -> None:  # pragma: no cover - exercised through the desktop
        self.completed.emit(
            *probe_provider(self.provider, self.api_key, self.custom_base_url)
        )


class ProviderSettingsTab(QWidget):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._worker: _ProviderProbe | None = None
        self._config = load_provider_config()
        self._models = dict(self._config["models"])
        self._base_urls = dict(self._config["base_urls"])
        self._current_provider = "none"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("AI provider")
        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        intro = QLabel(
            "RedSight does not require a provider to open. Select one here when "
            "you are ready; cloud credentials are encrypted for your Windows "
            "account, and LM Studio needs no API key."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#AAB4BF;")
        layout.addWidget(intro)

        form = QFormLayout()
        self.provider_combo = QComboBox()
        for label, slug in PROVIDER_LABELS:
            self.provider_combo.addItem(label, slug)
        form.addRow("Provider", self.provider_combo)

        self.model_edit = QLineEdit()
        self.model_edit.setClearButtonEnabled(True)
        self.model_edit.setPlaceholderText("Provider default")
        form.addRow("Model", self.model_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setClearButtonEnabled(True)
        form.addRow("API key", self.key_edit)

        self.custom_url_edit = QLineEdit()
        self.custom_url_edit.setClearButtonEnabled(True)
        self.custom_url_edit.setPlaceholderText("https://provider.example/v1")
        form.addRow("Base URL", self.custom_url_edit)
        layout.addLayout(form)

        self.remove_key = QCheckBox("Remove the saved key for this provider")
        layout.addWidget(self.remove_key)

        actions = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#9FAAB6;")
        layout.addWidget(self.status)
        layout.addStretch(1)

        selected = self.provider_combo.findData(self._config["active_provider"])
        self.provider_combo.setCurrentIndex(selected if selected >= 0 else 0)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.test_button.clicked.connect(self._test_connection)
        self.remove_key.toggled.connect(self._remove_toggled)
        self._provider_changed()

    def _provider_changed(self, *_args: Any) -> None:
        previous = self._current_provider
        if previous in self._models:
            self._models[previous] = self.model_edit.text().strip()
        if previous in self._base_urls:
            self._base_urls[previous] = self.custom_url_edit.text().strip()

        provider = str(self.provider_combo.currentData() or "none")
        self._current_provider = provider
        self.model_edit.setText(self._models.get(provider, ""))
        self.custom_url_edit.setText(self._base_urls.get(provider, ""))
        supports_key = provider not in {"none", "lmstudio"}
        requires_key = provider in PROVIDER_KEY_ENV and provider != "custom"
        configured = has_stored_secret(provider)

        self.model_edit.setEnabled(provider != "none")
        self.key_edit.setEnabled(supports_key)
        self.remove_key.setEnabled(supports_key and configured)
        self.remove_key.setChecked(False)
        self.custom_url_edit.setEnabled(provider in PROVIDER_BASE_URLS)
        self.test_button.setEnabled(provider != "none")
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(
            "Stored securely - leave blank to keep"
            if configured
            else (
                "Enter API key"
                if requires_key
                else ("Optional for this endpoint" if provider == "custom" else "Not required")
            )
        )

        if provider == "none":
            self.status.setText(
                "No provider configured. The Command Center remains available; "
                "chat will ask you to configure a provider."
            )
        elif provider == "lmstudio":
            self.status.setText("Configure its endpoint and loaded model in the LM Studio tab.")
        elif configured:
            self.status.setText("An encrypted key is stored for this provider.")
        elif provider == "custom":
            self.status.setText(
                "An API key is optional for custom endpoints that allow unauthenticated access."
            )
        else:
            self.status.setText("No key is stored yet. You may save now and add it later.")

    def _remove_toggled(self, checked: bool) -> None:
        self.key_edit.setEnabled(not checked and self._current_provider not in {"none", "lmstudio"})

    def _test_connection(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        provider = self._current_provider
        key = self.key_edit.text().strip() or configured_secret(provider)
        custom_url = self.custom_url_edit.text().strip()
        if provider in PROVIDER_BASE_URLS:
            try:
                _normalise_url(custom_url, "Custom provider URL")
            except ValueError as exc:
                QMessageBox.warning(self, "AI provider", str(exc))
                return

        self.test_button.setEnabled(False)
        self.status.setText("Testing the selected provider...")
        worker = _ProviderProbe(provider, key, custom_url, self)
        worker.completed.connect(self._test_finished)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _test_finished(self, ok: bool, message: str) -> None:
        self._worker = None
        self.test_button.setEnabled(self._current_provider != "none")
        colour = "#57D68D" if ok else "#FF8A80"
        self.status.setStyleSheet(f"color:{colour};")
        self.status.setText(message)
        if not ok:
            QMessageBox.warning(self, "AI provider", message)

    def apply(self) -> Path:
        provider = self._current_provider
        self._models[provider] = self.model_edit.text().strip()
        if provider in self._base_urls:
            self._base_urls[provider] = self.custom_url_edit.text().strip()
        config = {
            "active_provider": provider,
            "models": self._models,
            "base_urls": self._base_urls,
            "custom_base_url": self._base_urls.get("custom", ""),
        }
        typed_key = self.key_edit.text().strip()
        path = save_provider_config(
            config,
            api_key=typed_key or None,
            clear_secret=bool(self.remove_key.isChecked()),
        )
        self._config = load_provider_config(path)
        apply_provider_environment(self._config)
        self.key_edit.clear()
        self._provider_changed()
        return path


class RuntimeSettingsTab(QWidget):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        config = load_runtime_config()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Runtime and storage")
        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        intro = QLabel(
            "These values are machine-local. Changes are applied to new RedSight "
            "processes after restart and never modify the source repository."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#AAB4BF;")
        layout.addWidget(intro)

        form = QFormLayout()
        data_row = QHBoxLayout()
        self.data_root_edit = QLineEdit(str(config.get("data_root") or ""))
        self.data_root_edit.setClearButtonEnabled(True)
        self.data_root_edit.setPlaceholderText("Use the installed RedSight data folder")
        self.browse_button = QPushButton("Browse...")
        data_row.addWidget(self.data_root_edit, 1)
        data_row.addWidget(self.browse_button)
        form.addRow("Data directory", data_row)

        self.runtime_combo = QComboBox()
        self.runtime_combo.addItem("Automatic", "")
        self.runtime_combo.addItem("Native (no Docker required)", "native")
        self.runtime_combo.addItem("Container (Docker / WSL2)", "container")
        index = self.runtime_combo.findData(config.get("runtime_mode", ""))
        self.runtime_combo.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Runtime mode", self.runtime_combo)

        self.auto_start = QCheckBox("Allow RedSight to start a detected local model server")
        self.auto_start.setChecked(bool(config.get("auto_start", True)))
        form.addRow("Local server", self.auto_start)
        layout.addLayout(form)

        note = QLabel(
            "Choose Native on a laptop that cannot use Docker/WSL2. Changing modes "
            "does not delete containers, models, memory, or indexed data."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9FAAB6;")
        layout.addWidget(note)
        layout.addStretch(1)

        self.browse_button.clicked.connect(self._browse)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose the RedSight data directory", self.data_root_edit.text()
        )
        if path:
            self.data_root_edit.setText(path)

    def apply(self) -> Path:
        path = self.data_root_edit.text().strip()
        if path:
            target = Path(os.path.expandvars(path)).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".redsight-write-test"
            try:
                probe.write_text("ok", encoding="ascii")
                probe.unlink()
            except OSError as exc:
                raise RuntimeError(f"The data directory is not writable: {target} ({exc})") from exc
            path = str(target)
        return save_runtime_config(
            {
                "data_root": path,
                "runtime_mode": str(self.runtime_combo.currentData() or ""),
                "auto_start": bool(self.auto_start.isChecked()),
            }
        )


class DiagnosticsTab(QWidget):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Configuration diagnostics")
        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)

        actions = QHBoxLayout()
        refresh = QPushButton("Refresh")
        open_settings = QPushButton("Open settings folder")
        open_logs = QPushButton("Open logs folder")
        actions.addWidget(refresh)
        actions.addWidget(open_settings)
        actions.addWidget(open_logs)
        actions.addStretch(1)
        layout.addLayout(actions)

        refresh.clicked.connect(self.refresh)
        open_settings.clicked.connect(lambda: self._open(SETTINGS_DIR))
        open_logs.clicked.connect(lambda: self._open(LOG_DIR))
        self.refresh()

    @staticmethod
    def _open(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def refresh(self) -> None:
        provider = load_provider_config()
        active = provider["active_provider"]
        runtime = load_runtime_config()
        lines = [
            f"Python: {sys.version.split()[0]}",
            f"Settings folder: {SETTINGS_DIR}",
            f"Provider configuration: {'present' if PROVIDER_CONFIG.exists() else 'not created'}",
            f"Active provider: {active}",
            f"Encrypted provider key: {'present' if has_stored_secret(active) else 'not configured'}",
            f"LM Studio configuration: {'present' if RUNTIME_CONFIG.exists() else 'not created'}",
            f"LM Studio endpoint: {_lm_endpoint()}",
            f"Runtime mode: {runtime.get('runtime_mode') or 'automatic'}",
            f"Data directory: {runtime.get('data_root') or 'installer default'}",
            f"Backend API: {os.environ.get('REDSIGHT_API_BASE_URL', 'http://127.0.0.1:8000')}",
            "",
            "No secret values are included in this report.",
        ]
        self.report.setPlainText("\n".join(lines))


class AdvancedSettingsDialog(QDialog):
    """Stable base dialog extended by later Settings overlay modules."""

    def __init__(self, window: QWidget, *args: Any, **kwargs: Any) -> None:
        super().__init__(window, *args, **kwargs)
        self.window = window
        self.setObjectName("RedSightAdvancedSettingsDialog")
        self.setWindowTitle("RedSight Settings")
        self.setMinimumSize(760, 590)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.provider_tab = ProviderSettingsTab(self)
        self.runtime_tab = RuntimeSettingsTab(self)
        self.diagnostics_tab = DiagnosticsTab(self)
        self.tabs.addTab(self.provider_tab, "AI Provider")
        self.tabs.addTab(self.runtime_tab, "Runtime")
        self.tabs.addTab(self.diagnostics_tab, "Diagnostics")
        layout.addWidget(self.tabs, 1)

        hint = QLabel("Saved changes are used immediately by this window and fully applied after restart.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9FAAB6;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is not None:
            save_button.setText("Save & Apply")
            save_button.setObjectName("PrimaryButton")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        try:
            self.provider_tab.apply()
            self.runtime_tab.apply()
            self.diagnostics_tab.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "RedSight Settings", f"Settings were not saved:\n\n{exc}")
            return
        QMessageBox.information(
            self,
            "RedSight Settings",
            "Settings saved. Restart RedSight to apply provider or runtime changes to the backend.",
        )
        self.accept()


def open_settings(window: QWidget) -> int:
    dialog = AdvancedSettingsDialog(window)
    window._redsight_settings_dialog = dialog  # type: ignore[attr-defined]
    try:
        return int(dialog.exec())
    finally:
        window._redsight_settings_dialog = None  # type: ignore[attr-defined]


def attach_settings(window: QWidget) -> QAction:
    """Place a visible Settings action at the right of the top toolbar."""
    existing = getattr(window, "_redsight_settings_action", None)
    if existing is not None:
        return existing

    toolbar = window.findChild(QToolBar, "RedSightBrandToolbar")
    if toolbar is None:
        toolbar = QToolBar("RedSight Controls", window)
        toolbar.setObjectName("RedSightSettingsToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    spacer = QWidget(toolbar)
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    toolbar.addWidget(spacer)

    action = QAction("⚙  Settings", window)
    action.setObjectName("RedSightSettingsAction")
    action.setShortcut("Ctrl+,")
    action.setToolTip("Configure AI providers, LM Studio, MCP servers and RedSight runtime")
    action.triggered.connect(lambda _checked=False: open_settings(window))
    toolbar.addAction(action)
    window.addAction(action)

    window._redsight_settings_action = action  # type: ignore[attr-defined]
    window._redsight_settings_toolbar = toolbar  # type: ignore[attr-defined]
    return action


def _patch_window_class(cls: type[Any]) -> bool:
    if getattr(cls, "_redsight_stage106_installed", False):
        return False
    original_init = cls.__init__

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        # The Stage 10.2 branding toolbar is attached after construction. Queue
        # this so Settings joins that toolbar rather than creating a duplicate.
        QTimer.singleShot(0, lambda: attach_settings(self))

    cls.__init__ = patched_init
    cls._redsight_stage106_installed = True
    return True


def install() -> dict[str, Any]:
    """Install Settings on both maintained Command Center window classes."""
    patched: list[str] = []
    config = load_provider_config()
    apply_provider_environment(config)
    from app.ui.command_center import CommandCenterMainWindow

    if _patch_window_class(CommandCenterMainWindow):
        patched.append("CommandCenterMainWindow")
    try:
        from app.ui.stable_command_center import StableCommandCenterMainWindow

        if _patch_window_class(StableCommandCenterMainWindow):
            patched.append("StableCommandCenterMainWindow")
    except Exception:
        pass
    return {
        "patched": patched,
        "provider": config["active_provider"],
        "configured": PROVIDER_CONFIG.exists(),
    }


__all__ = [
    "PROVIDER_CONFIG",
    "PROVIDER_SECRETS",
    "RUNTIME_CONFIG",
    "SETTINGS_DIR",
    "AdvancedSettingsDialog",
    "ProviderSettingsTab",
    "apply_provider_environment",
    "attach_settings",
    "configured_secret",
    "has_stored_secret",
    "install",
    "load_provider_config",
    "load_runtime_config",
    "open_settings",
    "probe_provider",
    "protect_secret",
    "save_provider_config",
    "save_runtime_config",
    "unprotect_secret",
]
