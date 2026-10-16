# Initial local engine verification

Verification date: 2026-10-17 (Australia/Sydney).

## Scope and evidence

The user ran the checks on the target Ubuntu laptop and supplied terminal output.
The results below summarize that output and the user's listening and Wi-Fi status
reports. They establish a working recorded-audio pipeline, not a completed
push-to-talk application or a sustained-performance benchmark.

No recordings, transcripts, generated answers, raw terminal logs, model binaries
or personal filesystem paths are included in this report.

## Hardware and toolchain

| Component | Observed configuration |
| --- | --- |
| Operating system | Ubuntu 26.04.1 LTS |
| CPU | Intel Core i7-11800H (project target; CPU identification was not captured in these logs) |
| System RAM | `free -h` reports 14 GiB usable total; project target is 16 GB installed |
| GPU | NVIDIA GeForce RTX 3050 Ti Laptop GPU, 4096 MiB VRAM |
| NVIDIA driver | 595.91.07 |
| CUDA toolkit | 12.4, NVCC 12.4.131 |
| Build compilers | GCC/G++ 13.4.0, explicitly selected for llama.cpp |
| System default compilers | GCC/G++ 15.2.0; not used for the CUDA build |
| CMake | 4.2.3 |
| Git | 2.53.0 |
| Python project management | uv 0.12.18, Python 3.12 project constraint |

`nvidia-smi` reported CUDA 13.2 as the driver's supported CUDA version; the
installed compiler reported toolkit 12.4. These are different measurements.
A small CUDA program compiled with G++ 13.4 and returned the expected GPU result
of 42. This observed success does not imply that Ubuntu 26.04 is a validated
platform for every CUDA 12.4 workload.

## Models and runtime settings

### Qwen through llama.cpp

- Source release: `v0.7.0`.
- Source commit: `620d2225cc436ab0b001e3200e590e3b286ef9ab`.
- Binary reports: `0.7.0-dev (build 1, commit 620d222)`, GNU 13.4.0, Linux x86_64.
- CUDA build enabled, with native GPU architecture and G++ 13 as CUDA host compiler.
- Both `llama-cli` and `llama-server` built successfully; device listing found CUDA0.
- Model: `Qwen/Qwen3-4B-GGUF`, `Qwen3-4B-Q4_K_M.gguf`.
- Model revision: `bc640142c66e1fdd12af0bd68f40445458f3869b`.
- Model SHA-256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`.
- The user confirmed that the downloaded model checksum matched.

Server settings used for the combined tests:

```text
--alias qwen3-4b
--host 127.0.0.1
--port 8080
--ctx-size 4096
--parallel 1
--gpu-layers auto
--fit on
--fit-target 512
--batch-size 256
--ubatch-size 128
--jinja
--chat-template-kwargs '{"enable_thinking":false}'
--offline
--no-webui
```

Requests used the local `/v1/chat/completions` endpoint, temperature 0.7,
non-streaming responses and a 160-token output limit for combined tests. A short
system instruction established on-device operation and requested brief answers.
The diagnostic rejected empty answers, reasoning markup and unfinished responses.

### Speech recognition

- Engine: faster-whisper 1.2.1.
- Model: `Systran/faster-whisper-small.en`.
- Model revision: `d1d751a5f8271d482d14ca55d9e2deeebbae577f`.
- Device/compute type: CPU/int8; eight CPU threads, one worker.
- Transcription: English, beam size 5, VAD enabled, previous-text conditioning disabled.
- Input: a ten-second user-recorded WAV; transcription was fully consumed before timing ended.
- PyAV 19.0.1 initially failed on the removed `metadata_errors` argument.
  Constraining PyAV to `>=18,<19` resolved the environment to 18.1.0.
  Synthetic mono/stereo decoding and the real recording then passed. See
  [dependency compatibility](dependency-compatibility.md).

### Speech synthesis and playback

- Engine: Piper (`piper-tts` 1.8.0).
- Voice: `en_US-ljspeech-medium`, loaded explicitly on CPU (`use_cuda=False`).
- Voice repository: `rhasspy/piper-voices`.
- Voice revision: `c10ece1aade47bb51c153c893d14e5bf8e5b7117`.
- Expected ONNX SHA-256: `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`.
- Output: mono, signed 16-bit PCM WAV at 22050 Hz; playback through `aplay`.
- The user confirmed clear, complete playback during the independent Piper test.
- Independent Piper timing output and a separate voice checksum result were not
  supplied; combined synthesis timings are recorded below.

At report preparation, the local environment reported Python 3.12.14,
CTranslate2 4.8.3 and ONNX Runtime 1.31.0 in addition to the engine versions above.
Exact Python package resolutions are recorded in the repository's `uv.lock`.

## Independent results

| Check | Result |
| --- | --- |
| CUDA compilation/execution | Expected GPU result returned |
| llama.cpp build/device discovery | Both executables built; NVIDIA GPU detected |
| Qwen inference | Completed a short response; about 57.1 generated tokens/s, 0.998 s generation and 0.046 s prompt processing in one request |
| Whisper loading | 0.57 s in the successful transcription run |
| Whisper transcription | 10.00 s recording transcribed in 1.25 s, then 1.14 s |
| Piper generation/listening | User reported hearing the full sentence clearly |

The first Qwen prompt used the ambiguous phrase "local voice assistant" and
received a geographically focused explanation. The combined test clarified
on-device operation in the system instruction. No broader response-quality
evaluation has been performed.

## Combined recorded-audio pipeline

The diagnostic loaded Whisper and Piper once per process, then performed two
sequential turns against a running llama-server:

```text
Recorded WAV → Whisper → local Qwen HTTP request → Piper → aplay
```

Temporary synthesized WAV files were removed on exit. The diagnostic did not
capture live microphone input, execute model-proposed tools or retain conversation
history between turns. All three models remained loaded for the final memory
snapshot in each run.

| Run | Whisper + Piper load | Turn | Whisper | Qwen request | Piper | Processing before playback |
| --- | --- | --- | --- | --- | --- | --- |
| Initial combined run | 1.60 s | 1 | 1.19 s | 0.59 s | 0.27 s | 2.06 s |
| Initial combined run | 1.60 s | 2 | 1.12 s | 0.53 s | 0.27 s | 1.92 s |
| Wi-Fi off; llama-server retained | 1.58 s | 1 | 1.14 s | 0.62 s | 0.24 s | 2.00 s |
| Wi-Fi off; llama-server retained | 1.58 s | 2 | 1.13 s | 0.47 s | 0.21 s | 1.81 s |
| Wi-Fi off; llama-server restarted | 1.63 s | 1 | 1.15 s | 0.61 s | 0.25 s | 2.02 s |
| Wi-Fi off; llama-server restarted | 1.63 s | 2 | 1.13 s | 0.47 s | 0.23 s | 1.84 s |

All six turns completed without a reported pipeline error. The playback command
returned successfully in each turn. Times are printed to two decimal places, so
rounded stage values may not sum exactly to the printed total.

Timing excludes recording duration, model loading and speaker playback. It measures
complete response generation and synthesis, not streaming time to first token or
first audible sample. The repeated input can benefit from Qwen's prompt cache,
and answer lengths vary. These six samples do not establish median/p95 latency
over representative workloads.

### Memory snapshots with all three models loaded

| Run | Total GPU memory used | llama-server GPU memory | Available system RAM | Swap used |
| --- | --- | --- | --- | --- |
| Initial combined run | 3100 / 4096 MiB | 3072 MiB | 7.8 GiB | 48 MiB |
| Wi-Fi off; server retained | 3100 / 4096 MiB | 3072 MiB | 7.9 GiB | 48 MiB |
| Wi-Fi off; server restarted | 3100 / 4096 MiB | 3072 MiB | 8.0 GiB | 48 MiB |

These are end-of-run snapshots, not peak memory measurements. GPU use is observed;
the exact offloaded layer count was not supplied, so full GPU offload is not claimed.

## Offline evidence and limits

The user reported disabling Wi-Fi, then repeated the test successfully. They then
reported restarting llama-server while Wi-Fi remained off and supplied another
successful two-turn run. A changed server process ID is visible in the supplied
output. Whisper and Piper were also reloaded in a fresh Python process.

The Python runs set `UV_OFFLINE=true`, `HF_HUB_OFFLINE=1` and
`HF_HUB_DISABLE_TELEMETRY=1`, loaded explicit local model paths and used only the
fixed loopback Qwen endpoint. This supports restart and operation with Wi-Fi
disabled and existing assets present. Other network interfaces were not audited,
and no packet capture or outbound-connection audit was performed. This is not
proof that no component attempted an external request.

## Remaining milestone verification

- Live push-to-talk capture, microphone-off behavior and device failures.
- Explicit state transitions, cancellation, deadlines and recovery from unavailable engines.
- Tool schema validation, allowlist rejection and confirmation policy tests.
- Backend health/readiness, authenticated transport and origin restrictions.
- Frontend/Tauri integration and visible errors.
- Twenty consecutive turns, longer/context-heavy prompts, silence and noisy input.
- Representative latency distribution and peak RAM/VRAM monitoring.
- Network observation and loopback-only listener verification for the integrated application.
- Exact GPU offload configuration and reproducible startup documentation.
- Piper engine/voice distribution licensing review before packaging or release.

The next implementation phase is the controller, typed interfaces and explicit
state machine. The engine checks do not mark the complete push-to-talk milestone done.
