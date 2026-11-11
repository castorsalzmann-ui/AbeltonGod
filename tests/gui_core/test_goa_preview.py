"""Goa clip preview (D-035 (2), #546, #571): saw, resonant filter, glide, ping-pong echoes.

No sound-quality claim: the checks are bytes, lengths, peaks, measured pitch (spectrum,
instantaneous frequency), spectral centroid and echo positions. Expected values are written
here; the notes are constructed here (plain events), so the checks hold for any generator.
"""

from __future__ import annotations

import dataclasses
import random
import struct

import numpy as np
import pytest

from audio_engine import goa_clips
from gui_core import goa_preview as gp
from gui_core import preview_dsp as dsp
from gui_core.goa_preview import PreviewNote as N

SR = 44100
ECHOES = {"lead": 7, "arp": 7, "pluck": 6, "pad": 0}  # derived in test_preview_dsp (wet 0.3/0.15)
MONO_VOICES = ("lead", "arp", "pluck")


def centroid(x: np.ndarray) -> float:
    power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    return float(np.sum(power * np.fft.rfftfreq(len(x), 1 / SR)) / np.sum(power))


def window(x: np.ndarray, start_s: float, seconds: float, offset: int = 0) -> np.ndarray:
    a = offset + int(start_s * SR)
    return x[a: a + int(seconds * SR)]


# --- with the clip generator's options (what the GUI calls) ----------------------------------
@pytest.mark.parametrize("voice", goa_clips.VOICES)
def test_voice_preview_deterministic_length_peak(voice):
    a = gp.voice_preview_wav_bytes(voice, seed=3, bars=2, bpm=140)
    assert a == gp.voice_preview_wav_bytes(voice, seed=3, bars=2, bpm=140)
    assert a[:4] == b"RIFF" and a[8:12] == b"WAVE"
    assert struct.unpack("<HHIIHH", a[20:36]) == (1, 2, SR, SR * 4, 4, 16)  # PCM stereo 16 bit
    x = gp.render_voice_preview(voice, seed=3, bars=2, bpm=140)
    # 2 bars of 4 beats at 140 bpm = 3.4286 s, plus the 0.5 s tail, plus the echoes: 3
    # sixteenths at 140 bpm = 0.32143 s = 14175 samples each
    assert x.ndim == 2 and x.shape[1] == 2
    assert abs(len(x) - ((8 * 60 / 140 + 0.5) * SR + ECHOES[voice] * 14175)) <= 1
    assert abs(gp.preview_seconds(seed=3, bars=2, bpm=140, voices=[voice]) - len(x) / SR) < 1e-9
    assert x.dtype == np.float32 and np.all(np.isfinite(x))
    # peak 0.8 whenever the generator wrote a note for this voice (whatever the notes are)
    assert goa_clips.clip_notes(voice, seed=3, bars=2, bpm=140), "seed 3 gives no notes"
    assert abs(float(np.max(np.abs(x))) - 0.8) < 1e-6
    assert not x[-1].any()  # the buffer ends in exact silence
    assert len(a) == 44 + 4 * len(x)


def test_mix_preview_deterministic_and_uses_every_voice():
    m = gp.mix_preview_wav_bytes(seed=11, bars=1)
    assert m == gp.mix_preview_wav_bytes(seed=11, bars=1)
    mix = gp.render_mix_preview(seed=11, bars=1)
    assert abs(float(np.max(np.abs(mix))) - 0.8) < 1e-6
    singles = {v: gp.render_voice_preview(v, seed=11, bars=1) for v in goa_clips.VOICES}
    assert len(mix) == max(len(s) for s in singles.values())
    for v, s in singles.items():
        assert not np.allclose(mix[: len(s)], s, atol=1e-3), v
    only_pad = gp.render_mix_preview(seed=11, bars=1, voices=["pad"])
    np.testing.assert_allclose(only_pad, singles["pad"], atol=1e-6)
    no_lead = gp.render_mix_preview(seed=11, bars=1, voices=["arp", "pad", "pluck"])
    assert not np.allclose(no_lead, mix, atol=1e-3)
    # two voices: the mix is lead (gain 1.0) + pad (gain 0.6), each at its own peak,
    # renormalised to 0.8; rebuilt here from the single-voice previews (the pad has no echoes
    # and is shorter)
    two = gp.render_mix_preview(seed=11, bars=1, voices=["lead", "pad"])
    ref = singles["lead"] / 0.8
    ref[: len(singles["pad"])] += 0.6 * singles["pad"] / 0.8
    ref = ref * (0.8 / np.max(np.abs(ref)))
    np.testing.assert_allclose(two, ref, atol=2e-3)


def test_longest_clip_is_bounded():
    x = gp.render_mix_preview(seed=0, bars=16, bpm=135)
    assert len(x) / SR <= gp.MAX_SECONDS == 32.0
    # 64 beats at 135 bpm + 0.5 s + 7 echoes of 3 sixteenths (1/3 s each)
    assert abs(len(x) / SR - (64 * 60 / 135 + 0.5 + 7 / 3)) < 1e-3


def test_property_random_options():
    rng = random.Random(5460)
    for _ in range(8):
        opts = {"seed": rng.randint(0, 10**6), "bars": rng.randint(1, 16),
                "bpm": round(rng.uniform(135, 150), 1),
                "root": rng.choice(["A", "C#", "Eb", "G", "B"]),
                "scale": rng.choice(["phrygian", "phrygian_dominant", "harmonic_minor",
                                     "aeolian"]),
                "density": round(rng.random(), 2), "register": rng.randint(-2, 2),
                "arp_pattern": rng.choice(["up", "down", "updown", "random"])}
        v = rng.choice(list(goa_clips.VOICES))
        x = gp.render_voice_preview(v, **opts)
        assert np.all(np.isfinite(x)) and len(x) / SR <= gp.MAX_SECONDS
        echo = round(3 * 60 / opts["bpm"] / 4 * SR)
        assert abs(len(x) - ((opts["bars"] * 240 / opts["bpm"] + 0.5) * SR
                             + ECHOES[v] * echo)) <= 1
        peak = float(np.max(np.abs(x)))
        assert peak == 0.0 or abs(peak - 0.8) < 1e-6
        assert peak > 0 or not goa_clips.clip_notes(v, **opts)
        assert not x[-1].any()


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        gp.render_voice_preview("bass", seed=0)
    with pytest.raises(ValueError):
        gp.render_mix_preview(seed=0, bars=17)
    with pytest.raises(ValueError):
        gp.voice_preview_wav_bytes("lead", sections=[])
    with pytest.raises(ValueError):
        gp.render_events("bass", [], 140, 4)
    with pytest.raises(ValueError):
        gp.render_events_mix({"lead": [], "bass": []}, 140, 4)
    for bpm, beats in ((0, 4), (float("nan"), 4), (140, 0), (140, -1)):
        with pytest.raises(ValueError):
            gp.render_events("lead", [N(60, 0, 1, 100)], bpm, beats)
    with pytest.raises(ValueError):  # 64 beats at 100 bpm = 38.4 s: above MAX_SECONDS
        gp.render_events("pad", [N(60, 0, 1, 100)], 100, 64)
    assert gp.PREVIEW_LABEL == "grobe Vorschau"


# --- with constructed note events -------------------------------------------------------------
@pytest.mark.parametrize("voice", list(gp.VOICES))
def test_no_notes_is_silence_and_events_are_deterministic(voice):
    x = gp.render_events(voice, [], 145, 8)
    assert x.shape[1] == 2 and x.dtype == np.float32 and not x.any()
    # 8 beats at 145 bpm + 0.5 s + echoes of 13686 samples (3 sixteenths at 145 bpm = 0.31034 s)
    assert abs(len(x) - ((8 * 60 / 145 + 0.5) * SR + ECHOES[voice] * 13686)) <= 1
    notes = [N(57, 0.0, 0.6, 120), N(64, 0.5, 0.25, 84), N(60, 1.0, 0.25, 84),
             N(69, 2.5, 1.0, 120), N(57, 3.0, 0.5, 84)]
    a = gp.render_events(voice, notes, 145, 8)
    assert a.tobytes() == gp.render_events(voice, notes, 145, 8).tobytes()
    assert a.tobytes() == gp.render_events(voice, notes[::-1], 145, 8).tobytes()  # order-free
    assert abs(float(np.max(np.abs(a))) - 0.8) < 1e-6


@pytest.mark.parametrize("voice", list(gp.VOICES))
def test_no_sound_before_the_first_note(voice):
    # replaces "silence where no note is": the first note starts on beat 3 at 150 bpm =
    # 1.2 s = sample 52920; everything before it is exactly 0 on both channels.
    x = gp.render_events(voice, [N(60, 3.0, 0.5, 110), N(67, 5.0, 0.5, 110)], 150, 8)
    assert not x[:52920].any()
    assert float(np.max(np.abs(x[52920: 52920 + 4410]))) > 0.05


def test_onsets_follow_the_notes_at_the_clips_tempo():
    # Dry pluck signal (before the echoes): sound where a 16th carries a note, silence where
    # neither it nor the 16th before carries one (note 0.2 beat + 20 ms release ends inside
    # its own 16th at 144 bpm). Four bars, so a tempo error of 2 % moves the last bar's notes
    # by more than a 16th (review of #550).
    steps = [k for k in range(64) if k % 4 == 0 or k in (6, 11, 29, 46, 63)]
    notes = [N(45 + k % 5, k * 0.25, 0.2, 96) for k in steps]
    x = np.abs(gp.render_voice_dry("pluck", notes, 144, 16))
    x = x / np.max(x)
    step = 0.25 * 60 / 144 * SR  # one 16th in samples (float: no rounding drift)
    for k in range(64):
        a = int(k * step + step / 4)
        seg = x[a: a + int(step / 4)]
        if k in steps:
            assert seg.max() > 0.05, k
        elif k - 1 not in steps:
            assert seg.max() < 1e-3, k


# lowest and highest note of each voice's register window (goa_melody.WINDOW), in Hz
@pytest.mark.parametrize("voice,pitch,hz", [
    ("lead", 60, 261.626), ("lead", 83, 987.767), ("arp", 57, 220.000), ("arp", 80, 830.609),
    ("pad", 48, 130.813), ("pad", 59, 246.942), ("pluck", 36, 65.406), ("pluck", 59, 246.942)])
def test_fundamental_sits_at_the_notes_frequency(voice, pitch, hz):
    # One note of 2 s, dry voice signal (an echo is a delayed copy: it ripples the spectrum
    # and moved this estimate by 0.13 % at 65 Hz). Measured: mean frequency of the spectral
    # lines within 3 % of the expected value (lines = bins above 1 % of the strongest bin
    # there; the pad has two, 0.4 % above and below). Tolerance 0.1 % = 1.7 cents. No partial
    # an octave below.
    x = gp.render_voice_dry(voice, [N(pitch, 0, 4, 100)], 120, 4)[: 2 * SR]
    power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    band = (freqs > 0.97 * hz) & (freqs < 1.03 * hz)
    lines = band & (power >= 0.01 * np.max(power[band]))
    measured = float(np.sum(power[lines] * freqs[lines]) / np.sum(power[lines]))
    assert measured == pytest.approx(hz, rel=1e-3)
    assert np.sum(power[band]) > 1e-3 * np.sum(power)  # the line is really there
    below = (freqs > 0.4 * hz) & (freqs < 0.6 * hz)
    assert np.max(power[below]) < 1e-3 * np.max(power[band])


PAD_HZ = {48: 130.81, 49: 138.59, 51: 155.56, 52: 164.81, 53: 174.61, 56: 207.65,
          57: 220.00, 58: 233.08}  # equal temperament, written out


@pytest.mark.parametrize("chord,absent", [
    ((48, 52, 57), (49, 51, 53, 56, 58)),  # a triad (the first clip generator's pad)
    ((52, 57), (49, 51, 53, 56, 58, 48))])  # root plus fifth (the cell generator's pad)
def test_pad_energy_sits_at_its_chord_tones(chord, absent):
    # Constructed pad notes, so the check does not depend on what a generator writes. The
    # strongest bins are the notes' fundamentals or whole multiples of them (saw partials;
    # each line is a pair 0.4 % above and below). At the fundamentals of notes that are NOT
    # in the events (a semitone beside the chord tones) there is less than 1 % of the
    # amplitude found at the weakest chord tone.
    notes = [N(p, 0, 8, 78) for p in chord]
    x = gp.render_events("pad", notes, 145, 8)[:, 0].astype(np.float64)
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    tones = [PAD_HZ[p] for p in chord]
    top = sorted(freqs[np.argsort(spec)[-40:]])
    for f0 in tones:
        assert any(abs(f - f0) < 0.006 * f0 for f in top), (f0, top)
    for f in top:
        assert any(abs(f / f0 - round(f / f0)) * f0 < 0.006 * f + 0.5 for f0 in tones), f

    def level(hz):
        return float(np.max(spec[(freqs > 0.99 * hz) & (freqs < 1.01 * hz)]))

    weakest = min(level(f0) for f0 in tones)
    for p in absent:
        assert level(PAD_HZ[p]) < 0.01 * weakest, p


def test_accent_amount_is_the_higher_of_two_velocity_levels():
    assert gp.ACCENT_VELOCITY_LOW == 84 and gp.ACCENT_VELOCITY_HIGH == 120
    assert [gp.accent_amount(v) for v in (1, 84, 93, 102, 120, 127)] == [0, 0, 0.25, 0.5, 1, 1]


@pytest.mark.parametrize("voice,pitch", [  # lowest, middle, highest note of the voice's window
    ("lead", 60), ("lead", 72), ("lead", 83), ("arp", 57), ("arp", 69), ("arp", 80),
    ("pluck", 36), ("pluck", 48), ("pluck", 59)])
def test_filter_opens_with_the_accent_and_closes_during_the_note(voice, pitch):
    # Spectral centroid of the dry voice signal, one 2-beat note at the start of a 64-beat
    # clip (so the slow ramp adds almost nothing).
    def note(velocity, start=0.0):
        return gp.render_voice_dry(voice, [N(pitch, start, 2, velocity)], 145, 64)

    plain, accented = note(84), note(120)
    first, later = centroid(window(plain, 0, 0.05)), centroid(window(plain, 0.2, 0.05))
    assert centroid(window(accented, 0, 0.05)) > 1.1 * first  # accent lift
    assert centroid(window(accented, 0.2, 0.05)) > 1.1 * later
    assert first > 1.3 * later  # the envelope: the cutoff falls during the note
    assert centroid(window(accented, 0, 0.05)) > 1.3 * centroid(window(accented, 0.2, 0.05))
    # the two levels of the first clip generator (100 and 110-114) are told apart as well
    assert centroid(window(note(114), 0, 0.05)) > 1.05 * centroid(window(note(100), 0, 0.05))
    # slow ramp over the clip: the same note at beat 60 of 64 is brighter (60 beats at
    # 145 bpm = sample 1094897)
    late = note(84, start=60.0)
    assert centroid(window(late, 0, 0.05, offset=1094897)) > 1.1 * first
    # an accent is also louder: (120 / 84) ** 2 = +6.2 dB before the filter moves; RMS of
    # the first 0.4 s
    def rms(x):
        return float(np.sqrt(np.mean(window(x, 0, 0.4) ** 2)))

    assert rms(accented) > 1.2 * rms(plain)


@pytest.mark.parametrize("voice,low,high", [("lead", 60, 83), ("arp", 57, 80),
                                            ("pluck", 36, 59)])
def test_level_is_similar_across_the_register_window(voice, low, high):
    # RMS of one unaccented 2-beat note, lowest against highest note of the window: within a
    # factor of 1.5 (3.5 dB). For lead and arp this needs the cutoff to follow the pitch
    # (key_track); with a fixed band the top note of the lead was 3.5 times the level.
    def rms(pitch):
        x = gp.render_voice_dry(voice, [N(pitch, 0, 2, 84)], 145, 64)
        return float(np.sqrt(np.mean(window(x, 0, 0.9) ** 2)))

    assert 1 / 1.5 < rms(high) / rms(low) < 1.5


def test_pad_has_no_accent_lift_and_fades_in():
    soft = gp.render_voice_dry("pad", [N(52, 0, 4, 84)], 145, 8)
    hard = gp.render_voice_dry("pad", [N(52, 0, 4, 120)], 145, 8)
    np.testing.assert_allclose(hard, soft * (120 / 84) ** 2, rtol=1e-9, atol=1e-12)
    # attack 0.25 s: the first 20 ms are far below the level after 0.3 s
    assert np.max(np.abs(soft[:882])) < 0.15 * np.max(np.abs(window(soft, 0.3, 0.1)))


def instantaneous_hz(x: np.ndarray) -> np.ndarray:
    """Frequency per sample of the one partial between 200 and 300 Hz: phase slope of the
    analytic signal of that band (flat 200-300 Hz, raised-cosine edges down to 140 and up to
    420 Hz, negative frequencies dropped)."""
    spec = np.fft.fft(x)
    freqs = np.fft.fftfreq(len(x), 1 / SR)
    weight = ((freqs >= 200.0) & (freqs <= 300.0)).astype(np.float64)
    rise = (freqs > 140.0) & (freqs < 200.0)
    weight[rise] = 0.5 - 0.5 * np.cos(np.pi * (freqs[rise] - 140.0) / 60.0)
    fall = (freqs > 300.0) & (freqs < 420.0)
    weight[fall] = 0.5 + 0.5 * np.cos(np.pi * (freqs[fall] - 300.0) / 120.0)
    phase = np.unwrap(np.angle(np.fft.ifft(spec * weight)))
    return np.diff(phase) * SR / (2 * np.pi)


@pytest.mark.parametrize("voice", MONO_VOICES)
def test_overlap_glides_and_no_overlap_jumps(voice):
    # MIDI 57 -> 61 = 220.00 -> 277.18 Hz at 120 bpm; the second note starts at beat 0.5 =
    # sample 11025. The measured band holds only the fundamental (2 x 220 = 440 is outside).
    # Stated glide time 40 ms, a straight line in pitch (4 semitones): 1 semitone = 233.08 Hz
    # after 10 ms, 2 = 246.94 Hz after 20 ms, 3 = 261.63 Hz after 30 ms, arrived after 40 ms.
    assert gp.GLIDE_S == 0.040

    def hz_at(notes, ms):
        f = instantaneous_hz(gp.render_voice_dry(voice, notes, 120, 4))
        i = 11025 + int(ms * SR / 1000)
        return float(np.median(f[i - 44: i + 44]))  # 2 ms around the point

    slide = [N(57, 0.0, 0.7, 100), N(61, 0.5, 1.0, 100)]  # overlap: 0.2 beat
    assert hz_at(slide, -20) == pytest.approx(220.00, rel=0.005)
    assert hz_at(slide, 10) == pytest.approx(233.08, rel=0.01)
    assert hz_at(slide, 20) == pytest.approx(246.94, rel=0.01)
    assert hz_at(slide, 30) == pytest.approx(261.63, rel=0.01)
    assert hz_at(slide, 50) == pytest.approx(277.18, rel=0.005)  # arrived (40 ms + 10)
    assert hz_at(slide, 200) == pytest.approx(277.18, rel=0.002)
    jump = [N(57, 0.0, 0.5, 100), N(61, 0.5, 1.0, 100)]  # touching, no overlap
    assert hz_at(jump, -20) == pytest.approx(220.00, rel=0.005)
    # once the first note's release has faded (lead 60, arp 30, pluck 20 ms) the pitch is the
    # second note's; for the pluck that is already true at +30 ms, where a glide is 3/4 done
    faded_ms = {"lead": 80, "arp": 50, "pluck": 30}[voice]
    assert hz_at(jump, faded_ms) == pytest.approx(277.18, rel=0.005)


def test_slide_does_not_restart_the_envelopes():
    # pluck: the amplitude decays (time constant 0.3 s). A slid note continues the first
    # note's envelope, a separate note starts a new one: 0.5 s after the first note's start
    # the slid version is quieter than a freshly started note of the same pitch.
    slide = gp.render_voice_dry("pluck", [N(45, 0, 1.2, 100), N(52, 1.0, 1.0, 100)], 120, 4)
    fresh = gp.render_voice_dry("pluck", [N(45, 0, 0.9, 100), N(52, 1.0, 1.0, 100)], 120, 4)
    rms_slide = float(np.sqrt(np.mean(window(slide, 0.6, 0.1) ** 2)))
    rms_fresh = float(np.sqrt(np.mean(window(fresh, 0.6, 0.1) ** 2)))
    assert 0.02 * rms_fresh < rms_slide < 0.7 * rms_fresh
    # and the first note is cut where the second starts (one voice at a time)
    cut = gp.render_voice_dry("pluck", [N(45, 0, 3.0, 100), N(52, 1.0, 1.0, 100)], 120, 4)
    np.testing.assert_allclose(cut, slide, rtol=0, atol=1e-12)


@pytest.mark.parametrize("voice,bpm,delay,wet", [
    ("lead", 145, 13686, 0.30), ("arp", 145, 13686, 0.30), ("pluck", 145, 13686, 0.15),
    ("lead", 135, 14700, 0.30)])
def test_echoes_three_sixteenths_apart_alternate_sides_and_end_in_silence(voice, bpm, delay,
                                                                          wet):
    # 3 sixteenths at 145 bpm = 0.310345 s = 13686 samples; at 135 bpm = 1/3 s = 14700.
    # One 16th note at the clip start: it and its release end before the first echo.
    # Echo j is the dry note times wet * 0.4^(j-1) / (1 - wet): first left, second right, ...
    assert gp.delay_samples(bpm) == delay
    assert gp.DELAY_SIXTEENTHS == 3 and gp.DELAY_FEEDBACK == 0.40
    x = gp.render_events(voice, [N(64, 0.0, 0.25, 110)], bpm, 4).astype(np.float64)
    dry = x[:delay]
    assert float(np.max(np.abs(dry))) == pytest.approx(0.8, abs=1e-6)
    np.testing.assert_array_equal(dry[:, 0], dry[:, 1])  # the dry note sits in the middle
    count = ECHOES[voice]
    for j in range(1, count + 1):
        seg = x[j * delay: (j + 1) * delay]
        side = (j - 1) % 2
        gain = wet * 0.4 ** (j - 1) / (1 - wet)
        np.testing.assert_allclose(seg[:, side], gain * dry[:, 0], rtol=0, atol=2e-7)
        assert not seg[:, 1 - side].any()  # the other channel is silent during this echo
        assert float(np.max(np.abs(seg))) >= 0.8 * 10 ** (-60 / 20)  # rendered: above -60 dB
    assert not x[(count + 1) * delay:].any()  # silence after the last echo
    assert wet * 0.4 ** count / (1 - wet) < 10 ** (-60 / 20)  # the next one would be below
    # the buffer is the clip, the 0.5 s tail and exactly `count` echo times long
    assert abs(len(x) - ((4 * 60 / bpm + 0.5) * SR + count * delay)) <= 1


def test_pad_has_no_echo():
    x = gp.render_events("pad", [N(48, 0.0, 0.5, 100)], 145, 4)
    np.testing.assert_array_equal(x[:, 0], x[:, 1])
    assert not x[int(1.0 * SR):].any()  # 0.5 beat = 0.21 s + 0.4 s release, then nothing


@pytest.mark.parametrize("voice", list(gp.VOICES))
@pytest.mark.parametrize("resonance", ["own", "max"])
def test_extreme_notes_stay_finite_and_bounded(voice, resonance, monkeypatch):
    # Highest and lowest note of the voice's window with the register option at +2 / -2
    # octaves, velocity 127, slides, at the end of the clip (cutoff ramp at its top), with
    # the voice's own resonance and with the highest the filter accepts (q = 20).
    # Stated bound for the dry voice signal: peak <= 20 (tested, not proven); the finished
    # preview is at PEAK = 0.8.
    if resonance == "max":
        monkeypatch.setitem(gp.VOICES, voice, dataclasses.replace(gp.VOICES[voice], q=dsp.Q_MAX))
    lo, hi = {"lead": (36, 107), "arp": (33, 104), "pad": (24, 83), "pluck": (12, 83)}[voice]
    for pitches in ((hi, hi - 12, hi), (lo, lo + 12, lo), (lo, hi, lo), (0, 127, 0)):
        notes = [N(pitches[i % 3], 12 + i * 0.25, 0.3 if i % 3 == 0 else 0.2, 127)
                 for i in range(16)]
        dry = gp.render_voice_dry(voice, notes, 150, 16)
        assert np.all(np.isfinite(dry)) and 0 < float(np.max(np.abs(dry))) <= 20.0
        x = gp.render_events(voice, notes, 150, 16)
        assert np.all(np.isfinite(x)) and abs(float(np.max(np.abs(x))) - 0.8) < 1e-6


def test_no_aliasing_at_the_highest_lead_note():
    # MIDI 83 = 987.77 Hz, held 4 s; second 2 to 3 of the dry lead signal. Harmonics 1..20
    # lie below 0.45 * SR = 19845 Hz. Everything further than 60 Hz from a harmonic is below
    # -80 dB of the strongest line; nothing above 19905 Hz.
    x = gp.render_voice_dry("lead", [N(83, 0, 4, 120)], 60, 8)[2 * SR: 3 * SR]
    spec = np.abs(np.fft.rfft(x * np.blackman(SR)))
    freqs = np.fft.rfftfreq(SR, 1 / SR)
    stray = np.ones(len(freqs), dtype=bool)
    for k in range(1, 21):
        stray &= np.abs(freqs - k * 987.767) > 60.0
    assert float(np.max(spec[stray])) < 1e-4 * float(np.max(spec))
    assert float(np.max(spec[freqs > 19905.0])) < 1e-4 * float(np.max(spec))


def test_property_random_events():
    rng = random.Random(571)
    for _ in range(10):
        voice = rng.choice(list(gp.VOICES))
        bpm = round(rng.uniform(135, 150), 1)
        beats = rng.choice([4, 8, 16])
        notes = [N(rng.randint(24, 100), rng.randrange(0, beats * 4) / 4,
                   rng.choice([0.1, 0.2, 0.25, 0.3, 0.5, 1.0, 3.0]), rng.randint(1, 127))
                 for _ in range(rng.randint(1, 40))]
        x = gp.render_events(voice, notes, bpm, beats)
        echo = round(3 * 60 / bpm / 4 * SR)
        assert abs(len(x) - ((beats * 60 / bpm + 0.5) * SR + ECHOES[voice] * echo)) <= 1
        assert np.all(np.isfinite(x)) and abs(float(np.max(np.abs(x))) - 0.8) < 1e-6
        assert not x[-1].any()
        first = int(min(n.start for n in notes) * 60 / bpm * SR) - 1
        assert not x[: max(0, first)].any()
