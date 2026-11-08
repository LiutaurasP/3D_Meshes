; Inno Setup script: installer for Windows that also registers .subdron project files.
; First run "python packaging\build.py" on Windows, then open this file in Inno Setup and press Compile.

#define AppName "Subdron Sonar Studio"
#define AppVersion "0.1.0"
#define AppExe "Subdron Sonar Studio.exe"

[Setup]
AppId={{6E0B7A52-3C1D-4F4B-9A57-2B8F0D5C1E21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Subdron
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=Subdron Sonar Studio Setup {#AppVersion}
SetupIconFile=icons\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
WizardStyle=modern

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Registry]
; Double clicking a .subdron file opens it in the app
Root: HKA; Subkey: "Software\Classes\.subdron"; ValueType: string; ValueData: "SubdronSonarStudio.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\SubdronSonarStudio.Project"; ValueType: string; ValueData: "{#AppName} Project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SubdronSonarStudio.Project\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SubdronSonarStudio.Project\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
