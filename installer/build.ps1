# Builds the Windows desktop app and its installer.
#   GitHub Actions runs this for every version tag. To build by hand on Windows (Python 3.12 and Inno Setup 6 installed):
#   pip install -r requirements.txt -r requirements-desktop.txt
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Version 1.0.0 -Repo owner/repo
param([string]$Version = "1.0.0", [string]$Repo = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# The version and the update source are written into the app so it knows what it is and where to look for updates.
@"
"""The app version. The release build replaces it with the version from the git tag (for example v1.2.0 -> 1.2.0)."""
__version__ = "$Version"
UPDATE_REPO = "$Repo"          # owner/repo on GitHub that publishes releases; the release build fills this in
"@ | Set-Content backend\version.py -Encoding utf8

python -m PyInstaller --noconfirm --clean --windowed --name "NQ-ES Options" --icon assets\icon.ico `
  --add-data "frontend;frontend" --add-data "tradingview;tradingview" --add-data "assets;assets" --add-data ".env.example;." `
  --collect-submodules uvicorn --collect-data tzdata `
  --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms --hidden-import pystray._win32 `
  NQES.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "${env:ProgramFiles}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) was not found" }
& $iscc "/DMyVersion=$Version" installer\setup.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem dist\installer
