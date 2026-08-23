; TellMeSensei per-user Windows installer.
; Build with scripts/build_installer.ps1 so paths and version come from the repo.

#define AppName "TellMeSensei"
#ifndef VersionLabel
  #define VersionLabel "0.5.0"
#endif
#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
#ifndef PortableDir
  #define PortableDir "..\..\dist\TellMeSensei"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\installer"
#endif

[Setup]
AppId={{D4B4E8C6-8B91-4C8B-9C20-2C3A0DA2A8B4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#VersionLabel}
DefaultDirName={localappdata}\Programs\TellMeSensei
DefaultGroupName=TellMeSensei
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=TellMeSensei-Setup-{#VersionLabel}
SetupIconFile=..\..\assets\tellme_sensei.ico
UninstallDisplayIcon={app}\TellMeSensei.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#PortableDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\TellMeSensei"; Filename: "{app}\TellMeSensei.exe"; IconFilename: "{app}\TellMeSensei.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\TellMeSensei"; Filename: "{app}\TellMeSensei.exe"; IconFilename: "{app}\TellMeSensei.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\TellMeSensei.exe"; Description: "Launch TellMeSensei"; Flags: nowait postinstall skipifsilent
