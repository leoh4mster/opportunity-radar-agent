$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $Python -m streamlit run frontend/streamlit_app.py `
  --server.headless true `
  --server.address 127.0.0.1 `
  --server.port 8501 `
  --browser.gatherUsageStats false
