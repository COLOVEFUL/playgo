@echo off
rem 打包发行版：收集前后端与已下载引擎到 dist-app/（开箱即玩，无需联网）
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [PlayGo] 确保前端已构建...
if not exist "frontend\dist\index.html" (
  cd frontend && call npm install && call npm run build && cd ..
)

set OUT=dist-app\PlayGo
if exist dist-app rmdir /s /q dist-app
mkdir "%OUT%"

xcopy /e /i /q backend\src "%OUT%\backend\src" >nul
xcopy /e /i /q backend\tests "%OUT%\backend\tests" >nul
copy /y backend\pyproject.toml "%OUT%\backend\" >nul
copy /y backend\uv.lock "%OUT%\backend\" >nul
xcopy /e /i /q backend\engines "%OUT%\backend\engines" >nul
xcopy /e /i /q frontend\dist "%OUT%\frontend\dist" >nul
xcopy /e /i /q docs "%OUT%\docs" >nul
copy /y start.bat "%OUT%\" >nul
copy /y LICENSE "%OUT%\" >nul
copy /y README.md "%OUT%\" >nul
copy /y README.zh-CN.md "%OUT%\" >nul

echo [PlayGo] 打包完成: dist-app\PlayGo （zip 后即可分发）
explorer dist-app
endlocal
