# ADR-0001 — Runtime híbrido Rust + Python/PydanticAI

**Status:** Accepted  
**Date:** 2026-09-30

## Contexto

O projeto precisa combinar captura/visão de baixa latência, matemática determinística, modelos treináveis e uma camada de agente flexível.

## Decisão

Usar:

- **Rust** no caminho crítico e em serviços de estado/eventos;
- **Python** para treinamento e PydanticAI-slim;
- **ONNX** como formato preferencial para inferência de modelos em produção;
- **Tauri/Svelte** para UI desktop.

## Consequências positivas

- latência e uso de memória previsíveis no runtime;
- ecossistema de ML completo no treino;
- LLM fora do caminho crítico;
- modelos substituíveis;
- fronteiras testáveis.

## Trade-offs

- IPC entre processos;
- schemas precisam ser versionados;
- build/release envolve mais de uma toolchain.

## Rejeitado por enquanto

- Python puro no runtime inteiro;
- Rust puro para todo o treinamento/visão;
- framework de agente pesado como núcleo do aplicativo.
