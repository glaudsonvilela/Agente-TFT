# Prévia Ubuntu: DINO + cálculo Rust (10/10/2026)

## Estágio verificado

- O executável Rust agora anuncia `rank_advice` e `match_memory` e atende às operações de ranking, confirmação e evento de combate que já existiam no código fonte.
- Na prévia de uma cena inédita, o Rust leu estágio 5-1, ouro 22, nível 8 e XP 6. Em quadros posteriores leu estágio 5-2 e calculou variação de ouro de -13 em 90 segundos.
- O ranking foi executado, mas respondeu `NO_ACTIONABLE_NATIVE_CANDIDATE`: nenhuma opção tinha evidência suficiente nesta cena. A tela de diagnóstico expõe esse resultado e os números observados.
- Testes: 9 testes de `live_rank` passaram; 12 testes de `test_decision_priority` passaram; a prévia rodou sem erro de processo.

## Limites observados

- Nenhuma unidade do tabuleiro foi identificada com confiabilidade nessa cena; o DINO mostra apenas códigos e nomes hipotéticos.
- HP, itens, identidades das unidades, sinergias contadas e rival atual ainda faltam para uma recomendação estratégica específica.
- A geometria das barras foi localizada, mas a arena não foi calibrada para atribuir os hexágonos. Logo, `board_candidates=0` no cálculo, apesar de barras detectadas.
- A prévia é um diagnóstico Ubuntu com replay local; ainda não é a interface final do Windows.

## Arquivos pendentes preservados

As alterações já presentes em `training/materialize_champion_restart.py`, `training/prepare_champion_restart.py`, `training/train_champion_yolo_restart.py` e `weights/` não fizeram parte desta integração e ficaram fora do commit. A coleção de recortes e os pesos provisórios DINO permanecem no SSD, fora do Git.
