# Agente TFT — Plano de treinamento GPU na Akash Network

**Status:** PROPOSTO / NÃO IMPLANTADO  
**Escopo:** migração da execução do treinamento PyTorch e simulações offline para GPUs contratadas no marketplace da Akash.  
**Importante:** o blockchain coordena pagamentos e leases; o cálculo do PyTorch acontece **off-chain**, no container do provedor.

## Objetivo e limites

- O software Windows captura o jogo/replay, e o core Linux processa reconhecimento e calcula decisões com Rust/ONNX sem depender da internet.
- O treino central é um **pipeline lógico**; não exige um servidor dedicado próprio 24/7. Pode ser orquestrado por scripts de operação e armazenamento externo privado. A API remota do repositório é legado e **não significa** que a Akash esteja integrada.
- A GPU Akash processa lotes revisados (percepção, modelos de valor, simulação/rollouts), não controla o cliente e não vê a tela do jogador em tempo real.
- Dados de terceiros devem ter consentimento e minimização; provedores são terceiros, sem confidencialidade garantida por padrão.
- Sem automação de movimentação financeira: Keplr, swap AKT → ACT, assinatura, escolha de bids e cancelamento de leases são ações do operador.

## Fluxo pretendido

```text
Windows → captura da sessão
   ↓
Linux: OCR + detecção + GameState + eventos + registros aprovados
   ↓
Selagem da sessão / versão do patch / hashes / deduplicação
   ↓
Revisão e export de dataset sem segredos nem dados pessoais
   ↓
Storage privado externo (dados, manifest, checksums)
   ↓
Operador: Akash Console Air + Keplr + orçamento ACT + bid GPU
   ↓
Container imutável: Python/PyTorch/CUDA + Rust opcional
   ↓
Treino/validação offline (holdout separado, logs mínimos)
   ↓
Checkpoints exportados para storage persistente EXTERNO
   ↓
Avaliação contra champion: confiança, métricas, rollback
   ↓
Manifest assinado/verificado e modelo aprovado ONNX
   ↓
Cliente baixa atualização em momento ocioso, valida hash e ativa atomicamente
```

## Onboarding operacional — sem cartão

1. Aguarde a confirmação de AKT **nativo** na Keplr. Não pressuponha que uma bridge pendente já concluiu.
2. Acesse o [Console Air](https://akash.network/docs/getting-started/console-air-onboarding/) e conecte **Keplr**.
3. Converta apenas o AKT planejado em **ACT** para escrow, mantendo AKT para taxas. Confira a cotação e a operação na carteira.
4. Na interface, configure container Docker e recursos de GPU/RAM/CPU/disco; peça propostas (bids) e compare **preço efetivo, disponibilidade, reputação e duração**. Não fixe preço/hora no código.
5. Confirme manualmente a implantação **somente** quando houver orçamento suficiente e uma estratégia de backup/restauração de checkpoints.
6. Ao terminar o treinamento, exporte pesos e métricas, verifique integridade, encerre o lease e confira o saldo residual de ACT/escrow.

> **Nenhum passo acima está automatizado nem foi executado por este repositório.** Não envie frase de recuperação, chave privada, dados bancários, seed ou token da Keplr para containers, GitHub Actions, logs, scripts ou variáveis SDL.

## Perfil inicial da GPU (hipótese para pesquisa)

- Uma GPU NVIDIA com CUDA, **preferencialmente 16–24 GB de VRAM**, dependendo dos modelos e ofertas.
- Container PyTorch com versão e digest imutáveis, sem `latest` em produção.
- Um único job pequeno e reprodutível: reconhecimento visual supervisionado com dados já autorizados.
- Separar treinamento e validação por partida/fonte, evitando vazamento de frames da mesma partida entre splits.
- Medir epochs, throughput, custo de execução, memória GPU, checkpoints e qualidade contra baseline.
- Para trabalho distribuído entre várias GPUs, exigir prova de ganho após medir o custo de comunicação; não presumir que vários leases formam automaticamente um cluster.

## Segurança e persistência

- Storage persistente **fora** do provider/lease (objeto privado criptografado); disco de container pode desaparecer quando o lease termina.
- Entradas e saídas identificadas por hash, schema, patch, dataset, seed e revisão do código.
- Jamais colocar arquivos de credenciais em imagens Docker ou repositório público. Preferir credenciais curtas geradas pelo operador e rotacioná-las após o job. SDL/manifesto não deve conter segredos.
- Evitar endpoints públicos; qualquer API remota precisará de TLS, autenticação, limites e auditabilidade antes de ser habilitada.
- Checkpoints brutos são **candidatos**; só publicar um champion após testes em holdout independente e validação de compatibilidade.
- Nunca promover pesos durante uma partida; manter rollback e modo offline.
- Não automatizar novas locações ou gasto após falha/reconexão. Operador deve ver o custo antes de assinar.

## Critérios para afirmar que a migração está implementada

- [ ] AKT confirmado na Keplr e orçamento/ACT disponível.
- [ ] Bid real de GPU revisado e lease criado voluntariamente pelo operador.
- [ ] Docker com PyTorch e CUDA reconhecendo GPU do provedor.
- [ ] Dataset revisado transferido para storage externo privado, com checksums.
- [ ] Job reproduzível e relatório de treino/validação emitidos.
- [ ] Checkpoint recuperado após encerramento de lease.
- [ ] Export ONNX testado no cliente local, com benchmark e rollback.
- [ ] Custos reais e limites de orçamento registrados.
- [ ] Política de privacidade e segurança validada para dados de usuários.

## Relação com o código legado

`agent/core/remote_training.py`, `trainer/` e `configs/services/neural*.json` descrevem o contrato pré-existente de API/atualizações remotas; **não são um backend de Akash**. URLs `.invalid` são placeholders, não endpoints reais. A migração demandará novo adaptador de jobs, empacotamento Docker, configuração de storage, ingestão de resultados e testes de integração. Até lá, o sistema local preserva a inferência e a funcionalidade offline.

**Documentação oficial:** [Console Air](https://akash.network/docs/developers/deployment/akash-console/with-wallet/), [GPU deployments](https://akash.network/docs/learn/core-concepts/gpu-deployments/), [marketplace e escrow](https://akash.network/docs/getting-started/core-concepts/).

