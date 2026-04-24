@echo off
REM start_server.bat - launches uvicorn backend. Called hidden by launch.vbs.
REM Arg 1: port number (default 8000)
setlocal

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

pushd "%~dp0\..\backend"
python -m uvicorn main:app --host 127.0.0.1 --port %PORT%
popd

endlocal
