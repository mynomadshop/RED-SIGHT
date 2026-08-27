

# REDSIGHT_STAGE115_MODEL_RESOLUTION
# ---------------------------------------------------------------------------
# RedSight Stage 11.5 - make a chat request name a model LM Studio actually has,
# and keep a native install off the container-only hostname.
#
# Two shipped behaviours make a local LM Studio unreachable from the desktop UI:
#
#   * LmStudioConfig.base_url defaults to http://host.docker.internal:1234/v1,
#     which resolves only inside a container. A native install has no such host,
#     so every request fails while the Settings dialog's own connection test -
#     which probes the endpoint directly - still passes.
#
#   * /api/v1/chat passes no model, so chat() sends the literal id "default".
#     settings.lmstudio.model_id is never consulted. LM Studio answers 404 for a
#     model it has not got, so the query never reaches the loaded model.
#
# Both are corrected here by wrapping the provider after the class is defined,
# so nothing above this line changes. Appended by installer/app-overlay.
# ---------------------------------------------------------------------------

_RS115_NON_CHAT_MARKERS = (
    "embed", "bge-", "gte-", "e5-", "minilm", "nomic-embed", "rerank", "clip",
)
_RS115_CONTAINER_HOSTS = ("host.docker.internal", "//qdrant", "//redsight")


def _rs115_stored_base_url():
    """The endpoint setup recorded for this machine, or an empty string.

    redsight_bootstrap is written into each RedSight virtualenv by setup. Its
    absence means this is not a RedSight desktop install - a container, say -
    and nothing should be rewritten.
    """
    try:
        import redsight_bootstrap

        return redsight_bootstrap.base_url()
    except Exception:
        return ""


def _rs115_preferred_base_url(current):
    """Replace a container-only endpoint with the recorded local one."""
    text = str(current or "")
    lowered = text.lower()
    if not any(host in lowered for host in _RS115_CONTAINER_HOSTS):
        return text
    stored = _rs115_stored_base_url()
    if not stored:
        return text
    return stored


def _rs115_install_provider_fixes():
    import os as _os

    provider = LmStudioProvider
    if getattr(provider, "_redsight_stage115_installed", False):
        return

    original_init = provider.__init__
    original_chat = provider.chat

    def __init__(self, base_url=None, timeout=None):
        original_init(self, base_url=base_url, timeout=timeout)
        self._redsight_resolved_model = ""
        # An explicit base_url from the caller is always honoured; only the
        # settings default is corrected.
        if not base_url:
            corrected = _rs115_preferred_base_url(self.base_url)
            if corrected and corrected != self.base_url:
                logger.info(
                    "RedSight: LM Studio endpoint %s is container-only; using %s",
                    self.base_url,
                    corrected,
                )
                self.base_url = corrected
                self._client = None

    async def _resolve_model_id(self):
        """The model id a chat request should carry.

        Configured value first, then whatever LM Studio reports as loaded, and
        only then the shipped "default" so behaviour never gets worse than
        before this patch.
        """
        cached = getattr(self, "_redsight_resolved_model", "")
        if cached:
            return cached

        configured = ""
        try:
            configured = str(get_settings().lmstudio.model_id or "").strip()
        except Exception:
            configured = ""
        if not configured:
            configured = str(_os.environ.get("LM_STUDIO_MODEL") or "").strip()

        if not configured:
            try:
                models = await self.list_models()
            except Exception:
                models = []
            for info in models:
                name = str(getattr(info, "model_id", "") or "")
                lowered = name.lower()
                if any(marker in lowered for marker in _RS115_NON_CHAT_MARKERS):
                    continue
                configured = name
                break
            if not configured and models:
                configured = str(getattr(models[0], "model_id", "") or "")

        if configured:
            self._redsight_resolved_model = configured
            return configured
        return "default"

    async def chat(
        self,
        messages,
        model_id=None,
        stream=False,
        temperature=0.7,
        max_tokens=None,
        tools=None,
        **kwargs,
    ):
        if not model_id:
            model_id = await self._resolve_model_id()
        return await original_chat(
            self,
            messages,
            model_id=model_id,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            **kwargs,
        )

    provider.__init__ = __init__
    provider._resolve_model_id = _resolve_model_id
    provider.chat = chat
    provider._redsight_stage115_installed = True


try:
    _rs115_install_provider_fixes()
except Exception:  # pragma: no cover - a patch failure must not break imports
    import traceback

    traceback.print_exc()
