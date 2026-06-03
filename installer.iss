; Inno Setup installer for the two-part embeddable Windows build.
;
; Compiled by build_windows_installer.ps1 AFTER build_windows_embed.ps1 has
; produced dist\telegram-download-chat\ (runtime\ + app\ + launchers). It wraps
; that portable tree into a setup.exe with Start Menu / desktop shortcuts and an
; uninstaller.
;
; Per-user install (PrivilegesRequired=lowest, DefaultDirName under
; {localappdata}) is deliberate: the in-app self-update
; (telegram_download_chat.core.app_updater) swaps the app\ directory in place,
; which must work without elevation. Installing into Program Files would make
; that fail.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Telegram Download Chat"
#define MyAppPublisher "popstas"

[Setup]
; Keep this AppId stable across releases so upgrades replace in place.
AppId={{A1B2C3D4-E5F6-47A8-9B0C-1D2E3F405162}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Telegram Download Chat
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=telegram-download-chat-v{#MyAppVersion}-setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole portable tree (runtime\ + app\ + launchers).
Source: "dist\telegram-download-chat\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Icon for shortcuts and the uninstaller entry.
Source: "assets\icon.ico"; DestDir: "{app}"; DestName: "icon.ico"; Flags: ignoreversion

[Icons]
; Launch the GUI via pythonw.exe (no console). WorkingDir is the install ROOT,
; not app\, so app\ is never the process cwd (which would block the rename swap
; performed by the in-app updater).
Name: "{group}\{#MyAppName}"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m telegram_download_chat gui"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m telegram_download_chat gui"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\python\pythonw.exe"; Parameters: "-m telegram_download_chat gui"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
