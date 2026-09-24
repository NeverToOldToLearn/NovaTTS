# OpenAI-Compatible `/v1/audio/speech` Endpoint

NovaTTS exposes an OpenAI-compatible TTS endpoint for integration with tools like **Open-WebUI**.

## Endpoint

```
POST http://localhost:8765/v1/audio/speech
```

## Request Format

```json
{
  "model": "nova-balanced",
  "input": "Hello, world!",
  "voice": "default",
  "response_format": "mp3",
  "speed": 1.0,
  "instructions": "Speak cheerfully"
}
```

### Parameters

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `model` | string | Yes | — | Model profile: `nova-fast`, `nova-balanced`, `nova-expressive`, or any custom name. Maps to TTS instruction presets. |
| `input` | string | Yes | — | Text to synthesize. Max 4096 characters. |
| `voice` | string | Yes | — | Voice name (e.g., `default`, `en-US-Neural-C`, or any registered speaker). |
| `response_format` | string | No | `mp3` | Output format: `mp3`, `wav`, `pcm`, `opus`, `aac`, `flac`. |
| `speed` | float | No | `1.0` | Playback speed: 0.25–4.0. |
| `instructions` | string | No | — | Voice design hints (e.g., "whisper", "cheerful"). Passed to Qwen TTS backend. |

## Response

Returns audio data with appropriate `Content-Type` header:

```
Content-Type: audio/mpeg  (for MP3)
Content-Type: audio/wav   (for WAV)
Content-Type: audio/pcm   (for PCM)
...etc
```

Body: raw audio bytes.

## Model Profiles

Maps OpenAI `model` param to NovaTTS instruction presets:

| Model | Instruction | Use Case |
|-------|-------------|----------|
| `nova-fast` | `emotion=fast` | Low-latency, minimal emotion |
| `nova-balanced` | `emotion=neutral` | Clear, neutral delivery |
| `nova-expressive` | `emotion=default` | Natural, expressive speech |
| Other | (ignored) | Falls back to `emotion=neutral` |

## Supported Audio Formats

- **mp3** — MPEG Layer 3 (default; best for streaming)
- **wav** — PCM WAV (uncompressed; highest fidelity)
- **pcm** — Raw PCM (16 kHz, 16-bit, mono)
- **opus** — Opus codec (lower bandwidth than MP3)
- **aac** — Advanced Audio Codec (Apple-friendly)
- **flac** — FLAC lossless (rare; largest files)

## Integration with Open-WebUI

### Setup

1. **Start NovaTTS backend:**
   ```bash
   cd backend
   source .venv/Scripts/activate  # Windows Git Bash
   python -m uvicorn novatts.main:app --host 0.0.0.0 --port 8765
   ```

2. **Start Open-WebUI** (on its default port 8080):
   ```bash
   open-webui serve
   ```

3. **Add NovaTTS as TTS provider in Open-WebUI:**
   - Admin → Settings → Text-to-Speech
   - TTS Engine: OpenAI
   - API Base URL: `http://localhost:8765`
   - Model: (any name, e.g., `nova-balanced`)
   - Voice: (any voice name, e.g., `default`)

### Example cURL Request

```bash
curl -X POST http://localhost:8765/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nova-balanced",
    "input": "Hello from NovaTTS!",
    "voice": "default",
    "response_format": "mp3",
    "speed": 1.0
  }' \
  --output output.mp3
```

## Error Handling

- **400** — Invalid `response_format` or `speed` out of range
- **422** — Validation error (empty `input`, text too long, missing required fields)
- **500** — Synthesis failed (Qwen backend error, voice not found, etc.)
- **502** — Bad Gateway (Qwen backend unreachable)

## Backwards Compatibility

The legacy `/speak` endpoint remains unchanged and is still used by the Visual Novel GUI.

## Architecture

1. **Request validation** → Pydantic models enforce OpenAI format
2. **Model profile lookup** → `model` param → TTS instruction preset
3. **TTS synthesis** → Qwen backend (same as `/speak`)
4. **Audio conversion** → `ffmpeg` subprocess handles format conversion
5. **Response** → Streamed audio with correct MIME type

## Port Configuration

- **NovaTTS backend:** default `8765` (configurable in `config.json`)
- **Open-WebUI:** default `8080` (separate process)
- **Qwen backend:** default `8080` (internal; managed by NovaTTS)

If ports conflict, adjust in:
- NovaTTS: `backend/config.json` → `"listen_port": 8765`
- Open-WebUI: `open-webui serve --port 8081` (or your preferred port)

Then update Open-WebUI TTS settings to match your NovaTTS port.
