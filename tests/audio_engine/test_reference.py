"""Reference analysis and nearest-candidate search (#480, first slice of #58).

Reference WAVs are written with the standard-library ``wave`` module or by hand (headers the
reader must also accept), never with the reader's own code. Expected measures are written
here or come from signals with a known answer; the distance used to judge the search is
recomputed here from its documented definition.
"""

from __future__ import annotations

import io
import math
import random
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from audio_engine import reference as R
from audio_engine.io import encode_wav
from audio_engine.kick import render_resolved
from audio_engine.params import KICK_SCHEMA_FILE, KickParamsError, load_schema, resolve_kick_params
from audio_engine.presets import load_preset, preset_names
from audio_engine.variants import make_variant

SR = 48000


def wav_bytes(channels: list[np.ndarray], sr: int = SR, bits: int = 24) -> bytes:
    """PCM WAV through the stdlib ``wave`` writer (independent of the reader under test)."""
    full = 2 ** (bits - 1) - 1
    ints = np.stack([np.round(np.clip(c, -1, 1) * full).astype(np.int64) for c in channels],
                    axis=1).reshape(-1)
    if bits == 16:
        frames = ints.astype("<i2").tobytes()
    else:
        frames = b"".join(int(v & 0xFFFFFF).to_bytes(3, "little") for v in ints.tolist())
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(bits // 8)
        w.setframerate(sr)
        w.writeframes(frames)
    return buf.getvalue()


def kick_like(sr: int = SR, ms: float = 400.0) -> np.ndarray:
    t = np.arange(int(sr * ms / 1000)) / sr
    f = 50 + 150 * np.exp(-t / 0.02)
    phase = 2 * np.pi * np.cumsum(f) / sr
    return 0.9 * np.sin(phase) * np.exp(-t / 0.08)


def write(tmp_path: Path, data: bytes, name: str = "ref.wav") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# --- reading ----------------------------------------------------------------------------------

@pytest.mark.parametrize("bits", [16, 24])
@pytest.mark.parametrize("sr", [44100, 48000])
def test_reads_mono_pcm_at_both_rates_and_depths(tmp_path, bits, sr):
    x = kick_like(sr)
    ref = R.read_reference_wav(write(tmp_path, wav_bytes([x], sr, bits)))
    full = 2 ** (bits - 1)
    expected = np.round(x * (full - 1)) / full
    assert (ref.sample_rate, ref.channels, ref.bit_depth) == (sr, 1, bits)
    assert np.array_equal(ref.samples, expected)


def test_stereo_is_the_mean_of_both_channels(tmp_path):
    x = kick_like()
    ref = R.read_reference_wav(write(tmp_path, wav_bytes([x, np.zeros_like(x)], bits=24)))
    full = 2 ** 23
    assert ref.channels == 2
    assert np.array_equal(ref.samples, np.round(x * (full - 1)) / full / 2)


def test_negative_24_bit_values_are_sign_extended(tmp_path):
    x = np.concatenate([np.full(4800, -0.5), np.full(4800, 0.5)])
    ref = R.read_reference_wav(write(tmp_path, wav_bytes([x], bits=24)))
    assert ref.samples[0] == pytest.approx(-0.5, abs=1e-6)
    assert ref.samples[-1] == pytest.approx(0.5, abs=1e-6)


def _riff(chunks: list[tuple[bytes, bytes]]) -> bytes:
    body = b"WAVE"
    for cid, data in chunks:
        body += cid + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _fmt(tag: int, channels: int, sr: int, bits: int, sub: int | None = None) -> bytes:
    block = channels * bits // 8
    head = struct.pack("<HHIIHH", tag, channels, sr, sr * block, block, bits)
    if sub is None:
        return head
    guid_tail = bytes.fromhex("000000001000800000aa00389b71")
    return head + struct.pack("<HHI", 22, bits, 0) + struct.pack("<H", sub) + guid_tail


def _pcm16(x: np.ndarray) -> bytes:
    return np.round(x * 32767).astype("<i2").tobytes()


def test_extensible_pcm_and_odd_extra_chunks_are_read(tmp_path):
    x = kick_like()
    data = _riff([(b"LIST", b"odd"), (b"fmt ", _fmt(0xFFFE, 1, SR, 16, sub=1)),
                  (b"data", _pcm16(x))])
    ref = R.read_reference_wav(write(tmp_path, data))
    assert np.array_equal(ref.samples, np.round(x * 32767) / 32768)


def _err(tmp_path, data: bytes) -> str:
    with pytest.raises(R.ReferenceAudioError) as exc:
        R.read_reference_wav(write(tmp_path, data))
    return str(exc.value)


@pytest.mark.parametrize(("data", "text"), [
    (b"not a wav at all", "Keine WAV-Datei"),
    (_riff([(b"data", b"\0\0")]), "fmt-Block"),
    (_riff([(b"fmt ", _fmt(1, 1, SR, 16))]), "keinen data-Block"),
    (_riff([(b"fmt ", _fmt(3, 1, SR, 32)), (b"data", b"\0" * 400)]), "PCM"),
    (_riff([(b"fmt ", _fmt(0xFFFE, 1, SR, 32, sub=3)), (b"data", b"\0" * 400)]), "PCM"),
    (_riff([(b"fmt ", _fmt(1, 1, SR, 8)), (b"data", b"\0" * 4800)]), "8 Bit"),
    (_riff([(b"fmt ", _fmt(1, 1, 96000, 16)), (b"data", b"\0" * 19200)]), "96000 Hz"),
    (_riff([(b"fmt ", _fmt(1, 3, SR, 16)), (b"data", b"\0" * 28800)]), "3 Kanäle"),
])
def test_unreadable_formats_are_rejected_in_german(tmp_path, data, text):
    assert text in _err(tmp_path, data)


def test_truncated_data_chunk_is_rejected(tmp_path):
    good = _riff([(b"fmt ", _fmt(1, 1, SR, 16)), (b"data", _pcm16(kick_like()))])
    assert "abgeschnitten" in _err(tmp_path, good[:-100])


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(R.ReferenceAudioError, match="Datei nicht lesbar"):
        R.read_reference_wav(tmp_path / "gone.wav")


def test_silent_files_are_rejected(tmp_path):
    zeros = np.zeros(SR // 2)
    assert "still" in _err(tmp_path, wav_bytes([zeros]))
    quiet = kick_like() * 10 ** (-61 / 20)  # peak about -62 dBFS
    assert "still" in _err(tmp_path, wav_bytes([quiet]))
    x = kick_like()
    assert "Mono" in _err(tmp_path, wav_bytes([x, -x]))  # cancels in the mono sum


def test_too_long_and_too_short_files_are_rejected(tmp_path):
    long = np.tile(kick_like(ms=500), 7)[: int(3.1 * SR)]  # a 3.1 s loop
    assert "zu lang" in _err(tmp_path, wav_bytes([long], bits=16))
    assert "zu kurz" in _err(tmp_path, wav_bytes([kick_like(ms=40)]))
    # the limit itself is allowed
    R.read_reference_wav(write(tmp_path, wav_bytes([np.tile(kick_like(ms=500), 6)], bits=16)))


def test_oversized_file_is_rejected_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "MAX_FILE_BYTES", 1000)
    assert "zu groß" in _err(tmp_path, wav_bytes([kick_like()]))


# --- measures (signals with a known answer) -----------------------------------------------------

def _sine(f: float, ms: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * ms / 1000)) / sr
    return np.sin(2 * np.pi * f * t)


def test_shares_and_body_pitch_on_known_signals():
    low = R.measure(_sine(50, 500) * np.exp(-np.arange(24000) / SR / 0.15), SR)
    assert low["sub_share"] > 0.98
    assert low["click_share"] < 0.02
    high = R.measure(_sine(3000, 500), SR)
    assert high["sub_share"] < 0.01
    assert high["click_share"] > 0.98
    steady = R.measure(_sine(80, 500), SR)
    assert steady["body_hz"] == pytest.approx(80, rel=0.005)
    assert steady["fundamental_hz"] == pytest.approx(80, rel=0.005)


def test_body_pitch_is_none_when_the_signal_ends_before_the_window():
    assert R.measure(_sine(80, 60), SR)["body_hz"] is None


def test_measures_count_from_the_onset_not_from_sample_0():
    x = kick_like()
    padded = np.concatenate([np.zeros(4800), x])  # 100 ms of silence in front
    assert R.measure(padded, SR) == R.measure(x, SR)
    assert R.measure(x * 0.25, SR) == R.measure(x, SR)  # level does not count


# --- search -------------------------------------------------------------------------------------

# Written here from the documented definition (module docstring of audio_engine.reference),
# not taken from the module.
SCALES = {"fundamental_hz": ("st", 1.0), "body_hz": ("st", 2.0),
          "decay_20db_ms": ("ln", math.log(1.25)), "decay_40db_ms": ("ln", math.log(1.25)),
          "sub_share": ("lin", 0.05), "click_share": ("lin", 0.05)}


def independent_distance(a: dict, b: dict) -> float:
    total = 0.0
    for name, (kind, scale) in SCALES.items():
        va, vb = a[name], b[name]
        if va is None and vb is None:
            d = 0.0
        elif va is None or vb is None:
            d = 3.0
        elif kind == "st":
            d = abs(12 * math.log2(va / vb)) / scale
        elif kind == "ln":
            d = abs(math.log(va / vb)) / scale
        else:
            d = abs(va - vb) / scale
        total += d * d
    return math.sqrt(total / len(SCALES))


def _preset_candidate(name: str):
    return next(c for c in R.candidates() if c.preset == name and c.variant == 0)


def test_grid_is_every_preset_with_its_variants():
    names = [c.name for c in R.candidates()]
    assert names == [f"{p} v{i}" for p in preset_names("kick")
                     for i in range(R.VARIANTS_PER_PRESET)]
    for p in preset_names("kick"):  # variant 0 is the preset itself (never gated)
        expected = resolve_kick_params(load_preset(p))
        expected.pop("variants")  # a batch instruction, not part of one kick
        assert _preset_candidate(p).params == expected


@pytest.mark.parametrize("name", preset_names("kick"))
def test_a_written_preset_is_found_as_itself(tmp_path, name):
    cand = _preset_candidate(name)
    audio = render_resolved(cand.params)
    path = write(tmp_path, encode_wav(audio, SR, 24))
    match = R.match_reference_file(path)
    assert match.nearest.name == cand.name
    assert match.total < 0.05, match.distances
    assert match.reference["sample_rate"] == SR and match.reference["channels"] == 1


def _random_variant(rng: random.Random, sr: int = SR) -> tuple[str, dict]:
    name = rng.choice(preset_names("kick"))
    base = dict(load_preset(name), seed=rng.randrange(2**32), sample_rate=sr)
    return name, make_variant(base, rng.randrange(1, 10**6))


@pytest.mark.parametrize("seed", range(6))
def test_a_render_with_known_params_finds_a_candidate_at_least_as_close_as_its_preset(seed):
    """Property: a variant (own base seed, so own click noise, index outside the grid) of a
    random preset, as reference. The nearest candidate is at least as close as that preset by
    the independently recomputed distance, the reported distance is right, and the family is
    the preset's own."""
    rng = random.Random(1000 + seed)
    for _ in range(8):
        name, params = _random_variant(rng)
        ref = R.measure(render_resolved(params), SR)
        match = R.match_measures(ref)
        to_preset = independent_distance(ref, _preset_candidate(name).measures)
        assert independent_distance(ref, match.nearest.measures) <= to_preset + 1e-12
        assert match.total == pytest.approx(independent_distance(ref, match.nearest.measures))
        assert min(independent_distance(ref, c.measures) for c in R.candidates()) == \
            pytest.approx(match.total)
        assert match.nearest.preset == name, (params, match.nearest.name, match.distances)


def test_a_44k1_reference_finds_its_preset_family(tmp_path):
    rng = random.Random(7)
    for k in range(6):
        name, params = _random_variant(rng, sr=44100)
        path = write(tmp_path, encode_wav(render_resolved(params), 44100, 16), f"r{k}.wav")
        match = R.match_reference_file(path)
        assert match.nearest.preset == name, (name, match.nearest.name, match.distances)


def test_stereo_with_equal_channels_matches_like_mono(tmp_path):
    x = render_resolved(_preset_candidate("punchy").params)
    mono = R.match_reference_file(write(tmp_path, wav_bytes([x]), "m.wav"))
    stereo = R.match_reference_file(write(tmp_path, wav_bytes([x, x]), "s.wav"))
    assert stereo.nearest.name == mono.nearest.name
    assert stereo.distances == mono.distances


def _random_contract_params(rng: random.Random) -> dict:
    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    while True:
        p = {"schema_version": "0.2", "seed": rng.randrange(2**32)}
        for k in ("length_ms", "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms",
                  "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive",
                  "tone", "peak_ceiling_dbfs"):
            p[k] = rng.uniform(props[k]["minimum"], props[k]["maximum"])
        try:
            return resolve_kick_params(p)
        except KickParamsError:
            continue


@pytest.mark.parametrize("seed", range(3))
def test_measures_stay_valid_over_the_whole_contract_range(seed):
    rng = random.Random(seed)
    for _ in range(8):
        params = _random_contract_params(rng)
        m = R.measure(render_resolved(params), SR)
        for k, v in m.items():
            assert v is None or math.isfinite(v), (k, v, params)
        for k in ("sub_share", "click_share"):
            assert 0.0 <= m[k] <= 1.0
        match = R.match_measures(m)
        assert independent_distance(m, match.nearest.measures) == pytest.approx(match.total)
        assert match.total <= min(independent_distance(m, _preset_candidate(p).measures)
                                  for p in preset_names("kick")) + 1e-12


def test_same_file_same_answer_and_candidates_re_render(tmp_path):
    x = render_resolved(_random_variant(random.Random(3))[1])
    path = write(tmp_path, encode_wav(x, SR, 24))
    a = R.match_reference_file(path)
    R.candidates.cache_clear()
    b = R.match_reference_file(path)
    assert (a.nearest.name, a.distances, a.total) == (b.nearest.name, b.distances, b.total)
    assert [c.name for _, c in a.ranking] == [c.name for _, c in b.ranking]
    nearest = b.nearest
    assert R.measure(render_resolved(nearest.params), SR) == nearest.measures
