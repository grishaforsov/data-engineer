@echo off
setlocal enabledelayedexpansion

REM 1) Go to this folder
cd /d "%~dp0"

REM 2) Ensure venv
if not exist ".venv" (
  py -3.11 -m venv .venv
)

REM 3) Activate venv
call ".venv\Scripts\activate.bat"

REM 4) Upgrade pip
python -m pip install --upgrade pip

REM 5) Install requirements (exact versions)
pip install -r requirements.txt

REM 6) Streamlit: disable usage stats prompt (no email request)
if not exist ".streamlit" (
  mkdir ".streamlit" >nul 2>&1
)
> ".streamlit\config.toml" (
  echo [browser]
  echo gatherUsageStats = false
)

REM 7) Run app
streamlit run app.py

pause
