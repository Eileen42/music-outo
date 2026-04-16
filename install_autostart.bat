@echo off
echo.
echo  ============================================
echo   자동 시작 등록/해제
echo  ============================================
echo.

set SHORTCUT_NAME=YPA-Backend.lnk
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set TARGET=%~dp0start_backend.vbs

if exist "%STARTUP_DIR%\%SHORTCUT_NAME%" (
    echo [!] 이미 등록되어 있습니다.
    echo     경로: %STARTUP_DIR%\%SHORTCUT_NAME%
    echo.
    set /p REMOVE="제거하시겠습니까? (y/n): "
    if /i "%REMOVE%"=="y" (
        del "%STARTUP_DIR%\%SHORTCUT_NAME%"
        echo [OK] 자동 시작이 해제되었습니다.
    )
) else (
    echo Windows 시작 시 백엔드 서버가 콘솔 창 없이 자동 실행됩니다.
    echo.
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%STARTUP_DIR%\%SHORTCUT_NAME%'); $sc.TargetPath = 'wscript.exe'; $sc.Arguments = '\"'+'%TARGET%'+'\"'; $sc.WorkingDirectory = '%~dp0'; $sc.WindowStyle = 7; $sc.Description = 'YouTube Playlist Automator Backend (silent)'; $sc.Save()"
    echo [OK] 자동 시작 등록 완료!
    echo     위치: %STARTUP_DIR%\%SHORTCUT_NAME%
    echo     실행: start_backend.vbs (콘솔 창 없음)
)

echo.
pause
