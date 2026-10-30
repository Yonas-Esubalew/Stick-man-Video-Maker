@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_VERSION=3.13.7"
set "PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"

if exist "python\python.exe" goto install_packages

if not exist "python" mkdir "python"
echo Downloading portable Python %PYTHON_VERSION%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ZIP%'"
if errorlevel 1 (
  echo Could not download portable Python.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath 'python' -Force"
del /q "%PYTHON_ZIP%"

for %%F in (python\*._pth) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$path='%%F'; $text=Get-Content -Raw $path; $text=$text -replace '#import site', 'import site'; if ($text -notmatch 'Lib\\site-packages') { $text += [Environment]::NewLine + 'Lib\\site-packages' }; Set-Content -NoNewline -Path $path -Value $text"
)

:install_packages
if not exist "python\get-pip.py" (
  echo Downloading pip bootstrap...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile 'python\get-pip.py'"
  if errorlevel 1 (
    echo Could not download get-pip.py.
    pause
    exit /b 1
  )
  "python\python.exe" "python\get-pip.py" --no-warn-script-location
  if errorlevel 1 exit /b 1
)

"python\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

echo.
echo Portable Python is ready. Run SRT_Video_Generator.bat to launch the app.
pause
