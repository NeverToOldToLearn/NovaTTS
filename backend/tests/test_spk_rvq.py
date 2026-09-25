"""Tests for pre-extracted .spk/.rvq voice reference handling."""

from pathlib import Path

from novatts.tts import spk_rvq
from novatts.tts.spk_rvq import (
    collect_wavs,
    convert_samples_dir,
    register_sample,
    unpaired_wavs,
    voice_ref_for,
)


class FakeRegister:
    """Records register_voice calls to assert which payload form is used."""

    def __init__(self):
        self.calls = []

    def register_voice(self, name, wav_bytes=None, *, ref_text="", spk_bytes=None, rvq_bytes=None):
        self.calls.append(
            {
                "name": name,
                "wav": wav_bytes,
                "ref_text": ref_text,
                "spk": spk_bytes,
                "rvq": rvq_bytes,
            }
        )


def make_sample(dirpath: Path, stem: str, with_pair: bool = True, with_txt: bool = True) -> Path:
    wav = dirpath / f"{stem}.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 600)
    if with_txt:
        (dirpath / f"{stem}.txt").write_text("The reference line.", encoding="utf-8")
    if with_pair:
        (dirpath / f"{stem}.spk").write_bytes(b"\x00\x00" * 8)  # 16 bytes, f32 mult of 4
        (dirpath / f"{stem}.rvq").write_bytes(b"\x01\x02\x03")
    return wav


def test_voice_ref_for_missing_pair_is_none(tmp_path):
    wav = make_sample(tmp_path, "alice", with_pair=False)
    assert voice_ref_for(wav) is None


def test_voice_ref_for_incomplete_pair_is_none(tmp_path):
    wav = make_sample(tmp_path, "bob", with_pair=False)
    (tmp_path / "bob.spk").write_bytes(b"\x00\x00")
    assert voice_ref_for(wav) is None


def test_voice_ref_for_complete_pair(tmp_path):
    wav = make_sample(tmp_path, "carol")
    ref = voice_ref_for(wav)
    assert ref is not None
    assert ref.name == "carol"
    assert ref.spk.read_bytes() == b"\x00\x00" * 8
    assert ref.ref_text() == "The reference line."


def test_voice_ref_for_no_txt(tmp_path):
    wav = make_sample(tmp_path, "dave", with_txt=False)
    ref = voice_ref_for(wav)
    assert ref is not None
    assert ref.ref_text() == ""


def test_register_sample_prefers_pair(tmp_path):
    backend = FakeRegister()
    wav = make_sample(tmp_path, "erin")
    register_sample(backend, wav)
    (call,) = backend.calls
    assert call["name"] == "erin"
    assert call["wav"] is None
    assert call["spk"] == b"\x00\x00" * 8
    assert call["rvq"] == b"\x01\x02\x03"
    assert call["ref_text"] == "The reference line."


def test_register_sample_falls_back_to_wav(tmp_path):
    backend = FakeRegister()
    wav = make_sample(tmp_path, "frank", with_pair=False)
    register_sample(backend, wav)
    (call,) = backend.calls
    assert call["name"] == "frank"
    assert call["spk"] is None
    assert call["rvq"] is None
    assert call["wav"] == wav.read_bytes()


def test_convert_samples_dir_skips_paired(tmp_path):
    make_sample(tmp_path, "george", with_pair=True)
    make_sample(tmp_path, "hannah", with_pair=False)
    # qwen-codec.exe is not installed here, so the only pair-less wav
    # should end up in "failed" (missing binary), not "converted".
    summary = convert_samples_dir(tmp_path)
    assert summary["total"] == 2
    assert summary["converted"] == 0
    assert summary["skipped"] == 1  # george already has a pair
    assert summary["failed"] == 1
    assert "hannah.wav" in summary["errors"][0]


def test_collect_wavs_filters_quicktest_and_big(tmp_path):
    make_sample(tmp_path, "x", with_pair=False)
    (tmp_path / "output_quick_test.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    big = tmp_path / "big.wav"
    big.write_bytes(b"RIFF" + b"\x00" * 6_000_000)
    names = {p.name for p in collect_wavs(tmp_path)}
    assert "x.wav" in names
    assert "output_quick_test.wav" not in names
    assert "big.wav" not in names


def test_unpaired_wavs(tmp_path):
    make_sample(tmp_path, "a", with_pair=True)
    make_sample(tmp_path, "b", with_pair=False)
    unpaired = unpaired_wavs(tmp_path)
    assert [p.stem for p in unpaired] == ["b"]


def test_codec_bin_path_defaults_to_tts_server_sibling(monkeypatch):
    monkeypatch.setattr(spk_rvq.settings, "qwen_codec_bin", "")
    monkeypatch.setattr(spk_rvq.settings, "qwen_bin", r"D:\qwentts\build\Release\tts-server.exe")
    assert spk_rvq.codec_bin_path() == Path(r"D:\qwentts\build\Release\qwen-codec.exe")


def test_codec_bin_path_explicit_wins(monkeypatch):
    monkeypatch.setattr(spk_rvq.settings, "qwen_codec_bin", r"C:\tools\qwen-codec.exe")
    monkeypatch.setattr(spk_rvq.settings, "qwen_bin", r"D:\qwentts\build\Release\tts-server.exe")
    assert spk_rvq.codec_bin_path() == Path(r"C:\tools\qwen-codec.exe")
