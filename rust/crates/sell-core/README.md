# sell-core

Avaliador conservador de oportunidades de venda no bench.

Ele não possui valores hardcoded de venda. O caller precisa fornecer uma
`SellConfig` explícita e validada para o ruleset atual.

Regras de segurança factual:

- somente unidades realmente observadas no bench;
- nenhuma venda se a pressão de bench estiver abaixo do threshold;
- preserva material de upgrade por padrão;
- ignora unidade itemizada por padrão;
- sem regra de valor de venda → sem oportunidade;
- board-strength loss é 0 apenas porque o alvo está no bench;
- confiança é capada.

O resultado é `SellOpportunityFact`, que o Opportunity Engine compara com
BUY/ROLL/LEVEL/HOLD/etc.
