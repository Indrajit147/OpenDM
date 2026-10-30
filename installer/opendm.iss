; OpenDM per-user installer (Inno Setup 6). No admin rights needed. Built by scripts\build.py:
;   ISCC /DAppVersion=0.8.0-rc.1 /DFileVersion=0.8.0.0 /DSourceDir=...\dist\OpenDM /DIconFile=...\build\opendm.ico opendm.iss
; Decision D12; see docs\DECISIONS.md (D60+) for the choices below.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z (scripts\build.py does this)
#endif
#ifndef FileVersion
  #error Pass /DFileVersion=x.y.z.0 (four numbers; scripts\build.py does this)
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<dist\OpenDM folder>
#endif

#define AppName "OpenDM"
#define HostName "io.github.indrajit147.opendm"
#define AppUserModelID "Indrajit147.OpenDM"
#define DataDir "{localappdata}\OpenDM"

[Setup]
; Never change AppId: upgrades and the uninstaller find the installation by it.
AppId={{862F85C1-3E08-4A1C-B8A0-F6BDA0393A80}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Indrajit Gupta
AppPublisherURL=https://github.com/Indrajit147/OpenDM
AppSupportURL=https://github.com/Indrajit147/OpenDM/issues
AppCopyright=Copyright (C) 2026 Indrajit Gupta
VersionInfoVersion={#FileVersion}
VersionInfoProductTextVersion={#AppVersion}
; Per user, no UAC prompt. {userpf} is %LOCALAPPDATA%\Programs; the folder page allows D:/E:.
PrivilegesRequired=lowest
DefaultDirName={userpf}\{#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
; The app holds this mutex while running (core/branding.py APP_MUTEX).
AppMutex={#AppName}-AppRunning
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#IconFile}
; Shown before the folder page: what OpenDM sends where (docs\PRIVACY.md, CODE_SIGNING.md).
InfoBeforeFile=privacy-note.txt
UninstallDisplayIcon={app}\OpenDM.exe
UninstallDisplayName={#AppName}
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2/ultra64
SolidCompression=yes
; Logs go next to the setup's temp files only when /LOG is passed (used by the install test).
SetupLogging=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
FinishedLabel=Setup has installed [name] on your computer.%n%nTo use it with Chrome or Edge, open OpenDM and go to Settings > Browser.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the runtime folder completely, so no stale library is left behind.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\extension"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\OpenDM.exe"; AppUserModelID: "{#AppUserModelID}"; Comment: "Free, open-source download manager"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\OpenDM.exe"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; Native Messaging for Chrome and Edge (spec 6.6). opendm-host.exe --register below writes the
; manifest these keys point to; the keys are listed here so the uninstaller always removes them.
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\{#HostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#HostName}.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\{#HostName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#HostName}.json"; Flags: uninsdeletekey

[Run]
Filename: "{app}\opendm-host.exe"; Parameters: "--register"; Flags: runhidden waituntilterminated
Filename: "{app}\OpenDM.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\{#HostName}.json"
; yt-dlp and FFmpeg, which the app downloads into its own folder (D66); upgrades keep them.
Type: filesandordirs; Name: "{app}\tools"
; Installers left by the in-app updater (D65).
Type: filesandordirs; Name: "{app}\updates"

[Code]
// Downloaded files are never touched. Settings and history in the data folder (and helper
// tools that 0.7 kept there) are deleted only if the user says so (default: keep; a silent uninstall keeps them unless
// /DELETEDATA=1 is passed).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
  Answer: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  Data := ExpandConstant('{#DataDir}');
  if not DirExists(Data) then
    Exit;
  if ExpandConstant('{param:DELETEDATA|0}') = '1' then
    Answer := IDYES
  else
    Answer := SuppressibleMsgBox(
      'Also delete your OpenDM settings and download history?' + #13#10 + #13#10 +
      Data + #13#10 + #13#10 +
      'Files you downloaded are not affected.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO);
  if Answer = IDYES then
    DelTree(Data, True, True, True);
end;
