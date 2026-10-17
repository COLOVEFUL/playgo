@echo off
rem 弈 · PlayGo 调试入口：重启服务 + 部署最新代码 + 启动（独立于 start.bat）
rem 区别：每次强制重建前端（不存在"旧 dist 顶包"）；先杀 8900 端口旧实例，
rem 可反复执行即重启。构建失败立即退出，不会用旧产物启动。
rem 不带 --reload：uvicorn 在 reload/workers 模式下于 Windows 强制
rem SelectorEventLoop，asyncio 子进程不可用，KataGo 引擎会直接起不来
rem （create_subprocess_exec 抛 NotImplementedError）。改后端代码后重跑本脚本即可。
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [PlayGo] 检查运行环境...
where uv >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 uv，请先安装：https://docs.astral.sh/uv/
  pause
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Node.js，请先安装 Node 18+。
  pause
  exit /b 1
)

rem ── 1. 重启服务：终止 8900 端口上的旧实例 ──
rem 监听者可能只是 worker（uvicorn.exe 壳 → venv python → 监听 python），
rem 只杀监听者会被上层进程复活或留下孤儿；故先沿 python/uv/uvicorn 父链
rem 上溯到树根，再 taskkill /T 连同 katago 子进程整树终止。
powershell -NoProfile -Command "$roots=@{}; Get-NetTCPConnection -LocalPort 8900 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p=$_.OwningProcess; while($true){ $proc=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p); if(-not $proc){break}; $par=Get-CimInstance Win32_Process -Filter ('ProcessId='+$proc.ParentProcessId); if($par -and $par.Name -match '^(python|pythonw|uv|uvicorn)\.exe$'){$p=$par.ProcessId}else{break} }; $roots[$p]=1 }; foreach($r in $roots.Keys){ taskkill /F /T /PID $r | Out-Null }; exit $roots.Count" >nul 2>nul
if errorlevel 1 (
  echo [PlayGo] 已终止旧服务进程，准备以最新代码重启
) else (
  echo [PlayGo] 端口 8900 空闲，直接启动
)

rem ── 2. 部署最新代码：后端依赖 + 前端强制重建 ──
cd backend
uv sync --group dev
if errorlevel 1 ( echo [错误] 后端依赖同步失败 & pause & exit /b 1 )
cd ..\frontend
if not exist node_modules call npm install
call npm run build
if errorlevel 1 ( echo [错误] 前端构建失败，请检查上方 TS/打包报错 & pause & exit /b 1 )
cd ..\backend

rem ── 3. 启动（延迟 2 秒再开浏览器，避免抢在端口就绪之前）──
echo [PlayGo] 启动服务：http://127.0.0.1:8900 （改动后重跑本脚本即重启生效）
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8900"
uv run uvicorn playgo.main:app --host 127.0.0.1 --port 8900
endlocal
