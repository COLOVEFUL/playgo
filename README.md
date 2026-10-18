# 弈 · PlayGo

[English](README.md) · [中文](README.zh-CN.md)

A local Go (weiqi/baduk) game with a **KataGo-powered AI**
offering 20K–9D human-style rank profiles, live AI hints and territory estimation,
byo-yomi clocks, undo, automatic SGF saving and AI deep review — all running
on your own machine, no account, no network required after setup.

![Engine](https://img.shields.io/badge/AI-KataGo%20b18c384nbt-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

- **Local two-player** — hot-seat play, black first, Chinese (area) scoring
- **Play vs AI** — **20K/15K/10K/5K/1K/1D/3D/5D/7D/9D**, plus
  **Maximum**. The default is Quick practice at 10K. Kyu counts down as strength increases; dan counts up.

  | Level | Model and method | Limits |
  |---|---|---|
  | Quick practice: 15K/10K/5K/1K/1D/3D | Existing main model, KaTrain-style calibrated rank algorithm, 1 visit | Estimates only; calibration does not transfer unchanged across models |
  | Human style: 20K–9D presets | Official Human SL `b18c384nbt-humanv0`, original-probability policy sampling | Human-style targets, not PlayGo match-calibrated ranks; high-dan strength may fall short |
  | Maximum, CPU | `lionffen_b6c64`, best searched move, 160 visits | Model-dependent, no fixed dan claim |
  | Maximum, GPU | `kata1-b18c384nbt`, best searched move, 800 visits | Stronger model/search budget, no fixed dan claim |

  Quick practice needs no additional model. Choose **Human style** and download
  its optional model (~95MB) to use human-style targets; the new-game dialog also links to this download. Without it,
  Quick practice and Maximum remain available using your existing main model. The download restarts
  the engine automatically. Human-style play uses the same 18-block, 384-channel human
  model on CPU and GPU; CPU inference may be slower than the lite model. The main
  model uses 64 visits only to decide when to pass. Hints and review still use the
  main model at their own analysis budgets.

  These labels follow [KataGo's Human SL profiles and recommended sampling recipe](https://github.com/lightvector/KataGo/blob/v1.18.1/docs/Analysis_Engine.md#human-sl-analysis-guide),
  also used by [KaTrain's human-like AI](https://github.com/sanderland/katrain#ais).
  Human-style labels are 19×19 imitation targets. Quick practice adapts KaTrain’s
  calibrated-rank candidate-count formula, uniform sampling without replacement,
  and key-move/endgame safeguards; it stays within the reference 15K–3D range.
  PlayGo has not match-calibrated either mode. Neither mode gives equivalents of Chinese rank certificates
  or any particular server's ranks; **9D is not professional 9 dan**. Raw high-dan
  policy can be weaker than its target, especially in complex fights. The dialog
  shows the actual main model, network scale (`b` = blocks, `c` = channels), backend
  and visit budget; the game sidebar follows the active engine, including fallback.

- **Clock & byo-yomi** — default 30:00 main time, then 60 s ×3 Japanese-style
  byo-yomi: each turn restarts at a full period, and a period is spent only
  when it expires mid-turn (several can burn in one turn); loss when they run
  out (presets: 5:00 / 60:00 / free)
- **Undo** — 1 move in PvP; in AI mode back to your previous turn (Ctrl+Z)
- **AI hint** — top-3 candidate moves with win rates shown from *your* side's
  view (playing White no longer shows Black's number), always computed by the
  strongest available engine, toggleable
- **Territory estimation** — per-point ownership heatmap + win rate / score lead
- **Auto-save** — finished games are written as SGF under `records/`
- **AI review** — replay any saved game with a clickable win-rate curve,
  per-move grading (brilliant → blunder), engine suggestions, and territory replay
- **Review hints** — at any replay position, request live top-3 candidate moves
  with win rates and compare what you played against the engine's pick — no
  full-game analysis needed first
- **Takeover** — take over any reviewed position and play it out yourself,
  handling both Black and White to verify your reading; free clock, original
  board size and komi, hints/territory still available; takeover games are not saved.
  **Return to review** takes you back to the original record and takeover move
- **Scoring** — after two passes, or at any moment via the **Score** button:
  the engine marks dead stones and counts both sides with the chosen komi,
  then asks whether you accept the verdict — confirm to end and save the game,
  or keep playing (no moves are undone)

To explore a variation, open a saved game in Records and use the arrows, slider,
or curve to choose a position. Toggle **AI hint** for live candidates (win rates
are shown for the side to move), or click **Take over** to play both sides and
undo moves freely. Click **Return to review** to resume the original replay;
you can choose another position and take over again. Suggestions refresh as you
navigate, with loading/error messages; stale results from earlier positions or
records are discarded. Switching languages preserves the board size and position.

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
├── dev.bat                 Debug entry (kill old instance → force frontend rebuild → serve)
├── package.bat             Bundles frontend+backend+engines into dist-app/ (offline-ready)
├── backend/                Python package (uv-managed)
│   ├── src/playgo/
│   │   ├── rules.py        Go rules: legal moves, captures, positional superko,
│   │   │                   Chinese area scoring (数子法) — pure, fully unit-tested
│   │   ├── game.py         Authoritative game state machine: turn order, per-player
│   │   │                   clocks, byo-yomi periods, undo semantics, scoring flow
│   │   │                   (two passes or on demand; declining resumes losslessly)
│   │   ├── katago.py       KataGo **analysis engine** wrapper: subprocess lifecycle,
│   │   │                   JSON-line protocol, perspective pinned to Black
│   │   │                   (reportAnalysisWinratesAs=BLACK — winrate/scoreLead/
│   │   │                   ownership arrive black-viewpoint, no flipping),
│   │   │                   ranks = Human SL policy; Maximum = main-model search
│   │   ├── main.py         FastAPI app: REST + /ws, AI move orchestration,
│   │   │                   auto dead-stone detection, review batch analysis,
│   │   │                   review hints & position takeover
│   │   ├── downloader.py   On-demand engine/model download with progress callbacks
│   │   ├── sgf.py          SGF (FF4) writer/parser + records library
│   │   └── settings.py     Time presets, difficulty table, engine-package
│   │                       registry, official download URLs
│   ├── tests/              Tests: rules, ko, scoring, clocks/byo-yomi timeout,
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
4. In AI mode `schedule_ai()` asks the engine for a move at the selected rank's
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
`GET /api/review/hint` · `POST /api/review/takeover` ·
`GET /api/engines/status` · `POST /api/engines/download` · `POST /api/engines/select`

WS `/ws` events: `state`, `clocks`, `engine`, `download`, `saved`,
`review_progress|done|error`, `error`.

## 🛠️ Technology choices

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.11+ / FastAPI / uvicorn** | subprocess management and async I/O for the engine pipes; typed request models; first-class WebSocket |
| Backend tooling | **uv** (deps + venv), **ruff** (lint/format), **pytest** | modern, fast, one-file config; the package builds via `uv_build` so `uv run uvicorn playgo.main:app` just works |
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
  review analysis. When installed, the auxiliary human model is loaded via
  `-human-model` in this same process.
- **Difficulty** uses per-query `humanSLProfile=rank_*`, `includePolicy=true`,
  and `ignorePreRootHistory=false`. Ranked moves sample the full `humanPolicy`
  after legal-move filtering; the main model's top pass is respected. Maximum
  takes the main model's best move. Missing human policies raise an explicit
  error, preserving the selected rank. Old API IDs `easy/medium/hard` migrate
  to `15k/1d/max` (a strategy migration, not a strength equivalence).
  `ai_style=rank|human` selects Quick practice or Human style; default `rank`.
  Quick practice requests the main network policy with 1 visit, with no Human SL
  dependency. Unsupported combinations and missing policies fail explicitly.
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

To distribute the default CPU-only offline copy: download the CPU package, then
`package.bat` → `dist-app/PlayGo` (CPU engine/model and license texts included).

The default `package.bat` distribution includes only the CPU lite engine and model.
GPU (~100MB) and Human SL (~95MB) downloads are optional, performed in the app;
even if installed on the packaging machine they are excluded from the release.

### Development mode

One-click debug entry (restart + redeploy: kills any old instance on port
8900, force-rebuilds the frontend, starts the server; safe to run
repeatedly):

```
double-click  dev.bat
```

Or manually, in two terminals:

```bash
# terminal 1 — backend (do NOT add --reload: on Windows, reload mode
# disables asyncio subprocesses and the KataGo engine cannot start;
# restart manually after backend changes)
cd backend && uv run uvicorn playgo.main:app --port 8900

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
