# Catálogo visual ativo

`active-visual-reference-v1.json` escolhe o conjunto, a versão Data Dragon e o
banco de ícones que o HUB usa em uma sessão. Em cada atualização, altere este
arquivo e substitua os dados em `knowledge/`; valide o vínculo com o patch no
contexto da partida. Uma gravação antiga continua ligada ao seu próprio patch.

O escopo `set_plus_core` reúne arte do conjunto ativo, itens comuns
`TFT_Item_*` e itens radiantes reutilizados. No catálogo 16.19.1 são 328
entradas e 193 artes distintas. Cada candidato visual conserva os IDs e nomes
do Data Dragon; artes idênticas podem representar mais de um ID. O catálogo
de atributos do CommunityDragon é ligado apenas por `api_name` exato: 134
itens comuns e 37 radiantes têm essa chave no release 18.3. Os itens próprios
do conjunto usam IDs visuais `DA_*`, sem chave equivalente no release atual;
nomes parecidos não são tratados como prova de equivalência.

Não coloque aqui as coordenadas do tabuleiro, a região do HP ou a região do
ouro. Elas ficam em `configs/ui`, `configs/player-list`, `configs/hud` e
`configs/roi`. Mudanças na interface do jogo exigem uma calibração visual nova;
mudanças de campeões, itens e eventos exigem apenas novo catálogo/regras do
patch. As leituras de HP e ouro são observações do quadro, nunca valores de
um catálogo ou evento.

O HUB atual produz candidatos visuais. Nenhum candidato de campeão ou item
vira identidade verificada apenas pela presença no catálogo.
