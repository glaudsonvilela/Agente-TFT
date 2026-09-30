# ADR-0002 — Ubuntu para desenvolvimento; Windows como runtime live

**Status:** Accepted  
**Date:** 2026-09-30

## Contexto

O desenvolvimento atual acontece em Ubuntu, onde o TFT para PC não está instalado. O runtime final de observação durante uma partida de TFT no PC será validado em Windows.

O projeto continua sendo **single-host no runtime final**: TFT e Agente TFT no mesmo PC Windows. Não há dependência de pendrive, drive externo, segundo computador ou máquina virtual.

## Decisão

Separar explicitamente dois ambientes.

### Development Host — Ubuntu

Usado para:

- contratos e core Rust;
- PydanticAI-slim;
- Riot/Data Dragon/CommunityDragon ingestion;
- Knowledge Pack;
- TFT Math;
- simulador e self-play;
- treinamento PyTorch;
- export ONNX;
- visão usando screenshots, vídeos e replays;
- UI e telemetria;
- testes unitários, golden e replay.

### Live Runtime Target — Windows

Usado posteriormente para:

- captura da janela do TFT;
- detecção de janela/processo;
- calibração de ROIs em resolução real;
- medição end-to-end durante uma partida;
- validação de compatibilidade operacional.

## Capture abstraction

O restante do sistema não pode depender de uma API específica do Windows.

A camada de captura expõe uma interface comum:

```text
CaptureSource
├── ReplayVideoSource      # Ubuntu/Windows
├── StaticFrameSource      # testes/golden
├── DesktopSource          # desenvolvimento visual
└── WindowsTftSource       # runtime live
```

Todas produzem o mesmo `FrameEnvelope`, então percepção, GameState, eventos, policy e agente permanecem idênticos.

## Restrições

- sem VM como dependência para executar TFT/Vanguard;
- sem injeção;
- sem leitura de memória do jogo;
- sem driver próprio;
- sem tentativa de ocultar processo;
- sem acoplamento do core a Win32.

## Consequências

- podemos desenvolver a maior parte do sistema integralmente em Ubuntu;
- replay torna os testes determinísticos;
- CI pode compilar/testar componentes multiplataforma;
- Windows entra apenas onde é tecnicamente necessário;
- nenhum redesign será necessário quando migrarmos da fonte replay para captura live.
