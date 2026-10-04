[Setup]
AppId=AgenteTFT-HM45-Online
AppName=Agente TFT · Instalador online HM4.5
AppVersion=0.6.1
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AgenteTFT-HM45-Online-Setup
Compression=lzma2
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableReadyPage=yes
WizardStyle=modern
WizardSizePercent=115
SetupLogging=yes

[Code]
var
  DownloadPage: TDownloadWizardPage;
  OverviewPage: TWizardPage;
  Explanation: TNewStaticText;

procedure InitializeWizard;
begin
  OverviewPage := CreateCustomPage(wpWelcome, 'Instalação em duas etapas',
    'O Agente TFT baixará e verificará o pacote completo no Windows.');
  Explanation := TNewStaticText.Create(OverviewPage);
  Explanation.Parent := OverviewPage.Surface;
  Explanation.Left := ScaleX(12);
  Explanation.Top := ScaleY(20);
  Explanation.Width := OverviewPage.SurfaceWidth - ScaleX(24);
  Explanation.Height := ScaleY(160);
  Explanation.AutoSize := False;
  Explanation.WordWrap := True;
  Explanation.Caption :=
    '1. O pacote completo vem da prévia de versão do Agente TFT no GitHub. ' +
    'O download exige internet e ocupa temporariamente cerca de 600 MB no disco.' + #13#10#13#10 +
    '2. Antes de abrir qualquer programa baixado, este iniciador confere o SHA-256 ' +
    'da versão escolhida.' + #13#10#13#10 +
    '3. O assistente completo instala o aplicativo, a voz local e a VM WSL 2 ' +
    'e explica o reinício, caso o Windows precise dele.';
  DownloadPage := CreateDownloadPage(
    'Baixando o Agente TFT',
    'O pacote completo será verificado antes de abrir a instalação guiada.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  InstallerPath: String;
  ResultCode: Integer;
begin
  Result := '';
  DownloadPage.Clear;
  DownloadPage.Add('@@OFFLINE_URL@@', 'AgenteTFT-HM45-Setup.exe',
    '@@OFFLINE_SHA256@@');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      Result := 'O download ou a verificação SHA-256 falhou: ' + GetExceptionMessage;
    end;
  finally
    DownloadPage.Hide;
  end;
  if Result <> '' then
    Exit;
  InstallerPath := ExpandConstant('{tmp}\AgenteTFT-HM45-Setup.exe');
  if not Exec(InstallerPath, '', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
    Result := 'O Windows não conseguiu abrir o instalador completo.'
  else if ResultCode <> 0 then
    Result := 'A instalação completa terminou com erro. Código: ' + IntToStr(ResultCode);
end;
