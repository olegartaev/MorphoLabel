#ifndef MyAppVersion
  #define MyAppVersion "0.5.0-beta.2-dev"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\..\dist\MorphoLabel"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\..\dist\installer"
#endif
[Setup]
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
Filename: "{app}\MorphoLabel.exe"; Description: "Start MorphoLabel"; Flags: nowait postinstall skipifsilent
