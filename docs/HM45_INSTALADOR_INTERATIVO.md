# Instalador guiado HM4.5

O arquivo entregue ao usuário será `AgenteTFT-HM45-Online-Setup.exe`, um
iniciador pequeno. Ele baixa `AgenteTFT-HM45-Setup.exe` de uma prévia de versão
no GitHub, verifica o SHA-256 fixado no iniciador e abre o assistente completo.
O pacote baixado contém aplicativo Windows e VM WSL 2; a configuração começa
na mesma sequência, sem comandos manuais para o usuário. Uma conexão com a
internet é necessária no início; após o download, a instalação completa não
depende da rede.

## O que o usuário verá

1. **Verificação automática:** mostra captura Rust, prévia 720p e VM WSL 2,
   além da privacidade do replay. Confere Windows x64, memória, espaço,
   virtualização, WSL 2 e SHA-256 do rootfs antes de qualquer mudança.
2. **Instalação:** habilita WSL 2 com uma janela UAC quando necessário,
   importa `AgenteTFT-Core-v2` na conta original do usuário e testa a VM; a versão anterior é preservada.
   Se houver reinicialização, registra uma retomada única em `HKCU\RunOnce`
   e oferece **Reiniciar agora**, após pedir que o usuário salve seu trabalho.
3. **Concluir:** o botão para abrir o Agente TFT só aparece depois que os
   testes internos e a conexão IP Windows–VM passam. Um erro mantém o diagnóstico visível e grava
   `%LOCALAPPDATA%\AgenteTFT-HM45\setup.log`.

O Inno Setup mostra uma única página explicativa antes da cópia e cria atalhos
no menu Iniciar e na área de trabalho. O assistente abre automaticamente,
verifica o PC e requer apenas o clique **Instalar VM** antes das etapas de
sistema. Ao voltar de um reinício, ele retoma sem repetir a introdução.

O instalador não reinicia o Windows automaticamente. A importação e a
verificação rodam no contexto do usuário; somente `wsl --install
--no-distribution` pede elevação. As demais distribuições WSL e `.wslconfig`
ficam intactas. Um WSL sem nenhuma distribuição é um estado válido: o instalador
importa a VM nesse caso, inclusive se `wsl --list --quiet` devolver um código
diferente de zero. Uma VM existente com o mesmo nome precisa passar no teste de
saúde; se falhar, ela é preservada para diagnóstico em vez de ser apagada.
O modo silencioso é recusado nesta fase, pois ele não conseguiria explicar a
permissão do Windows, o reinício e o resultado do teste de saúde.

## Contrato para empacotar

`scripts/build_hm45_installer_windows.py` recebe:

- `dist/AgenteTFT-HUD-HM4-Auto/AgenteTFT-HUD-HM4-Auto.exe`, já compilado com
  `hm45_setup` e `hm45_setup_core`;
- `build/hm45-core/AgenteTFT-Core-v2.tar`;
- `build/hm45-core/core-package.json` com `schema_version=1`,
  `distro_name=AgenteTFT-Core-v2`, `rootfs_file`, `sha256`, `version` e
  `analysis_health_contract=l3_ocr_b4_roi_v1`;
- `/opt/agente-tft/bin/health-check` no rootfs. O comando deve aceitar
  `--version <version>`, testar L3/OCR/B4 com quadros pela conexão local e
  imprimir `AGENTETFT_CORE_HEALTH_OK` somente após sucesso.

O build recusa o pacote se faltar qualquer um desses elementos ou se o hash
não bater. O rootfs real é produzido por `scripts/build_hm45_core.py`: Rust
Linux, Tesseract residente, L3 ONNX e catálogo B4 fixado. O build executa
L3/OCR/HP/B4 por TCP dentro do contêiner sem rede externa. O workflow
`.github/workflows/hm45-lab-package.yml` monta esse rootfs e empacota o
instalador Windows como **artefato de laboratório**. A compilação sintática
separada do Inno usa um rootfs fictício que é apagado e não é publicado.

O relatório do instalador mantém `release_ready=false` até um teste no Windows
com WSL 2 real, captura Rust e replay na tela. O pacote HM4 já publicado não
é substituído por este fluxo.

O iniciador online é gerado por `scripts/build_hm45_online_installer_windows.py`
a partir do instalador completo já verificado. O URL aponta para uma tag de
prévia de versão fixa, e o SHA-256 do pacote completo é incorporado ao
iniciador. O pacote completo e o iniciador precisam ser enviados para a mesma
prévia de versão no GitHub. Artefatos temporários de CI não servem como fonte
permanente: expiram e podem exigir autenticação. O instalador online mostra o
progresso e recusa abrir um download incompleto ou com hash diferente.

## Caminho dos quadros e limites de desempenho

```text
Monitor/janela → captura Rust 1080p/20 Hz → prévia Windows ≤720p
                       │
                       ├─ L3 320×192 / 8 Hz → WSL por TCP local
                       ├─ OCR RGB 1920×1080 / até 2 Hz → WSL por TCP local
                       ├─ HP RGB 1920×1080 / até 1 Hz → WSL por TCP local
                       └─ B4 RGB 1920×1080 / até 0,2 Hz → WSL por TCP local
```

O transporte de análise é RGB sem perdas e não rebaixa os pixels usados por
OCR e B4. A compressão zlib de dois quadros reais custou cerca de 135 ms por
quadro no host de desenvolvimento, então a sessão usa RGB bruto no loopback.
O envio só ocorre na frequência do respectivo leitor. A prévia não atravessa
a VM. A coleta PNG foi reduzida a 0,2 Hz no perfil VM e fica limitada a 90
amostras e 384 MiB; o treino neural continua offline, sem bloquear o replay.

Num quadro real HM4 de 1920×1080, com o núcleo limitado a 2 CPUs, foram
medidos aproximadamente 5 ms de ida e volta no L3 (320×192), 167 ms no OCR,
33 ms no HP e 77 ms no B4. O teste de saúde em 2 CPUs e limite de 768 MiB
atingiu pico de 194 MiB de memória do contêiner. Esses números são de Linux
com Docker em IP local; o atraso da captura WGC e do WSL no Windows deve ser
medido no PC de destino. A aba Performance mostra FPS efetivo da prévia,
tempo de renderização e p95 de cada etapa.

O B4 mantém arte oficial carregada uma vez por sessão. O teste de snapshot
confirma equivalência com o caminho anterior; uma medição parcial de B4 com
um quadro HM4 caiu de ~0,20 s para ~0,02 s depois do aquecimento. O HUB ainda
gera candidatos para células e itens, sem transformar candidatos em nomes de
campeões confirmados. O modo VM não emite dicas genéricas de economia ou de
item sem evidência confiável.

## Validações nesta etapa

`python -m unittest discover -s apps/hud_mapper/tests -p 'test_hm45_setup.py' -v`
verifica hash alterado, manifesto inválido, importação idempotente, preservação
de VM com falha e retomada após reinício. O workflow
`.github/workflows/hm45-installer.yml` executa esses contratos no Windows e
compila as páginas do Inno Setup com material de teste não publicável.
`apps/hud_mapper/tests/hm45_vm_e2e.py` exercita o cliente de IP contra o
núcleo real em Docker e valida a identidade dos quadros e a resposta dos
quatro componentes. O teste de campo deve registrar pelo menos cinco minutos
de replay na tela, FPS efetivo, p95 de OCR/B4, uso de RAM e erros de captura.
