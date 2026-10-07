[Setup]
AppName=Agente TFT · Laboratório HM4.5
AppVersion=0.7.0
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
SetupIconFile=hm45-design-icon.ico
SetupLogging=yes

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal\voices"
Type: filesandordirs; Name: "{app}\_internal\sherpa_onnx"
Type: filesandordirs; Name: "{app}\_internal\sherpa_onnx_core"
Type: filesandordirs; Name: "{app}\_internal\supertonic"

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
    'O Agente TFT usa captura Rust no Windows. Em partida ao vivo, amostras visuais de aprendizado são salvas localmente em baixa frequência; os pesos ficam congelados durante a partida e o treino só pode começar depois que a sessão é encerrada e selada.');
  AddParagraph(OverviewPage, 102,
    'O assistente verifica o PC e instala o núcleo WSL 2. O BigBANANA treina após a partida e distribui versões aprovadas entre partidas; a análise local permanece ativa mesmo sem conexão.');
  AddParagraph(OverviewPage, 200,
    'Se o Windows precisar habilitar o WSL 2, pedirá permissão de administrador. Caso exija reinício, o assistente mostrará o botão Reiniciar agora e continuará no próximo login.');
end;
