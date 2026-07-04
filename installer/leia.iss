; Inno Setup script para o LeIA — Leitor Inteligente com IA
; Empacota Python embeddable + código + first_run.py.
; Use o Inno Setup 6.x: iscc.exe installer\leia.iss

#define MyAppName "LeIA"
#define MyAppVersion "1.5.1"
#define MyAppPublisher "LeIA Project"
#define MyAppURL "https://github.com/"
#define MyAppExeName "leia.vbs"

[Setup]
AppId={{B7A6F4C0-3D9E-4C7A-9D6B-A1F0B1B2B3C4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=LeIA_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
LicenseFile=EULA.txt

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "_build\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "_build\backend\*"; DestDir: "{app}\backend"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "_build\frontend\*"; DestDir: "{app}\frontend"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "_build\voices\*"; DestDir: "{app}\voices"; Flags: recursesubdirs createallsubdirs ignoreversion skipifsourcedoesntexist
Source: "leia.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "first_run.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "EULA.txt"; DestDir: "{app}"; Flags: ignoreversion

; .vbs precisa ser executado via wscript.exe — CreateProcess direto no .vbs
; falha com "código 193 / não é um aplicativo Win32 válido".
[Icons]
Name: "{group}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\leia.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\leia.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "wscript.exe"; Parameters: """{app}\leia.vbs"""; WorkingDir: "{app}"; Description: "Executar {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  RemoveData: Integer;
  AppDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataDir := ExpandConstant('{userappdata}\LeIA');
    if DirExists(AppDataDir) then
    begin
      RemoveData := MsgBox(
        'Deseja remover também os modelos e cache em ' + AppDataDir + '? (pode ocupar mais de 2 GB)',
        mbConfirmation, MB_YESNO);
      if RemoveData = IDYES then
        DelTree(AppDataDir, True, True, True);
    end;
  end;
end;
