# Fontes 3D do Set 18 para o reconhecedor visual

**Correção de fonte (09/10/2026):** os 65 pacotes `.skn`/`.obj` inventariados
abaixo vieram dos arquivos WAD antigos de League. Eles **não são os modelos
efetivamente usados no Set 18**. O [levantamento do cliente Unreal de TFT](https://docs.modelviewer.lol/tft-unreal-extraction)
identifica as malhas e texturas do Set 18 em plugins `Character_*` do jogo;
explica que as cópias WAD ficaram desatualizadas após a migração. Assim, a
prévia anterior de Nidalee era inadequada também pela origem da malha, além de
pose, iluminação e câmera. O inventário abaixo registra arquivos baixados,
**não cobertura visual válida do Set 18**.

Já existe uma alternativa sem recorrer a vídeos: o acervo de [renders nomeados
do Set 18](https://modelviewer.lol/extras), gerados dos modelos Unreal. As 65
referências do projeto estão em
`docs/evidence/recognizer-training-20261005/named-render-references.json`;
as 65 imagens locais no SSD foram conferidas pelos SHA-256 desse manifesto,
sem ausências. A [prévia de Nidalee](https://modelviewer.lol/model-viewer?group=extras&alias=da_18_nidalee_ue&id=0)
mostra a personagem do Set 18. Essas imagens são referências de identidade
para revisar recortes reais; o fundo, texto, escala e vista do render diferem
dos pixels do tabuleiro. Não entram automaticamente como exemplos de treino nem
validam sozinhas o reconhecedor.

Auditoria de 09/10/2026, ligada ao catálogo 16.19.1 e aos 65 nomes de `named-board-bench-dataset/data.yaml`. A fonte foi o [acervo de assets do CommunityDragon](https://github.com/communitydragon/docs/blob/master/assets.md), congelado no patch 16.19. Os arquivos brutos e o manifesto com URL e SHA-256 permanecem no SSD, em `diagnostics/3d-model-audit-20261009`; não entram no Git nem no instalador.

## Cobertura verificada

- Os 65 nomes do detector foram associados aos IDs do catálogo Riot já armazenado no projeto. Dez nomes portugueses exigiram correspondência pelo ID original; cinco IDs de variantes exigiram usar o diretório do personagem base.
- Os 65 diretórios têm malha `.skn` e pelo menos um objeto `.obj`. São 322 partes `.obj` com vértices e faces válidos, 65 arquivos `.skn` e 86 texturas baixadas, 220,5 MiB ao todo, sem erro de transferência. Todas as 86 imagens de textura puderam ser decodificadas. A pasta base de Zyra não oferece textura direta; a associação de materiais das demais malhas ainda precisa de revisão.
- Muitos personagens têm várias partes e versões visuais no mesmo pacote. Renderizar todas simultaneamente misturaria acessórios e formas incompatíveis. Nidalee também possui um diretório separado para a forma felina. A cobertura de arquivos não equivale a cobertura de poses, animações ou identidade confiável no vídeo.
- Uma prévia de Nidalee foi renderizada a partir do `.obj` e da textura reais em quatro ângulos. O classificador atual de recortes não a reconheceu como Nidalee em nenhum dos quatro; a probabilidade atribuída à classe ficou entre 0,012 e 0,035. Esse é um teste de incompatibilidade entre render simples e captura de partida, não uma avaliação estatística de treino sintético.
- A comparação visual com dois recortes da própria partida confirmou que a prévia não reproduz pose, perspectiva, iluminação nem enquadramento vistos pelo reconhecedor. O usuário identificou o primeiro recorte, antes rotulado como Nidalee, como Rakan; exemplos já rotulados de Rakan têm a mesma aparência. Essa identidade foi colocada em quarentena, sem trocar automaticamente seu rótulo para Rakan. Após a correção, resta **um recorte de Nidalee no treino**, sem exemplos da classe na validação ou no teste. O manifesto original informa que não há verdade de referência humana independente. A comparação `diagnostics/3d-model-audit-20261009/nidalee-real-gameplay-vs-render.png` fica apenas no SSD.

## Uso no próximo experimento

Priorizar os quadros reais do jogo: recortar o campeão na imagem original, manter a caixa e a origem do vídeo, revisar o nome e separar partidas inteiras entre treino, validação e teste. Como o vídeo já é uma imagem 2D, não há conversão de modelo 3D necessária para formar esses exemplos. Ampliar os exemplos por campeão, pose, arena, combate e reserva; o único exemplo atual de Nidalee não mede generalização. **Não usar a prévia 3D atual no treino ou como rótulo.** Se futuramente as malhas forem usadas como aumento de dados, primeiro reproduzir câmera, escala, iluminação, animação e fundo reais e medir ganho em partidas separadas. Poses reais exigem esqueleto e animações, como descrito pelo [formato SKN/SKL/ANM](https://github.com/Crauzer/lol2gltf). Medir localização e identidade no tabuleiro e nas duas reservas antes de trocar o modelo do aplicativo. Não converter previsões em rótulos.
