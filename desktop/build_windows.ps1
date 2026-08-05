$ErrorActionPreference = "Stop"
$desktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $desktopRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found at $python"
}

$svg = Join-Path $desktopRoot "assets\oilmart.svg"
$ico = Join-Path $desktopRoot "assets\oilmart.ico"
& $python -c "from PyQt6.QtCore import QSize; from PyQt6.QtGui import QIcon; from PyQt6.QtWidgets import QApplication; import sys; a=QApplication([]); i=QIcon(sys.argv[1]); p=i.pixmap(QSize(256,256)); raise SystemExit(0 if p.save(sys.argv[2], 'ICO') else 1)" $svg $ico

& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $desktopRoot "dist") `
    --workpath (Join-Path $desktopRoot "build") `
    (Join-Path $desktopRoot "oilmart.spec")

$exe = Join-Path $desktopRoot "dist\OilMart POS.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build finished without producing $exe"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = Join-Path $desktop "OilMart POS.lnk"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $exe
$link.WorkingDirectory = Split-Path -Parent $exe
$link.IconLocation = "$exe,0"
$link.Description = "OilMart offline point of sale"
$link.Save()

Write-Host "Built: $exe"
Write-Host "Shortcut: $shortcut"
