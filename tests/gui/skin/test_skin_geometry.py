"""Thorn geometry (#407). Pure vector data: no window needed. The expected values are written
here, not derived from the module's own helpers."""

from __future__ import annotations

import os
import random

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtGui  # noqa: F401
else:
    pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from gui.skin import geometry as geo  # noqa: E402

SIZES = [(360, 260), (460, 340), (720, 520), (1200, 800), (1600, 1000), (400, 1100)]


def _random_sizes(n=40, seed=407):
    rng = random.Random(seed)
    return [(rng.randint(360, 1800), rng.randint(260, 1200)) for _ in range(n)]


@pytest.mark.parametrize("size", SIZES)
def test_thorns_on_all_four_edges_and_corners(size):
    thorns = geo.build_thorns(*size)
    for edge in ("top", "right", "bottom", "left"):
        assert sum(t.kind == f"edge:{edge}" for t in thorns) >= 4, edge
    for corner in ("tl", "tr", "br", "bl"):
        assert sum(t.kind == f"corner:{corner}" for t in thorns) == 1, corner


@pytest.mark.parametrize("size", SIZES + _random_sizes())
def test_tips_stay_inside_the_widget_so_nothing_is_clipped(size):
    w, h = size
    for t in geo.build_thorns(w, h):
        for pt in (t.tip, t.a, t.b):
            assert -0.01 <= pt.x() <= w + 0.01 and -0.01 <= pt.y() <= h + 0.01, (t.kind, pt)
        bb = t.path().boundingRect()  # curves too, not only the corner points
        assert bb.left() >= -0.01 and bb.top() >= -0.01, t.kind
        assert bb.right() <= w + 0.01 and bb.bottom() <= h + 0.01, t.kind


@pytest.mark.parametrize("size", SIZES)
def test_edge_thorns_point_outward(size):
    w, h = size
    r = geo.reach_for(w, h)
    body = geo.body_rect(w, h, r)
    for t in geo.build_thorns(w, h):
        if not t.kind.startswith("edge:"):
            continue
        edge = t.kind.split(":")[1]
        tip = t.tip
        outward = {
            "top": body.top() - tip.y(),
            "bottom": tip.y() - body.bottom(),
            "left": body.left() - tip.x(),
            "right": tip.x() - body.right(),
        }[edge]
        assert outward >= 0.3 * r, (edge, outward)  # sticks out of the body
        assert outward <= r + 0.01  # but never beyond the reach


@pytest.mark.parametrize("size", SIZES + _random_sizes(15, seed=3))
def test_bases_tile_each_edge_without_gaps_or_overlaps(size):
    """Clean joins: the base of each thorn starts exactly where the previous one ends."""
    for edge in ("top", "right", "bottom", "left"):
        run = [t for t in geo.build_thorns(*size) if t.kind == f"edge:{edge}"]
        for prev, nxt in zip(run, run[1:], strict=False):
            assert prev.b.x() == pytest.approx(nxt.a.x(), abs=1e-6)
            assert prev.b.y() == pytest.approx(nxt.a.y(), abs=1e-6)


@pytest.mark.parametrize("size", SIZES + _random_sizes(15, seed=5))
def test_each_edge_run_spans_from_corner_horn_to_corner_horn(size):
    """The thorn run starts and ends 1.55 reach from the corners: no missing stretch."""
    w, h = size
    r = geo.reach_for(w, h)
    clear = 1.55 * r
    thorns = geo.build_thorns(w, h)
    top = [t for t in thorns if t.kind == "edge:top"]
    assert top[0].a.x() == pytest.approx(r + clear, abs=1e-6)
    assert top[-1].b.x() == pytest.approx(w - r - clear, abs=1e-6)
    left = [t for t in thorns if t.kind == "edge:left"]
    assert left[0].a.y() == pytest.approx(r + clear, abs=1e-6)
    assert left[-1].b.y() == pytest.approx(h - r - clear, abs=1e-6)


@pytest.mark.parametrize("size", SIZES)
def test_thorn_sizes_vary_on_every_edge(size):
    r = geo.reach_for(*size)
    body = geo.body_rect(*size, r)
    for edge in ("top", "right", "bottom", "left"):
        heights = set()
        for t in geo.build_thorns(*size):
            if t.kind != f"edge:{edge}":
                continue
            h = {
                "top": body.top() - t.tip.y(),
                "bottom": t.tip.y() - body.bottom(),
                "left": body.left() - t.tip.x(),
                "right": t.tip.x() - body.right(),
            }[edge]
            heights.add(round(h))
        assert len(heights) >= 3, (edge, heights)


def test_border_scales_with_the_window():
    prev = None
    for w, h in [(360, 260), (460, 340), (720, 520), (1200, 800)]:
        bb = geo.thorn_union(w, h).boundingRect()
        # The union spans (almost) the whole widget: tips reach the outer ring.
        assert bb.width() >= 0.97 * w and bb.height() >= 0.97 * h, (w, h, bb)
        if prev is not None:
            assert bb.width() > prev.width() and bb.height() > prev.height()
        prev = bb
    # More run length -> more thorns.
    small = len(geo.build_thorns(360, 260))
    large = len(geo.build_thorns(1200, 800))
    assert large > small


def test_reach_grows_with_size_but_is_clamped():
    assert geo.reach_for(360, 260) == pytest.approx(20.28, abs=0.01)  # 0.078 * 260
    assert geo.reach_for(100, 100) == 18.0
    assert geo.reach_for(5000, 5000) == 34.0


def test_geometry_is_deterministic():
    a = [(t.kind, t.tip.x(), t.tip.y()) for t in geo.build_thorns(460, 340)]
    b = [(t.kind, t.tip.x(), t.tip.y()) for t in geo.build_thorns(460, 340)]
    assert a == b


def test_corner_horns_are_curved_not_straight():
    for t in geo.build_thorns(460, 340):
        if t.kind.startswith("corner:"):
            # A straight edge a->tip would put the control point on the chord.
            chord_mid_x = (t.a.x() + t.tip.x()) / 2
            chord_mid_y = (t.a.y() + t.tip.y()) / 2
            off = abs(t.ctrl_a.x() - chord_mid_x) + abs(t.ctrl_a.y() - chord_mid_y)
            assert off > 5.0, t.kind
