# Treino e teste da percepção completa — 10/10/2026

## Escopo obrigatório

O próximo experimento deve avaliar a cadeia completa por partida, em quadros inteiros: identificação do mapa e da perspectiva; 28 casas do próprio tabuleiro e 28 do rival quando visíveis; nove posições de cada banco; localização, identidade e rastreamento de unidades; cinco cards e nomes da loja; itens equipados e reserva de itens; painel de sinergias; estágio, ouro, nível, XP, HP e nomes dos jogadores. A telemetria liga observações sucessivas por partida, jogador, casa e posição de banco. Ela registra a origem e a incerteza de cada hipótese, sem transformar previsão do modelo em rótulo de treino.

Não tratar uma caixa localizada como nome reconhecido, nem uma coordenada de layout como valor lido. Tabuleiro e banco são espaços distintos. A identidade do dono da arena precisa de evidência do placar e de transições, não da aparência do mascote ou do mapa.

## Estado encontrado

| Camada | Material existente | Limite atual |
| --- | --- | --- |
| Campeões | `champion-reset-20261009/roster/unified-reviewed-candidates-20261010.json`: 287 candidatos de 65 classes em 21 vídeos; 204 confirmados pelo usuário, 80 associados visualmente pelo assistente e 3 por painel/UI. A auditoria das fontes encontrou 139 recortes confirmados em VODs 4K, incluindo 27 cuja resolução faltava no manifesto mas foi aferida no arquivo original. | Só 12 classes têm cinco ou mais recortes 4K antes da revisão de pose; nenhuma tem cinco poses distintas aprovadas. Faltam no mínimo 194 recortes se exigirmos 4K para todos, ou 147 se todos os recortes confirmados de outras resoluções passarem na revisão de qualidade e pose. Os 80 associados visualmente não podem virar rótulos sem revisão. |
| Mapas e casas | Topologia lógica 4×7 por lado e perfis de arena lago, vermelha e cibernética; há propostas de pontos em 1920×1080. | As projeções dependem da arena e não foram validadas como rótulos. Vermelha e cibernética propõem os dois lados; no trecho do lago só o lado inferior está visível. |
| Bancos | Topologia de nove posições e propostas superior/inferior para arena cibernética. | Não confundir banco superior com linha do tabuleiro; ocupação e perspectiva ainda precisam de revisão por quadro. |
| Loja e economia | Localizador experimental para cards, estágio, ouro, nível, XP e HP; layout da loja 1080p e leitores OCR existentes. | O experimento conjunto tem apenas propostas de caixas. Não há valores de teste completos verificados em partidas independentes. |
| Itens | Catálogo ativo de 328 entradas e 193 artes distintas; classificador experimental e treino sintético de HUD. | Validação sintética compartilha as artes de origem; seis recortes reais são insuficientes para medir acerto em jogo. O modelo com contadores não foi promovido. |
| Sinergias | OCR do painel esquerdo em Rust, aliases de atributos e cálculo condicional de composições. | Há leitura de texto e regras, mas não treino visual validado de ícones/contagens; leitura parcial não deve definir campeão nem rótulo. |
| Jogadores e adversários | Propostas de linhas, avatares e HP no placar; memória de adversários no software. | Nome/HP/dono da arena e estabilidade por jogador ainda carecem de referência humana independente. |
| Telemetria | Módulos de mapa espacial, memória, identidade de partida e eventos; contrato `state → features → candidates → scores → recommendation → player action → outcome`. | Falta avaliação ponta a ponta da troca de arena, banco→casa, venda e combate em partidas novas. |

## Bloqueios antes de alugar GPU para treino completo

1. Revisar qualidade, identidade e pose dos candidatos; manter os 80 rótulos inferidos pelo assistente fora do treino. Exigir frente, costas, tabuleiro e banco quando disponíveis, sem contar quadros quase iguais como poses novas.
2. Revisar em quadros inteiros as 22 categorias listadas em `experiments/full-hud-readiness-20261010/report.json`, incluindo itens e sinergias próprias e do rival. Registrar também **valores** de ouro, XP, estágio, HP, card e nome, não só caixas.
3. Criar uma única divisão treino/validação/teste **por vídeo/partida**, usada por todas as tarefas. A auditoria atual aponta três conflitos entre divisões de campeão e HUD (`-YQHDFlMRRs`, `8W7Wfnf36M8`, `wr5_dV3QajM`); não reutilizar esses splits antigos no próximo resultado.
4. Separar partida inédita para teste integral, com métricas por mapa, casa, banco, localização, identidade, item, sinergia, texto/valor e continuidade temporal. Exibir também falsos positivos em fundo/passivas.
5. Só então preparar pacote e comando de treino remoto. O deployment de teste da RTX 3090 foi fechado; nenhuma GPU está contratada agora.

### Auditoria reproduzível dos recortes

`training/audit_champion_pose_candidates.py` lê o elenco atual e registra dimensões, uma medida de foco, origem do vídeo, resolução e pares visualmente parecidos no relatório `champion-reset-20261009/roster/pose-candidate-audit-20261010.json`. Ela **não** altera rótulos nem a elegibilidade de treino. A medida de foco e a semelhança servem somente para organizar revisão humana: HUD, oclusões e animações podem enganar ambas. As 12 classes que alcançam cinco recortes 4K brutos são Amumu, Diana, Hecarim, Kha'Zix, LeBlanc, Lillia, Lux, Ornn, Rengar, Shen, Varus e Xayah; algumas têm repetições próximas ou vêm de um único vídeo. Camille, Cascalho, Kayle, Lobo Trevoguari e Rubrivira não têm recorte com status `user_confirmed_candidate` no manifesto atual; painéis e outras hipóteses foram mantidos em seus estados separados.

O vídeo 4K local `QX9HEpdPMNk.webm` foi amostrado em 12 quadros; o trecho é sobretudo combate avançado com efeitos grandes e unidades sobrepostas. A folha `source-review-20261010/QX9HEpdPMNk-4k-overview/contact.jpg` fica como inspeção de fonte, sem gerar rótulos ou contar novas poses. A coleta deve priorizar trechos de preparação, banco visível e unidades isoladas.

## Regra de integração

Resultados de imagem, OCR, geometria e regras do jogo são evidências com origem, horário, perspectiva e confiança separados. Uma hipótese de campeão só entra na memória de uma casa ou banco após associação temporal estável; a telemetria preserva revisões e contradições. O software ao vivo continua usando os componentes já aprovados até o novo conjunto passar no teste de partidas inéditas.
