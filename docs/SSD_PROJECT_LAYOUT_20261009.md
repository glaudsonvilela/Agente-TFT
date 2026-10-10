# Mapa do projeto no SSD

Há **um checkout principal** em `/mnt/sherlock-ssd/AgenteTFT/work/Agente-TFT`, na branch `main`. O GitHub também ficou com apenas `main` após a integração das branches antigas. Este arquivo registra os caminhos; não é uma medida de qualidade do reconhecedor.

| Caminho no SSD | Conteúdo e uso |
| --- | --- |
| `work/Agente-TFT` | Código ativo, documentação e testes |
| `champion-corpus` | **Pacote principal** de identidade: 734 treino, 32 validação, 127 teste; manifesto e revisão de 25 imagens pelo usuário |
| `champion-corpus/models/active` | Cópia dos pesos de campeões atualmente instalados |
| `champion-corpus/models/canonical-65-v1` | Candidato de treino, ainda não instalado |
| `diagnostics/yolo-hud-runtime-20261009-v2` | Pacote atual usado nos testes de reconhecimento |
| `sources` | Fontes baixadas; preservar para proveniência e novas revisões |
| `diagnostics` | Gravações, avaliações e experimentos; não é fonte de rótulos verificados por si só |
| `installers/hm45-vm-designer-20261008-r2` | Instalador mais recente preservado; o relatório ainda exige teste real no Windows/WSL2 |
| `archive` | Worktrees, trabalho incompleto e pastas antigas retiradas do caminho principal |

Os conjuntos históricos de `diagnostics`, inclusive o experimento de quatro horas com rótulos fracos gerados por modelo, **não entram automaticamente** no pacote principal. O pacote atual e a decisão de não instalar o novo candidato estão descritos em `docs/TFT_CHAMPION_CANONICAL_PACKAGE.md`.

Foram removidas as cópias antigas do runtime YOLO, instaladores anteriores e builds locais de 03/10. Os nomes, tamanhos e hashes dos executáveis/modelos removidos estão em `/mnt/sherlock-ssd/AgenteTFT/archive/removed-versions-20261009.json`. O runtime `v2`, o instalador `r2`, vídeos brutos, dados de avaliação e pesos de referência permanecem.

## Trabalho preservado fora da branch principal

- `archive/worktrees/yolo-champion-diagnostics`: alterações ainda incompletas de rastreamento visual e interface, mantidas na árvore de trabalho arquivada.
- `archive/worktrees/neural-bootstrap-deploy-fix`: arquivo experimental não versionado de avaliação, mantido na árvore de trabalho arquivada.
- `archive/pending/neural-combat-working-changes-20261009.tgz`: cópia das cinco alterações não concluídas do motor neural; também há um stash no repositório principal.
- `archive/old-work`: pastas de trabalho antigas de `board_hub` e `riot-reference-probe`.

Não há validação suficiente para trocar os pesos instalados de reconhecimento de campeões. O candidato acertou 104/127 recortes de teste contra 99/127 do ativo, mas empatou em 16/22 no subconjunto de tabuleiro e não tem teste independente completo em partidas distintas. Melhorias de nomes em partida continuam pendentes.
