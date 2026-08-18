"""
RedSight - High-Performance Local AI Intelligence Platform
Embedding Model Loader

Loads and manages embedding models for the knowledge pipeline.
Supports:
- sentence-transformers (local models like all-MiniLM-L6-v2)
- LM Studio / OpenAI-compatible API
- Graceful fallback when no model is available
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default local embedding model
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingModelLoader:
    """
    Loads embedding models for the knowledge pipeline.

    Priority:
    1. Pre-loaded model (passed in constructor)
    2. Local sentence-transformers model
    3. LM Studio / OpenAI-compatible API
    """

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        lmstudio_url: Optional[str] = None,
    ):
        self._model_name = model_name
        self._lmstudio_url = lmstudio_url
        self._model = None
        self._backend = None  # "local", "lmstudio", or None

    async def load(self) -> bool:
        """
        Load the embedding model.

        Tries local sentence-transformers first, then LM Studio API.
        Returns True if a model is loaded.
        """
        # Try 1: sentence-transformers (local)
        loaded = await self._load_local()
        if loaded:
            return True

        # Try 2: LM Studio / OpenAI API
        if self._lmstudio_url:
            loaded = await self._load_lmstudio()
            if loaded:
                return True

        logger.warning(
            "No embedding model available. "
            "Install sentence-transformers or configure LM Studio embedding endpoint."
        )
        return False

    async def _load_local(self) -> bool:
        """Load a local sentence-transformers model."""
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading local embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
            self._backend = "local"

            # Get model info
            self._model_name = self._model.model_name or self._model_name
            logger.info(
                f"Loaded {self._model_name} "
                f"(dim={self._model.get_sentence_embedding_dimension()}, "
                f"backend={self._backend})"
            )
            return True

        except ImportError:
            logger.info("sentence-transformers not installed, skipping local model")
            return False
        except Exception as e:
            logger.warning(f"Failed to load local embedding model: {e}")
            return False

    async def _load_lmstudio(self) -> bool:
        """Load an embedding model from LM Studio / OpenAI API."""
        try:
            import httpx

            # Test connectivity
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._lmstudio_url}/models",
                )
                resp.raise_for_status()

                models_data = resp.json()
                model_list = models_data.get("data", [])

                # Find an embedding model
                embed_model = None
                for m in model_list:
                    mid = m.get("id", "")
                    if "embed" in mid.lower() or "embedding" in mid.lower():
                        embed_model = mid
                        break

                if not embed_model and model_list:
                    # Use first available model as fallback
                    embed_model = model_list[0].get("id", "")

                if not embed_model:
                    logger.warning("No embedding model found in LM Studio")
                    return False

                self._model = {
                    "client": client,
                    "base_url": self._lmstudio_url,
                    "model_id": embed_model,
                }
                self._backend = "lmstudio"
                logger.info(
                    f"Using LM Studio embedding model: {embed_model} "
                    f"({self._lmstudio_url})"
                )
                return True

        except ImportError:
            logger.info("httpx not installed, skipping LM Studio model")
            return False
        except Exception as e:
            logger.warning(f"Failed to connect to LM Studio: {e}")
            return False

    @property
    def model(self) -> Optional[Any]:
        """Get the loaded model."""
        return self._model

    @property
    def backend(self) -> Optional[str]:
        """Get the backend type."""
        return self._backend

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Returns list of embedding vectors.
        """
        if not self._model:
            raise ValueError("No embedding model loaded")

        if self._backend == "local":
            return await self._embed_local(texts)
        elif self._backend == "lmstudio":
            return await self._embed_lmstudio(texts)
        else:
            raise ValueError(f"Unknown backend: {self._backend}")

    async def _embed_local(self, texts: List[str]) -> List[List[float]]:
        """Embed texts using local sentence-transformers."""
        import numpy as np

        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=min(32, len(texts)),
        )

        if isinstance(embeddings, np.ndarray):
            return embeddings.tolist()
        elif hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        else:
            return [list(e) for e in embeddings]

    async def _embed_lmstudio(self, texts: List[str]) -> List[List[float]]:
        """Embed texts using LM Studio / OpenAI API."""
        import httpx

        client = self._model["client"]
        base_url = self._model["base_url"]
        model_id = self._model["model_id"]

        # Batch requests if needed
        results = []
        batch_size = 10
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            async with httpx.AsyncClient(timeout=60) as batch_client:
                resp = await batch_client.post(
                    f"{base_url}/embeddings",
                    json={
                        "model": model_id,
                        "input": batch,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("data", []):
                    results.append(item.get("embedding", []))

        return results

    def get_info(self) -> Dict[str, Any]:
        """Get model information."""
        if not self._model:
            return {
                "loaded": False,
                "backend": None,
                "model_name": self._model_name,
                "lmstudio_url": self._lmstudio_url,
            }

        info = {
            "loaded": True,
            "backend": self._backend,
            "model_name": self._model_name,
        }

        if self._backend == "local":
            info["dimension"] = self._model.get_sentence_embedding_dimension()
        elif self._backend == "lmstudio":
            info["model_id"] = self._model["model_id"]
            info["base_url"] = self._model["base_url"]

        return info
