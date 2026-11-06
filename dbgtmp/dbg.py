import hashlib, sys, numpy as np
from audio_engine import laser, laser_fx
from audio_engine.presets import load_preset
from audio_engine.categories import get_category
from audio_engine.io import encode_wav
def H(a, tag):
    a = np.ascontiguousarray(a, dtype=np.float64)
    r = np.round(a*2**40)/2**40
    print(f"{tag:12s} exact={hashlib.sha256(a.tobytes()).hexdigest()[:12]} r40={hashlib.sha256(r.tobytes()).hexdigest()[:12]} sum={a.sum():.17g} max={np.abs(a).max():.17g}")
orig = laser_fx.echo_v2
def echo(x, p, d):
    H(x, "echo_in"); y = orig(x, p, d); H(y, "echo_out"); return y
laser_fx.echo_v2 = echo
for nm in ("high_pass","low_pass"):
    o = getattr(laser_fx, nm)
    def mk(o, nm):
        def f(x, *a, **k):
            H(x, nm+"_in"); y = o(x, *a, **k); H(y, nm+"_out"); return y
        return f
    setattr(laser_fx, nm, mk(o, nm))
od = laser._drive
def drive(x, a):
    y = od(x, a); H(x, "drive_in"); H(y, "drive_out"); return y
laser._drive = drive
on = laser._normalise
def norm(x, *a):
    H(x, "norm_in"); y = on(x, *a); H(y, "norm_out"); return y
laser._normalise = norm
import platform, sys
print(sys.version, np.__version__, platform.platform())
p = laser.resolve_laser_params(load_preset("blaster-echo","laser")) if hasattr(laser,"resolve_laser_params") else None
p = laser.resolve_laser_params(load_preset("blaster-echo","laser"))
audio, r = get_category("laser").render(p)
print("WAV", hashlib.sha256(encode_wav(audio, r["sample_rate"], r["bit_depth"])).hexdigest())
