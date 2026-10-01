# B3 — armazenamento externo sem mover a referência B1

O launcher original verificava 4 GiB livres na partição do projeto e gravava nela
venv/modelo/evidências. A saída do usuário mostrou 924 MiB livres em `/`, mas
834 GiB disponíveis no volume ext4 montado em `/mnt/sherlock-ssd`. Nenhum venv ou
modelo B3 tinha sido instalado. O disco de destino aparece como XS1000 de 931,5 GiB;
o SanDisk de 120 GB listado é outro disco, não utilizado nesta mudança.

## Execução

Do repositório original, informar as três variáveis juntas:

```bash
TFT_BOARD3_STORAGE_ROOT="/mnt/sherlock-ssd/Agente-TFT/board3" \
TFT_BOARD3_STORAGE_MOUNT="/mnt/sherlock-ssd" \
TFT_BOARD3_STORAGE_UUID="<UUID confirmado pelo lsblk/findmnt>" \
bash scripts/probe_match001_board_detector.sh \
  "telemetry/data/match-001-board-b1.BlHCOHWx"
```

O UUID não é descoberto e aprovado automaticamente: precisa corresponder ao volume
escolhido. ROOT sem MOUNT/UUID é recusado; não existe fallback para a partição cheia.
Sem essas variáveis, o destino padrão `telemetry/data` continua disponível.

```text
<STORAGE_ROOT>/
  board3-runtime/venv/             ambiente isolado, criado no caminho definitivo
  board3-models/                   pesos e metadados verificados
  cache/                          pip, Hugging Face, Torch
  tmp/                            temporários de instalação/Python
  match-001-board-b3.XXXXXXXX/     nova evidência, storage.json, logs e run/
```

O código, JPEGs, executável B1 e relatórios históricos NÃO são movidos ou alterados.
Não se altera o preflight, detector, prompt, limiares, catálogo, OCR, GameState ou
bancos A14–A16. Nenhum dado anterior é apagado. Não se cria symlink na pasta do
projeto, não se transfere um venv instalado e não se executa Cargo neste comando.
O relatório comparativo continua sendo `run/comparison.txt`.

## Verificações

O helper usa `findmnt --mountpoint` com colunas explícitas para verificar montagem
real, UUID, escrita e ausência de `noexec`. Exige ext4/ext3/ext2/xfs/btrfs para o
ambiente Unix. Confere os destinos existentes para não seguir symlinks ou submontagens
para outra partição. Mede os 4 GiB no DESTINO, antes de criar ambiente/cache/logs.
Revalida a montagem antes de criar diretórios e após setup, antes da inferência.
O limite separado de 3 GiB de RAM disponível permanece. SSD não aumenta a RAM.

`TMPDIR/TMP/TEMP`, `PIP_CACHE_DIR`, `XDG_CACHE_HOME`, `HF_HOME` e caches Torch são
configurados no processo B3, sem editar o shell do usuário. Desativa bytecode dos
imports do projeto e configura o pip para não carregar arquivos de configuração
que redirecionem os destinos; versões/repositórios dos pacotes continuam iguais.
O usuário deve ter permissão de escrita na pasta dedicada. Não usar sudo para
executar o B3, nem alterar permissões recursivamente em todo o SSD.

Essas verificações são pré-condições, não proteção contra remoção física forçada
durante uma escrita. Manter o SSD conectado até `BOARD3_EXIT`. O comando não monta,
formata, redimensiona ou edita fstab. A partição do sistema continua quase cheia:
redirecionar o B3 evita os novos arquivos pesados nela, mas não libera o espaço já
ocupado e não impede gravações de outros programas.

## Testes

20 testes de contratos locais: montagem ausente, UUID errado, ro/noexec, filesystem,
submontagem, symlink, disco destino cheio, partição do projeto cheia com destino
livre, repetição sem apagar conteúdo, escaping de caminhos e resolução real de TMPDIR.
O workflow acrescenta uma imagem ext4 descartável no runner CI para verificar uma
montagem/UUID reais, venv, pip cache, temporários e interrupção após desmontagem.
Essa imagem existe somente no runner: não formata nenhum dispositivo do usuário.
O teste neural anterior com pesos reais e o CI geral permanecem obrigatórios.
A execução no SSD do usuário e o comparativo dos 40 JPEGs ainda dependem do Ubuntu.
