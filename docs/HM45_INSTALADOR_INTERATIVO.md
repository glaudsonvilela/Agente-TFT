# Instalador guiado HM4.5

O HM4.5 terá um único `AgenteTFT-HM45-Setup.exe`. O Inno Setup copia o
aplicativo Windows e o pacote da VM; em seguida abre o assistente em português
dentro do executável do Agente TFT. A configuração da VM começa nessa mesma
instalação, sem comandos manuais para o usuário.

## O que o usuário verá

1. **O que será instalado:** captura Rust no Windows, prévia 720p e VM WSL 2
   leve para análise. O assistente avisa sobre a permissão do Windows e a
   possível reinicialização.
2. **Seu computador:** versão Windows x64, memória, espaço, virtualização,
   disponibilidade do WSL 2 e hash SHA-256 do rootfs. O resultado aparece
   antes de qualquer mudança no sistema.
3. **Privacidade:** explica que o player continua no Windows e que apenas
   recortes necessários cruzam a conexão IP local. O arquivo do vídeo não é
   importado pelo Agente TFT.
4. **Instalação:** habilita WSL 2 com uma janela UAC quando necessário,
   importa `AgenteTFT-Core-v1` na conta original do usuário e testa a VM.
   Se houver reinicialização, registra uma retomada única em `HKCU\RunOnce`
   e orienta o usuário a salvar o trabalho antes de reiniciar.
5. **Concluir:** o botão para abrir o Agente TFT só aparece depois que o
   teste de saúde da VM passa. Um erro mantém o diagnóstico visível e grava
   `%LOCALAPPDATA%\AgenteTFT-HM45\setup.log`.

O instalador não reinicia o Windows automaticamente. A importação e a
verificação rodam no contexto do usuário; somente `wsl --install
--no-distribution` pede elevação. As demais distribuições WSL e `.wslconfig`
ficam intactas. Uma VM existente com o mesmo nome precisa passar no teste de
saúde; se falhar, ela é preservada para diagnóstico em vez de ser apagada.

## Contrato para empacotar

`scripts/build_hm45_installer_windows.py` recebe:

- `dist/AgenteTFT-HUD-HM4-Auto/AgenteTFT-HUD-HM4-Auto.exe`, já compilado com
  `hm45_setup` e `hm45_setup_core`;
- `build/hm45-core/AgenteTFT-Core-v1.tar`;
- `build/hm45-core/core-package.json` com `schema_version=1`,
  `distro_name=AgenteTFT-Core-v1`, `rootfs_file`, `sha256`, `version` e
  `analysis_health_contract=l3_ocr_b4_roi_v1`;
- `/opt/agente-tft/bin/health-check` no rootfs. O comando deve aceitar
  `--version <version>`, testar L3/OCR/B4 com recortes pela conexão local e
  imprimir `AGENTETFT_CORE_HEALTH_OK` somente após sucesso.

O build recusa o pacote se faltar qualquer um desses elementos ou se o hash
não bater. A compilação sintática do Inno no CI usa um rootfs fictício que é
apagado e **não é publicado**. O pacote final continua bloqueado até o worker
Linux e o teste de ponta a ponta num Windows com WSL 2 real estarem prontos.
O relatório de build marca `release_ready=false` por esse motivo. O HM4 já
publicado não foi substituído por este fluxo.

## Validações nesta etapa

`python -m unittest discover -s apps/hud_mapper/tests -p 'test_hm45_setup.py' -v`
verifica hash alterado, manifesto inválido, importação idempotente, preservação
de VM com falha e retomada após reinício. O workflow
`.github/workflows/hm45-installer.yml` executa esses contratos no Windows e
compila as páginas do Inno Setup com material de teste não publicável.
