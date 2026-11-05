"""GUI tests run headless: the offscreen platform must be set before Qt is imported."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
