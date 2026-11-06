import hashlib, sys, numpy as np, platform
from audio_engine import laser, laser_fx
from audio_engine.presets import load_preset
def H(a, tag):
    a = np.ascontiguousarray(a, dtype=np.float64)
    print(f"{tag:14s} exact={hashlib.sha256(a.tobytes()).hexdigest()[:12]} sum={a.sum():.17g} last={a.ravel()[-1]:.17g} n={a.size}")
def wrap(name, hashargs=False):
    o = getattr(laser, name)
    def f(*a, **k):
        y = o(*a, **k)
        if isinstance(y, tuple):
            for i, e in enumerate(y): H(e, f"{name}[{i}]")
        else: H(y, name)
        return y
    setattr(laser, name, f)
for n in ("_sweep_freq","_phase","_saw_bandlimited","_amp_envelope","_decimate","_noise_layers"):
    wrap(n)
o = laser._saw_tables
t = o(96000)
H(t, "saw_tables")
print(platform.platform(), np.__version__)
p = laser.resolve_laser_params(load_preset("blaster-echo","laser"))
laser.render_resolved(p)
