# Experimento Akash de percepção completa — 10/10/2026

## Escopo e integridade

`prepare.py` empacota os 206 recortes de campeões confirmados pelo usuário no conjunto após o reset, pertencentes a 60 classes. Os outros cinco nomes do elenco de 65 continuam sem recorte confirmado e sem peso semântico. A rotina verifica SHA-256 de cada imagem. Não inclui pesos antigos de TFT nem transforma predição do assistente em rótulo. `training_eligible=false` no manifesto original continua intacto: a autorização atual permite **experimento**, sem promoção automática ao YOLI.

O pacote inclui os perfis e leitores existentes para os dois tabuleiros de 28 casas, bancos de nove posições, loja, itens, sinergias, ouro, XP, nível, estágio, HP, streak, jogadores e telemetria; inclui ainda o catálogo e modelo de itens, código Rust/Python e quatro replays 1080p. Esse material acompanha o teste integrado. Sem anotações humanas completas, as demais categorias não são retreinadas nem recebem porcentagem inventada de acerto.

## Execução

O arquivo SDL gerado em `experiments/akash-full-perception-20261010-ready/deploy.yml` pede uma RTX 3090, quatro CPUs, 16 GiB de RAM, 30 GiB de disco e lance máximo de 500 uact/bloco, aproximadamente 0,30 ACT/hora a seis segundos por bloco. O preço efetivo é o lance do provedor escolhido no Console Air. O contêiner usa a imagem pública `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`, testada quanto à existência do tag, e instala `onnxruntime==1.23.2` ao iniciar.

Na [Console Air](https://air.akash.network/), a carteira Keplr deve assinar a criação da implantação e a escolha do provedor. O agente não acessa a chave. Após a lease ficar ativa e exibir URL HTTPS, execute `upload.sh URL` (ou forneça a URL ao agente para que ele execute). O endpoint recebe separadamente o pacote central e os replays, verifica SHA-256 e só então inicia o treino. O token de upload está no SDL e no helper; estes arquivos ficam fora do Git com permissão local restrita.

O treino primeiro extrai recursos genéricos do DINOv2 e ConvNeXt, compara ambos e a fusão em um vídeo mantido fora do ajuste e grava uma cabeça linear usando todos os recortes confirmados. Em seguida, usa a RTX 3090 por duas horas para ajustar a última etapa de ConvNeXt com variações de imagem. Os primeiros 45 minutos preservam um vídeo para diagnóstico; o restante usa todos os recortes para o modelo final. O resultado permanece experimental. O endpoint `/status` e o log mostram fase, perda, tempo e memória GPU. Os pesos e relatórios podem ser baixados em `/download/` com o token.

O aluguel **não fecha automaticamente** ao fim do script. Depois de baixar os resultados, fechar a implantação no Console Air devolve o saldo não consumido do depósito. A [documentação da Akash](https://akash.network/docs/learn/core-concepts/deployments/) descreve a cobrança por bloco e o fechamento da lease.

## Referência local antes do aluguel

O ensaio executado na GTX 1060 com o mesmo conjunto obteve 21/31 para a fusão, 18/31 para ConvNeXt e 14/31 para DINOv2, em 17 classes visíveis no vídeo separado `8W7Wfnf36M8`. O mesmo vídeo foi usado para selecionar a configuração da cabeça, portanto **não é teste final intocado**. Não mede mapa, banco, itens, OCR ou estabilidade temporal. Artefato: `experiments/akash-full-perception-20261010-v2/local-smoke/report.json`.
