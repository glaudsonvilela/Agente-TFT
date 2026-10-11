# ADR-0004 — Akash Network para treinamento neural remoto

**Status:** Accepted as architectural direction; implementation pending  
**Date:** 2026-10-11  
**Supersedes:** [ADR-0003](0003-remote-training-plane.md) apenas quanto ao provedor computacional (HOMELAB → Akash). O isolamento de comandos do cliente continua obrigatório.

## Contexto

O plano original de treinamento remoto em servidor próprio exigia operação, energia, manutenção e capacidade GPU dedicada. O objetivo do Agente TFT é treinar de forma escalável, sob demanda, sem depender da GPU dos jogadores, mantendo o motor local Rust e a inferência ONNX.

O operador optou por avaliar a **Akash Network**, que permite contratar containers GPU via marketplace descentralizado com Keplr/ACT. A blockchain gerencia leases e pagamentos; o treinamento ocorre no hardware do provedor, fora da cadeia.

## Decisão

Adotar Akash como **backend preferencial futuro de GPU** para PyTorch, simulações, comparações challenger/champion e processamento em lote. Os datasets/checkpoints aprovados ficam em storage privado persistente **independente dos leases**. O operador gerencia carteira e custos manualmente.

- Cliente Windows/Linux não passa a controlar GPUs, wallets ou leases.
- Não há necessidade de servidor HOMELAB dedicado como requisito de computação.
- Worker remoto é temporário; contratos `TrainingJobRequest/TrainingJobResult` continuam abstratos e podem ser adaptados.
- A comunicação de dados sensíveis requer controle de acesso, TLS e minimização. Provedores GPU não devem ser tratados como terceiros confiáveis por padrão.
- GPU e storage precisam de orçamento e proposta explícita; não há criação de gasto automático.
- Publicação de champion requer holdout e validação, hashes, compatibilidade e rollback fora da partida.
- Em falha da Akash, da internet ou de créditos, o software continua com a última versão local aprovada.

## Status

Esta ADR **não declara implementação**: ainda faltam adapter de jobs, containers versionados, storage, autenticação, automação de backup e validação GPU real. Sem custos aprovados, sem deploy on-chain e sem software do jogador operando diretamente uma carteira.

## Consequências

Benefícios: locação sob demanda, possível acesso a GPUs mais potentes, flexibilidade de provedor, escala por contrato.

Custos/riscos: preços variáveis, disponibilidade não garantida, exposição do workload a provedores externos, backups obrigatórios, manutenção do pipeline de deploy e custos de dados/rede.

**Plano detalhado:** [AKASH_TRAINING.md](../AKASH_TRAINING.md).  
**Akash oficial:** https://akash.network/docs/developers/deployment/akash-console/with-wallet/
