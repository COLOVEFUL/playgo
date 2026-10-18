@echo off
rem 默认发行版只收集CPU轻量包；GPU强网与Human SL由用户在应用内按需下载
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "backend\engines\bundled\eigen\katago.exe" (
  echo [PlayGo] 请先在应用内下载CPU轻量包，再打包。
  exit /b 1
)
if not exist "backend\engines\downloaded\lionffen_b6c64.txt.gz" (
  echo [PlayGo] 缺少CPU轻量模型，请先在应用内下载CPU轻量包。
  exit /b 1
)

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
mkdir "%OUT%\backend\engines\downloaded"
xcopy /e /i /q backend\engines\bundled\eigen "%OUT%\backend\engines\bundled\eigen" >nul
copy /y backend\engines\downloaded\lionffen_b6c64.txt.gz "%OUT%\backend\engines\downloaded\" >nul
rem 不收集choice.json、GPU包和Human SL大模型，避免打包机缓存增大发行包
xcopy /e /i /q frontend\dist "%OUT%\frontend\dist" >nul
xcopy /e /i /q docs "%OUT%\docs" >nul
copy /y start.bat "%OUT%\" >nul
copy /y LICENSE "%OUT%\" >nul
copy /y README.md "%OUT%\" >nul
copy /y README.zh-CN.md "%OUT%\" >nul

echo [PlayGo] 打包完成: dist-app\PlayGo （zip 后即可分发）
explorer dist-app
endlocal
