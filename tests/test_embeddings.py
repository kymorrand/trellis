"""Tests for trellis.memory.embeddings — Ollama embedding generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from trellis.memory.embeddings import generate_embedding, generate_embeddings_batch

# Dimension expected from nomic-embed-text
DIM = 768


def _fake_embedding(dim: int = DIM) -> list[float]:
    """Return a deterministic fake embedding vector."""
    return [float(i) / dim for i in range(dim)]


class TestGenerateEmbedding:
    """Tests for single-text embedding generation."""

    @pytest.mark.asyncio
    async def test_returns_list_of_floats(self) -> None:
        """Single text returns list[float] of length 768."""
        fake_resp = httpx.Response(
            200,
            json={"embeddings": [_fake_embedding()]},
        )
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embedding("hello world")

        assert isinstance(result, list)
        assert len(result) == DIM
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_empty_text_returns_valid_embedding(self) -> None:
        """Empty text still returns a valid embedding (not an error)."""
        fake_resp = httpx.Response(
            200,
            json={"embeddings": [_fake_embedding()]},
        )
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embedding("")

        assert isinstance(result, list)
        assert len(result) == DIM

    @pytest.mark.asyncio
    async def test_connection_failure_returns_empty_list(self) -> None:
        """Ollama connection failure returns empty list (graceful degradation)."""
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.side_effect = httpx.ConnectError("Connection refused")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embedding("hello world")

        assert result == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self) -> None:
        """Non-200 response returns empty list."""
        fake_resp = httpx.Response(500, json={"error": "model not found"})
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embedding("hello")

        assert result == []

    @pytest.mark.asyncio
    async def test_long_text_truncated_before_sending(self) -> None:
        """Text over 32000 chars is truncated before sending to Ollama."""
        long_text = "a" * 50000
        fake_resp = httpx.Response(
            200,
            json={"embeddings": [_fake_embedding()]},
        )
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embedding(long_text)

            # Verify the text sent to Ollama was truncated
            call_args = instance.post.call_args
            sent_json = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
            sent_input = sent_json["input"]
            assert len(sent_input) <= 32000

        assert len(result) == DIM

    @pytest.mark.asyncio
    async def test_custom_ollama_url(self) -> None:
        """Custom Ollama URL is used in the request."""
        fake_resp = httpx.Response(
            200,
            json={"embeddings": [_fake_embedding()]},
        )
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            await generate_embedding("test", ollama_url="http://custom:9999")

            call_args = instance.post.call_args
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            assert "custom:9999" in str(url)


class TestGenerateEmbeddingsBatch:
    """Tests for batch embedding generation."""

    @pytest.mark.asyncio
    async def test_batch_returns_correct_count(self) -> None:
        """Batch of 3 texts returns 3 embeddings."""
        texts = ["hello", "world", "test"]
        fake_resp = httpx.Response(
            200,
            json={"embeddings": [_fake_embedding() for _ in texts]},
        )
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embeddings_batch(texts)

        assert len(result) == 3
        assert all(len(e) == DIM for e in result)

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty_list(self) -> None:
        """Empty input list returns empty list without calling Ollama."""
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embeddings_batch([])

        assert result == []
        instance.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_connection_failure_returns_empty_list(self) -> None:
        """Ollama connection failure in batch returns empty list."""
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.side_effect = httpx.ConnectError("Connection refused")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embeddings_batch(["hello", "world"])

        assert result == []

    @pytest.mark.asyncio
    async def test_batch_truncates_long_texts(self) -> None:
        """Long texts in batch are truncated before sending."""
        texts = ["short", "a" * 50000]
        fake_resp = httpx.Response(
            200,
            json={"embeddings": [_fake_embedding() for _ in texts]},
        )
        with patch("trellis.memory.embeddings.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = fake_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await generate_embeddings_batch(texts)

            call_args = instance.post.call_args
            sent_json = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
            sent_input = sent_json["input"]
            assert all(len(t) <= 32000 for t in sent_input)

        assert len(result) == 2
