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
DisableWelcomePage=yes
DisableFinishedPage=yes
WizardStyle=modern
WizardSizePercent=115
SetupIconFile=hm45-design-icon.ico
SetupLogging=yes

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal\voices"
Type: filesandordirs; Name: "{app}\_internal\sherpa_onnx"
Type: filesandordirs; Name: "{app}\_internal\sherpa_onnx_core"
Type: filesandordirs; Name: "{app}\_internal\supertonic"
Type: filesandordirs; Name: "{app}\_internal\webview"
Type: filesandordirs; Name: "{app}\_internal\pythonnet"
Type: filesandordirs; Name: "{app}\_internal\clr_loader"

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
function InitializeSetup: Boolean;
begin
  Result := not WizardSilent;
  if not Result then
    MsgBox('Este pacote requer a instalação guiada para verificar o WSL 2 e a VM.', mbError, MB_OK);
end;
