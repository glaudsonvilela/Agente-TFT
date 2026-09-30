# Project Scope — Agente TFT

## Missão

Construir um **coach estratégico local de Teamfight Tactics** capaz de observar o estado disponível da partida, manter memória temporal do lobby, avaliar alternativas e apresentar uma recomendação curta e acionável.

O produto não é um chatbot genérico de TFT. É um **motor de decisão que consegue conversar**.

## Contrato de saída

Toda recomendação no modo de partida deve seguir esta ordem:

1. **AÇÃO** — o que fazer agora;
2. **MOTIVO** — uma frase curta;
3. **PARADA / PRÓXIMO PASSO** — quando interromper ou reavaliar;
4. **CONFIANÇA** — derivada dos dados/modelos, nunca inventada pelo LLM.

Exemplo:

```text
ROLE 18–22G AGORA

Player 2 começou a contestar sua carry.
Busque X 2★ e pare.

Confiança: 84%
```

## Decisões-alvo

- BUY / SKIP;
- SELL;
- ROLL por orçamento;
- ROLL até condição de parada;
- LEVEL agora / depois;
- HOLD ECON;
- EQUIP / HOLD ITEM;
- AUGMENT choice;
- PIVOT / PARTIAL PIVOT;
- POSITIONING;
- SCOUT target;
- abandonar unidade 3★ quando a contestação tornar a linha ruim.

## Não objetivos iniciais

- automação de mouse/teclado;
- injeção no processo do jogo;
- leitura de memória do cliente;
- bypass de mecanismos anti-cheat;
- LLM calculando probabilidades sem ferramenta determinística;
- arquitetura multiagente complexa antes de existir um GameState confiável.

## Princípios

- **Estado antes de estratégia.**
- **Cálculo antes de linguagem.**
- **Eventos antes de polling pesado.**
- **Confiança explícita.**
- **Patch-aware por padrão.**
- **Replay/laboratório como ambiente principal de P&D.**
