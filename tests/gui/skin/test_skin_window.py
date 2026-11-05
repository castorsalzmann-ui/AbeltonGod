"""CompactGoaWindow and ChromeThornFrame on the offscreen platform (#407). This checks widget
state and pixels of an offscreen render; it says nothing about the look on Windows or about
the behaviour next to Live."""

from __future__ import annotations

import os

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from gui import skin_demo  # noqa: E402
from gui.skin import geometry as geo  # noqa: E402
from gui.skin.settings import MIN_SIZE, SkinSettings, load_settings  # noqa: E402
from gui.skin.window import CompactGoaWindow, GoaPlaceholderPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    w = CompactGoaWindow(settings_path=tmp_path / "skin.json", settings=SkinSettings())
    yield w
    w.close()


def test_window_builds_with_defaults(window):
    window.show()
    assert (window.width(), window.height()) == (460, 340)
    assert window.always_on_top() is True
    assert window.frame.animated() is False  # measured > 1 % idle CPU: off by default
    assert isinstance(window.body, GoaPlaceholderPanel)
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_minimum_size_is_respected(window):
    window.show()
    window.resize(50, 50)
    assert (window.width(), window.height()) == MIN_SIZE
    assert window.minimumWidth() == 360 and window.minimumHeight() == 260


def test_always_on_top_toggles_and_keeps_visibility(window):
    window.show()
    window.set_always_on_top(False)
    assert window.always_on_top() is False
    assert window.isVisible()
    assert not window.strip.pin_button.isChecked()
    window.strip.pin_button.click()  # the chrome button
    assert window.always_on_top() is True
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_body_slot_accepts_any_widget(window):
    custom = QLabel("hello slot")
    window.set_body(custom)
    assert window.body is custom
    assert custom.parentWidget() is not None
    assert window.body_slot.count() == 1  # the placeholder was released
    again = QLabel("second")
    window.set_body(again)
    assert window.body is again and window.body_slot.count() == 1


def test_placeholder_render_says_it_is_not_connected(window):
    seen = []
    window.body.render_requested.connect(lambda s, b: seen.append((s, b)))
    window.body.section.setText("Peak")
    window.body.bpm.setText("148")
    window.body.render_button.click()
    assert seen == [("Peak", "148")]
    assert "nichts gerendert" in window.body.status.text()


def test_settings_round_trip_through_the_window(qapp, tmp_path):
    path = tmp_path / "skin.json"
    w = CompactGoaWindow(settings_path=path, settings=SkinSettings())
    w.show()
    w.resize(500, 380)
    w.move(30, 40)
    w.set_always_on_top(False)
    w.set_animation(True)
    w.close()
    saved = load_settings(path)
    assert (saved.width, saved.height) == (500, 380)
    assert saved.always_on_top is False and saved.animation is True
    assert saved.x is not None and saved.y is not None

    w2 = CompactGoaWindow(settings_path=path)  # reads the file
    w2.show()
    assert (w2.width(), w2.height()) == (500, 380)
    assert w2.always_on_top() is False
    assert w2.frame.animated() is True
    w2.close()


def test_no_file_is_written_without_a_path(qapp, tmp_path, monkeypatch):
    """settings= without settings_path must not persist (never touch ~/AbeltonGod)."""
    default = tmp_path / "home_default.json"
    monkeypatch.setenv("ABELTONGOD_SKIN_SETTINGS", str(default))
    w = CompactGoaWindow(settings=SkinSettings())
    w.show()
    w.close()
    assert w.save_settings() is False
    assert not default.exists()
    w = CompactGoaWindow()  # neither path nor settings: defaults, no read, no write
    w.show()
    w.close()
    assert not default.exists()
    # Asking for the default location explicitly does persist.
    w = CompactGoaWindow(use_default_path=True)
    w.show()
    w.close()
    assert default.exists()


def test_animation_timer_follows_the_switch(window):
    window.show()
    assert not window.frame._timer.isActive()
    window.strip.anim_button.click()
    assert window.frame.animated() and window.frame._timer.isActive()
    window.set_animation(False)
    assert not window.frame._timer.isActive()


def test_painting_is_transparent_outside_and_opaque_inside(window):
    window.show()
    window.resize(460, 340)
    img = window.grab().toImage()
    assert img.pixelColor(0, img.height() // 2).alpha() == 0  # left of every thorn
    assert img.pixelColor(img.width() // 2, img.height() // 2).alpha() == 255  # body
    # A thorn is opaque at its centroid.
    for t in window.frame.thorns():
        if t.kind == "edge:top":
            cx = (t.a.x() + t.b.x() + t.tip.x()) / 3
            cy = (t.a.y() + t.b.y() + t.tip.y()) / 3
            assert img.pixelColor(round(cx), round(cy)).alpha() == 255
            break


def test_body_content_stays_inside_the_rail(window):
    window.show()
    for size in ((360, 260), (460, 340), (900, 600)):
        window.resize(*size)
        QApplication.processEvents()
        inner = window.frame.content_rect()
        assert inner.contains(window.body.geometry()), size
        assert window.frame.body_rect().toAlignedRect().contains(inner), size


def test_frame_paths_scale_with_window(window):
    window.show()
    window.resize(460, 340)
    small = geo.thorn_union(window.width(), window.height()).boundingRect()
    window.resize(900, 600)
    big = geo.thorn_union(window.width(), window.height()).boundingRect()
    assert big.width() > small.width() * 1.8


def test_screenshots_are_written_for_three_sizes(window, tmp_path):
    paths = skin_demo.save_screenshots(window, tmp_path / "shots")
    assert [p.name for p in paths] == [
        "goa_skin_460x340.png", "goa_skin_360x260.png", "goa_skin_720x520.png"]
    assert all(p.stat().st_size > 1000 for p in paths)
