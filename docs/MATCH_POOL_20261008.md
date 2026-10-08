# Pool de contexto por partida — 8 de outubro de 2026

O worker Rust mantém um SQLite separado por partida. `observations` conserva os quadros; `match_pool` retém a última leitura não vazia de estágio, recursos, loja, traços, tabuleiro, itens e adversários, com o instante de origem. Candidatos de campeão e item são guardados por posição sem virarem identidades verificadas. Cada época do replay fica isolada.

O cálculo reúne leituras de loja e HUB feitas em quadros diferentes. Para decidir uma compra, ainda aplica validade curta à loja, ao ouro e ao traço; o histórico mais antigo serve para contexto. A mesma meta de traço recebe uma chave única entre os dois leitores e só uma dica publicada é marcada como falada. Um campeão já visto em campo como candidato persistente deixa de ser sugerido apenas para completar o mesmo traço.

Validação: 76 testes Rust e 237 testes Python passaram (4 ignorados). No replay do Ubuntu, a sessão curta de 49 segundos registrou uma única dica de Ornn, uma única emissão no SQLite e uma fala gravada. A sessão anterior de cerca de quatro minutos tinha anunciado Ornn duas vezes e só trouxe mais uma orientação de nível, confirmando que a seleção de ações ainda é estreita.

Pendências para o coach: ampliar o cálculo de oportunidades de combate, composição, itens e adversários usando a pool; recuperar HP quando a leitura deixa de aparecer; medir a relevância das recomendações contra partidas anotadas. A redação atual ainda usa textos preparados no cliente Python, portanto a fala livre baseada no resultado estruturado do Rust ainda não está concluída. Não tratar candidatos visuais como rótulos de treino.
