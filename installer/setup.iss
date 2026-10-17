; Installer for the NQ-ES Options desktop app (Inno Setup 6). Built by installer\build.ps1.
; Installs for the current user only (no admin rights), so the app can update itself silently.
#ifndef MyVersion
  #define MyVersion "1.0.0"
#endif
#define MyAppName "NQ-ES Options"
#define MyExe "NQ-ES Options.exe"

[Setup]
AppId={{8C3E6F2A-5B1D-4E7A-9F0C-2D4B6A8E1F37}
AppName={#MyAppName}
AppVersion={#MyVersion}
AppVerName={#MyAppName} {#MyVersion}
AppPublisher=Henry
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=NQ-ES-Options-{#MyVersion}-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "autostart"; Description: "Start with Windows (keeps collecting data in the background)"

[InstallDelete]
; old program libraries are removed first so nothing stale is left behind. Your settings and data are in a different folder.
Type: filesandordirs; Name: "{app}\_internal"
; shortcuts from 1.0.0 had the old name
Type: files; Name: "{autoprograms}\NQ-ES Options.lnk"
Type: files; Name: "{autodesktop}\NQ-ES Options.lnk"

[Files]
Source: "..\dist\NQ-ES Options\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; the shortcuts carry the Q DATA name and icon; the desktop one is made on every install and update
Name: "{autoprograms}\Q DATA"; Filename: "{app}\{#MyExe}"; IconFilename: "{app}\{#MyExe}"
Name: "{autodesktop}\Q DATA"; Filename: "{app}\{#MyExe}"; IconFilename: "{app}\{#MyExe}"

[Registry]
; Only on a normal (not silent) install: a silent self-update must not turn autostart back on if you switched it off in the tray.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyExe}"" --background"; Tasks: autostart; Check: not WizardSilent

[Run]
; After an install or a silent self-update the app starts again (the updater passes /relaunch=--background when it was in the tray).
; refresh Windows' icon cache so the desktop and taskbar show the current Q DATA icon straight away
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden waituntilterminated skipifdoesntexist
Filename: "{app}\{#MyExe}"; Parameters: "{param:relaunch|}"; Description: "Open Q DATA"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""{#MyExe}"""; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sys}\reg.exe"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""{#MyAppName}"" /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"

[UninstallDelete]
Type: files; Name: "{autodesktop}\Q DATA.lnk"
