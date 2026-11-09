"""Goa clip mode (D-035, #546): one looping .mid per voice, no song form.

The MIDI is read back with a parser written here (not the module's writer), and scales,
windows and note counts are written out in the test from the documented rules.
"""

from __future__ import annotations

import random
import struct

import pytest

from audio_engine import goa_clips

# Pitch classes relative to the root, written here independently of goa_melody.SCALES.
SCALE_STEPS = {
    "phrygian": {0, 1, 3, 5, 7, 8, 10},
    "phrygian_dominant": {0, 1, 4, 5, 7, 8, 10},
    "harmonic_minor": {0, 2, 3, 5, 7, 8, 11},
    "aeolian": {0, 2, 3, 5, 7, 8, 10},
}
ROOTS = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6,
         "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
# documented windows (lowest, highest MIDI note) before the register shift
WINDOW = {"lead": (60, 83), "arp": (57, 80), "pad": (48, 59), "pluck": (36, 59)}


def parse_smf(data: bytes) -> dict:
    """Minimal independent SMF reader: format, ppq, tempo, notes (abs ticks), end tick."""
    assert data[:4] == b"MThd"
    _, fmt, ntrk, ppq = struct.unpack(">IHHH", data[4:14])
    assert data[14:18] == b"MTrk"
    (length,) = struct.unpack(">I", data[18:22])
    body = data[22:22 + length]
    assert len(data) == 22 + length
    i, tick, tempo, name, end = 0, 0, None, None, None
    on: dict[int, tuple[int, int]] = {}
    notes = []
    while i < len(body):
        delta = 0
        while True:
            b = body[i]
            i += 1
            delta = (delta << 7) | (b & 0x7F)
            if b < 0x80:
                break
        tick += delta
        st = body[i]
        if st == 0xFF:
            typ, ln = body[i + 1], body[i + 2]
            payload = body[i + 3:i + 3 + ln]
            i += 3 + ln
            if typ == 0x51:
                tempo = int.from_bytes(payload, "big")
            elif typ == 0x03:
                name = payload.decode("ascii")
            elif typ == 0x2F:
                end = tick
                assert i == len(body)
        elif st & 0xF0 == 0x90:
            pitch, vel = body[i + 1], body[i + 2]
            assert pitch not in on, "same pitch started while sounding"
            on[pitch] = (tick, vel)
            i += 3
        elif st & 0xF0 == 0x80:
            pitch = body[i + 1]
            s, vel = on.pop(pitch)
            notes.append((s, tick, pitch, vel))
            i += 3
        else:
            raise AssertionError(f"unexpected status {st:#x}")
    assert not on, "note without note-off"
    return {"format": fmt, "tracks": ntrk, "ppq": ppq, "tempo": tempo, "name": name,
            "end": end, "notes": sorted(notes)}


def _random_options(rng: random.Random) -> dict:
    voices = rng.sample(list(goa_clips.VOICES), rng.randint(1, 4))
    o = {"seed": rng.randint(0, 10**6), "bars": rng.randint(1, 16),
         "bpm": round(rng.uniform(135, 150), 2), "root": rng.choice(list(ROOTS)),
         "scale": rng.choice(list(SCALE_STEPS)),
         "arp_pattern": rng.choice(["up", "down", "updown", "random"]),
         "progression": [rng.randint(0, 6) for _ in range(rng.randint(1, 16))],
         "voices": voices}
    if rng.random() < 0.5:
        o["density"] = {v: rng.choice([0.0, 1.0, round(rng.random(), 3)])
                        for v in goa_clips.VOICES}
    else:
        o["density"] = round(rng.random(), 3)
    o["register"] = {v: rng.randint(-2, 2) for v in goa_clips.VOICES}
    return o


def _half_up(x: float) -> int:
    return int(x + 0.5)


def _check_clip(voice: str, opts: dict) -> None:
    m = parse_smf(goa_clips.clip_to_midi(voice, **opts))
    bars = opts.get("bars", 4)
    assert m["format"] == 0 and m["tracks"] == 1 and m["ppq"] == 480
    assert m["end"] == bars * 4 * 480, "loop length must be exact in ticks"
    assert m["tempo"] == round(60_000_000 / opts.get("bpm", 145))
    assert m["name"] == f"Goa {voice}"
    rpc = ROOTS[opts.get("root", "A")]
    allowed = {(rpc + s) % 12 for s in SCALE_STEPS[opts.get("scale", "phrygian")]}
    reg = opts.get("register", {}).get(voice, 0)
    lo, hi = WINDOW[voice][0] + 12 * reg, WINDOW[voice][1] + 12 * reg
    for s, e, pitch, vel in m["notes"]:
        assert pitch % 12 in allowed, (voice, pitch)
        assert lo <= pitch <= hi, (voice, pitch, lo, hi)
        assert 0 <= s < e <= m["end"] and 1 <= vel <= 127
    d = opts["density"][voice] if isinstance(opts.get("density"), dict) \
        else opts.get("density", {"lead": 0.6, "arp": 1.0, "pad": 0.0, "pluck": 0.5}[voice])
    n = len(m["notes"])
    if voice == "lead":
        assert n == bars * _half_up(d * 8)
    elif voice in ("arp", "pluck"):
        assert n == bars * _half_up(d * 16)
    else:
        chord_bars = 4 - _half_up(3 * d)
        slots = _expected_slots(bars, len(opts.get("progression", [0, 5, 6, 4])))
        runs = [sum(1 for s in slots if s == k) for k in sorted(set(slots))]
        assert n == 3 * sum(-(-r // chord_bars) for r in runs)  # one triad per strike
    if voice in ("arp", "pad"):
        prog = opts.get("progression", [0, 5, 6, 4])
        slots = _expected_slots(bars, len(prog))
        for s, _, pitch, _ in m["notes"]:
            want = _triad(rpc, opts.get("scale", "phrygian"), prog[slots[s // 1920]])
            assert pitch % 12 in want, (voice, s, pitch, want)


def _expected_slots(bars: int, k: int) -> list[int]:
    """Spec (coordinator, #546): spread K chords evenly over the bars; fewer bars than
    chords -> the first `bars` chords, one per bar."""
    if bars < k:
        return list(range(bars))
    out = []
    for b in range(bars):
        out.append(int(b * k / bars + 1e-9))  # float route, not the module's integer //
    return out


def _triad(rpc: int, scale: str, degree: int) -> set[int]:
    steps = sorted(SCALE_STEPS[scale])
    return {(rpc + steps[(degree + j) % 7]) % 12 for j in (0, 2, 4)}


@pytest.mark.parametrize("voice", goa_clips.VOICES)
def test_default_clip_is_four_bars_in_scale(voice):
    _check_clip(voice, {"seed": 7})
    assert goa_clips.clip_length_ticks(seed=7) == 7680


@pytest.mark.parametrize("bars", [1, 3, 16])
def test_loop_length_exact_in_ticks(bars):
    for v in goa_clips.VOICES:
        assert parse_smf(goa_clips.clip_to_midi(v, seed=1, bars=bars))["end"] == bars * 1920


# A phrygian (A Bb C D E F G), triads written out by hand (pitch classes):
# degree 0 = A C E, 5 = F A C, 6 = G Bb D, 4 = E G Bb
TRIAD_A_PHRYGIAN = {0: {9, 0, 4}, 5: {5, 9, 0}, 6: {7, 10, 2}, 4: {4, 7, 10}}


@pytest.mark.parametrize(("bars", "degrees_per_bar"), [
    (4, [0, 5, 6, 4]),
    (8, [0, 0, 5, 5, 6, 6, 4, 4]),
    (5, [0, 0, 5, 6, 4]),
    (2, [0, 5]),
    (1, [0]),
    (16, [0] * 4 + [5] * 4 + [6] * 4 + [4] * 4),
])
@pytest.mark.parametrize("pad_density", [0.0, 0.5, 1.0])
def test_pad_and_arp_run_through_the_progression(bars, degrees_per_bar, pad_density):
    opts = {"seed": 2, "bars": bars, "progression": [0, 5, 6, 4],
            "density": {"pad": pad_density, "arp": 1.0}}
    pad = parse_smf(goa_clips.clip_to_midi("pad", **opts))["notes"]
    arp = parse_smf(goa_clips.clip_to_midi("arp", **opts))["notes"]
    for b, deg in enumerate(degrees_per_bar):
        mid = b * 1920 + 960  # middle of bar b: which pad notes sound there?
        sounding = {p % 12 for s, e, p, _ in pad if s <= mid < e}
        assert sounding == TRIAD_A_PHRYGIAN[deg], (b, sounding)
        in_bar = {p % 12 for s, _, p, _ in arp if b * 1920 <= s < (b + 1) * 1920}
        assert in_bar and in_bar <= TRIAD_A_PHRYGIAN[deg], (b, in_bar)
    text = goa_clips.render_readme({"pad": "x", "arp": "y", "lead": "z", "pluck": "w"},
                                   **opts)
    assert "chord per bar (arp and pad): " + ", ".join(map(str, degrees_per_bar)) in text


def test_song_mode_pad_unchanged():
    # goa_melody keeps its own rule: density 0 -> one 4-bar chord on the first degree
    from audio_engine import goa_melody
    o = goa_melody.normalise({"seed": 2, "length": 4})
    notes = goa_melody.voice_pattern("pad", o, 1.0)["notes"]
    assert [(n["pitch"], n["start"], n["duration"]) for n in notes] == \
        [(48, 0.0, 15.9375), (52, 0.0, 15.9375), (57, 0.0, 15.9375)]


def test_same_options_same_bytes_other_seed_other_bytes():
    a = goa_clips.build_clips(seed=42, bars=8, root="F#", scale="harmonic_minor")
    b = goa_clips.build_clips(seed=42, bars=8, root="F#", scale="harmonic_minor")
    c = goa_clips.build_clips(seed=43, bars=8, root="F#", scale="harmonic_minor")
    assert a == b and list(a) == list(goa_clips.VOICES)
    assert a["lead"] != c["lead"] and a["pluck"] != c["pluck"]


def test_property_random_options_over_full_range():
    rng = random.Random(546)
    for _ in range(60):
        opts = _random_options(rng)
        clips = goa_clips.build_clips(**opts)
        assert list(clips) == [v for v in goa_clips.VOICES if v in opts["voices"]]
        for v in clips:
            _check_clip(v, opts)
            assert clips[v] == goa_clips.clip_to_midi(v, **opts)


@pytest.mark.parametrize("bad", [
    {"bars": 0}, {"bars": 17}, {"bars": 2.0}, {"bars": True},
    {"sections": []}, {"energy": 1.0}, {"title": "x"}, {"length": 4},
    {"bpm": 151}, {"scale": "dorian"}, {"density": 1.5}, {"register": 3},
])
def test_invalid_options_raise(bad):
    with pytest.raises(ValueError):
        goa_clips.build_clips(seed=0, **bad)


def test_write_clips_one_file_per_voice_and_refuses_existing(tmp_path):
    mids, readme = goa_clips.write_clips(tmp_path / "out", seed=5, bars=2, voices=["pad", "lead"])
    assert [p.name for p in mids] == ["goa_lead_seed5_145bpm_2bars.mid",
                                      "goa_pad_seed5_145bpm_2bars.mid"]
    assert mids[0].read_bytes() == goa_clips.clip_to_midi("lead", seed=5, bars=2)
    text = readme.read_text(encoding="utf-8")
    assert "Not tested in Live" in text and "section" not in text.lower()
    before = {p: p.read_bytes() for p in (tmp_path / "out").iterdir()}
    with pytest.raises(FileExistsError):
        goa_clips.write_clips(tmp_path / "out", seed=5, bars=2, voices=["lead", "arp"])
    after = {p: p.read_bytes() for p in (tmp_path / "out").iterdir()}
    assert after == before  # the arp clip was not written either


def test_write_failure_removes_partial_files(tmp_path, monkeypatch):
    import builtins
    real_open = builtins.open
    calls = {"n": 0}

    def flaky(path, mode="r", *a, **k):
        if "x" in mode:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError(28, "No space left on device")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", flaky)
    with pytest.raises(OSError):
        goa_clips.write_clips(tmp_path, seed=1)
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_clips(tmp_path, capsys):
    rc = goa_clips.main(["--out", str(tmp_path / "c"), "--seed", "9", "--bars", "1",
                         "--density", "lead=1,arp=0.5", "--register", "pad=-1",
                         "--voices", "lead,arp,pad"])
    assert rc == 0
    names = sorted(p.name for p in (tmp_path / "c").iterdir())
    assert names == ["README.md", "goa_arp_seed9_145bpm_1bars.mid",
                     "goa_lead_seed9_145bpm_1bars.mid", "goa_pad_seed9_145bpm_1bars.mid"]
    lead = parse_smf((tmp_path / "c" / "goa_lead_seed9_145bpm_1bars.mid").read_bytes())
    assert len(lead["notes"]) == 8 and lead["end"] == 1920
    assert goa_clips.main(["--out", str(tmp_path / "c"), "--seed", "9", "--bars", "1"]) == 2
    assert goa_clips.main(["--out", str(tmp_path / "d"), "--bars", "20"]) == 2
    assert "bars must be" in capsys.readouterr().err
