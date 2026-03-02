\
; Inno Setup script (template)
; Requires Inno Setup installed on the build machine.
; Build target: dist\BarcaCatalogSuite\

#define MyAppName "Barca Catalog Suite"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "BARCA"
#define MyAppExeName "BarcaCatalogSuite.exe"

[Setup]
AppId={{A2B7C0E6-7C7F-4B5B-9E0F-1D2B5E8E1234}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output_installer
OutputBaseFilename=BarcaCatalogSuite_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "..\dist\BarcaCatalogSuite\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
