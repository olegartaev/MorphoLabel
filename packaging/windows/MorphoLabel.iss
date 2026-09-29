#ifndef MyAppVersion
  #define MyAppVersion "0.5.0-beta.9"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\..\dist\MorphoLabel"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\..\dist\installer"
#endif
[Setup]
SetupIconFile=..\..\build\brand\MorphoLabel.ico
UninstallDisplayIcon={app}\MorphoLabel.exe
AppId={{B1BB76C4-FF12-4FF4-8A27-0CB1BBA5513A}
AppName=MorphoLabel
AppVersion={#MyAppVersion}
AppPublisher=Oleg Artaev
AppPublisherURL=https://github.com/olegartaev/MorphoLabel
AppSupportURL=https://github.com/olegartaev/MorphoLabel/issues
DefaultDirName={localappdata}\Programs\MorphoLabel
DefaultGroupName=MorphoLabel
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyOutputDir}
OutputBaseFilename=MorphoLabel-{#MyAppVersion}-Setup-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=MorphoLabel
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\MorphoLabel"; Filename: "{app}\MorphoLabel.exe"
Name: "{autodesktop}\MorphoLabel"; Filename: "{app}\MorphoLabel.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\MorphoLabel.exe"; Description: "Start MorphoLabel (AI support is offered before any large download)"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; MorphoLabel-owned per-user state: managed AI runtime/model, setup state,
; hardware/UI settings, caches and diagnostics. Scientific projects are stored
; wherever the user created them and are never placed here automatically.
Type: filesandordirs; Name: "{localappdata}\MorphoLabel"
; Remove the exact legacy SIMM machine-tuning cache left by older builds.
; Do not remove the whole SIMM directory because it may contain unrelated legacy data.
Type: files; Name: "{localappdata}\SIMM\performance_engine_tuning.json"
Type: files; Name: "{localappdata}\SIMM\performance_engine_tuning.json.lock"
; Remove any app-owned leftovers not tracked by the installer manifest.
Type: filesandordirs; Name: "{app}"
