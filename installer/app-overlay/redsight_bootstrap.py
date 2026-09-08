"""RedSight Stage 11.5 - runtime configuration bootstrap.

Why this module exists
----------------------
RedSight's backend reads its LM Studio endpoint through
``app/config/settings.py``. That ``Settings`` class uses ``env_prefix``
``RED_SIGHT_``, and nothing in the application calls ``load_dotenv``, so a
plain ``LM_STUDIO_BASE_URL=...`` line in ``.env`` never reaches it. Only
``LmStudioConfig``'s own ``mode="before"`` validator looks at that name, and it
reads it from the real process environment. With nothing there the field keeps
its shipped default, ``http://host.docker.internal:1234/v1``, which resolves
only inside a container - so a native install talks to a host that does not
exist, while the Settings dialog's own connection test, which probes the
endpoint directly, still reports success.

This module is the single place that turns the stored endpoint into the process
environment the backend actually reads. Setup copies it into each virtualenv's
``site-packages`` next to a ``redsight_bootstrap.pth`` holding
``import redsight_bootstrap``, so every Python process started from those
environments is configured before any application code runs - the launcher, a
hand-run ``scripts/start.py``, or the actions gateway alike.

Stored configuration
--------------------
``%LOCALAPPDATA%\\RedSight\\settings\\lmstudio.json``::

    {
      "version": 1,
      "base_url": "http://127.0.0.1:1234/v1",
      "model": "qwen/qwen3-8b",
      "timeout_seconds": 180,
      "auto_start": true,
      "data_root": "C:\\\\Users\\\\me\\\\RedSight\\\\data",
      "runtime_mode": "native",
      "ui_effects": "reduced"
    }

Only standard library imports are used: this runs at interpreter startup, before
site-packages is fully usable, and it must never be able to stop Python.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import secrets
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict

__all__ = [
    "CONFIG_PATH",
    "DEFAULT_BASE_URL",
    "PROVIDER_CONFIG_PATH",
    "PROVIDER_SECRETS_PATH",
    "LOCAL_API_TOKEN_PATH",
    "apply_environment",
    "base_url",
    "load_config",
    "model_id",
    "normalize_base_url",
    "provider_environment",
    "root_url",
    "save_config",
]

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_TIMEOUT = 180

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_VERSION_TAIL_RE = re.compile(r"/v\d+$")


def _local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


CONFIG_PATH = _local_app_data() / "RedSight" / "settings" / "lmstudio.json"
PROVIDER_CONFIG_PATH = CONFIG_PATH.with_name("provider.json")
PROVIDER_SECRETS_PATH = CONFIG_PATH.with_name("provider-secrets.json")
LOCAL_API_TOKEN_PATH = _local_app_data() / "RedSight" / "private" / "api-token"

_PROVIDERS = {
    "none", "lmstudio", "openai", "anthropic", "gemini", "xai",
    "openrouter", "groq", "mistral", "together", "deepseek", "cerebras", "custom",
}
_PROVIDER_KEY_ENV = {
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


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte)))


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), pointer), buffer


def _read_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _unprotect_secret(value: str) -> str:
    """Read a CurrentUser DPAPI value without ever making startup fail."""
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
    except Exception:
        return ""


def provider_environment(
    config_path: Path | str | None = None,
    secrets_path: Path | str | None = None,
) -> Dict[str, str]:
    """Translate the Settings provider files into backend environment values.

    No provider file means legacy local-first behaviour. An explicit ``none``
    means the UI should open unconfigured and chat should direct the user back
    to Settings instead of silently trying a local or cloud service.
    """
    config_target = Path(config_path) if config_path else PROVIDER_CONFIG_PATH
    if not config_target.is_file():
        return {}
    stored = _read_object(config_target)
    active = str(stored.get("active_provider") or "none").strip().lower()
    if active not in _PROVIDERS:
        active = "none"

    models = stored.get("models")
    model = str(models.get(active) or "").strip() if isinstance(models, dict) else ""
    result = {
        "REDSIGHT_ACTIVE_PROVIDER": active,
        "REDSIGHT_PROVIDER_MODEL": model,
    }
    if active not in _PROVIDER_KEY_ENV:
        return result

    result["RED_SIGHT_PLATFORM__MODE"] = "cloud_allowed"
    result["RED_SIGHT_ROUTING__CLOUD_FALLBACK"] = "true"
    secret_target = Path(secrets_path) if secrets_path else PROVIDER_SECRETS_PATH
    encrypted = _read_object(secret_target).get(active)
    secret = _unprotect_secret(str(encrypted or ""))
    if secret:
        result[_PROVIDER_KEY_ENV[active]] = secret
    stored_urls = stored.get("base_urls")
    configured_url = ""
    if isinstance(stored_urls, dict):
        configured_url = str(stored_urls.get(active) or "").strip().rstrip("/")
    if active == "custom" and not configured_url:
        configured_url = str(stored.get("custom_base_url") or "").strip().rstrip("/")
    if configured_url:
        result[f"REDSIGHT_{active.upper()}_BASE_URL"] = configured_url
        if active == "custom":
            result["REDSIGHT_CUSTOM_BASE_URL"] = configured_url
    return result


def local_api_token(path: Path | str | None = None) -> str:
    """Return the shared per-user token used by both local FastAPI services."""
    explicit = str(os.environ.get("REDSIGHT_LOCAL_API_TOKEN") or "").strip()
    if explicit:
        return explicit
    target = Path(path) if path else LOCAL_API_TOKEN_PATH
    try:
        value = target.read_text(encoding="utf-8").strip()
        if value:
            return value
    except Exception:
        pass
    value = secrets.token_urlsafe(32)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value + "\n")
    except FileExistsError:
        value = ""
        for _ in range(20):
            try:
                value = target.read_text(encoding="utf-8").strip()
            except OSError:
                value = ""
            if value:
                break
            time.sleep(0.05)
        if not value:
            raise RuntimeError("The local API token file exists but is empty")
    return value


def normalize_base_url(value: Any) -> str:
    """Turn whatever was typed into an OpenAI-compatible base URL.

    Accepts ``127.0.0.1:1234``, ``http://host:1234``, ``.../v1``,
    ``.../v1/models`` and ``.../v1/chat/completions``.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if not _SCHEME_RE.match(text):
        text = "http://" + text
    text = text.rstrip("/")
    for tail in ("/chat/completions", "/models"):
        if text.endswith(tail):
            text = text[: -len(tail)]
    text = text.rstrip("/")
    if not _VERSION_TAIL_RE.search(text):
        text = text + "/v1"
    return text


def _defaults() -> Dict[str, Any]:
    return {
        "version": 1,
        "base_url": DEFAULT_BASE_URL,
        "model": "",
        "timeout_seconds": DEFAULT_TIMEOUT,
        "auto_start": True,
        "data_root": "",
        "runtime_mode": "",
        "ui_effects": "reduced",
    }


def load_config(path: Path | str | None = None) -> Dict[str, Any]:
    """The stored settings, with every key present and the URL normalised."""
    target = Path(path) if path else CONFIG_PATH
    config = _defaults()
    try:
        # utf-8-sig so a byte order mark written by a Windows editor cannot
        # make the whole file unreadable.
        raw = target.read_text(encoding="utf-8-sig")
        stored = json.loads(raw)
        if isinstance(stored, dict):
            for key in ("base_url", "model", "timeout_seconds", "auto_start",
                        "data_root", "runtime_mode", "ui_effects"):
                if stored.get(key) is not None:
                    config[key] = stored[key]
    except Exception:
        # A missing or unreadable file means "use the defaults", never a crash.
        pass

    config["base_url"] = normalize_base_url(config["base_url"]) or DEFAULT_BASE_URL
    config["model"] = str(config["model"] or "")
    try:
        config["timeout_seconds"] = int(config["timeout_seconds"])
    except Exception:
        config["timeout_seconds"] = DEFAULT_TIMEOUT
    config["auto_start"] = bool(config["auto_start"])
    config["data_root"] = str(config["data_root"] or "")
    config["runtime_mode"] = str(config["runtime_mode"] or "")
    effects = str(config["ui_effects"] or "").strip().lower()
    config["ui_effects"] = effects if effects in ("full", "reduced", "off") else "reduced"
    return config


def save_config(config: Dict[str, Any], path: Path | str | None = None) -> Path:
    """Write the settings back, atomically and without a byte order mark."""
    target = Path(path) if path else CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    merged = load_config(target)
    for key, value in (config or {}).items():
        if key in merged:
            merged[key] = value
    merged["version"] = 1
    merged["base_url"] = normalize_base_url(merged["base_url"]) or DEFAULT_BASE_URL

    body = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(body, encoding="utf-8")
    os.replace(str(temp), str(target))
    return target


def base_url(path: Path | str | None = None) -> str:
    """The OpenAI-compatible base URL, e.g. ``http://127.0.0.1:1234/v1``."""
    return load_config(path)["base_url"]


def root_url(path: Path | str | None = None) -> str:
    """The server root without the version segment, for ``LM_STUDIO_URL``."""
    return _VERSION_TAIL_RE.sub("", base_url(path)).rstrip("/")


def model_id(path: Path | str | None = None) -> str:
    """The model a chat request should name, or an empty string if unknown."""
    return load_config(path)["model"]


def environment(path: Path | str | None = None) -> Dict[str, str]:
    """The variables the RedSight processes need, without applying them.

    ``LM_STUDIO_BASE_URL`` is the name the backend's settings validator reads.
    ``LM_STUDIO_URL`` and ``LM_BASE_URL`` are the historical names the desktop
    launchers and the actions gateway use. The ``RED_SIGHT_LMSTUDIO__*`` names
    are what pydantic-settings resolves natively through its own prefix and
    nested delimiter, so the endpoint still lands even if that validator
    changes.
    """
    config = load_config(path)
    url = config["base_url"]
    vars_: Dict[str, str] = {
        "LM_STUDIO_BASE_URL": url,
        "LM_BASE_URL": url,
        "LM_STUDIO_URL": _VERSION_TAIL_RE.sub("", url).rstrip("/"),
        "LM_STUDIO_TIMEOUT": str(config["timeout_seconds"]),
        "RED_SIGHT_LMSTUDIO__BASE_URL": url,
        "RED_SIGHT_LMSTUDIO__TIMEOUT_SECONDS": str(config["timeout_seconds"]),
        "REDSIGHT_LOCAL_API_TOKEN": local_api_token(),
    }
    if config["model"]:
        vars_["LM_STUDIO_MODEL"] = config["model"]
        vars_["RED_SIGHT_LMSTUDIO__MODEL_ID"] = config["model"]
    if config["data_root"]:
        vars_["RED_SIGHT_PLATFORM__DATA_ROOT"] = config["data_root"]
    vars_["REDSIGHT_UI_EFFECTS"] = config["ui_effects"]
    # The desktop UI's own status probes are hardcoded to 127.0.0.1:1234; this
    # is the value they are redirected to when the endpoint differs.
    vars_["LM_STUDIO_MODELS_URL"] = url + "/models"

    if config["runtime_mode"] == "native":
        # No Qdrant server runs natively. Saying so up front skips a DNS lookup
        # for the container hostname "qdrant" and the connection attempt that
        # follows it, which is pure startup latency before the store falls back
        # to its embedded mode anyway.
        vars_["VECTOR_BACKEND_EMBEDDED"] = "true"
        vars_["VECTOR_BACKEND_HOST"] = "127.0.0.1"
        vars_.setdefault("VECTOR_BACKEND_URL", "")
    vars_.update(provider_environment())
    return vars_


def apply_environment(path: Path | str | None = None, override: bool = False) -> Dict[str, str]:
    """Put the stored settings into ``os.environ``.

    Existing values win by default: an explicit variable set by a launcher or
    by docker-compose is a deliberate override and must not be undone here.
    """
    applied: Dict[str, str] = {}
    try:
        for key, value in environment(path).items():
            if override or not os.environ.get(key):
                os.environ[key] = value
                applied[key] = value
    except Exception:
        # Never let configuration stop the interpreter from starting.
        return applied
    return applied


# Importing this module is what configures the process. Guarded so a corrupt
# configuration file can never make Python itself fail to start.
try:
    apply_environment()
except Exception:
    pass
