# localai

[![CI](https://github.com/ringo7pie/localai/actions/workflows/ci.yml/badge.svg)](https://github.com/ringo7pie/localai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Running a pack of local AI services on a single 24 GB GPU — and measuring which ones are worth running.**

localai is the glue, ops tooling and evaluation harness behind a personal GPU server (NVIDIA A30, 24 GB):
an LLM server (Ollama), a MoE inference engine that splits experts between CPU and GPU (Strata),
image-to-3D generation (Hunyuan3D, Pixal3D), a ComfyUI watertight-mesh workflow, a bridge that lets Claude Code / Codex
hand mechanical coding work to a local Qwen, and a harness that compares cloud and local models on the same problems.

> 日本語の詳細は [README.ja.md](README.ja.md)。

| | |
|---|---|
| **Portfolio page** | [docs/portfolio.md](docs/portfolio.md) — problems, design decisions, measured numbers |
| **Live reports** | `https://ringo7pie.github.io/localai/` — evaluation reports (Japanese) |
| **Architecture** | [docs/architecture.md](docs/architecture.md) |
| **Requirements** | [docs/hardware-requirements.md](docs/hardware-requirements.md) |

![Landing page of the service portal](docs/images/portal.png)

## Highlights

- **GPU arbitration.** One GPU, several heavy services. A small dependency-free web portal starts and stops them,
  stops the other running GPU service before it starts one and unloads the Ollama model before a Strata start; systemd
  `Conflicts=` covers the case where someone calls `systemctl` directly.
- **A MoE model that does not fit in VRAM, served on a 24 GB card.** Strata's engine is built from a pinned commit
  (CUDA 13.2, `sm_80`) and exposed as an OpenAI-compatible API in five variants.
- **An evaluation harness with hidden tests.** Nine models (two Claude, five Ollama, two Strata) answer the same
  16 problems; coding answers run against hidden tests in a sandbox. One finding: the *thinking budget* that looked like a
  handicap for Strata was in fact what kept its score up (45 of 49 runs hit the budget; removing it dropped one variant from
  69 % to 0 %).
- **A second, harder round (2026-10-18).** Nine problems built to separate Sonnet from Opus, run against eight Claude
  configurations (Sonnet / Opus × four effort levels, three runs each) and nine local models. All eight Claude
  configurations land at 98–100 %; the best local model reaches 78 % and takes about four times as long per problem.
- **Reproducible installs.** Upstream projects are pinned to commits, setup scripts are non-interactive, idempotent and
  need no `sudo`; unit files are rendered for wherever you cloned the repo.
- **License-aware publishing.** What may and may not be redistributed was checked against upstream `LICENSE` files —
  see [NOTICE.md](NOTICE.md).

## Architecture

```mermaid
flowchart LR
  subgraph clients["clients"]
    browser["browser"]
    cloud["Claude Code / Codex"]
  end
  subgraph server["GPU server (Ubuntu, systemd --user)"]
    portal["portal :8080"]
    webui["Open WebUI :8081"]
    ollama["Ollama :11434"]
    strata["Strata :8082-8086"]
    h3d["Hunyuan3D :7860"]
    p3d["Pixal3D :7861"]
    comfy["ComfyUI :8188"]
    gpu[("A30 24 GB")]
  end
  browser --> portal
  portal -- "systemctl --user" --> webui & strata & h3d & p3d & comfy
  portal -- "unload before Strata" --> ollama
  webui --> ollama & strata
  cloud -- "MCP" --> bridge["local-ai-bridge / qwen-worker"] --> ollama
  ollama & strata & h3d & p3d & comfy --> gpu
```

## What is in the box

| Path | What it is | GPU needed |
|---|---|---|
| `localai` | Entry script: `doctor`, `install`, `start` / `stop` / `status`, `test` | no |
| `tools/portal` | Service portal (port 8080): start / stop, GPU exclusion, memory limits. No dependencies | no |
| `tools/strata` | MoE CPU–GPU split inference engine, five model variants (ports 8082–8086) | yes |
| `tools/pixal3d` | Multi-view images → 3D mesh (Pixal3D, port 7861) | yes |
| `tools/hunyuan3d` | Four images → 3D mesh (Hunyuan3D-2mv, port 7860). **Needs license acceptance**, see below | yes |
| `tools/comfyui` | ComfyUI + watertight-mesh workflow (port 8188); native parts built from source | yes |
| `tools/qwen-worker` | MCP server that lets Claude Code / Codex use a local Qwen for read-only research and sandboxed edits | no (calls Ollama) |
| `tools/local-ai-bridge` | Heavier bridge: task ledger, git-worktree isolation, verification, budgets | no (calls Ollama) |
| `tools/model-eval` | Evaluation harness, hidden-test grading, HTML report builders | no (calls servers) |
| `tools/qwen-model-bench` | Measure whether one Ollama model is usable on this machine | yes |
| `tools/status`, `tools/gpu-watch-gui` | What is Qwen doing now / small GTK GPU monitor | no |
| `Documents/` | Evaluation reports and guides (self-contained HTML, Japanese) | — |
| `knowledge/` | Operational notes: measured facts, constraints, decisions (Japanese) | — |

## Quick start

Tested configuration: Ubuntu 24.04, NVIDIA A30 24 GB, driver 595, CUDA 13.2 + 12.6, 64 GB RAM.
Other setups are **unverified** — see [docs/hardware-requirements.md](docs/hardware-requirements.md).

```bash
git clone https://github.com/ringo7pie/localai.git
cd localai
./localai doctor              # checks GPU, CUDA, RAM, disk, uv, Ollama, ports
./localai install ollama      # prints the official Ollama steps and `ollama pull qwen3.8:27b`
./localai install portal      # the web portal (port 8080); no GPU needed
./localai start portal
```

Then add what you need: `./localai install strata`, `pixal3d`, `comfyui`, `hunyuan3d`, `qwen-worker`.
Heavy services are started from the portal (or `./localai start <name>`), one GPU service at a time.

No GPU? You can still read the reports, run the portal and run the unit tests:

```bash
./localai test                # GPU-free tests, reported per tool
python3 tools/portal/portal.py --host 127.0.0.1 --port 18080
```

## Evaluation snapshot (2026-10-18)

A harder round: six coding problems (hidden tests, sandboxed) and three math problems, written so that Sonnet and Opus
might come apart. Open the reports (Japanese, self-contained HTML):

- [AIモデル評価_2026-10-18.html](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_2026-10-18.html) — results, conditions and caveats
- [AIモデル評価_出題内容_2026-10-18.html](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_%E5%87%BA%E9%A1%8C%E5%86%85%E5%AE%B9_2026-10-18.html) — the nine problems explained, with examples and figures
- [ローカルAI一覧_2026-10-18.html](https://ringo7pie.github.io/localai/reports/%E3%83%AD%E3%83%BC%E3%82%AB%E3%83%ABAI%E4%B8%80%E8%A6%A7_2026-10-18.html) — the local models on this machine

Ability = mean score over the nine problems. Time = median seconds per run. Claude was run three times per problem
through sub-agents (time includes API wait); local models once per problem, on this machine (generation only, no model load).

| Model | Ability | Median time |
|---|---|---|
| Sonnet 5.5 xHigh | 98.6 % | 98 s |
| Sonnet 5.5 Low | 98.4 % | 29 s |
| Opus 5.5 xHigh | 99.9 % | 123 s |
| Opus 5.5 Low | 98.8 % | 31 s |
| Strata official IQ3_XXS | 77.8 % | 363 s |
| Strata Coder IQ1_M | 68.2 % | 393 s |
| Strata official IQ3_S | 66.5 % | 451 s |
| Strata Swift 1.5 IQ3_XXS | 55.2 % | 364 s |
| gemma4:31b-it-qat | 54.5 % | 443 s |
| qwen3.8:27b | 27.8 % | 534 s |
| gemma4:e4b | 18.0 % | 115 s |
| qwen3.8-flash-next IQ4_XS (Ollama) | 11.1 % | 1,404 s |
| Strata RVN IQ3_S | 4.0 % | 480 s |

Medium and High effort for both Claude models are in the report (98–100 % as well).

- **Facts.**
  - Sonnet and Opus are mostly not separated. Only at High is Opus ahead (every Opus run scored above every Sonnet run);
    at xHigh, Medium and Low the score ranges overlap.
  - The one systematic difference is a single case in problem H3: Sonnet failed it in 12 of 12 runs, Opus in 1 of 12.
  - Dropping effort from xHigh to Low cuts the time to a third or a quarter and leaves ability in the same 98–100 % band.
  - No local model fully solved H3 (type inference) or H5 (minimal DFA).
  - Most of qwen3.8:27b's lost points are runs that stop in the middle of thinking with an empty answer.
- **Caveats.** One run per cell for local models, so small gaps are noise. The problems were chosen to be hard for Claude;
  the gap on everyday work may be smaller (not measured).

## Earlier round (2026-10-08)

The first round: 3D math, six coding problems and nine extra problems. Open the reports (Japanese, self-contained HTML):

- [AIモデル評価_2026-10-08.html](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_2026-10-08.html) — full tables, method and caveats
- [AIモデル評価_出題内容_2026-10-08.html](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_%E5%87%BA%E9%A1%8C%E5%86%85%E5%AE%B9_2026-10-08.html) — the 16 problems explained

Ability = mean score per problem; time = median seconds. Few trials per cell — treat small differences as noise.

| Model | 3D math | Coding (6) | Extra (9) |
|---|---|---|---|
| Sonnet 5.5 xHigh | 100 % · 67 s | 100 % · 46 s | 100 % · 2 s |
| Opus 5.5 xHigh | 100 % · 62 s | 100 % · 59 s | 100 % · 3 s |
| qwen3.8:27b (Ollama) | 88 % · 873 s | 83 % · 243 s | 100 % · 13 s |
| gemma4:31b-it-qat | 100 % · 3,660 s | 92 % · 699 s | 100 % · 45 s |
| Strata official IQ3_XXS | 100 % · 839 s | 84 % · 464 s | 98 % · 8 s |
| Strata Coder IQ1_M | 100 % · 728 s | 59 % · 406 s | 89 % · 7 s |

![Coding results per problem and model](docs/images/eval-coding-heatmap.png)

## Security notes

- The portal and the model servers listen on the LAN and have **no authentication**. Anyone on the network can start and
  stop services. Keep them behind a firewall or bind them to `127.0.0.1`.
- One Strata variant is an *abliterated* model (refusal direction removed) and answers harmful requests. If you expose it,
  set `STRATA_API_KEY`.
- Messages that Qwen returns through `qwen-worker` / `local-ai-bridge` (summaries and diffs) travel through the cloud
  parent. This is not a "nothing leaves the machine" setup.

## License and third-party notices

The code and documents in this repository are MIT-licensed ([LICENSE](LICENSE)). Upstream software and model weights are
**not** redistributed; setup scripts fetch them from their sources under their own licenses. See [NOTICE.md](NOTICE.md).

- **Hunyuan3D-2** is under the *Tencent Hunyuan 3D 2.0 Community License*, which does not apply in the EU, UK and
  South Korea. This repository therefore does not ship patches against it, and `tools/hunyuan3d/setup-server.sh`
  asks you to accept the license (`--accept-tencent-license`) before it fetches anything.
- **Pixal3D** output is treated as non-commercial (NVIDIA Source Code License components, Meta DINOv3).
- Product and company names belong to their owners; this project is not affiliated with or endorsed by them.
