@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo No encuentro venv\Scripts\python.exe.
    echo Crea el entorno virtual e instala requirements.txt antes de iniciar.
    pause
    exit /b 1
)

"venv\Scripts\python.exe" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
if errorlevel 1 pause
