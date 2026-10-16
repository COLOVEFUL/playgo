# 弈 · PlayGo

本地围棋对弈程序：拟真木纹棋盘、KataGo AI 三档棋力、AI 推荐与形势判断、
读秒计时、悔棋、自动存谱与 AI 深度复盘。

## 功能

- **双人对弈**：同屏轮流落子（黑先白后，中国规则数子法）
- **人机对弈**：KataGo 引擎，三档难度（参考社区棋力对照）
  | 难度 | 棋力 | 机制 |
  |---|---|---|
  | 简单 | 约 15k~5k | 极低搜索量 + 宽采样，走出"人味"失误 |
  | 中等 | 约业余 1~4 段 | 中等搜索量 + 窄采样 |
  | 困难 | 超职业 | 800 visits 全力搜索（GPU） |
- **计时读秒**：主时 30:00（可选 5:00 / 60:00 / 不限时），耗尽后 60s 读秒 ×3，用尽判负
- **悔棋**：人人退 1 手；人机退回到您上一手之前（Ctrl+Z）
- **AI 推荐**：当前局面 Top-3 候选 + 胜率（最高棋力引擎计算，可开关）
- **形势判断**：领地热力图 + 胜率/目差（ownership 逐点归属）
- **自动存谱**：对局结束自动保存 SGF 到 `records/`
- **AI 深度复盘**：逐步回放 + 胜率曲线（可点击跳转）+ 每手评价
  （神之一手/好棋/普通/缓手/恶手/败着）+ AI 建议 + 形势回看
- **终局点目**：双停一手后引擎自动判定死活，可手动调整死子，数子法判定

## 快速开始

### 环境

- Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 18+（仅首次构建前端需要）
- 显卡可选（NVIDIA/AMD 皆可，OpenCL 加速；无显卡走 CPU）

### 启动

```
双击 start.bat
```

或手动：

```
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync && uv run uvicorn playgo.main:app --port 8900
浏览器打开 http://127.0.0.1:8900
```

### AI 引擎

程序按需下载 KataGo 官方引擎与网络（一次性，保存在本地）：

- **CPU 引擎（Eigen）**：6MB，任何机器可用
- **GPU 引擎（OpenCL）**：6MB，有 N/A 卡时自动启用
- **强网络 b18c384nbt**：94MB，三档难度共用（棋力由搜索量与采样控制）

主菜单「引擎状态」处点击即可下载，进度实时可见。
分发离线版：先在本机下载齐全，再运行 `package.bat` 打包。

## 项目结构

```
├── start.bat            一键启动
├── package.bat          打包发行版（含引擎，离线可玩）
├── backend/             Python FastAPI
│   ├── src/playgo/
│   │   ├── rules.py     围棋规则（数子法/位置超级劫）+ 测试
│   │   ├── game.py      对局状态机（计时读秒/悔棋/终局）
│   │   ├── katago.py    KataGo Analysis 引擎封装
│   │   ├── sgf.py       SGF 读写
│   │   ├── downloader.py 引擎按需下载
│   │   ├── settings.py  配置（难度表/用时预设/直链）
│   │   └── main.py      REST + WebSocket 入口
│   └── engines/         引擎与模型（git 忽略，本地保存）
├── frontend/            TypeScript + Canvas（Vite）
│   └── src/
│       ├── board.ts     拟真棋盘渲染（木纹/棋子/动画/覆盖层）
│       ├── audio.ts     落子音效（WebAudio 合成）
│       └── screens/     menu / play / review 三屏
├── records/             对局棋谱（SGF + 分析缓存）
└── design/              UI 设计稿
```

## 开发

```
cd backend && uv run pytest        # 19 项测试
cd backend && uv run ruff check .  # lint
cd frontend && npm run dev         # 前端开发服务器（代理到 8900）
```

## 说明

- 引擎与模型来自 [KataGo 官方发布](https://github.com/lightvector/KataGo) 与
  [katagotraining.org](https://katagotraining.org/networks/)，遵守其许可证
- 中国规则：贴 7.5 目（可在新建对局时调整），数子法计胜负
- 首次 GPU 分析会触发 OpenCL 调优（数十秒），之后毫秒级响应
