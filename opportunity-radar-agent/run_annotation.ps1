$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
}
& $python -m streamlit run evaluation/annotation_app.py `
    --server.address 127.0.0.1 --server.port 8502 --server.headless true `
    --browser.gatherUsageStats false
