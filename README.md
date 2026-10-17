# 弈 · PlayGo

[English](README.md) · [中文](README.zh-CN.md)

A local Go (weiqi/baduk) game with a **KataGo-powered AI**
offering three strength levels, live AI hints and territory estimation,
byo-yomi clocks, undo, automatic SGF saving and AI deep review — all running
on your own machine, no account, no network required after setup.

![Engine](https://img.shields.io/badge/AI-KataGo%20b18c384nbt-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

- **Local two-player** — hot-seat play, black first, Chinese (area) scoring
- **Play vs AI** — three levels on the official KataGo `b18c384nbt` network:

  | Level | Approx. strength | How |
  |---|---|---|
  | Easy 简单 | ~15k–5k | tiny visit budget + wide policy sampling (plays plausible, human-like mistakes) |
  | Medium 中等 | ~amateur 1–4 dan | medium budget + narrow sampling |
  | Hard 困难 | superhuman | 800 visits (GPU), best move |

- **Clock & byo-yomi** — default 30:00 main time, then 60 s ×3 byo-yomi
  periods, loss on expiry (presets: 5:00 / 60:00 / free)
- **Undo** — 1 move in PvP; in AI mode back to your previous turn (Ctrl+Z)
- **AI hint** — top-3 candidate moves with win rates, always computed by the
  strongest available engine, toggleable
- **Territory estimation** — per-point ownership heatmap + win rate / score lead
- **Auto-save** — finished games are written as SGF under `records/`
- **AI review** — replay any saved game with a clickable win-rate curve,
  per-move grading (brilliant → blunder), engine suggestions, and territory replay
- **Scoring** — after two passes the engine marks dead stones automatically;
  you can adjust them by clicking, then confirm the area-scoring result

## 📄 License

- **PlayGo's own code** (everything in this repository except downloaded
  binaries): **MIT** — see [LICENSE](LICENSE).
- **KataGo engine** and its **neural networks** are third-party works by
  David J Wu ("lightvector") and katagotraining.org contributors, both under
  MIT-style licenses. They are **not committed to this repo**; the app
  downloads them on demand from official sources into `backend/engines/`
  (and `package.bat` bundles them for offline distribution, which requires
  shipping their license texts — already handled).
- Full details: [docs/licenses/THIRD-PARTY-NOTICES.md](docs/licenses/THIRD-PARTY-NOTICES.md)

## 🏗️ Architecture

```
┌─────────────────────────── Browser ───────────────────────────┐
│  TypeScript + Canvas 2D (no framework, ~40 KB gzipped)        │
│  main.ts (router)  board.ts (renderer)  audio.ts (WebAudio)   │
│  screens/menu · play · review                                  │
└───────▲───────────────────────────────────────▲───────────────┘
        │ REST  /api/...                         │ WebSocket /ws
        │ (commands & queries)                   │ (state, clocks, downloads…)
┌───────┴───────────────────────────────────────┴───────────────┐
│  Python 3.11+ · FastAPI + uvicorn          playgo.main        │
│                                                                │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ GameSession │  │ EngineManager│  │ DownloadManager    │    │
│  │ (game.py)   │  │ (katago.py)  │  │ (downloader.py)    │    │
│  │ rules.py    │  │  ↕ stdin/    │  │  GitHub releases + │    │
│  │ Board, ko,  │  │    stdout    │  │  katagotraining.org│    │
│  │ area score, │  │  JSON lines  │  │  exe + model, zip  │    │
│  │ clocks,     │  └──────┬───────┘  │  extract, progress │    │
│  │ byo-yomi,   │         │          └────────────────────┘    │
│  │ undo        │  katago.exe analysis (subprocess)            │
│  └────────────┘  Engine packages: CPU lite (default) /        │
│                  GPU strongest (optional); startup falls back │
│                  to the other installed package on failure    │
│                                                                │
│  sgf.py (SGF read/write)   settings.py (presets & URLs)       │
│  records/ (SGF + analysis cache)   ticker task (clock → WS)   │
└────────────────────────────────────────────────────────────────┘
```

### Source layout

```
├── start.bat               One-click launcher (build if needed → serve → open browser)
├── package.bat             Bundles frontend+backend+engines into dist-app/ (offline-ready)
├── backend/                Python package (uv-managed)
│   ├── src/playgo/
│   │   ├── rules.py        Go rules: legal moves, captures, positional superko,
│   │   │                   Chinese area scoring (数子法) — pure, fully unit-tested
│   │   ├── game.py         Authoritative game state machine: turn order, per-player
│   │   │                   clocks, byo-yomi periods, undo semantics, pass/scoring flow
│   │   ├── katago.py       KataGo **analysis engine** wrapper: subprocess lifecycle,
│   │   │                   JSON-line protocol, perspective pinned to Black
│   │   │                   (reportAnalysisWinratesAs=BLACK — winrate/scoreLead/
│   │   │                   ownership arrive black-viewpoint, no flipping),
│   │   │                   difficulty = visit budget + policy-pow sampling
│   │   ├── main.py         FastAPI app: REST + /ws, AI move orchestration,
│   │   │                   auto dead-stone detection, review batch analysis
│   │   ├── downloader.py   On-demand engine/model download with progress callbacks
│   │   ├── sgf.py          SGF (FF4) writer/parser + records library
│   │   └── settings.py     Time presets, difficulty table, engine-package
│   │                       registry, official download URLs
│   ├── tests/              45 tests: rules, ko, scoring, clocks/byo-yomi timeout,
│   │                       engine normalization (black-perspective),
│   │                       engine-package selection & defaulting
│   └── engines/            Runtime home of katago.exe + networks (git-ignored)
│       ├── bundled/eigen/    CPU engine (cpu package component)
│       ├── downloaded/       GPU engine + strong/lite networks
│       └── choice.json       User's package choice (written on explicit switch)
├── frontend/               TypeScript + Vite (no runtime framework)
│   └── src/
│       ├── board.ts        Canvas renderer: flat kaya-toned board, gradient stones,
│       │                   place/capture animations, hover ghost, hint rings,
│       │                   ownership heatmap, dead-stone marking, review nav
│       ├── audio.ts        Stone "clack" synthesized via WebAudio (no assets)
│       ├── api.ts          REST helper + WebSocket bus with auto-reconnect
│       ├── types.ts        DTOs mirroring the backend
│       ├── style.css       Design system (dark-theme tokens)
│       └── screens/        menu.ts · play.ts · review.ts
├── records/                Saved games: YYYY-MM-DD/NNN-Result.sgf (+ .analysis.json)
└── docs/licenses/          KataGo engine & network license texts, third-party notices
```

### How a move travels

1. Player clicks an intersection → `POST /api/game/move {point}`.
2. `GameSession.play` validates turn, legality (captures / suicide / superko)
   via `rules.py`, settles the mover's clock, records the move.
3. The new state is broadcast on `/ws`; the frontend animates the stone and
   any captures, plays the synthesized sound.
4. In AI mode `schedule_ai()` asks the engine for a move at the difficulty's
   visit budget; the reply is validated against turn state (so undo/new-game
   races can't corrupt the game) and applied the same way.
5. Hints / territory are `GET` queries with a cache keyed by the full move
   sequence — undo-and-replay correctly invalidates it.

### Coordinate systems (a real pitfall, handled in `katago.py` / `sgf.py`)

| Representation | Origin | Notes |
|---|---|---|
| Internal `point = y*19+x` | top-left, y down | used everywhere in PlayGo |
| KataGo analysis `"Q16"` | bottom-left, letters skip **I** | converted in/out |
| SGF `pd` | top-left, letters a–s (no skip) | converted in/out |
| Perspective | — | the engine is pinned with `reportAnalysisWinratesAs=BLACK` (matching the shipped config): winrate / scoreLead / ownership always arrive in **Black's viewpoint** regardless of whose turn it is, and flow through unmodified |

### API surface

REST: `GET /api/state` · `POST /api/game/new|move|pass|resign|undo|dead-stones|confirm-score` ·
`GET /api/game/hint|territory` · `GET /api/records[/{file}]` · `POST /api/review/analyze` ·
`GET /api/engines/status` · `POST /api/engines/download` · `POST /api/engines/select`

WS `/ws` events: `state`, `clocks`, `engine`, `download`, `saved`,
`review_progress|done|error`, `error`.

## 🛠️ Technology choices

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.11+ / FastAPI / uvicorn** | subprocess management and async I/O for the engine pipes; typed request models; first-class WebSocket |
| Backend tooling | **uv** (deps + venv), **ruff** (lint/format), **pytest** (45 tests) | modern, fast, one-file config; the package builds via `uv_build` so `uv run uvicorn playgo.main:app` just works |
| Frontend | **TypeScript + Canvas 2D, Vite** | a Go board is one big custom-drawn surface; no framework overhead (~40 KB gz), full control of rendering, DPR-correct drawing |
| Charts | hand-rolled canvas lines, colors validated for CVD | the win-rate curve is one diverging series; a charting library would outweigh it |
| Audio | WebAudio synthesis | zero audio assets to license or ship |
| Persistence | plain **SGF** files + JSON analysis cache | open format readable by any Go tool |

### How KataGo is used (and other open-source software)

- PlayGo **does not link or modify KataGo code**. It spawns the official
  release executable as a child process in **analysis mode**
  (`katago analysis -config … -model …`), speaks its documented JSON-line
  protocol over stdin/stdout, and terminates it on shutdown.
  One persistent process serves every need: AI moves, hints, territory,
  review analysis — queries differ only in visit budget and sampling.
- **Difficulty** is implemented per query: `maxVisits` caps the search and the
  move is either taken as-is (hard) or sampled from the top-k candidate moves
  with weights `prior^p` (easy/medium) — this reproduces human-like
  inaccuracy at low cost on a single strong network.
- **Black-viewpoint contract**: the subprocess is started with
  `reportAnalysisWinratesAs=BLACK` (the same value the official config ships
  since v1.13), so every winrate, score lead and ownership value — for AI
  moves, hints, territory and review alike — already is from Black's
  perspective no matter whose turn it is; nothing downstream flips it. Review
  caches carry a `perspective` marker and pre-fix caches are treated as
  un-analyzed.
- **Dead-stone detection** at scoring reuses the analysis `ownership` vector:
  stones sitting on points owned by the opponent beyond a threshold are
  proposed as dead; the player can override by clicking.
- Engine packages (v1.18.1) and networks are downloaded **from official sources
  only** (GitHub releases · katagotraining.org): the **CPU lite package is the
  default** (Eigen + lionffen_b6c64 lightweight net, ~8 MB — plays smoothly
  without a GPU), while the **GPU strongest package is optional** (OpenCL +
  `kata1-b18c384nbt` strong net, ~100 MB), downloaded in-app on demand and
  switchable at any time; a selected GPU package that fails to start falls back
  to the installed CPU package. The server warms the engine at startup,
  absorbing first-run OpenCL tuning (~a minute, cached afterwards); query
  timeouts scale with difficulty and a wedged engine instance is restarted and
  retried automatically.
- Other open-source components and their licenses are inventoried in
  [docs/licenses/THIRD-PARTY-NOTICES.md](docs/licenses/THIRD-PARTY-NOTICES.md).

## 🚀 Getting started

### Prerequisites

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/)
- **Node.js 18+** (only to build the frontend once)
- Optional: any NVIDIA/AMD GPU (OpenCL) for fast analysis; CPU-only works with
  reduced visit budgets automatically

### One click (Windows)

```
double-click  start.bat
```

It builds the frontend if needed, syncs the backend, starts the server on
`http://127.0.0.1:8900` and opens your browser.

### Manual, step by step

```bash
# 1. Frontend: install dev tools and build the static bundle
cd frontend
npm install
npm run build            # outputs frontend/dist/

# 2. Backend: install dependencies (creates .venv via uv)
cd ../backend
uv sync                  # add --group dev for pytest/ruff/ty

# 3. Run the server (it also serves frontend/dist at /)
uv run uvicorn playgo.main:app --host 127.0.0.1 --port 8900

# 4. Open http://127.0.0.1:8900
```

### First-run engine setup

With no engine present, the menu's engine panel shows two **engine-package
cards** to download and switch between:

- **CPU Lite (default)** — Eigen engine + lionffen_b6c64 lightweight net,
  ~8 MB. The recommended choice for computers without a GPU: small download,
  responsive play.
- **GPU Strongest (optional)** — OpenCL engine + b18c384nbt strong net,
  ~100 MB. Requires a dedicated GPU; activates automatically once downloaded.

Downloads land in `backend/engines/` and persist. Any fully-installed package
can be switched to at any time with one click (the engine process restarts;
switching mid-game is safe). If you skip downloading, AI features will prompt
for it when first needed.

To distribute a fully offline copy: run the downloads once, then
`package.bat` → `dist-app/PlayGo` (engines and license texts included).

### Development mode

```bash
# terminal 1 — backend with autoreload
cd backend && uv run uvicorn playgo.main:app --port 8900 --reload

# terminal 2 — Vite dev server with /api and /ws proxied to 8900
cd frontend && npm run dev    # http://localhost:5173

# tests & lint
cd backend && uv run pytest && uv run ruff check .
cd frontend && npx tsc --noEmit
```

## 📊 Project status

All core flows are covered by automated tests (rules/ko/scoring/clocks) and
were verified end-to-end in a real browser against the live engine:
game → AI reply → hints → territory → undo → scoring → SGF save → review
analysis. Known simplifications: single concurrent game per server session;
board size fixed at 19×19.

**UI languages**: Chinese and English — follows your browser language on first
visit, switchable anytime from the header toggle (persisted).

## 🤝 Credits

- [KataGo](https://github.com/lightvector/KataGo) by David J Wu
  ("lightvector") and contributors — engine and training infrastructure
- Networks by the [KataGo distributed training](https://katagotraining.org/) community
- PlayGo is an independent project; it is not affiliated with KataGo
