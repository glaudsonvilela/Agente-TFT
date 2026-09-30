# meta-context

Contexto estatístico externo para o Opportunity Engine.

Fontes possíveis:

- MetaTFT;
- estatísticas próprias;
- outras fontes permitidas/importadas.

Princípios:

- contexto externo é **prior**, não decisão;
- snapshot tem provenance, URL e timestamp;
- patch/set mismatch é ignorado por padrão;
- dados stale são ignorados;
- influência externa tem limite absoluto configurável;
- métricas externas nunca substituem GameState, TFT Math ou scouting observado.

Exemplo:

```text
MetaTFT:
comp X avg place 3.8

Partida:
3 jogadores contestando X

Opportunity Engine:
meta_prior +0.06
contest_penalty -0.42
→ linha pode continuar ruim
```
