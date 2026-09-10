"""Reload the active encrypted desktop provider without restarting services."""

from __future__ import annotations

from pathlib import Path

from app.models.cloud_providers import (
    AnthropicProvider,
    CustomOpenAIProvider,
    GoogleGeminiProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    XAIProvider,
)

COMPATIBLE_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "deepseek": "https://api.deepseek.com",
    "cerebras": "https://api.cerebras.ai/v1",
}


def provider_from_environment(values: dict[str, str]):
    active = values.get("REDSIGHT_ACTIVE_PROVIDER", "none")
    model = values.get("REDSIGHT_PROVIDER_MODEL", "")
    if active in {"none", "lmstudio"}:
        return None, model or None, active
    key_name = "GOOGLE_API_KEY" if active == "gemini" else f"{active.upper()}_API_KEY"
    if active == "custom":
        key_name = "REDSIGHT_CUSTOM_API_KEY"
    key = values.get(key_name, "")
    if not key and active != "custom":
        return None, model or None, active
    url = values.get(f"REDSIGHT_{active.upper()}_BASE_URL", "")
    native = {"openai": OpenAIProvider, "anthropic": AnthropicProvider,
              "gemini": GoogleGeminiProvider, "xai": XAIProvider}
    if active in native:
        provider = native[active](api_key=key, model_id=model, base_url=url or None)
    elif active == "custom":
        if not url or not model:
            return None, model or None, active
        provider = CustomOpenAIProvider(api_key=key, model_id=model, base_url=url)
    elif active in COMPATIBLE_ENDPOINTS:
        if not model:
            return None, None, active
        provider = OpenAICompatibleProvider(provider=active, api_key=key, model_id=model,
                                            base_url=url or COMPATIBLE_ENDPOINTS[active])
    else:
        return None, model or None, active
    return provider, model or None, active


class SavedProviderSelection:
    def __init__(self):
        self.fingerprint = None
        self.selected = None
        self.providers = []

    def get(self):
        try:
            import redsight_bootstrap as bootstrap
        except ImportError:
            return None  # Source-only/Docker installs keep environment configuration.
        config = Path(bootstrap.PROVIDER_CONFIG_PATH)
        if not config.is_file():
            return None
        paths = (config, Path(bootstrap.PROVIDER_SECRETS_PATH))
        fingerprint = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                            if path.exists() else (str(path), 0, 0) for path in paths)
        if fingerprint != self.fingerprint:
            try:
                selected = provider_from_environment(bootstrap.provider_environment())
            except (ValueError, TypeError):
                selected = (None, None, "invalid configuration")
            self.selected = selected
            self.fingerprint = fingerprint
            if selected[0] is not None:
                # Keep in-flight requests alive when users change providers.
                self.providers.append(selected[0])
        return self.selected

    async def close(self):
        for provider in self.providers:
            await provider.close()
        self.providers.clear()
        self.selected = None
        self.fingerprint = None
