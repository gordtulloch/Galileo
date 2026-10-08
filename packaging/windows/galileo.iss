; Inno Setup script: wraps dist\Galileo into one Galileo-Setup-<version>-win-x64.exe.
; Build (from the repo root):  iscc /DAppVersion=0.9.0 packaging\windows\galileo.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1F0E52-3C0A-4D6E-9A57-0A1B2C3D4E5F}
AppName=Galileo
AppVersion={#AppVersion}
AppPublisher=Gord Tulloch
DefaultDirName={autopf}\Galileo
DefaultGroupName=Galileo
UninstallDisplayIcon={app}\Galileo.exe
SetupIconFile=..\..\assets\images\galileo.ico
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=Galileo-Setup-{#AppVersion}-win-x64
Compression=lzma2/ultra
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\Galileo\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Galileo"; Filename: "{app}\Galileo.exe"
Name: "{autodesktop}\Galileo"; Filename: "{app}\Galileo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Galileo.exe"; Description: "Launch Galileo"; Flags: nowait postinstall skipifsilent
