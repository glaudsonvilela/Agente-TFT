[Setup]
AppName=Agente TFT · Laboratório HM4.5
AppVersion=0.6
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
WizardStyle=modern
WizardSizePercent=115
SetupLogging=yes

[Files]
Source: "..\dist\AgenteTFT-HUD-HM4-Auto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "hm45-core\core-package.json"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "hm45-core\AgenteTFT-Core-v1.tar"; DestDir: "{app}\core"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Agente TFT HM4.5"; Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"
Name: "{autoprograms}\Configurar VM do Agente TFT"; Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"; Parameters: "--setup-assistant"

[Run]
Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"; Parameters: "--setup-assistant"; Description: "Configurar e testar a VM"; Flags: skipifsilent

[Code]
var
  OverviewPage: TWizardPage;
  PrivacyPage: TWizardPage;

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
    'O aplicativo Windows e uma VM leve são configurados no mesmo processo.');
  AddParagraph(OverviewPage, 18,
    '1. O aplicativo Windows captura a janela ou o monitor pelo módulo Rust. A prévia fica no Windows em até 720p.');
  AddParagraph(OverviewPage, 102,
    '2. O assistente verifica o PC e instala uma distribuição WSL 2 própria do Agente TFT. Ela executa a análise dos quadros de imagem.');
  AddParagraph(OverviewPage, 200,
    '3. Ao final, o assistente testa a VM. Se o Windows precisar habilitar o WSL 2, mostrará a solicitação de administrador e poderá exigir um reinício.');

  PrivacyPage := CreateCustomPage(OverviewPage.ID, 'Conexão local e seus dados',
    'Entenda como o vídeo é usado antes de prosseguir.');
  AddParagraph(PrivacyPage, 18,
    'O vídeo continua aberto no seu player. O Agente TFT lê a tela escolhida; não é necessário enviar o arquivo da partida.');
  AddParagraph(PrivacyPage, 102,
    'A análise envia quadros RGB da tela escolhida pela conexão IP local entre o Windows e a VM, sem perda de resolução. A prévia de até 720p permanece no Windows e não passa pela VM.');
  AddParagraph(PrivacyPage, 200,
    'O instalador não altera outras distribuições WSL nem o arquivo global .wslconfig. O assistente explica cada etapa e só anuncia conclusão após o teste de saúde.');
end;
