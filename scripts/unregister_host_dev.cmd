@echo off
rem Remove the dev registration made by register_host_dev.cmd.
setlocal
set "NAME=io.github.indrajit147.opendm"
reg delete "HKCU\Software\Google\Chrome\NativeMessagingHosts\%NAME%" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\%NAME%" /f >nul 2>&1
if exist "%~dp0..\build\native-host" rmdir /s /q "%~dp0..\build\native-host"
echo Unregistered %NAME%.
