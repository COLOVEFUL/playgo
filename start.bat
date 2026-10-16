@echo off
rem 弈 · PlayGo 一键启动：起后端 + 自动打开浏览器
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [PlayGo] 检查运行环境...

rem ── 前端：无构建产物则构建 ──
if not exist "frontend\dist\index.html" (
  echo [PlayGo] 首次运行：构建前端页面...
  where node >nul 2>nul
  if errorlevel 1 (
    echo [错误] 未找到 Node.js，请先安装 Node 18+ 或手动执行 frontend 目录的构建。
    pause
    exit /b 1
  )
  cd frontend
  if not exist node_modules call npm install
  call npm run build
  cd ..
)

rem ── 后端依赖 ──
where uv >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 uv，请先安装：https://docs.astral.sh/uv/
  pause
  exit /b 1
)
cd backend
uv sync >nul 2>nul

rem ── 启动 ──
echo [PlayGo] 启动服务：http://127.0.0.1:8900
start "" http://127.0.0.1:8900
uv run uvicorn playgo.main:app --host 127.0.0.1 --port 8900
endlocal
