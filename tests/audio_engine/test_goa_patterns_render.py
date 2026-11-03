"""Pins the render values of the Goa output (gate, velocity, accent velocity, slide overlap)
and the 'arp sequence advances on rests' rule. Every expected number is written here by
hand (PPQ 480: step = 120 ticks, slide overlap 0.03125 beat = 15 ticks); the MIDI is read by
the small reader below, not by the module under test."""

import pytest

from audio_engine import goa_patterns as gp

STEP, OVERLAP = 120, 15
# kind -> (gate ticks, velocity, accent velocity); 0.15 / 0.18 / 0.12 beat * 480, rounded
RENDER = {"bass": (72, 100, 127), "lead": (86, 96, 124), "arp": (58, 90, 120)}


def midi_notes(data):
    """-> sorted [(start, end, pitch, velocity)] from a format-0 SMF."""
    body = data[22:]
    pos = t = 0
    open_, out = {}, []
    while pos < len(body):
        d = 0
        while True:
            b = body[pos]
            pos += 1
            d = (d << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        t += d
        st = body[pos]
        if st == 0xFF:
            pos += 3 + body[pos + 2]
        else:
            if st == 0x90:
                open_[body[pos + 1]] = (t, body[pos + 2])
            else:
                s, v = open_.pop(body[pos + 1])
                out.append((s, t, body[pos + 1], v))
            pos += 3
    assert not open_
    return sorted(out)


@pytest.mark.parametrize("kind", gp.KINDS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_render_values_gate_velocity_accent_slide(kind, seed):
    line = gp.generate(kind, root=36, scale="phrygian", bars=4, density=0.8,
                       accent=0.4, slide=0.5, seed=seed)
    gate, vel, acc_vel = RENDER[kind]
    steps = line["steps"]
    expected = []
    for i, s in enumerate(steps):
        if not s["on"]:
            continue
        end = i * STEP + gate
        if s["slide"]:  # generator only slides onto a different pitch on the next step
            assert steps[i + 1]["on"] and steps[i + 1]["note"] != s["note"]
            end = (i + 1) * STEP + OVERLAP
        expected.append((i * STEP, end, s["note"], acc_vel if s["accent"] else vel))
    assert midi_notes(gp.line_to_midi(line)) == sorted(expected)
    # the test must exercise all four cases
    flags = [(s["accent"], s["slide"]) for s in steps if s["on"]]
    assert (True, False) in flags and (False, True) in flags and (False, False) in flags


@pytest.mark.parametrize("seed", range(8))
def test_arp_sequence_advances_on_rests(seed):
    # aeolian, root 40, one octave, pattern up: chord tones 40, 43, 47, 50 (written by hand).
    line = gp.arp_line(40, "aeolian", bars=2, density=0.5, octaves=1, pattern="up", seed=seed)
    chord = [40, 43, 47, 50]
    sounding = [(i, s["note"]) for i, s in enumerate(line["steps"]) if s["on"]]
    assert len(sounding) == 16  # 8 per bar: there are rests
    for i, pitch in sounding:
        assert pitch == chord[i % 4], f"step {i}"
