@echo off
setlocal
cd /d "%~dp0"

if not exist "python\python.exe" (
  echo Portable Python was not found.
  echo Expected: %~dp0python\python.exe
  pause
  exit /b 1
)

if not exist "ffmpeg\ffmpeg.exe" (
  echo FFmpeg was not found.
  echo Expected: %~dp0ffmpeg\ffmpeg.exe
  pause
  exit /b 1
)

if not exist "output" mkdir "output"

echo Starting SRT Video Generator on your browser...
echo Starting local video server on http://127.0.0.1:8765
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /PID %%P /F >nul 2>&1
start "SRT Slideshow Server" /b cmd /c "python\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765 > server.log 2>&1"

set "READY="
for /l %%N in (1,1,20) do (
  if not defined READY (
    curl.exe --silent --fail http://127.0.0.1:8765/ >nul 2>&1
    if not errorlevel 1 set "READY=1"
    if not defined READY timeout /t 1 /nobreak >nul
  )
)

if not defined READY (
  echo The local server did not start. See server.log for details.
  type server.log
  pause
  exit /b 1
)

echo SRT Video Generator is ready. Opening your browser...
start "" "http://127.0.0.1:8765"
endlocal
