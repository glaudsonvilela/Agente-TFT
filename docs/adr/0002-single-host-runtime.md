# ADR-0002 — Runtime local single-host como topologia canônica

**Status:** Accepted  
**Date:** 2026-09-30

## Contexto

Foram considerados modos portáteis, armazenamento externo e execução em segundo computador. O projeto seguirá no mesmo PC do jogo durante desenvolvimento e operação local.

## Decisão

A topologia canônica será **single-host local**:

- Windows 10/11 no PC principal;
- Agente TFT executado como aplicação normal de usuário;
- inicialização opcional no login via mecanismo padrão do Windows;
- detecção da janela/processo do TFT apenas para ativar o modo de observação;
- captura de tela por APIs normais do sistema;
- sem injeção, leitura de memória do jogo, driver próprio ou técnicas de ocultação;
- sem dependência de pendrive, drive externo ou segundo computador.

## Consequências

- instalação e atualização mais simples;
- telemetria, Knowledge Pack e modelos permanecem no armazenamento local padrão;
- caminho de captura fica desacoplado do restante do sistema para permitir mudanças futuras sem alterar GameState/Policy/Agent;
- comportamento de inicialização deve ser visível, desativável e auditável.
