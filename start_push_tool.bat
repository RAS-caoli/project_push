@echo off
setlocal
powershell -NoLogo -ExecutionPolicy Bypass -File "%~dp0start_push_tool.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo The GitHub push tool failed to start. See the error message above.
  pause
)
exit /b %EXIT_CODE%
