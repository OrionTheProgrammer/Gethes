#define MyAppName "Gethes"
#ifndef MyAppVersion
  #define MyAppVersion "0.02"
#endif
#define MyAppPublisher "Gethes Project"

[Setup]
AppId={{9DBBF68B-1A65-4A63-AB4F-74A177CD5E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=
OutputDir=..\release
OutputBaseFilename=Gethes-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
SetupLogging=yes
UninstallDisplayIcon={app}\Gethes.exe

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Gethes\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Gethes"; Filename: "{app}\Gethes.exe"
Name: "{group}\{cm:UninstallProgram,Gethes}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Gethes"; Filename: "{app}\Gethes.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Gethes.exe"; Description: "{cm:LaunchProgram,Gethes}"; Flags: nowait postinstall skipifsilent
