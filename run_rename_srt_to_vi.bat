@echo off
setlocal

set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=."

python rename_srt_to_vi.py "%ROOT%"

echo.
pause
