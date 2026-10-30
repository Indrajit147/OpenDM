@echo off
rem Register the OpenDM native messaging host for Chrome and Edge (current user, dev checkout).
rem Writes build\native-host\ and two HKCU registry keys. Undo with unregister_host_dev.cmd.
setlocal
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "NAME=io.github.indrajit147.opendm"
set "EXT_ID=pjkejmcidaikllfpgmfginpahcockofb"
set "OUT=%ROOT%\build\native-host"
set "PY=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Python venv not found: %PY%
  exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"

> "%OUT%\opendm-host.cmd" (
  echo @echo off
  echo "%PY%" -m opendm.host %%*
)

rem JSON needs the backslashes doubled.
set "HOST_PATH=%OUT%\opendm-host.cmd"
set "HOST_JSON=%HOST_PATH:\=\\%"
> "%OUT%\%NAME%.json" (
  echo {
  echo   "name": "%NAME%",
  echo   "description": "OpenDM download manager",
  echo   "path": "%HOST_JSON%",
  echo   "type": "stdio",
  echo   "allowed_origins": ["chrome-extension://%EXT_ID%/"]
  echo }
)

reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\%NAME%" /ve /t REG_SZ /d "%OUT%\%NAME%.json" /f >nul || exit /b 1
reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\%NAME%" /ve /t REG_SZ /d "%OUT%\%NAME%.json" /f >nul || exit /b 1
echo Registered %NAME% for Chrome and Edge:
echo   %OUT%\%NAME%.json
