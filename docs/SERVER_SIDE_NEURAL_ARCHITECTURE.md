# Agente TFT — treino em GPUs Akash + inferência local

**Status da migração:** PLANEJADA; ainda sem deployment GPU validado na Akash.  
**Fonte de requisitos:** [Plano de treinamento Akash](AKASH_TRAINING.md).

## Decisão de arquitetura

A infraestrutura preferencial de **treinamento e avaliação neural** será a **Akash Network**, substituindo a necessidade de manter um servidor de treino dedicado. A Akash é um mercado descentralizado: leases e pagamentos usam blockchain, enquanto os containers PyTorch/CUDA executam nos servidores GPU dos provedores (**off-chain**).

O cliente TFT continua com inferência compacta local (ONNX) e matemática Rust em Windows/Linux. Treinar na Akash **não significa** executar inferência de cada frame pela internet; a latência e a disponibilidade do jogo não podem depender de um lease remoto.

## Durante a partida

```text
TFT Windows → captura → Linux (OCR/ONNX/Rust)
                                ↓
                     GameState / Decision Core
                                ↓
                     recomendação na interface
```

Os pesos locais aprovados ficam congelados durante toda a partida. Sem rede, o programa usa o último modelo aprovado e fallback determinístico.

## Treino pós-partida — desenho alvo

```text
Sessão local consentida e selada
  ↓
Triagem gold / silver / quarantine; proveniência, deduplicação e hash
  ↓
Dataset privado e desidentificado no storage externo
  ↓
Operador escolhe GPU, bid, duração e limite de gastos no Console Air
  ↓
Lease Akash (Keplr, ACT) → Worker Docker / PyTorch / CUDA
  ↓
Treinamento de challenger + simulação offline / Shadow
  ↓
Avaliação holdout, métricas e comparação com champion
  ↓
Persistir checkpoints fora do lease; publicar manifest se aprovado
  ↓
Cliente busca atualização depois da partida, valida SHA-256/versão
  ↓
Ativação atômica apenas quando ocioso + rollback
```

### Separação entre responsabilidades

**PC do jogador:**
- captura visual, OCR, Rust Math, inferência local e estado da partida;
- registro do replay e export consentido de evidências revisadas;
- consulta de manifest, download e ativação segura do novo modelo.

**Operador/plano de treinamento:**
- curadoria dos datasets, splits por sessão, rótulos e revisão de qualidade;
- hospedagem privada de datasets/artefatos e dos manifests assinados;
- escolha de lances GPU, criação/encerramento de leases e monitoração de custos;
- execução de Docker/PyTorch com sementes/versões identificadas;
- avaliação dos challengers, aprovação do champion e auditoria.

**GPU contratada na Akash:**
- somente computação offline autorizada; não recebe chaves privadas nem controle do computador;
- dados são processados por provedor terceirizado; confidencialidade requer medidas específicas;
- armazenamento efêmero não pode ser a única cópia dos checkpoints.

## Política de promoção neural

1. Predição do modelo não vira rótulo automaticamente; gates `gold/silver/quarantine` permanecem obrigatórios.
2. Validação independente por partidas, patches e versões; evitar leakage por imagens duplicadas da mesma partida.
3. Candidate não é champion por apresentar uma única métrica favorável.
4. Pacote aprovado deve ter versionamento, hash, verificação de compatibilidade e possibilidade de rollback.
5. Atualizações em segundo plano são automáticas no software, mas **nunca trocam pesos durante partida ativa**.
6. Falha de rede, da GPU, da blockchain ou do serviço remoto não bloqueia o cliente.

## O que já existe e o que falta

**Existe no repositório:** componentes de percepção e inferência local, contrato abstrato de treinamento remoto, sistemas de replay/seleção de evidências, mecanismos de validação e atualização de modelos.

**Ainda falta integrar:** adaptador Akash de submissão/monitoramento de jobs, imagem CUDA/PyTorch fixada e testada, storage persistente privado, transporte de resultados, medição de custos, e testes de ponta a ponta com uma GPU contratada. Não existe endpoint Akash operacional no projeto.

Configurações legadas de serviço que usam domínio `.invalid` são **placeholders** e não devem ser interpretadas como serviço publicado. Não substituir essas URLs por um endereço de carteira ou gateway de blockchain.

## Segurança

- Somente o operador usa Keplr, AKT/ACT e aprovação de transações; nunca distribuir a carteira/seed com o app.
- Nenhuma chave API, seed, credencial de storage ou token de usuário pode constar de código Git, manifests SDL públicos ou logs.
- Dados da partida devem ser consentidos e minimizados; usar criptografia em trânsito, controle de acesso e retenção definida.
- O treinamento na Akash é **off-chain**: o protocolo de blockchain não garante privacidade dos dados enviados ao container.

Ver também [ADR-0004](adr/0004-akash-training-backend.md) e [guia técnico da Akash](https://akash.network/docs/getting-started/console-air-onboarding/).
