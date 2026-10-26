; Instalador convencional de Windows para el bundle creado por PyInstaller.
; La versión se recibe desde build_windows.py con /DMyAppVersion=x.y.z.

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "Laboratorio FIR de punto fijo"
#define MyAppPublisher "FIR Fixed Lab"
#define MyAppExeName "FIR Fixed Lab.exe"

[Setup]
AppId={{A5B91B29-6B20-46E6-9F1A-38B650DF1E69}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Laboratorio FIR de punto fijo
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\release
OutputBaseFilename=FIR-Fixed-Lab-Setup-{#MyAppVersion}-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\..\dist\FIR Fixed Lab\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos adicionales:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir el Laboratorio FIR de punto fijo"; Flags: nowait postinstall skipifsilent
