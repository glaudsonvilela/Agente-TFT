# Modelos 3D do Set 18 para o reconhecedor visual

Auditoria de 09/10/2026, ligada ao catálogo 16.19.1 e aos 65 nomes de `named-board-bench-dataset/data.yaml`. A fonte foi o [acervo de assets do CommunityDragon](https://github.com/communitydragon/docs/blob/master/assets.md), congelado no patch 16.19. Os arquivos brutos e o manifesto com URL e SHA-256 permanecem no SSD, em `diagnostics/3d-model-audit-20261009`; não entram no Git nem no instalador.

## Cobertura verificada

- Os 65 nomes do detector foram associados aos IDs do catálogo Riot já armazenado no projeto. Dez nomes portugueses exigiram correspondência pelo ID original; cinco IDs de variantes exigiram usar o diretório do personagem base.
- Os 65 diretórios têm malha `.skn` e pelo menos um objeto `.obj`. São 322 partes `.obj` com vértices e faces válidos, 65 arquivos `.skn` e 86 texturas baixadas, 220,5 MiB ao todo, sem erro de transferência. Todas as 86 imagens de textura puderam ser decodificadas. A pasta base de Zyra não oferece textura direta; a associação de materiais das demais malhas ainda precisa de revisão.
- Muitos personagens têm várias partes e versões visuais no mesmo pacote. Renderizar todas simultaneamente misturaria acessórios e formas incompatíveis. Nidalee também possui um diretório separado para a forma felina. A cobertura de arquivos não equivale a cobertura de poses, animações ou identidade confiável no vídeo.
- Uma prévia de Nidalee foi renderizada a partir do `.obj` e da textura reais em quatro ângulos. O classificador atual de recortes não a reconheceu como Nidalee em nenhum dos quatro; a probabilidade atribuída à classe ficou entre 0,012 e 0,035. Esse é um teste de incompatibilidade entre render simples e captura de partida, não uma avaliação estatística de treino sintético.

## Uso no próximo experimento

Gerar recortes sintéticos com câmera, escala, iluminação, oclusão, fundo de arena e estados visuais próximos ao jogo. As malhas estáticas são um começo; poses reais exigem esqueleto e animações, como descrito pelo [formato SKN/SKL/ANM](https://github.com/Crauzer/lol2gltf). Usar imagens 3D somente como aumento do conjunto de treino, com proveniência explícita. Manter partidas reais inteiramente separadas para validação e teste e medir, por nome, localização e identidade no tabuleiro e nas duas reservas antes de trocar o modelo do aplicativo. Não converter previsões em rótulos.
