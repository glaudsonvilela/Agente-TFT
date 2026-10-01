# B2 — Hipóteses visuais de presença no banco

## Resultado B1 recebido

O usuário mediu 40 JPEGs: 17 `reference_arena_match`, 23 `unresolved`; 360 observações de banco divididas em 9 `bar_candidate`, 22 `empty_reference_match`, 207 `projection_unavailable` e 122 `unknown`. Foram 232 propostas de barra (181 verdes/51 vermelhas), NÃO 232 unidades identificadas. Zero OCR/erros. Mediana da análise: 6.2579295 ms; decodificação+análise: 81.346579 ms. Não subtrair percentis como se fossem medições pareadas de um estágio nem concluir 60fps de captura contínua.

O frame 200000 ms é a própria referência: seus nove matches de vazio não são validação independente. `unresolved` não significa que 23 tabuleiros estavam ausentes: B1 testa duas decorações da arena, não a geometria completa.

## Objetivo

Sair de sinais isolados para hipóteses por espaço do banco, mantendo o registro B1 integral para regressão. B2 continua local, opt-in e sem OCR. Não muda a referência da loja (S4), não aprova S5 e não libera o HP em quarentena.

## O que está implementado

1. **Compatibilidade visual local:** se as decorações B1 não correspondem, três recortes na borda inferior do banco podem estabelecer `bench_structure_match`. Todos precisam passar: correlação de forma >=0.90, erro residual médio <=6, fração alterada <=0.05, textura de referência e offset por canal limitado a 40. Isso não reconhece o dono do tabuleiro, fase ou qualquer arena arbitrária. Não transfere as assinaturas para uma arena de forma diferente. O fallback só autoriza as hipóteses do banco; nunca muda o status B1 nem valida as células do tabuleiro.
2. **Compensação visual limitada:** a mediana da diferença em cada canal remove um deslocamento aditivo de iluminação. A textura, os resíduos e os limites continuam sendo testados. Uma imagem plana não estabelece vazio. Nenhuma correção de HP, nome ou ação é realizada, e não há treino de pesos.
3. **Suporte conjunto:** o campo `occupied_visual` exige uma única barra elegível na faixa do banco e um único componente conectado de diferença visual abaixo dela, chegando à faixa inferior de suporte. Componentes grandes, cortados nas bordas ou sem altura/área suficientes não são usados. Cor não determina equipe; largura da barra não vira HP; o ponto inferior da caixa não vira `ground_point`.
4. **Vazio visual:** exige semelhança da região texturizada com a referência vazia, sem barra ou corpo concorrente, com critérios próprios mais estritos (correlação >=0.98, residual <=4 e fração alterada <=0.01). Ausência de barra sozinha não estabelece vazio. Múltiplos sinais ou sinais contraditórios ficam ambíguos. Falta de suporte fica desconhecida.

Essas regras são hipóteses visuais: `occupancy=true/false/null` aparece somente no novo bloco `bench_presence`. Não é acurácia validada, identidade de campeão, confirmação temporal nem autorização para mudar o GameState. Falsos positivos/negativos são possíveis. O componente conectado é uma diferença de aparência, não um detector treinado de corpo.

## Organização

A topologia de 9 espaços e a projeção B1 ficam preservadas. A política adicional fica em `configs/ui/match001-bench-presence-v1.json`, presa ao blob do perfil B1. Não contém campeões, set, itens ou regras de dano. Preparação RGB e detector de barras existentes são reutilizados; nenhum novo backend ou dependência de visão é adicionado.

O mesmo executável recebe opcionalmente a política como quinto argumento. Sem ela, o caminho B1 permanece. `read` (B1) e `bench_presence` (B2) são blocos distintos sobre o MESMO frame decodificado. O runner reutiliza preparação de manifesto, subprocesso com limite, verificações de hashes, validação B1 e visor existentes. Não faz uma cópia de todo o motor por versão.

## Evidências e visor

O comando compara o bloco `read` completo com o relatório B1 histórico, não apenas as contagens. Qualquer diferença falha a validação e mantém os arquivos brutos. Os hashes das imagens, sementes, configurações, manifesto e executável são verificados antes/depois. Não lê valores esperados dos prelabels e não utiliza os timestamps para escolher uma ocupação.

O visor exibe hipóteses de presença, recortes e componentes. O mapa do tabuleiro não é habilitado pelo fallback exclusivo do banco. Não é necessário rotular manualmente. Tempos B1, tempo adicional B2 e total de decodificação+ambas as análises ficam separados; nenhum ganho de velocidade é pressuposto. Os backends do ambiente são registrados, não congelados automaticamente.

```bash
bash scripts/probe_match001_bench_presence.sh \
  telemetry/data/match-001-board-b1.BlHCOHWx
```

Compila apenas o app em `rust/target/board-b2`, sem sobrescrever os binários B1, HP ou loja. Usa os 40 JPEGs e cria `telemetry/data/match-001-bench-b2.XXXXXXXX/evaluation/`, com relatório, regressão e resultado nativo/visor. Não extrai novamente MP4. Sem servidor, cliques, memória de processo, promoção ou treinamento.

## Validação

Testes de referência texturizada, barra/corpo conjuntos e separados, múltiplos sinais, offsets limitados, painel amplo, regiões cortadas, suporte inferior, geometrias inválidas, corrupção de evidências e regressão B1 completa. A integração real gera PNGs, roda o Rust com FFmpeg e usa Tesseract-sentinela para detectar OCR indevido. A execução no Match001 é a medição seguinte no Ubuntu; protótipos Python de comparação visual não substituem o teste nativo.

A revisão detalhada cobre o diff e suas integrações. A varredura estrutural de toda a árvore permanece, mas não significa revisão semântica integral nem resolução dos 22 apontamentos históricos.

## Próximo

Medir B2; tratar oclusões/variações que permanecem desconhecidas e ligar observações temporalmente próximas. Depois identificar unidades/estrelas e obter base/posição no chão para as células do tabuleiro, preservando cópias distintas. Itens/painel de atributos (vida, dano, defesas, habilidades) e integração com loja seguem no escopo. Servidor e vídeos externos continuam adiados.
