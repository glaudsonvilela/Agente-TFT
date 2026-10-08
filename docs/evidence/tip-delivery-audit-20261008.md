# Auditoria das dicas em texto — 2026-10-08

Esta nota descreve o comportamento do código nesta revisão. Uma dica exibida é uma
hipótese de ação baseada em leituras da tela; `confidence` de OCR não é uma
probabilidade calibrada de vitória. A voz está pausada nesta etapa para medir
percepção, decisão e apresentação em texto separadamente.

| Etapa | Quando segue | Quando fica sem dica |
| --- | --- | --- |
| Captura e OCR | Imagem de jogo em 16:9, normalizada para o leitor 1920×1080; campo único com confiança suficiente | Fonte errada, HUD encoberta, formato incompatível ou leitura ambígua |
| Candidatos | Ouro lido com confiança ≥0,85; regras de estágio/nível, loja e tabuleiro contribuem conforme cada tipo de ação | Sem ouro confirmado não surgem candidatos parciais; compras precisam de oferta atual e nome vinculado ao catálogo |
| Escolha Rust | Ação sustentada pelos recursos e pelo contexto da partida, com utilidade positiva | Ação inconsistente, opção sem evidência ou repetição da mesma decisão já mostrada |
| Texto na interface | Dica atual até 5 s; histórico distingue a dica anterior de uma nova | Mostra o diagnóstico da leitura atual e o estado da decisão, sem apresentar uma dica antiga como atual |

O modo ao vivo **gera dicas em texto** quando o motor de decisão está disponível.
O painel de desempenho dizia `disabled` no modo ao vivo; a indicação foi corrigida.
As sugestões de estado parcial aparecem como experimentais. O conselho de rolagem
atual exige HP recente ≤35, estágio ≥3, nível ≥6 e ouro ≥34; esse limite é
uma regra da política atual, não uma fronteira de segurança ou uma medida
aprendida de qual ação vence. Pares e sinergias dependem dos nomes da loja,
do catálogo do patch e dos candidatos persistentes do tabuleiro. Equipar um
item exige identidade confirmada do item e do campeão; um ícone candidato não
vira instrução afirmativa.

O motor Rust escolhe entre candidatos e registra os motivos de abstenção ou de
repetição. A interface agora expõe a leitura de espera também no Windows, e
indica quando o motor não encontrou uma ação sustentada. Voz e montagem de vídeo
das falas foram pausadas; a aplicação não inicia a API ElevenLabs. O pacote de
Windows deixou de exigir e incluir FFmpeg nesta configuração.

Validação local nesta revisão: testes de voz, runtime e interface, verificação
de sintaxe Python e JavaScript. Ainda falta compilar o instalador em um host
Windows e executar uma partida de ponta a ponta para medir a proporção de
leituras, candidatos, dicas atuais e abstenções. Os limiares de OCR e as
regras estratégicas acima devem ser reavaliados com evidência de partidas
diversas; esta revisão não os reduz arbitrariamente.

O leitor de loja com `tessdata_best` depende do modo residente de Tesseract.
Um teste isolado no modo que abre novos processos OCR ficou lento e não
reconheceu as ofertas; no modo residente, a mesma imagem voltou a ler os
nomes e custos, em cerca de 0,45 s. O aplicativo agora exige esse modo,
inclusive no MVP do Ubuntu, em vez de cair silenciosamente para o caminho
lento. O teste do Windows continua pendente.
