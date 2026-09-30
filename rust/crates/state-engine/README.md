# state-engine

Transforma mudanças semânticas entre dois `GameState` em `GameEventKind`.

Exemplos:

- gold 50 → 48 → `GoldChanged`;
- troca de shop → `ShopChanged`;
- Planning → Combat → `CombatStarted`;
- adversário observado novamente → `OpponentObserved`;
- cópias vistas no lobby mudam → `ContestationChanged`.

A comparação ignora diferenças irrelevantes como apenas o timestamp de uma observação de shop quando o conteúdo da loja não mudou.
