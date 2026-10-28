"""Deterministic sample synthesis and analysis. Implemented in Phase 01."""

ENGINE_NAME = "abeltongod-audio-engine"
# Bump on EVERY change that alters rendered bytes (#35): minor for a byte change (0.1.0 ->
# 0.2.0), patch only for changes that keep every byte identical. Update the golden hashes in
# tests/audio_engine/test_engine_version.py in the same PR. 0.1.0: continuous drive (#16),
# after the unversioned byte changes of #20 (anti-aliased drive) and #26 (RIFF pad byte).
ENGINE_VERSION = "0.1.0"
