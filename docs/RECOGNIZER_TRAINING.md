# Treinamento do reconhecedor — missão em andamento

## Checkpoint de 05/10/2026

O objetivo é reconhecer unidades reais em VODs diferentes dos usados para
treino, medir confusões por identidade e reaproveitar os dados entre patches.
Não há ativação deste modelo no instalador neste checkpoint.

Implementação nativa Rust em `tools/unit-features-lab`:

- `vod-collector`: amostra VODs, detecta barras verdes, salva recortes,
  embeddings DINO INT8, quadros de contexto e proveniência. Previsões nunca
  viram rótulos automaticamente.
- `train-classifier`: treina classificadores softmax supervisionados com
  pesos balanceados por classe, sobre cores, DINO e DINO + cores.
- `evaluate-vod-head`: reutiliza embeddings selados por hash para avaliar
  novos classificadores e produzir uma fila de divergências para revisão.
- `contact-sheet`: monta páginas de recortes para inspeção visual.
- `fetch-vod-segments.mjs`: aquisição de segmentos públicos autorizados;
  Node é usado apenas para download, não para visão ou treinamento.

`live.rs` contém um observador experimental anterior. Não existe perfil
ativo nem pacote de modelos instalado por este trabalho. Alterações Python
anteriores da integração das dicas continuam pendentes na árvore de trabalho.

## Primeiro treinamento real de uma camada de identificação

Usa as anotações existentes, verificando hashes, catálogo e separação por
fonte/sessão/partida. DINO permanece congelado: os pesos novos são os da
camada classificadora. Não confundir isso com retreino do backbone.

| Entrada do classificador | Acertos nos 29 recortes nomeados antigos |
|---|---:|
| Histogramas espaciais HSV | 9 |
| Vetores DINO INT8 | 22 |
| DINO + HSV com pesos iguais | 14 |

A comparação anterior por vizinho mais próximo obteve 20/29 com DINO.
Esses poucos exemplos já foram reutilizados no desenvolvimento; não demonstram
precisão em uma partida nova. A validação antiga tem somente três unidades
nomeadas. Alguns IDs de treino têm apenas um exemplo. Softmax não foi calibrado
e não é autorização para declarar identidade verificada.

Relatório reproduzível: `evidence/recognizer-training-20261005/initial-supervised-report.json`.
Modelos e imagens ficam no SSD privado. O checkpoint JSON registra diretórios,
fontes e contagens alcançadas, sem URLs temporárias dos segmentos.

## Fontes novas e separação

- Avaliação: <https://www.twitch.tv/videos/2883698368>, k3soju, primeiras
  seis horas contínuas, grade de 10 segundos (2.160 amostras planejadas).
- Ampliação do treino: <https://www.twitch.tv/videos/2891050468>, Dishsoap,
  13.740 segundos, grade de 20 segundos (687 amostras planejadas).
  Essa fonte já pertencia exclusivamente ao treino.

O usuário declarou autorização dos criadores para treinamento. As mídias
continuam privadas. O título/data do VOD não comprovam o patch exato.
O catálogo visual está vinculado ao Set 18; vinculação exata de patch exige
evidência adicional quando não houver indicação visível.

A coleta extensa usa decodificação de keyframes para reduzir o custo de
decodificar vídeos longos. Os tempos são a grade nominal do filtro FFmpeg,
não PTS exatos dos quadros originais; podem ter deslocamento dentro do GOP.
Uma coleta separada de 180 quadros a 1 Hz usa decodificação completa.
Nenhuma dessas medições demonstra FPS da captura/preview no Windows.

## Atualizações sem refazer tudo

1. Manter captura, geometria, pré-processamento e encoder versionados por
   contrato. Revalidar a geometria se a interface do jogo mudar.
2. Vincular cada exemplo a fonte, instante, pixels, revisão, conjunto e
   identidade oficial. Revisões incertas ficam fora do treino.
3. Armazenar embeddings uma vez por hash de pixels + encoder + pré-processamento.
   Treinar a camada pequena novamente sem reprocessar o vídeo inteiro.
4. Manter uma galeria por conjunto/aparência. Mudanças numéricas de balanceamento
   atualizam regras/atributos e exigem regressão, sem obrigar novo treinamento
   visual. Aparências novas exigem novos exemplos.
5. Priorizar exemplos divergentes, desconhecidos, ocluídos e classes com pouca
   cobertura. Avaliar sempre em fonte separada e conservar testes anteriores.
6. Publicar um modelo apenas quando a cobertura, erros por classe, rejeição de
   não unidades e latência estiverem medidas. Não promover candidatos apenas
   porque produziram mais respostas.

Essa abordagem de classificador treinado sobre características congeladas é
compatível com a avaliação linear descrita no
[repositório DINOv2](https://github.com/facebookresearch/dinov2/blob/main/dinov2/eval/linear.py).
Aqui usamos uma implementação própria pequena em Rust, com protocolo e dados
TFT; não reproduzimos os resultados publicados do DINOv2.
