"""
trellis.memory.embeddings — Embedding generation via Ollama

Generates text embeddings using Ollama's local API with the nomic-embed-text
model (768 dimensions). All processing stays local — no cloud API calls,
no cost, full privacy.

Graceful degradation: returns empty list on connection failure. Callers
should fall back to keyword-only search when embeddings are unavailable.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# nomic-embed-text produces 768-dimensional vectors
EMBEDDING_DIM = 768

# Model to use for embeddings
EMBEDDING_MODEL = "nomic-embed-text"

# Nomic's context window is 8192 tokens. At ~4 chars/token, truncate at 32000 chars.
MAX_INPUT_CHARS = 32000

# Timeout for Ollama API calls (seconds)
OLLAMA_TIMEOUT = 60.0


def _truncate(text: str) -> str:
    """Truncate text to MAX_INPUT_CHARS to stay within model context window."""
    if len(text) > MAX_INPUT_CHARS:
        return text[:MAX_INPUT_CHARS]
    return text


async def generate_embedding(
    text: str, ollama_url: str = "http://localhost:11434"
) -> list[float]:
    """Generate a 768-dim embedding vector for a text string.

    Uses Ollama's /api/embed endpoint with nomic-embed-text.

    Args:
        text: The text to embed.
        ollama_url: Base URL for the Ollama API.

    Returns:
        List of 768 floats, or empty list on failure.
    """
    truncated = _truncate(text)

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{ollama_url}/api/embed",
                json={"model": EMBEDDING_MODEL, "input": truncated},
            )

            if resp.status_code != 200:
                logger.warning(
                    "Ollama embed failed (status %d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return []

            data = resp.json()
            embeddings = data.get("embeddings", [])
            if not embeddings:
                logger.warning("Ollama returned no embeddings")
                return []

            return embeddings[0]

    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.warning("Ollama embedding failed: %s", exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error generating embedding: %s", exc)
        return []


async def generate_embeddings_batch(
    texts: list[str], ollama_url: str = "http://localhost:11434"
) -> list[list[float]]:
    """Batch embedding generation. Ollama handles batching internally.

    Args:
        texts: List of texts to embed.
        ollama_url: Base URL for the Ollama API.

    Returns:
        List of embedding vectors (one per input text), or empty list on failure.
    """
    if not texts:
        return []

    truncated = [_truncate(t) for t in texts]

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{ollama_url}/api/embed",
                json={"model": EMBEDDING_MODEL, "input": truncated},
            )

            if resp.status_code != 200:
                logger.warning(
                    "Ollama batch embed failed (status %d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return []

            data = resp.json()
            embeddings = data.get("embeddings", [])
            return embeddings

    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.warning("Ollama batch embedding failed: %s", exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error in batch embedding: %s", exc)
        return []
