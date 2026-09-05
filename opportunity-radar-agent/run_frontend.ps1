$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $Python -m streamlit run frontend/streamlit_app.py
