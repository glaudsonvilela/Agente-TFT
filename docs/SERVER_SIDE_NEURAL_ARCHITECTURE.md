# Agente TFT — arquitetura neural no servidor

## Decisão

A rede neural não é parte do software Windows e não é hospedada no WSL local.

O Windows é um cliente leve de captura e interface. O servidor é a autoridade
para inferência neural, memória de aprendizado, treinamento, challengers e
promoção de modelos.

## Cliente Windows

Responsabilidades permitidas:

- captura autorizada da tela/janela do TFT;
- prévia local e HUD;
- OCR/leitores não neurais quando úteis;
- telemetria;
- buffer local limitado;
- geração de sessão selada após a partida;
- transporte autenticado de frames/ROIs e evidências;
- exibição de GameState, recomendações e estado do learner recebidos do servidor.

O cliente não deve conter:

- pesos do reconhecedor de campeões;
- encoder DINO;
- trainer neural;
- challenger weights;
- lógica de promoção de modelo;
- dataset principal de treinamento.

## Servidor

O servidor mantém:

- champion neural ativo;
- DINO/encoder e heads;
- inferência de percepção;
- memória temporal;
- supervisão autônoma gold/silver/quarantine;
- dataset acumulado;
- treinamento pós-partida;
- comparação challenger x champion;
- shadow candidates;
- histórico de métricas e proveniência;
- posteriormente, simulador e policy/value ranking.

## Fluxo durante a partida

```
Windows capture
      |
      v
ROI/frame scheduler
      |
      v
authenticated transport
      |
      v
SERVER neural inference
      |
      v
structured GameState / recommendation
      |
      v
Windows HUD
```

Nenhum treinamento acontece durante a partida.

## Fluxo depois da partida

```
sealed Windows session
      |
      v
upload resumível + hashes
      |
      v
server autonomous supervision
      |
      v
gold / silver / quarantine
      |
      v
server challenger training
      |
      v
frozen validation
      |
      +--> worse/tie -> discard
      |
      +--> better -> shadow candidate
```

## Segurança de promoção

Um challenger não substitui o modelo ativo só porque venceu uma única partida
ou uma única validação. O servidor registra o candidato em shadow e exige os
gates independentes do projeto antes de promoção.

## WSL local

O WSL pode continuar existindo como ferramenta de compatibilidade/transportes
ou para componentes não neurais, mas não é a residência da rede neural nem do
trainer.

## Regra permanente

Novos recursos neurais devem ser implementados primeiro no servidor. O cliente
Windows deve permanecer pequeno, atualizável e sem pesos neurais proprietários.
