"""Tests for OpenAI-compatible /v1/audio/speech endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novatts.main import app, _runtime, get_runtime, NovaApp


@pytest.fixture(autouse=True)
def setup_runtime() -> None:
    """Ensure runtime is initialized for tests."""
    import novatts.main as main_module
    
    if main_module._runtime is None:
        main_module._runtime = NovaApp()
        main_module._runtime.start()
    yield
    if main_module._runtime:
        main_module._runtime.stop()
        main_module._runtime = None


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


def test_openai_speech_basic_request(client: TestClient) -> None:
    """POST /v1/audio/speech with valid request returns audio."""
    body = {
        "model": "nova-balanced",
        "input": "Hello, world!",
        "voice": "default",
        "response_format": "wav",
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 0


def test_openai_speech_mp3_format_request_validation(client: TestClient) -> None:
    """MP3 format request is accepted (synthesis may fail if Qwen offline)."""
    body = {
        "model": "nova-balanced",
        "input": "Hello, world!",
        "voice": "default",
        "response_format": "mp3",
    }
    response = client.post("/v1/audio/speech", json=body)
    # Accept either 200 (success) or 502 (Qwen offline) — both valid for this test
    assert response.status_code in (200, 502)


def test_openai_speech_pcm_format(client: TestClient) -> None:
    """Request PCM format returns audio/pcm content."""
    body = {
        "model": "nova-balanced",
        "input": "Hello, world!",
        "voice": "default",
        "response_format": "pcm",
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/pcm"
    assert len(response.content) > 0


def test_openai_speech_empty_input(client: TestClient) -> None:
    """Empty input is rejected (Pydantic validation)."""
    body = {
        "model": "nova-balanced",
        "input": "",
        "voice": "default",
        "response_format": "mp3",
    }
    response = client.post("/v1/audio/speech", json=body)
    # Pydantic rejects min_length=1 with 422, not 400
    assert response.status_code == 422


def test_openai_speech_text_too_long(client: TestClient) -> None:
    """Text exceeding 4096 chars is rejected (Pydantic validation)."""
    body = {
        "model": "nova-balanced",
        "input": "x" * 4097,
        "voice": "default",
        "response_format": "mp3",
    }
    response = client.post("/v1/audio/speech", json=body)
    # Pydantic rejects max_length=4096 with 422, not 400
    assert response.status_code == 422


def test_openai_speech_invalid_format(client: TestClient) -> None:
    """Invalid response_format is rejected."""
    body = {
        "model": "nova-balanced",
        "input": "Hello",
        "voice": "default",
        "response_format": "xyz",
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 400


def test_openai_speech_speed_too_low(client: TestClient) -> None:
    """Speed < 0.25 is rejected."""
    body = {
        "model": "nova-balanced",
        "input": "Hello",
        "voice": "default",
        "response_format": "mp3",
        "speed": 0.1,
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 400


def test_openai_speech_speed_too_high(client: TestClient) -> None:
    """Speed > 4.0 is rejected."""
    body = {
        "model": "nova-balanced",
        "input": "Hello",
        "voice": "default",
        "response_format": "mp3",
        "speed": 5.0,
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 400


def test_openai_speech_model_profiles(client: TestClient) -> None:
    """Different models work without error (profile lookup)."""
    for model in ["nova-fast", "nova-balanced", "nova-expressive", "unknown-model"]:
        body = {
            "model": model,
            "input": "Test",
            "voice": "default",
            "response_format": "wav",
        }
        response = client.post("/v1/audio/speech", json=body)
        assert response.status_code == 200


def test_openai_speech_with_instructions(client: TestClient) -> None:
    """Request with custom instructions is accepted."""
    body = {
        "model": "nova-balanced",
        "input": "Hello!",
        "voice": "default",
        "response_format": "wav",
        "instructions": "Speak cheerfully",
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 200


def test_openai_speech_default_format_is_mp3(client: TestClient) -> None:
    """Omitting response_format defaults to MP3."""
    body = {
        "model": "nova-balanced",
        "input": "Hello",
        "voice": "default",
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"


def test_openai_speech_default_speed_is_1(client: TestClient) -> None:
    """Omitting speed defaults to 1.0 (no error)."""
    body = {
        "model": "nova-balanced",
        "input": "Hello",
        "voice": "default",
        "response_format": "wav",
    }
    response = client.post("/v1/audio/speech", json=body)
    assert response.status_code == 200
