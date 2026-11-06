; NovaTTS 2.5.0c - Inno Setup installer
;
; Per-user install to %LOCALAPPDATA%\NovaTTS (same AppId as 2.5.0b, so it
; upgrades in place). The heavy AI-tools build (Vulkan SDK, whisper.cpp,
; qwentts.cpp, Qwen3-TTS models) runs once after install via
; Run-Install-AITools.cmd; the base payload stays small (~47 MB).
;
; Build:
;   & "C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\NovaTTS-2.5.0c.iss
; Output: dist-installer\NovaTTS-Setup-2.5.0c.exe

#define MyAppName "NovaTTS"
#define MyAppVersion "2.5.0d"
#define MyAppPublisher "NovaTTS"
#define MyAppURL "https://github.com/"
#define MyAppExeName "NovaTTS.exe"
#define MyPayloadDir "..\.build\2.5.0d\payload"

[Setup]
; Reuse the 2.5.0b AppId so this is an in-place upgrade.
AppId={{A7B3C1D2-E4F5-6789-ABCD-EF0123456789}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist-installer
OutputBaseFilename=NovaTTS-Setup-{#MyAppVersion}
SetupIconFile=novatts.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UsePreviousAppDir=yes
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no
CreateAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "aitools"; Description: "AI-tools downloaden en bouwen (Vulkan SDK, whisper.cpp, qwentts.cpp, Qwen3-TTS modellen; 30-60 min)"; GroupDescription: "AI-tools"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Clean payload assembled by the build step. No .venv, node_modules, build
; artefacts or machine-specific .env. Program files are replaced on upgrade.
Source: "{#MyPayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\*"

; Default data templates: install on a fresh install, but never clobber the
; user's speakers.json, emotion maps, game links or active game on upgrade.
Source: "{#MyPayloadDir}\data\*"; DestDir: "{app}\data"; Flags: onlyifdoesntexist recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\data\cache"
Name: "{app}\data\logs"
Name: "{app}\data\samples"; Flags: uninsneveruninstall
Name: "{app}\data\games"; Flags: uninsneveruninstall
Name: "{app}\data\voice_design"; Flags: uninsneveruninstall
Name: "{app}\logs"

[Icons]
Name: "{group}\NovaTTS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\installer\novatts.ico"
Name: "{group}\NovaTTS (console)"; Filename: "{app}\Start-NovaTTS.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\installer\novatts.ico"
Name: "{group}\AI-tools installeren / repareren"; Filename: "{app}\Run-Install-AITools.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\installer\novatts.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\NovaTTS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\installer\novatts.ico"

[Run]
; Always write/repair .env (BOM-free) before anything else, so the app has
; correct Qwen paths even if the user skips the AI-tools task.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Write-NovaTTSEnv.ps1"" -Root ""{app}"""; Flags: runhidden waituntilterminated

; Heavy autonomous setup: Vulkan SDK, whisper.cpp + qwentts.cpp (Vulkan),
; Qwen3-TTS GGUF models, then the corrected .env.
Filename: "{cmd}"; Parameters: "/c ""{app}\Run-Install-AITools.cmd"""; WorkingDir: "{app}"; Description: "AI-tools downloaden en bouwen (30-60 min)"; Flags: postinstall nowait; Tasks: aitools

Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data\cache"
Type: filesandordirs; Name: "{app}\data\logs"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\backend.log"
Type: files; Name: "{app}\gui.log"

[Code]
function InitializeUninstall(): Boolean;
var
  Answer: Integer;
begin
  Result := True;
  if not UninstallSilent then
  begin
    Answer := MsgBox(
      'Ook de AI-tools verwijderen?' + #13#10 + #13#10 +
      'Dat zijn de Vulkan-builds en Qwen3-TTS modellen (ca. 2,5 GB) in:' + #13#10 +
      ExpandConstant('{localappdata}\NovaTTS\AI-Tools') + #13#10 + #13#10 +
      'Kies Nee om ze te bewaren voor een herinstallatie.',
      mbConfirmation, MB_YESNO);
    if Answer = IDYES then
      DelTree(ExpandConstant('{localappdata}\NovaTTS\AI-Tools'), True, True, True);
  end;
end;

