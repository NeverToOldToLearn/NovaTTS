; NovaTTS — Inno Setup installer
; Bouwt een kleine installer (geen .venv/node_modules) die bij eerste run
; setup.ps1 draait om .venv + npm te installeren. Geschikt voor delen/zip.
;
; Bouwen:
;   .\installer\Build-Installer.ps1 [-WithVenv] [-InnoPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"]
; Vereisten: Inno Setup 6 (https://jrsoftware.org/isdl.php) — optioneel, zip werkt ook zonder.

#define MyAppName "NovaTTS"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "NovaTTS"
#define MyAppURL "https://github.com/"
#define MyAppExeName "start_all.cmd"

[Setup]
AppId={{8E2E5F1A-9A3C-4E7B-9F1A-2C3E4D5E6F70}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=..
OutputBaseFilename=NovaTTS-Setup-{#MyAppVersion}
WizardStyle=modern
SetupIconFile=novatts.ico
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousAppDir=yes
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no
; Voor portable herverhuizen: gebruiker mag overal installeren, geen registry
CreateAppDir=yes

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "runsetup"; Description: "Direct setup draaien (.venv + npm install)"; GroupDescription: "Setup"; Flags: checkedonce

[Files]
; Alles behalve gegenereerde/build artefacts — zie Build script voor exacte file list
; (ISCC kan ook met wildcards; Build-Installer.ps1 doet filtering)
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.venv\*,venv\*,node_modules\*,target\*,__pycache__\*,*.pyc,.mypy_cache\*,.ruff_cache\*,.pytest_cache\*,data\cache\*,installer\Output\*,*.log,backend.log,gui.log,backend\.env,NovaTTS-Portable-*.zip,NovaTTS-Setup-*.exe"
Source: "..\backend\.env.example"; DestDir: "{app}\backend"; DestName: ".env.example"; Flags: ignoreversion

[Icons]
Name: "{group}\NovaTTS Start"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--min"; WorkingDir: "{app}"; IconFilename: "{app}\installer\novatts.ico"; Flags: createonlyiffileexists
Name: "{group}\NovaTTS Visible"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--visible"; WorkingDir: "{app}"
Name: "{group}\NovaTTS Stop"; Filename: "{app}\stop_all.cmd"; WorkingDir: "{app}"
Name: "{group}\NovaTTS Setup (Repair)"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup.ps1"" -Force -Shortcuts"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\NovaTTS"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--min"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\installer\novatts.ico"; Flags: createonlyiffileexists

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup.ps1"" -Shortcuts"; Description: "Setup nu draaien (aanrader na installatie / na verhuizing)"; Flags: postinstall nowait skipifsilent; Tasks: runsetup
Filename: "{app}\{#MyAppExeName}"; Parameters: "--min"; Description: "NovaTTS starten"; Flags: postinstall nowait skipifsilent unchecked; Tasks: runsetup

[UninstallDelete]
Type: filesandordirs; Name: "{app}\backend\.venv"
Type: filesandordirs; Name: "{app}\gui\node_modules"
Type: filesandordirs; Name: "{app}\gui\dist"
Type: filesandordirs; Name: "{app}\data\cache"
Type: files; Name: "{app}\backend.log"
Type: files; Name: "{app}\gui.log"

[Code]
function InitializeUninstall(): Boolean;
var
  V: Integer;
begin
  if MsgBox('Ook de .venv, node_modules en cache verwijderen? Kies Nee om ze te behouden.', mbConfirmation, MB_YESNO) = IDYES then
  begin
    DelTree(ExpandConstant('{app}\backend\.venv'), True, True, True);
    DelTree(ExpandConstant('{app}\gui\node_modules'), True, True, True);
    DelTree(ExpandConstant('{app}\gui\dist'), True, True, True);
    DelTree(ExpandConstant('{app}\data\cache'), True, True, True);
  end;
  Result := True;
end;
