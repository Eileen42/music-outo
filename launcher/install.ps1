# ================================================================
# install.ps1
#   1) Create "Music Outo" shortcut on Desktop
#   2) Register in Windows Startup (auto-launch on boot)
#   Only touches HKCU / user folders - no admin rights needed.
#
#   Install:    powershell -ExecutionPolicy Bypass -File install.ps1
#   Uninstall:  powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#
# NOTE: This file is intentionally ASCII-only. PowerShell 5.1 reads
#       BOM-less files as system ANSI (cp949 on Korean Windows),
#       which corrupts non-ASCII characters and can cause parser errors.
# ================================================================

param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

# --- Paths --------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$LaunchVbs  = Join-Path $ScriptDir 'launch.vbs'
$IconPath   = Join-Path $ScriptDir 'icon.ico'   # optional

$DesktopDir = [Environment]::GetFolderPath('Desktop')
$StartupDir = [Environment]::GetFolderPath('Startup')

$ShortcutName    = 'Music Outo.lnk'
$DesktopShortcut = Join-Path $DesktopDir $ShortcutName
$StartupShortcut = Join-Path $StartupDir $ShortcutName

# --- Uninstall ----------------------------------------------------
if ($Uninstall) {
    foreach ($path in @($DesktopShortcut, $StartupShortcut)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
            Write-Host "[-] Removed: $path"
        }
    }
    Write-Host ""
    Write-Host "Uninstall complete."
    exit 0
}

# --- Install ------------------------------------------------------
if (-not (Test-Path -LiteralPath $LaunchVbs)) {
    Write-Error "launch.vbs not found at: $LaunchVbs"
    exit 1
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$WorkingDir,
        [string]$Icon
    )

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }

    $shell    = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)

    # Use wscript.exe as target so .vbs runs without any console window
    $shortcut.TargetPath       = "$env:WINDIR\System32\wscript.exe"
    $shortcut.Arguments        = "`"$Target`""
    $shortcut.WorkingDirectory = $WorkingDir
    $shortcut.Description      = 'Music Outo - YouTube Playlist Automator'

    if ($Icon -and (Test-Path -LiteralPath $Icon)) {
        $shortcut.IconLocation = "$Icon,0"
    }

    $shortcut.Save()

    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)    | Out-Null

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Failed to save shortcut: $Path"
    }
}

# 1) Desktop shortcut
New-Shortcut -Path $DesktopShortcut -Target $LaunchVbs -WorkingDir $ScriptDir -Icon $IconPath
Write-Host "[+] Desktop shortcut:  $DesktopShortcut"

# 2) Startup folder (auto-launch at boot so server is always ready)
New-Shortcut -Path $StartupShortcut -Target $LaunchVbs -WorkingDir $ScriptDir -Icon $IconPath
Write-Host "[+] Startup entry:     $StartupShortcut"

Write-Host ""
Write-Host "Install complete."
Write-Host "- Double-click the desktop icon to test now."
Write-Host "- From next boot onward, the server auto-starts in background."
