# Percepção, atributos e vídeos autorizados

## Entrega de 4 de outubro de 2026

- 219 imagens únicas dos cinco testes receberam revisão visual de cena pelo
  assistente: 133 tabuleiros, 37 lobbies, 30 carregamentos, 10 seleções
  compartilhadas, 5 desktops, 3 aprimoramentos e 1 outra tela.
- Três imagens têm rótulos parciais adicionais de HUD/unidades; duas também têm
  loja e itens. Há 15 caixas de unidades, uma leitura de duas estrelas e cinco
  identificações de itens (quatro no inventário, uma equipada). Identidades de
  campeões no tabuleiro e hexágonos permanecem desconhecidos.
- Um exemplo confirma que a loja contém **Polimorfia Menor**, um consumível,
  além de campeões e espaços vazios. Um outro contém uma bigorna no banco,
  excluída das caixas de campeões. O Pequeno Lendário também foi excluído.
- A revisão é do assistente, **sem validação humana independente**. Previsões
  anteriores não foram usadas como rótulos.

O pacote privado está em `datasets/review-20261004` no SSD. As imagens e nomes
dos jogadores não são publicados no Git. O formato novo é independente do
anotador legado `replay_labeler`, que continua aceitando o schema 1.

## Formato de revisão estruturada

`training.board_review` valida documentos `schema_version=2`, `kind=board_review`:

- `layout`: caixas, proprietário, zona, posição no banco e hexágono opcional;
  coordenadas de imagem não carregam IDs de patch.
- `hud`: HP, ouro, nível, XP atual/necessário e estágio.
- `entities`: identidade, estrelas e itens ligados a uma caixa pela chave `key`.
- `inventory` e `shop`: slots explícitos, distinguindo desconhecido, vazio,
  oclusão e identidade conhecida. Loja distingue campeão e consumível.
- `patch_binding`: nulo enquanto a versão não estiver comprovada; nomes visíveis
  podem ser anotados sem inventar um vínculo com IDs sazonais.
- `review`: procedência da revisão. Ausência de campo nunca significa negativo.

SHA do arquivo, SHA dos pixels e dimensões são verificados antes de treinar.
Hexágonos só são aceitos para unidades próprias durante planejamento; não se
rotula como posição estratégica o deslocamento durante combate.

```bash
.venv/bin/python -m training.board_review datasets/review-20261004/annotations.json
```

## Primeiro treino de presença do tabuleiro

Foram usados 166 frames de quatro partidas para treino e 53 de uma quinta para
avaliação. As partidas foram separadas por inspeção dos adversários visíveis,
mantendo cada captura inteira no mesmo grupo. Não há vínculo com IDs Riot.
Este alvo visual independe do patch; identidades sazonais continuam sem vínculo.

```bash
.venv/bin/python -m training.train_scene_gate \
  --annotations datasets/review-20261004/annotations.json \
  --output trainer/data/vision-runs/scene-gate-novo \
  --holdout-match match-9acfd9af --steps 400
```

Resultado: 5.978 parâmetros, 400 atualizações, oito tensores alterados e ONNX
de 25.143 bytes. A inferência CPU isolada teve p95 de 0,618 ms nesta máquina;
não inclui captura, redimensionamento, túnel ou UI e não mede o FPS do HUD.

**Avaliação: 40/53 (75,5%), com 13 falsos positivos.** Detectou os 21 tabuleiros,
mas confundiu lobbies/desktops com tabuleiro. O candidato não foi promovido.
O conjunto reservado não foi usado para escolher época ou limiar. Uma próxima
versão que use esses erros para ajuste precisará de outra avaliação independente.
Relatório: `docs/evidence/perception-catalog-20261004/scene-training.json`.

O painel e `tft painel` apresentam esse experimento separadamente do treino
de política. A consulta verifica o hash do ONNX e não executa seus tensores.

## Atributos por patch

`training.simulator_lab.attribute_worklist` verifica o release imutável e
enumera atributos, arrays numéricos e dependências por campeão. Recusa valores
não finitos e evita considerar apenas a presença de um objeto como cobertura.

Estado: 73/74 campeões têm os dez atributos básicos. Falta `damage` da Kayle.
Há 351 referências a variáveis/fórmulas nas descrições; 350 não correspondem
diretamente a um array numérico disponível. Mesmo uma correspondência não prova
a fórmula ou a semântica dos índices de estrelas.

As [notas oficiais da Riot](https://teamfighttactics.leagueoflegends.com/pt-br/news/game-updates/teamfight-tactics-patch-18-3/)
forneceram 23 observações numéricas adicionais para 17 campeões. O arquivo
`configs/simulation/official-patch-observations-18.3.json` mantém patch,
data, cobertura de estrelas e escala publicada. Uma lista com duas estrelas
não ganha um valor inventado para a terceira. Os hotfixes 18.3B não substituem
silenciosamente uma gravação vinculada a 18.3. Observações não sobrescrevem o
release nem viram habilidades executáveis sem definir alvos, tempo e efeitos.

```bash
.venv/bin/python -m training.simulator_lab.attribute_worklist \
  --release knowledge/releases/TFTSet18/18.3/0674657d3f7c165d37045fbd45d8f7c56b20aef064660e6906c3985f0c8a0299 \
  --official-observations configs/simulation/official-patch-observations-18.3.json \
  --output trainer/data/catalog-audit/attributes.json
```

O fornecedor CommunityDragon recusou o acesso ao snapshot e a referência
alternativa LoLChess consultada retornou 404. O snapshot PBE encontrado em outra
fonte foi excluído como substituto dos valores atuais. Continuam faltando
handlers e validação de habilidades, itens, características e mecânica sazonal.

## YouTube, Bilibili e Twitch

O usuário informou autorização dos criadores para treinamento, incluindo VODs
completos, e pediu seleção autônoma dos criadores relevantes. O registro
`configs/training/video-sources-20261004.json` guarda procedência, disponibilidade
e escopo. Links descobertos não contam como vídeos assistidos ou exemplos de treino.

Os cinco vídeos locais somam 7,01 horas. O VOD de Wasianiverson tem 4h49min50s;
foram revisados 57 frames a intervalos de cinco minutos e salvos possíveis
intervalos de mudança de partida. Isso **não estabelece fronteiras exatas,
resultados ou pares estado/ação**. Guias editados não são episódios completos.

As primeiras referências online incluem BunnyMuffins, Frodan, guias chineses
do Set 18 e uma fila de VODs da Twitch. O Bilibili retornou HTTP 412 na página
e no endpoint público de metadados consultados. Nenhum novo vídeo online foi
usado para atualizar pesos nesta entrega.

Para transformar VOD em supervisão de decisões:

1. Confirmar intervalos completos, modo de jogo, patch/hotfix e resultado.
2. Anotar o estado **anterior** à ação: unidades, estrelas, posições, economia,
   banco, loja, itens equipados/inventário e recursos sazonais.
3. Separar ação observada, explicação falada e efeito posterior; fala não prova
   que a ação ocorreu nem que foi ótima.
4. Agrupar a mesma partida publicada em plataformas distintas antes do split.
5. Medir precisão da percepção e fidelidade do combate antes de usar trajetórias
   simuladas para orientar o HUD.

O simulador completo e as dicas neurais do patch **continuam pendentes**. Estes
artefatos implementam a base auditável de rótulos e atributos; o laboratório
sintético não foi convertido em um simulador fiel apenas trocando seu catálogo.

### Ampliação do corpus e processamento incremental

`training.source_corpus` reuniu as transcrições dos cinco arquivos autorizados
com legendas públicas de três guias adicionais: Frodan/TFT, BunnyMuffins
fundamentos e `Must Know TFT Fundamentals`. O SQLite privado permite busca por
texto com URL, tempo, hash e declaração de patch. A cópia publicada no servidor
contém 4.155 trechos de oito fontes; seu relatório está em
`docs/evidence/hex-simulator-20261004/source-corpus.json`.

`training.transcribe_sources` completa o áudio por blocos de 120 segundos,
reutiliza as três transcrições integrais existentes após verificar hashes e
retoma blocos interrompidos. Usa CPU/int8, dois threads, arquivos temporários
pequenos no SSD e um lock de escritor. Cinco blocos novos atualizam o índice.
Segmentos antigos sobrepostos são substituídos; silêncio de um bloco também
substitui ASR anterior. Transcrições, legendas e nomes de canais **não viram
rótulos de ação/resultado nem atualizações de pesos automaticamente**.

Foram consultados os VODs públicos recentes dos quatro canais da fila. Um VOD
completo de Dishsoap foi baixado em 360p, com áudio/vídeo e duração conferidos;
um frame em t=600 mostra TFT PC e indicação 18.3, sem comprovar o hotfix. O VOD
de Subzeroark também foi baixado e conferido (TFT PC em t=600, patch não
estabelecido). Ambos entraram na fila incremental de transcrição, somando
aproximadamente sete horas adicionais. O arquivo Twitch `2889146353` é possível duplicata
do VOD local de Wasianiverson (criador, título e duração), aguardando confirmação
visual. Watch parties de Frodan permanecem identificadas como tal. O Bilibili
continua com acesso recusado, sem alegação de uso de seu conteúdo.

O suplemento [TFTCodex](https://tftcodex.com/cards.json), consultado em 04/10,
contém 88 entradas de unidades, 510 entradas na seção de itens (incluindo outros
tipos), 36 características e 246 aprimoramentos. Foi arquivado como candidato
com hash, sem substituir o release imutável. Há divergência de dano publicado
da Cassiopeia (420 no suplemento, 425 na nota oficial); o relatório preserva
a divergência e prioriza o fato oficial. Números presentes em texto não
estabelecem fórmulas, temporização ou handlers executáveis.

O processamento contínuo local roda como unidade de usuário
`agente-tft-asr-20261004.service`, com teto de dois núcleos, 1,5 GiB e seis horas.
Progresso e corpus ficam no SSD. Desligar o Ubuntu interrompe esse serviço;
os blocos já salvos permitem retomada. Não é um treino neural concluído sobre
todos os vídeos. Ainda faltam pares observados de estado/ação/resultado,
fronteiras de partidas e a validação do simulador sazonal.
