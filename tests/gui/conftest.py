"""GUI tests run headless: the offscreen platform must be set before Qt is imported.

Widget cleanup (cause shown with gdb, PR #412): a closed MainWindow is cyclic garbage in
Python (slots capture ``self``). Python's cyclic GC can run in ANY thread, and the render, Goa
and chat worker threads allocate a lot, so the GC sometimes ran inside a worker thread and
finalised a whole widget tree there. Qt widgets must be destroyed in the GUI thread: Shiboken
then queues the deletion for the main thread and the process died with SIGSEGV (call through a
null pointer in ``BindingManager::runDeletionInMainThread``, seen on Linux and as "Fatal Python
error: Aborted" on Windows). The fixture below deletes every top-level widget in the main thread
after each test, so no widget tree is left for the GC.
"""

import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def destroy_widgets_in_the_gui_thread():
    yield
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # no Qt: the GUI tests are skipped anyway
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()  # Python wrappers of the deleted widgets, collected here and not in a worker
