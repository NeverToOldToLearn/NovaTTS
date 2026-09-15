"""Audio format conversion via ffmpeg.

Supports WAV (input from Qwen3 backend) → MP3, Opus, AAC, FLAC, PCM output.
Returns audio bytes or writes to file.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Supported output formats and their MIME types
FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}

# ffmpeg codec and container settings per format
FORMAT_ARGS = {
    "mp3": ["-acodec", "libmp3lame", "-q:a", "2"],  # ~192 kbps
    "opus": ["-acodec", "libopus", "-b:a", "128k"],
    "aac": ["-acodec", "aac", "-b:a", "128k"],
    "flac": ["-acodec", "flac"],
    "wav": ["-acodec", "pcm_s16le"],
    "pcm": ["-acodec", "pcm_s16le", "-f", "s16le"],
}


def convert_audio(
    input_path: Path | str,
    output_format: str = "mp3",
) -> bytes:
    """Convert WAV audio to the specified format using ffmpeg.

    Args:
        input_path: Path to input WAV file.
        output_format: Output format (mp3, opus, aac, flac, wav, pcm).

    Returns:
        Audio data as bytes.

    Raises:
        ValueError: If format is unsupported.
        subprocess.CalledProcessError: If ffmpeg fails.
    """
    output_format = output_format.lower().strip()
    if output_format not in FORMAT_ARGS:
        raise ValueError(f"Unsupported format: {output_format}. Supported: {list(FORMAT_ARGS.keys())}")

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # ffmpeg reads from stdin (-i pipe:0) and writes to stdout (-f format pipe:1)
    # This keeps all data in memory without temp files.
    args = [
        "ffmpeg",
        "-i", str(input_path),
        "-loglevel", "error",  # Suppress ffmpeg's verbose output
    ]
    args.extend(FORMAT_ARGS[output_format])
    args.extend(["-f", output_format if output_format != "pcm" else "s16le", "pipe:1"])

    try:
        result = subprocess.run(args, capture_output=True, check=True, timeout=60)
        log.debug("Converted audio: %s → %s (%d bytes)", input_path.name, output_format, len(result.stdout))
        return result.stdout
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg conversion timed out for {input_path}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg conversion failed: {stderr}") from exc


def get_mime_type(format_name: str) -> str:
    """Return MIME type for a format."""
    fmt = format_name.lower().strip()
    return FORMAT_MIME.get(fmt, "audio/mpeg")
