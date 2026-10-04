[Setup]
AppName=Agente TFT · Laboratório HM4.5
AppVersion=0.6.1
DefaultDirName={localappdata}\AgenteTFT-HM45
DefaultGroupName=Agente TFT
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AgenteTFT-HM45-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\AgenteTFT-HUD-HM4-Auto.exe
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
WizardStyle=modern
WizardSizePercent=115
SetupLogging=yes

[Files]
Source: "..\dist\AgenteTFT-HUD-HM4-Auto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "hm45-core\core-package.json"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "hm45-core\AgenteTFT-Core-v2.tar"; DestDir: "{app}\core"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Agente TFT HM4.5"; Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"
Name: "{autodesktop}\Agente TFT HM4.5"; Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"
Name: "{autoprograms}\Configurar VM do Agente TFT"; Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"; Parameters: "--setup-assistant"

[Run]
Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"; Parameters: "--setup-assistant"; Description: "Configurar e testar a VM"; Flags: skipifsilent

[Code]
var
  OverviewPage: TWizardPage;

function InitializeSetup: Boolean;
begin
  Result := not WizardSilent;
  if not Result then
    MsgBox('Este pacote requer a instalação guiada para verificar o WSL 2 e a VM.', mbError, MB_OK);
end;

procedure AddParagraph(Page: TWizardPage; TopValue: Integer; TextValue: String);
var
  LabelControl: TNewStaticText;
begin
  LabelControl := TNewStaticText.Create(Page);
  LabelControl.Parent := Page.Surface;
  LabelControl.Left := ScaleX(8);
  LabelControl.Top := ScaleY(TopValue);
  LabelControl.Width := Page.SurfaceWidth - ScaleX(16);
  LabelControl.Height := ScaleY(78);
  LabelControl.AutoSize := False;
  LabelControl.WordWrap := True;
  LabelControl.Caption := TextValue;
end;

procedure InitializeWizard;
begin
  OverviewPage := CreateCustomPage(wpWelcome, 'O que será instalado',
    'O aplicativo Windows e a VM leve são configurados pelo assistente.');
  AddParagraph(OverviewPage, 18,
    'O Agente TFT usa captura Rust no Windows. A prévia fica no Windows em até 720p; os quadros para análise seguem por IP local à VM WSL 2. O arquivo do vídeo não é importado.');
  AddParagraph(OverviewPage, 102,
    'O assistente verifica o PC, instala a distribuição AgenteTFT-Core-v2 e testa a análise. A versão anterior e outras distribuições WSL são preservadas.');
  AddParagraph(OverviewPage, 200,
    'Se o Windows precisar habilitar o WSL 2, pedirá permissão de administrador. Caso exija reinício, o assistente mostrará o botão Reiniciar agora e continuará no próximo login.');
end;
