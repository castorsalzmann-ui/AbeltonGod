"""kick-params v0.3 fields in the engine (#120): tail_note, click_decay_ms, click_q, polarity,
offset_ms, clip_db, the resolved form, coercion and error wording. ``length_beats`` and its
-60 dB rule are in ``test_length_rule.py``, clip aliasing in ``test_clip_aliasing.py``.

Expected values are written by hand or computed here by another method (exact decimal
arithmetic for note frequencies, the stdlib ``wave`` reader for WAV samples), not taken from
the engine.
"""

from __future__ import annotations

import io
import json
import math
import random
import wave
from decimal import Decimal, getcontext

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from audio_engine import kick as K
from audio_engine.io import render_kick_wav, rerender_from_sidecar, write_kick
from audio_engine.params import (
    KICK_SCHEMA_FILE,
    NOTE_HZ,
    KickParamsError,
    load_schema,
    resolve_kick_params,
    tail_note_of,
)

V02 = {"schema_version": "0.2", "seed": 1}
V03 = {"schema_version": "0.3", "seed": 1}
# Hand-written v0.3 defaults (contract) and the 0.2 keys a resolved 0.2 document has.
V03_DEFAULTS = {"click_decay_ms": 3, "click_q": 0.9, "polarity": 1, "offset_ms": 0, "clip_db": 0}
RESOLVED_V02_KEYS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "length_ms",
    "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms", "amp_attack_ms", "amp_decay_ms",
    "click_level", "click_tone_hz", "drive", "tone", "peak_ceiling_dbfs",
}


def wav_ints(wav: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav)) as w:
        width, frames = w.getsampwidth(), w.readframes(w.getnframes())
    raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, width).astype(np.int64)
    value = sum(raw[:, b] << (8 * b) for b in range(width))
    return np.where(value >= 1 << (8 * width - 1), value - (1 << (8 * width)), value)


def wav(params: dict) -> bytes:
    return render_kick_wav(params)[0]


def _random_v02_fields(rng: random.Random) -> dict:
    """Every 0.2 sound field present with probability 0.6, drawn over its whole range."""
    start = rng.uniform(60, 600)
    fields = {
        "sample_rate": rng.choice([44100, 48000]), "bit_depth": rng.choice([16, 24]),
        "length_ms": rng.uniform(80, 600), "pitch_start_hz": start,
        "pitch_end_hz": rng.uniform(30, min(120, start)), "pitch_decay_ms": rng.uniform(2, 300),
        "amp_attack_ms": rng.uniform(0, 20), "amp_decay_ms": rng.uniform(20, 2000),
        "click_level": rng.uniform(0, 1), "click_tone_hz": rng.uniform(500, 12000),
        "drive": rng.uniform(0, 1), "tone": rng.uniform(-1, 1),
        "peak_ceiling_dbfs": rng.uniform(-12, -0.1),
    }
    out = {k: v for k, v in fields.items() if rng.random() < 0.6}
    if "pitch_end_hz" in out and "pitch_start_hz" not in out and out["pitch_end_hz"] > 220:
        del out["pitch_end_hz"]
    return {**V02, "seed": rng.randrange(2**32), **out}


# --- 0.2 unchanged; a 0.3 document without v0.3 fields renders like 0.2 ----------------------


def test_v02_resolution_has_no_v03_key() -> None:
    assert set(resolve_kick_params(V02)) == RESOLVED_V02_KEYS


@pytest.mark.parametrize("i", range(12))
def test_v03_document_without_new_fields_renders_like_v02(i) -> None:
    req = _random_v02_fields(random.Random(30120 + i))
    as_v03 = {**req, "schema_version": "0.3"}
    assert wav(as_v03) == wav(req)
    # Explicit defaults change nothing either.
    assert wav({**as_v03, **V03_DEFAULTS}) == wav(req)
    resolved = resolve_kick_params(as_v03)
    assert set(resolved) == RESOLVED_V02_KEYS | set(V03_DEFAULTS)
    assert {k: resolved[k] for k in V03_DEFAULTS} == V03_DEFAULTS


def test_v03_defaults_are_the_engine_010_constants() -> None:
    assert (K.CLICK_DECAY_MS, K.CLICK_Q, K.CLICK_LENGTH_MS) == (3.0, 0.9, 15.0)
    assert K.click_window_ms(3.0) == 15.0


# --- tail_note -----------------------------------------------------------------------------------


def _exact_note_hz(note: int) -> float:
    getcontext().prec = 50
    return float(Decimal(440) * Decimal(2) ** (Decimal(note - 69) / Decimal(12)))


def test_note_table_is_the_correctly_rounded_formula() -> None:
    assert sorted(NOTE_HZ) == list(range(23, 47))
    for note in range(23, 47):
        assert NOTE_HZ[note] == _exact_note_hz(note), note
        assert math.isclose(NOTE_HZ[note], 440 * 2 ** ((note - 69) / 12), rel_tol=1e-15)
    assert (NOTE_HZ[33], NOTE_HZ[45]) == (55.0, 110.0)  # A1, A2
    assert 30 <= NOTE_HZ[23] < 31 and 116 < NOTE_HZ[46] <= 120  # inside pitch_end_hz range


@pytest.mark.parametrize("note", range(23, 47))
def test_tail_note_sets_pitch_end_hz(note) -> None:
    p = resolve_kick_params({**V03, "tail_note": note, "pitch_start_hz": 300})
    assert "tail_note" not in p and p["pitch_end_hz"] == _exact_note_hz(note)
    assert abs(69 + 12 * math.log2(p["pitch_end_hz"] / 440) - note) < 1e-9
    assert tail_note_of(p) == note


@pytest.mark.parametrize("i", range(8))
def test_tail_note_renders_like_the_same_pitch_end_hz(i) -> None:
    rng = random.Random(40120 + i)
    note = rng.randint(23, 46)
    req = {**_random_v02_fields(rng), "schema_version": "0.3", "tail_note": note}
    req.pop("pitch_end_hz", None)
    req["pitch_start_hz"] = max(req.get("pitch_start_hz", 220), 117)
    plain = {**{k: v for k, v in req.items() if k != "tail_note"},
             "pitch_end_hz": _exact_note_hz(note)}
    assert wav(req) == wav(plain)


def test_tail_note_moves_the_measured_tail_pitch_by_an_octave() -> None:
    """Behaviour: 12 notes up doubles the tail frequency (zero crossings over the same
    interval, D-012 lesson), on long clean kicks whose pitch has settled."""
    def crossings(note):
        p = {**V03, "tail_note": note, "pitch_start_hz": 240, "pitch_decay_ms": 5,
             "length_ms": 1000, "amp_decay_ms": 2000, "click_level": 0, "drive": 0}
        x = wav_ints(wav(p))[24000:43200].astype(float)  # 500 ... 900 ms
        return int(np.sum(np.signbit(x[1:]) != np.signbit(x[:-1])))

    ratio = crossings(34) / crossings(22 + 12)  # same note: ratio 1 (sanity)
    assert ratio == 1
    assert crossings(46) / crossings(34) == pytest.approx(2.0, rel=0.03)
    assert crossings(33) / 2 / 0.4 == pytest.approx(55.0, rel=0.03)


def test_tail_note_coercion() -> None:
    for value in (33, 33.0, np.int64(33), np.int32(33), np.float64(33.0)):
        p = resolve_kick_params({**V03, "tail_note": value})
        assert p["pitch_end_hz"] == 55.0
    for value in (33.5, "33", True, 22, 47):
        with pytest.raises(KickParamsError):
            resolve_kick_params({**V03, "tail_note": value})


def test_tail_note_errors_are_readable() -> None:
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V03, "tail_note": 33, "pitch_end_hz": 55})
    text = str(exc.value)
    assert "- tail_note: cannot be combined with pitch_end_hz" in text
    assert "should not be valid under" not in text
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V03, "tail_note": 22})
    lines = str(exc.value).splitlines()[1:]
    assert lines == ["- tail_note: 22 is less than the minimum of 23"]  # no "unexpected" line
    for note in (46, 46.0, np.int64(46)):  # coerced to int before the message is written
        with pytest.raises(KickParamsError) as exc:
            resolve_kick_params({**V03, "tail_note": note, "pitch_start_hz": 100})
        assert "tail_note 46 (116.5409 Hz) must not be higher than pitch_start_hz (100)" in str(
            exc.value)


def test_tail_note_of_needs_an_exact_note_frequency() -> None:
    assert tail_note_of({"pitch_end_hz": 55.0}) == 33
    assert tail_note_of({"pitch_end_hz": 55}) == 33  # same number
    assert tail_note_of({"pitch_end_hz": 41.2}) is None
    assert tail_note_of({"pitch_end_hz": 48}) is None
    assert tail_note_of({}) is None


# --- click_decay_ms and click_q ------------------------------------------------------------------


@pytest.mark.parametrize("decay", [0.5, 1.0, 3.0, 3.1, 7.25, 12.0])
def test_click_window_and_fade(decay) -> None:
    sr = 48000
    c = K._click(sr, sr, 3500.0, 7, decay, 0.9)
    window = round(max(15.0, 5 * decay) * sr / 1000)
    assert np.all(c[window:] == 0.0) and c[window - 1] == 0.0  # ends in its fade at zero
    assert c[0] == 0.0 and np.max(np.abs(c)) == pytest.approx(1.0)
    assert np.count_nonzero(c[window - 200 : window - 1]) > 0  # the window is used up to the end


def test_longer_click_decay_puts_more_energy_into_the_first_10_ms() -> None:
    sr = 48000
    shares = []
    for decay in (0.5, 1.5, 3.0, 6.0, 12.0):
        c = K._click(sr, sr, 3500.0, 7, decay, 0.9)
        shares.append(float(np.sum(c[:480] ** 2)))  # same peak (1.0) for every decay
    assert shares == sorted(shares) and shares[-1] > 3 * shares[0]


def _bandwidth_octaves(c: np.ndarray, sr: int, centre: float) -> float:
    """Spectral spread around the centre: RMS distance in octaves, energy-weighted."""
    spec = np.abs(np.fft.rfft(c, 1 << 17)) ** 2
    f = np.fft.rfftfreq(1 << 17, 1 / sr)
    keep = f > 50
    octaves = np.log2(f[keep] / centre)
    return float(np.sqrt(np.sum(spec[keep] * octaves**2) / np.sum(spec[keep])))


def test_higher_click_q_narrows_the_click() -> None:
    sr = 48000
    spreads = [_bandwidth_octaves(K._click(sr, sr, 3000.0, 11, 12.0, q), sr, 3000.0)
               for q in (0.5, 0.9, 2.0, 4.0, 8.0)]
    assert spreads == sorted(spreads, reverse=True), spreads
    assert spreads[0] > 2 * spreads[-1]


@pytest.mark.parametrize("i", range(10))
def test_click_fields_over_their_range(i) -> None:
    rng = random.Random(50120 + i)
    req = {**_random_v02_fields(rng), "schema_version": "0.3", "click_level": rng.uniform(0.2, 1),
           "click_decay_ms": rng.uniform(0.5, 12), "click_q": rng.uniform(0.5, 8)}
    w, audio, p = render_kick_wav(req)
    ints = wav_ints(w)
    assert ints[0] == 0 and ints[-1] == 0
    full = 2 ** (p["bit_depth"] - 1) - 1
    assert np.max(np.abs(ints)) / full <= 10 ** (p["peak_ceiling_dbfs"] / 20) + 1e-12
    # Each field moves the output (P3: every exposed parameter changes the sound measurably).
    for field, other in (("click_decay_ms", 0.5 if req["click_decay_ms"] > 6 else 12),
                         ("click_q", 0.5 if req["click_q"] > 4 else 8)):
        assert wav({**req, field: other}) != w, field


# --- polarity ----------------------------------------------------------------------------------


@pytest.mark.parametrize("i", range(10))
def test_polarity_minus_one_is_the_exact_negation(i) -> None:
    rng = random.Random(60120 + i)
    req = {**_random_v02_fields(rng), "schema_version": "0.3",
           "clip_db": rng.choice([0, rng.uniform(0, 12)]), "offset_ms": rng.uniform(0, 12)}
    plus, minus = wav_ints(wav({**req, "polarity": 1})), wav_ints(wav({**req, "polarity": -1}))
    assert np.array_equal(minus, -plus)
    assert np.any(plus != 0)


@pytest.mark.parametrize("value", [1, 1.0, np.int64(1), -1, -1.0, np.int64(-1), np.float32(-1)])
def test_polarity_coercion(value) -> None:
    p = resolve_kick_params({**V03, "polarity": value})
    assert p["polarity"] == int(value) and type(p["polarity"]) is int
    json.dumps(p)


@pytest.mark.parametrize("value", [0, 2, -0.5, True, False, "1", None])
def test_polarity_rejects_other_values(value) -> None:
    with pytest.raises(KickParamsError):
        resolve_kick_params({**V03, "polarity": value})


# --- offset_ms ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset_ms", "sr", "expected"),
    [(0, 48000, 0), (0.01, 48000, 0), (0.0105, 48000, 1), (5, 48000, 240), (12, 48000, 576),
     (12, 44100, 529), (1 / 48, 48000, 1), (0.5, 44100, 22), (5, 44100, 220)],
)
def test_offset_is_whole_samples(offset_ms, sr, expected) -> None:
    # round(offset_ms * sr / 1000), round half to even: 5 ms at 44.1 kHz = 220.5 -> 220 (the
    # same rounding as the 5 ms fade-out); 0.5 ms at 44.1 kHz = 22.05 -> 22.
    assert K.offset_samples({"offset_ms": offset_ms, "sample_rate": sr}) == expected


@pytest.mark.parametrize("i", range(10))
def test_offset_is_exact_silence_then_the_shorter_kick(i) -> None:
    """The lead-in holds exact zeros, the file length stays, and what follows is the same
    kick rendered n - n_off samples long without offset (chain position: after the DC
    blocker, the mean correction and the normalisation)."""
    rng = random.Random(70120 + i)
    sr = rng.choice([44100, 48000])
    n_off = rng.randint(1, int(12 * sr / 1000))
    n = rng.randint(int(0.1 * sr), int(0.6 * sr))
    # Whole-sample lengths so both renders have exact sample counts: ms = samples * 1000 / sr.
    req = {**_random_v02_fields(rng), "schema_version": "0.3", "sample_rate": sr,
           "length_ms": n * 1000 / sr, "offset_ms": n_off * 1000 / sr,
           "clip_db": rng.choice([0, rng.uniform(0, 12)])}
    if K.offset_samples(req) != n_off or K.file_samples(req) != n:
        pytest.skip("float rounding of the chosen lengths")
    with_off = wav_ints(wav(req))
    without = wav_ints(wav({**req, "offset_ms": 0, "length_ms": (n - n_off) * 1000 / sr}))
    assert len(with_off) == n
    assert np.all(with_off[:n_off] == 0)
    assert np.array_equal(with_off[n_off:], without)


def test_offset_moves_the_onset_by_the_offset() -> None:
    """Behaviour: the first sample above 10 % of peak moves by n_off samples."""
    def onset(off):
        x = np.abs(wav_ints(wav({**V03, "offset_ms": off, "click_level": 0})))
        return int(np.flatnonzero(x > 0.1 * x.max())[0])

    assert onset(5) - onset(0) == 240
    assert onset(12) - onset(0) == 576


# --- clip_db (aliasing in test_clip_aliasing.py) -------------------------------------------------


def test_clip_zero_keeps_the_bytes() -> None:
    req = {**V03, "seed": 9, "drive": 0.45}
    assert wav({**req, "clip_db": 0}) == wav(req) == wav({**req, "clip_db": 0.0})


def _crest_db(ints: np.ndarray) -> float:
    x = ints.astype(float)
    return 20 * math.log10(np.max(np.abs(x)) / math.sqrt(np.mean(x**2)))


@pytest.mark.parametrize("i", range(6))
def test_clip_lowers_the_crest_factor(i) -> None:
    """3 and 6 dB lower the crest factor step by step; 12 dB stays below the unclipped one.

    Not monotonic up to 12 dB: on kicks that decay little inside the file (seeds 80120 and
    80125, amp_decay_ms > 1500 in a 300 ms file) crest 6 dB < crest 12 dB. Measured cause:
    the band-limited clip overshoots between the flat parts (peak / 99th percentile of |x|
    1.08 and 1.18 at 12 dB, against 1.01 unclipped), and the ceiling follows the overshoot.
    """
    rng = random.Random(80120 + i)
    req = {**_random_v02_fields(rng), "schema_version": "0.3", "length_ms": 300}
    c0, c3, c6, c12 = (_crest_db(wav_ints(wav({**req, "clip_db": db}))) for db in (0, 3, 6, 12))
    assert c0 > c3 > c6, (c0, c3, c6)
    assert c0 - c3 > 0.5 and c0 - c12 > 1.0, (c0, c3, c12)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / math.sqrt(np.dot(a, a) * np.dot(b, b)))


def test_clip_leaves_the_quiet_tail_clean(monkeypatch) -> None:
    """Behaviour: clip 6 dB flattens the attack and leaves the tail the same up to a level
    factor (correlation over 200 ... 400 ms).

    Measured 0.99849, not 1: the mean correction (Hann-shaped, over the whole file) carries
    the changed mean of the clipped attack into the tail. With ``_remove_mean`` switched off
    the correlation is 1.0 to 6 digits, so the clip itself leaves the tail untouched."""
    req = {**V03, "seed": 4, "drive": 0, "length_ms": 450}
    seg = slice(9600, 19200)
    a = wav_ints(wav(req)).astype(float)[seg]
    b = wav_ints(wav({**req, "clip_db": 6})).astype(float)[seg]
    assert _corr(a, b) > 0.998
    monkeypatch.setattr(K, "_remove_mean", lambda x: x)
    a2 = K.render_kick(req)[0][seg]
    b2 = K.render_kick({**req, "clip_db": 6})[0][seg]
    assert _corr(a2, b2) > 0.999999
    # The attack is changed: the first 20 ms differ clearly.
    assert _corr(K.render_kick(req)[0][:960], K.render_kick({**req, "clip_db": 6})[0][:960]) < (
        0.995)


@pytest.mark.parametrize(("sr", "clip_db"), [(48000, 12.0), (44100, 6.0), (48000, 3.0)])
def test_clip_sits_before_the_end_fade_out(sr, clip_db) -> None:
    """Chain position (contract: clip before the fade-out). A kick still loud at its end
    (amp_decay_ms 2000 in 150 ms): the last 5 ms follow the falling raised cosine of the fade,
    |x[i]| <= peak * w[i]. A clip after the fade would flatten the start of the fade at the
    clip level (|x| near the peak where w is 0.5)."""
    req = {**V03, "seed": 3, "sample_rate": sr, "length_ms": 150, "amp_decay_ms": 2000,
           "click_level": 0, "drive": 0, "clip_db": clip_db}
    x = np.abs(wav_ints(wav(req)).astype(float))
    m = round(0.005 * sr)
    w = (0.5 * (1 - np.cos(np.linspace(0, math.pi, m))))[::-1]
    tail = x[-m:]
    assert np.all(tail <= x.max() * w + 0.002 * x.max()), float(np.max(tail / x.max() - w))


@pytest.mark.parametrize("i", range(8))
def test_clip_over_its_range_keeps_the_ceiling_and_zero_ends(i) -> None:
    rng = random.Random(90120 + i)
    req = {**_random_v02_fields(rng), "schema_version": "0.3", "clip_db": rng.uniform(0, 12)}
    w, _, p = render_kick_wav(req)
    ints = wav_ints(w)
    full = 2 ** (p["bit_depth"] - 1) - 1
    assert ints[0] == 0 and ints[-1] == 0
    assert np.max(np.abs(ints)) / full <= 10 ** (p["peak_ceiling_dbfs"] / 20) + 1e-12


# --- every v0.3 field together: resolved form and sidecar --------------------------------------


def _random_v03_request(rng: random.Random) -> dict:
    req = {**_random_v02_fields(rng), "schema_version": "0.3"}
    for name, lo, hi in (("click_decay_ms", 0.5, 12), ("click_q", 0.5, 8), ("offset_ms", 0, 12),
                         ("clip_db", 0, 12)):
        if rng.random() < 0.6:
            req[name] = rng.choice([lo, hi, rng.uniform(lo, hi)])
    if rng.random() < 0.6:
        req["polarity"] = rng.choice([1, -1])
    if rng.random() < 0.5:
        req.pop("pitch_end_hz", None)
        req["tail_note"] = rng.randint(23, 46)
        req["pitch_start_hz"] = max(req.get("pitch_start_hz", 220), 117)
    return req


@pytest.mark.parametrize("i", range(16))
def test_resolved_form_is_valid_idempotent_and_rerenders(tmp_path, i) -> None:
    req = _random_v03_request(random.Random(100120 + i))
    p = resolve_kick_params(req)
    Draft202012Validator(load_schema(KICK_SCHEMA_FILE)).validate(p)
    assert not {"tail_note", "length_beats"} & set(p)
    assert resolve_kick_params(p) == p
    assert resolve_kick_params(json.loads(json.dumps(p))) == p
    assert wav(p) == wav(req)
    wav_path, json_path = write_kick(req, tmp_path)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    assert meta["parameters"]["schema_version"] == "0.3"
    assert rerender_from_sidecar(json_path) == wav_path.read_bytes()
    if "tail_note" in req:
        assert tail_note_of(meta["parameters"]) == req["tail_note"]


# --- error wording and validity (D-002: messages go back to Claude) ------------------------------


def test_unknown_and_early_fields_are_named_once() -> None:
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V02, "click_q": 2.0, "polarity": -1, "wobble": 1})
    lines = str(exc.value).splitlines()[1:]
    assert lines == [
        "- click_q, polarity: kick-params v0.3 field(s), only allowed with schema_version "
        "\"0.3\" (this document has schema_version '0.2')",
        "- (root): unknown field(s) 'wobble'",
    ]
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V03, "click_q": 9, "wobble": 1})
    lines = str(exc.value).splitlines()[1:]
    assert lines == ["- (root): unknown field(s) 'wobble'",
                     "- click_q: 9 is greater than the maximum of 8"]


@pytest.mark.parametrize("i", range(300))
def test_engine_accepts_exactly_what_the_schema_accepts(i) -> None:
    """Seeded: random documents near the v0.3 edges (wrong version, out of range, exclusions,
    unknown keys). Apart from the engine's own checks (pitch order, beats range, rule), a
    document is refused iff the schema refuses it."""
    rng = random.Random(110120 + i)
    doc = {"schema_version": rng.choice(["0.2", "0.3", "0.3", "0.4"]), "seed": 1}
    pool = {
        "tail_note": [22, 23, 33, 46, 47, 33.0, 33.5], "polarity": [1, -1, 0, 1.0],
        "click_q": [0.4, 0.5, 8, 8.1], "click_decay_ms": [0.4, 0.5, 12, 12.5],
        "offset_ms": [-1, 0, 12, 12.1], "clip_db": [-0.1, 0, 12, 13],
        "pitch_end_hz": [30, 55, 121], "length_ms": [80, 450], "wobble": [1],
        "length_beats": [0.1, 1, 5], "bpm": [128],
    }
    for key, values in pool.items():
        if rng.random() < 0.25:
            doc[key] = rng.choice(values)
    schema_ok = Draft202012Validator(load_schema(KICK_SCHEMA_FILE)).is_valid(doc)
    if schema_ok and "length_beats" in doc:
        doc["amp_decay_ms"] = 20  # keep the rule cheap: one render
    try:
        resolve_kick_params(doc)
        engine_ok = True
    except KickParamsError as exc:
        engine_ok = False
        text = str(exc)
        own_check = any(s in text for s in ("must not be higher", "80 ... 2000 ms", "decay"))
    assert engine_ok == schema_ok or (schema_ok and own_check), doc
