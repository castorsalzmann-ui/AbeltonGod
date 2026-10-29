# Research: AI audio generation for one-shots: local and online options (cluster 5)

> **Research only. D-005 keeps generative audio out of the MVP.** Nothing here is a plan to build. Building any of it needs the user to reopen D-005 (or to schedule the "generative audio backend" item from the `ROADMAP.md` parking lot as its own phase).

- **Date:** 2026-10-29. All web sources were retrieved on 2026-10-29.
- **Versions researched against:**
  - Stability AI **Stable Audio 3** family: model cards `stabilityai/stable-audio-3-small-sfx` and `stabilityai/stable-audio-3-medium` on Hugging Face, paper arXiv 2605.17991 (listed 2026-05-18); code `Stability-AI/stable-audio-3`, `main` README as rendered on 2026-10-29 (pins torch 2.7.1). The commit SHA could not be read: the GitHub API is not enabled for that repo in this session, and github.com blocks commit pages for the fetch tool.
  - Older Stability models: `stabilityai/stable-audio-open-1.0` (paper 2024-07-19), `stabilityai/stable-audio-open-small` (paper 2025-05-13).
  - `Stability-AI/stable-audio-tools`, `main`, `stable_audio_tools/inference/generation.py` (SHA not captured, same reason).
  - Stability REST API `v2beta/audio/stable-audio/text-to-audio` (model `stable-audio-3`). Stability Terms of Service effective 2026-09-30. Community License last updated 2024-07-05.
  - ElevenLabs Sound Effects API (`eleven_text_to_sound_v2` / `_v3`). ElevenLabs Terms of Use and ElevenCreative Terms, both last updated 2026-10-09.
  - Meta AudioCraft `main` README (AudioGen `facebook/audiogen-medium`). TangoFlux model card. PyTorch docs 2.14.
  - Hardware: NVIDIA GeForce RTX 5070, 12 GB GDDR7 (the user's GPU, `CURRENT_STATE.md`).
- **Receiving issue:** #102 (D-023 cluster 5; questionnaire tab 1, feature c). Rules: D-019 point 3, D-023.
- **Not covered here (other clusters):** Live functions, desktop window, kick-in-tracks, mix targets. Also not covered: distributor or streaming-platform rules on AI disclosure. The issue does not ask about them, but they matter for releases (see open user questions).
- **Existing notes checked:** no note in `docs/research/` covers generative audio. D-005 says the licence "must be checked for releases". Question 2 does that for the candidates below.

Confidence scale: **high** = official model card, licence, terms or API reference says it directly. **medium** = official source, but indirect or ambiguous, or a third-party host/doc. **low** = vendor marketing page or press only. **Interpretation** = my inference, labelled as such.

## Short answers

| # | Question | Answer in one line | Confidence |
| --- | --- | --- | --- |
| 1 | Models/services, local vs online | **Local, open weights:** Stable Audio 3 Small-SFX (433M per README / 0.6B per card, runs on CPU, ~1.7–2.4 GB peak VRAM on H200) and Medium (1.4B / ~2B, CUDA, 5–6.5 GB, needs Flash Attention 2). On paper both fit 12 GB. Older options: Stable Audio Open 1.0 / Small. AudioGen needs ≥16 GB and is non-commercial. **Online:** Stability API (`stable-audio-3`, 1–380 s, $0.08), ElevenLabs SFX API (0.5–30 s), plugins (Emergent Drums 2, Text-to-Sample cloud). No source gives RTX 5070 speed figures. | High for specs; low for plugins; RTX 5070 fit is interpretation |
| 2 | Licences for releasing music | **Stable Audio (self-hosted or API):** you own the output; free commercial use under US$1M yearly revenue, with registration. Outputs may not be used to train foundation models. The API ToS forbids passing outputs off as human-made. **ElevenLabs:** paid plan needed for commercial use. SFX only inside a larger work, **never as standalone samples or sample packs**. **AudioGen / TangoFlux:** non-commercial weights, so not usable for releases. | High (quoted terms); medium for the attribution scope |
| 3 | Reproducibility and coexistence | Local Stable Audio seeds the global torch RNG (`torch.manual_seed`), so a fixed seed is possible. PyTorch does **not** guarantee identical results across releases, platforms or CPU vs GPU. The Stability API has a `seed` (0 = random) but no determinism promise. ElevenLabs has **no seed**. Interpretation: AI output can sit beside the engine only as a **stored, hashed asset with provenance**, never as a "re-render from sidecar" source. The current sidecar contract would need a `contract-change`. | High for API facts; interpretation for the design |

## Question 1: Which current models/services generate drum one-shots or short samples? Which run locally on an RTX 5070 (VRAM, speed), which are online? Versions and dates.

**Answer.**

*Local, open weights (download, run on own machine)*

| Model (repo) | Date | Size | Max length / rate | Hardware facts from the source | Fits RTX 5070 12 GB? | Confidence |
| --- | --- | --- | --- | --- | --- | --- |
| **Stable Audio 3 Small-SFX** (`stabilityai/stable-audio-3-small-sfx`) | paper 2026-05-18, collection 2026-05-20 | 433M (README table), 0.6B (HF card) | 120 s; 44.1 kHz stereo | CPU supported. H200 PyTorch: 0.41 s for 5 s of audio. Peak VRAM 1.69 GB (5 s) to 2.40 GB (120 s). No Flash Attention needed (README names only Medium). | Interpretation: yes, by a wide margin on paper. Not measured on a 5070. | High (specs); size conflict between sources |
| **Stable Audio 3 Medium** (`stabilityai/stable-audio-3-medium`, plus `-medium-base`) | same | 1.4B (README), ~2B (HF card) | 380 s; 44.1 kHz stereo | CUDA. H200: 0.60 s for 5 s. Peak VRAM 5.07–6.52 GB. **Requires Flash Attention 2.** Without it the output is a "static glitch sound" (README troubleshooting). | Interpretation: VRAM yes. Software stack doubtful on Windows + Blackwell (see pitfalls). | High (specs) |
| Stable Audio 3 Large | same | 2.7B | 380 s | **API only.** Self-hosting for Enterprise customers only. | n/a | High |
| Stable Audio Open 1.0 (`stabilityai/stable-audio-open-1.0`) | paper 2024-07-19 | ~1B | 47 s; 44.1 kHz stereo | Card: "better at generating sound effects and field recordings than music". Trained on Freesound + FMA (CC0 / CC-BY / CC-Sampling+). | Interpretation: likely. No figure. | High |
| Stable Audio Open Small (`stabilityai/stable-audio-open-small`) | paper 2025-05-13 | 0.5B (card) | 11 s; 44.1 kHz stereo | CPU/Arm-optimised. 8 steps, "pingpong" sampler in the example. | Interpretation: likely. | High |
| AudioGen medium (`facebook/audiogen-medium`, AudioCraft) | AudioCraft `main` | 1.5B | 16 kHz EnCodec tokenizer | AudioCraft needs "a GPU with at least 16 GB of memory" for medium models. Python 3.9, PyTorch 2.1.0. | **No by the stated requirement** (12 GB < 16 GB). | High |
| TangoFlux (`declare-lab/TangoFlux`) | paper 2024-12-30 | not stated | 30 s; 44.1 kHz | no hardware figure | unknown | High (card) |

No drum-specific open-weights model came up in the sources opened today. The Stable Audio 3 cards and the Open cards do not mention one-shots at all. Their only drum example is a "128 BPM tech house drum loop" prompt (Open 1.0 / Open Small). **Interpretation:** a kick one-shot would come from a general SFX model plus prompting and trimming. Whether that is usable is a listening question (V9). This note makes no sound claim.

*Online (hosted)*

| Service | What it offers for short samples | Facts | Confidence |
| --- | --- | --- | --- |
| **Stability API**, `POST /v2beta/audio/stable-audio/text-to-audio`, `model=stable-audio-3` | text-to-audio, also audio-to-audio and inpaint | Duration 1–380 s (default 190). `seed` 0–4294967294. `steps` 4–8. `cfg_scale` 1–25. `output_format` `mp3`/`wav`. Async: returns an id, poll `/v2beta/audio/results/{id}`, results kept 24 h. Rate limit 150 req / 10 s. English prompts only. Rejects audio flagged as copyrighted (422). **8 credits = US$0.08 per generation.** Stable Audio 2.5 endpoints also exist (same price). | High |
| stableaudio.com (hosted app) | web app on the same models | Plans from US$12/month (Solo, 660 credits) up to US$199 (Studio). Stability's page lists no free hosted tier. | Medium (Stability explainer page, not the pricing page) |
| **ElevenLabs Sound Effects API** (`eleven_text_to_sound_v2` default, `eleven_text_to_sound_v3`) | text-to-SFX | `duration_seconds` 0.5–30 (unset = inferred). `loop` bool. `prompt_influence` 0–1 (default 0.3). **No `seed` parameter.** WAV/PCM 44.1 kHz needs the Pro tier or higher. | High |
| fal.ai hosting of Stable Audio 3 (e.g. `fal-ai/stable-audio-3/small/sfx/base/text-to-audio`) | third-party host | `seed` optional and returned in the response. Duration 1–120 s. US$0.0283 per audio. | Medium (third-party) |
| Emergent Drums 2 (Audialab) | VST3/AU plugin for drum one-shots, kicks included; Windows 7–11 | Generating needs an internet connection; saved samples play offline. Page says "royalty-free" but publishes no licence text. No seed/recall feature or API mentioned. US$149 list price. | Low (vendor page) |
| Text-to-Sample | web + VST3/AU plugin, one-shots and drum hits | Cloud GPU about 5–10 s per sample, about US$0.13 per sample. Offline version only for Apple Silicon, "coming soon". Model not named. Page says royalty-free, no licence text. | Low (vendor page) |
| DrumNet (Session Loops), Fadr DrumGPT | drum-sample plugins/tools | Article of 2026-02-03; local vs cloud and licence not stated. | Low (press) |

**Speed on an RTX 5070:** no source gives a figure. The only GPU timings are H200 (Stable Audio 3 README) and "a few seconds on a MacBook Pro M4" (cards). **Interpretation:** H200 numbers cannot be carried over. Measure instead (V3).

**Sources:**
- Stable Audio 3 code README and tables: https://github.com/Stability-AI/stable-audio-3 and https://raw.githubusercontent.com/Stability-AI/stable-audio-3/main/README.md (sections Models, Performance, VRAM, Flash Attention, CUDA Version, Troubleshooting, License)
- Stable Audio 3 cards: https://huggingface.co/stabilityai/stable-audio-3-small-sfx and https://huggingface.co/stabilityai/stable-audio-3-medium
- Stable Audio Open cards: https://huggingface.co/stabilityai/stable-audio-open-1.0 and https://huggingface.co/stabilityai/stable-audio-open-small
- ComfyUI tutorial (Medium/Small variants, seed control in Medium workflows): https://docs.comfy.org/tutorials/audio/stable-audio/stable-audio-3.md
- Stability API: https://docs.stability.ai/api-reference/stable-audio/text-to-audio.md, https://docs.stability.ai/api-reference.md, https://docs.stability.ai/pricing.md, https://docs.stability.ai/llms.txt
- stableaudio.com plans: https://stability.ai/explainers/stable-audio-vs-competitors-licensing-export-rights-and-self-hosting-compared
- ElevenLabs: https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert.md
- fal.ai: https://fal.ai/models/fal-ai/stable-audio-3/small/sfx/base/text-to-audio/llms.txt
- AudioCraft: https://github.com/facebookresearch/audiocraft and https://github.com/facebookresearch/audiocraft/blob/main/docs/AUDIOGEN.md
- TangoFlux: https://huggingface.co/declare-lab/TangoFlux
- Plugins: https://audialab.com/products/emergent-drums-2/, https://www.text-to-sample.com/, https://rekkerd.org/generate-drum-samples-with-drumnet-ai-powered-plugin-sale/
- RTX 5070 12 GB GDDR7: https://marketplace.nvidia.com/en-in/consumer/graphics-cards/nvidia-geforce-rtx-5070/

**Confidence:** high for model specs as published. The size conflicts are real: card vs README differ (0.6B vs 433M, ~2B vs 1.4B). **Interpretation:** the cards' figure may include the T5Gemma text encoder, but this is not established. Low for the plugin claims. The RTX 5070 fit is interpretation only.

## Question 2: What do the licences/terms say about releasing music made with the output?

**Answer.**

| Source | Ownership of output | Commercial release | Restrictions that matter for us | Confidence |
| --- | --- | --- | --- | --- |
| **Stability AI Community License** (self-hosted Stable Audio 3 Small/Medium, Open 1.0, Open Small; updated 2024-07-05) | IV(c)(iii): "You own any outputs generated from the Models or Derivative Works", subject to applicable law. | Free for individuals/organisations under **US$1,000,000 annual revenue**. Commercial use **requires registering** with Stability AI. Above the threshold the licence terminates; Enterprise licence needed. The `stability.ai/license` page lists Stable Audio 3.0 under the Community tier. | Outputs may not be used to create or improve a foundational generative AI model. The Acceptable Use Policy applies. Attribution ("Powered by Stability AI", Notice file, licence copy) is tied to **distributing the Materials or a Derivative Work**. **Interpretation:** a released track is an output, not a Material, so this clause would not require a credit on the track. Not confirmed by Stability. | High (licence text, via fetch summary); medium for the attribution scope |
| Stable Audio 3 model cards | Same licence ("stable-audio-community"). The T5Gemma encoder is also under the Gemma Terms of Use. Gated: you must accept the licence to download. | The cards say "For commercial use, please refer to" `stability.ai/license`. | The Medium card's gate links the **Stable Audio Open 1.0** licence while the body links a Stable Audio 3 `LICENSE.md`. The links are inconsistent, and the `LICENSE.md` itself failed to load today (V10). | High that it is inconsistent; the content of the SA3 `LICENSE.md` is unread |
| **Gemma Terms of Use** (text encoder; modified 2026-04-01) | §3.3: Google "claims no rights in Outputs you generate using Gemma". | no extra condition | Prohibited Use Policy (§3.2) applies. | High |
| **Stability Terms of Service** (API, stableaudio.com; effective 2026-09-30) | §4(a): "as between Stability and you, you own the Output (to the extent permitted by applicable law)". | Ownership is the basis. Stability's explainer says neither licence restricts use cases. | §3(b)(2): no training of competing models. §3(b)(9): **may not present AI-generated Outputs as human-made.** §3(b)(10): no removing watermarks/content credentials. §4(c): Stability may use inputs/outputs to improve its services, with opt-out. **Interpretation:** the "not as human-made" rule binds use of the Services (API/app). Whether the Acceptable Use Policy imposes the same on self-hosted use was not checked. | High |
| **ElevenLabs** Terms of Use + ElevenCreative Terms Exhibit 4 (Sound Effects; both updated 2026-10-09) + help-centre page | ToU §4(c)(ii): "as between you and ElevenLabs, you retain all rights in and to your Output." | **Free plan: no commercial licence**, attribution ("elevenlabs.io" in the title) required. Paid plans include a commercial licence, except Beta Services. | Sound-effects output may be used commercially **only as part of a larger work**. You may not sell, license or distribute it standalone, may not make it "available as isolated audio files or samples", and may not put it in a sound or sample library. ElevenLabs may train on your content unless you opt out (§4(d), §4(i)). **Interpretation:** a kick placed inside a released track fits "part of a larger work". Sharing the generated kick itself (sample pack, stems marketplace) does not. | High |
| **AudioCraft / AudioGen** | not addressed in the README | Weights are **CC-BY-NC 4.0** ("models weights … released under the CC-BY-NC 4.0 license"); code is MIT. | **Interpretation:** whether an NC weights licence binds outputs is legally unclear. For a release workflow, treat it as not usable. | High (licence label); interpretation for outputs |
| **TangoFlux** | not addressed | "The TangoFlux checkpoints are for non-commercial research use only." Also subject to the Stable Audio Open and WavCaps licences. | not usable for releases | High |
| Emergent Drums 2, Text-to-Sample | not published | Vendor pages say "royalty-free" / "usable commercially in tracks and releases". No licence text is linked on the pages opened. | Read the EULA before relying on it. | Low |

**Training data** (relevant to the user's risk view, not a licence term): the Stable Audio 3 cards list 1,278,902 recordings. 806,284 are licensed from AudioSparx and 472,618 come from Freesound (CC0 / CC-BY / CC-Sampling+). Music detected in the Freesound part was removed. The API page says AudioSparx honours opt-outs. Confidence: high (cards).

**Sources:**
- https://stability.ai/community-license-agreement
- https://stability.ai/license
- https://stability.ai/terms-of-service
- https://stability.ai/explainers/stable-audio-vs-competitors-licensing-export-rights-and-self-hosting-compared
- https://huggingface.co/stabilityai/stable-audio-3-medium
- https://huggingface.co/stabilityai/stable-audio-3-small-sfx
- https://ai.google.dev/gemma/terms
- https://elevenlabs.io/terms-of-use
- https://elevenlabs.io/creative-terms (Exhibit 4)
- https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform/llms.txt
- https://elevenlabs.io/service-specific-terms
- https://github.com/facebookresearch/audiocraft
- https://huggingface.co/declare-lab/TangoFlux
- vendor pages as in Q1

**Confidence:** high where a clause is quoted above. This is not legal advice. Copyright protection of AI output itself (whether anyone can own it) depends on the law of the country ("to the extent permitted by applicable law" in every set of terms). It is not researched here.

## Question 3: Reproducibility (seeded output), and how could results sit beside our deterministic engine as a separate source?

**Answer: facts.**
- **Self-hosted Stable Audio (stable-audio-tools):** `generate_diffusion_cond`, `generate_diffusion_cond_inpaint` and `generate_diffusion_uncond` take `seed: int = -1`. `-1` draws a random seed from NumPy's global RNG. The code then calls `torch.manual_seed(seed)` and draws the initial noise with `torch.randn(..., device=device)` from the **global** torch RNG (no `generator=` argument). The conditional functions do not print the seed they picked. (`stable_audio_tools/inference/generation.py`, `main`, around L94/L192–197, L317/L459–464, L19/L34–40. Line numbers are approximate, from the fetch tool's rendering; SHA not captured.) Confidence: high for the mechanism, medium for exact lines.
- **Stable Audio 3 package:** the README's examples (`StableAudioModel.from_pretrained("medium")`, `model.generate(prompt=..., duration=...)`) pass **no seed**. ComfyUI's Stable Audio 3 workflows expose a seed "for reproducibility" (Medium, Medium Base), and fal.ai accepts and returns `seed`. **Interpretation:** the model can be seeded. Whether `StableAudioModel.generate` takes a `seed` argument is unverified (V6). Confidence: medium.
- **PyTorch (docs 2.14):** "Completely reproducible results are not guaranteed across PyTorch releases, individual commits, or different platforms", and results "may not be reproducible between CPU and GPU executions, even when using identical seeds". `torch.use_deterministic_algorithms(True)` and `cudnn.benchmark = False` narrow nondeterminism where deterministic kernels exist. Confidence: high.
- **Stability API:** `seed` 0–4294967294, where "Omit this parameter or pass `0` to use a random seed". With `Accept: application/json` the response returns the `seed` used. The API reference makes no promise that the same seed and prompt give the same bytes, and the server-side model can change. Confidence: high (parameter). The absence of a guarantee is what the page did not say.
- **ElevenLabs SFX API:** no seed parameter. **Interpretation:** each call is a new, unrepeatable draw. Confidence: high (parameter list).
- **Plugins (Emergent Drums 2, Text-to-Sample):** no seed/recall or API mentioned. **Interpretation:** the only route into our stack would be the user exporting WAVs by hand. Confidence: low.

**Answer: how it could sit beside the engine (interpretation, a proposal for the lead, not a decision):**
1. **The WAV is the artefact, not the recipe.** The current sidecar contract says it "Must be sufficient to re-render the identical file" (`contracts/sample-metadata.schema.json` L5). `parameters` is the "Exact kick-params object used" (L23), and `engine` is `{name, version}` with `additionalProperties: false` (L14ff). An AI sample cannot meet L5 as a guarantee. So it needs either a separate source kind in the sidecar (e.g. `source: "dsp" | "generative" | "external"`) or a separate schema, through a `contract-change` PR owned by `audio-engineer`. For a generative sample, `sha256` (L39) becomes mandatory, and the stored file is the only copy of record.
2. **Provenance fields worth recording:** provider (`local` / `stability-api` / `elevenlabs`), model repo and weights file hash (or API model id), prompt, negative prompt, seed, steps, cfg, duration, sampler, precision, torch/CUDA/driver versions, device (CPU/GPU), timestamp, and a licence tag with its conditions (e.g. `elevenlabs-sfx: in-larger-work-only`). **Reproducibility claim:** "recorded, not guaranteed". A re-run counts as a new sample, like `allow_engine_mismatch=True` today (`docs/INTERFACES.md` L28).
3. **Determinism boundary:** everything downstream of the WAV (trim, fade, normalise, analysis, features, import) can stay deterministic and CI-testable on stored fixture WAVs. The generator itself stays outside CI (no GPU, no network, no model weights in CI), behind an interface that a fake can replace. That mirrors the Ableton test boundary.
4. **Process isolation:** torch + CUDA cu128 + model weights (several GB) as an optional extra or a separate venv/process. The NumPy engine's install and byte-identical goldens then stay untouched. Generation is offline batch work, not a real-time path, so the "no AI call in a real-time audio path" rule is not touched.
5. **Licence gate:** a sample tagged `in-larger-work-only` (ElevenLabs) must never land in an export or sample-pack feature. Non-commercial models (AudioGen, TangoFlux) should not be offered at all.

**Sources:**
- https://raw.githubusercontent.com/Stability-AI/stable-audio-tools/main/stable_audio_tools/inference/generation.py
- https://raw.githubusercontent.com/Stability-AI/stable-audio-3/main/README.md
- https://docs.comfy.org/tutorials/audio/stable-audio/stable-audio-3.md
- https://docs.pytorch.org/docs/2.14/notes/randomness.html
- https://docs.stability.ai/api-reference/stable-audio/text-to-audio.md
- https://docs.stability.ai/api-reference.md
- https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert.md
- repo files `contracts/sample-metadata.schema.json` L5, L14, L23, L39 and `docs/INTERFACES.md` L28 at `61088d1`

**Confidence:** high for the stated API and code facts. Points 1–5 are interpretation.

## Known pitfalls (for a later implementer)

- **Blackwell (RTX 50xx) needs CUDA 12.8 PyTorch builds.** The Stable Audio 3 README says `uv sync` installs PyTorch built against **CUDA 12.6 by default** (cu118/cu126/cu128 exist for torch 2.7.1). On the PyTorch forum, an RTX 5070 Ti on Windows 11 fails with "sm_120 is not compatible … no kernel image is available" until a cu128 build is installed. A PyTorch staff answer there says "All of our PyTorch binaries built with CUDA 12.8 already support Blackwell GPUs". Confidence: high (README); medium (forum, but staff answer). Sources: Stable Audio 3 README; https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120/221509
- **Medium needs Flash Attention 2.** The FlashAttention README lists Ampere/Ada/Hopper for FA2 and mentions Blackwell only for FA4. On Windows it says it "Might work for Windows starting v2.3.2" and that compilation "still requires more testing". The Stable Audio 3 README's example wheel is `flash_attn-2.6.3+cu126torch2.7`, and plain `uv sync` removes flash-attn (`uv sync --inexact`). **Interpretation:** Medium on Windows + RTX 5070 is the riskiest combination. Small-SFX avoids it. Source: https://github.com/Dao-AILab/flash-attention; Stable Audio 3 README.
- **Windows tooling:** the README's one-line installer needs Git Bash or WSL ("stock Windows has no bash"). Its CPU path via LiteRT/XNNPACK lists Windows. Confidence: high.
- **One-shot length:** the API minimum is 1 s, and the fal host minimum is also 1 s. Kicks are usually shorter. **Interpretation:** expect generate-then-trim, and the trim/fade belongs to our deterministic code.
- **Gated downloads:** the Hugging Face repos need a logged-in account and licence acceptance. An HF token would be a secret (`.env`, never the repo).
- **Global RNG seeding** in stable-audio-tools: anything else that draws from torch's global RNG in the same process between seeding and sampling would change the result. **Interpretation:** run each generation in a fresh, single-purpose process.

## Test strategy hints

- **CI can test:** sidecar/provenance schema validation; the licence-gate logic; deterministic post-processing (trim, fade, normalise, analysis) on committed fixture WAVs; a fake generator behind the interface; error paths (API 202 polling, 403/422/429, timeouts) against a recorded-response fake.
- **Needs the user's machine:** installing torch cu128 on Windows; GPU detection (`torch.cuda.get_arch_list()` contains `sm_120`); VRAM and time per one-shot; same-seed repeatability.
- **Needs the user's ears (or the `sound-designer`'s analysis plan):** whether any output is a usable Techno/Trance kick. This note makes no claim either way.

## To verify by experiment

Each becomes an issue for the owning role (D-019) if the user reopens D-005.

| ID | What | How | Owner (proposal) |
| --- | --- | --- | --- |
| V1 | Stable Audio 3 Small-SFX installs and runs on the user's Windows 11 + RTX 5070 | Fresh venv, torch 2.7.1 **cu128**. Check `torch.version.cuda == "12.8"` and that `sm_120` is in `torch.cuda.get_arch_list()`. Generate one 2 s clip. | audio-engineer (user's machine) |
| V2 | Stable Audio 3 Medium works on Windows + sm_120 with Flash Attention 2 | Try an FA2 wheel for cu128/torch 2.7. Confirm the output is not the "static glitch" failure mode. | audio-engineer (user's machine) |
| V3 | Peak VRAM and wall time per one-shot on RTX 5070 (Small-SFX, Medium; fp16/fp32; 8 vs 50 steps) | `torch.cuda.max_memory_allocated()` plus a timer, 10 runs each | audio-engineer |
| V4 | Same seed, same machine, same versions → byte-identical WAV? | Two fresh processes, same prompt and seed. Compare SHA-256. Then repeat with `torch.use_deterministic_algorithms(True)`. | audio-engineer |
| V5 | Same seed across CPU vs GPU and across torch versions | Compare SHA-256 and a feature distance. Expected to differ per the PyTorch docs; measure by how much. | audio-engineer |
| V6 | Does `StableAudioModel.generate` (stable-audio-3 package) accept a `seed` argument, and how does it seed? | Read the package source at a pinned commit SHA | researcher (code read) or audio-engineer |
| V7 | Stability API: same `seed` + prompt + params twice → same bytes? | Two calls, compare SHA-256 (costs about US$0.16) | needs user's API key and consent to spend |
| V8 | Shortest usable output and the trim workflow for one-shots (API minimum 1 s) | Generate 1 s, trim with our deterministic code, check the click/fade with existing analysis | audio-engineer |
| V9 | Is any output a usable kick for the user's taste range (`2026-10-28_kick-gen2-learnings.md`)? | Listening plan by `sound-designer`, then the user listens. No claim beforehand. | sound-designer + user |
| V10 | Exact text of the Stable Audio 3 `LICENSE.md` (fetch failed today) vs the 2024-07-05 Community License; resolve the Medium card's link to the Open 1.0 licence | Log in to HF, read the file, diff it against `stability.ai/community-license-agreement` | researcher |
| V11 | ElevenLabs `eleven_text_to_sound_v3` vs `v2`: release status (Beta Services would block commercial use) | Read the model/changelog page; check whether v3 is labelled beta | researcher |
| V12 | Emergent Drums 2 / Text-to-Sample EULA text for generated samples | Obtain the EULA from the vendor | researcher (or user, if behind a purchase) |

## Open questions only the user can answer

1. Reopen D-005 at all, and when (after which phase)?
2. Local only, or is an online API acceptable (cost per sample, network dependency, the vendor training on your outputs unless you opt out)?
3. Will you ever share or sell the generated one-shots themselves (sample packs, stems)? ElevenLabs forbids that; Stability's terms do not.
4. Is your yearly revenue (all of it, incl. affiliates) under US$1M, i.e. is the free Stability Community tier and its registration acceptable?
5. Do your distributors or labels require AI disclosure? Not researched here. Stability's API terms already forbid presenting outputs as human-made.

## Implications for the lead

- D-005's open point "licence must be checked for releases" now has an answer for the main candidates. Stable Audio 3 (self-hosted or API) allows commercial release for the user under the US$1M threshold, with registration. ElevenLabs allows it on a paid plan, in-track only. AudioGen and TangoFlux are out (non-commercial). Proposal: cite this note if D-005 is reopened. No decision change is proposed here.
- The most plausible local candidate on paper is **Stable Audio 3 Small-SFX** (CPU-capable, about 2.4 GB peak VRAM, no Flash Attention). Medium carries a Windows/Blackwell stack risk (V1, V2).
- If the feature is ever built, it needs a `contract-change` for the sidecar first (source kind, provenance, mandatory `sha256`, licence tag). Reason: L5 of `sample-metadata.schema.json` promises re-rendering, which a generative source cannot keep.
- Keep the generator out of the core package and out of CI. Torch/CUDA as an optional extra or a separate process, so the byte-identical engine goldens are unaffected.
- A "To verify" item never counts as verified. `CURRENT_STATE.md` should list this note's findings only as "researched, not verified".
