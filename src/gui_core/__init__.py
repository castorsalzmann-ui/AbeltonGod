"""UI-free service layer of the desktop GUI (D-029, issue #403).

Nothing in this package imports Qt. It holds the kick form model (built from the kick params
contract), the render service (engines in a worker thread, result objects instead of
exceptions), the waveform reader and the preview controller. ``src/gui/`` is a thin shell on
top of it.
"""
