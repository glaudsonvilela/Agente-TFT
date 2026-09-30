# riot-api

Cliente Rust para as fontes oficiais Riot usadas pelo Agente TFT.

## Rotas iniciais

- partida TFT ativa:
  `/lol/spectator/tft/v5/active-games/by-puuid/{puuid}`
- IDs de partidas:
  `/tft/match/v1/matches/by-puuid/{puuid}/ids`
- detalhe de partida:
  `/tft/match/v1/matches/{matchId}`

Para Brasil, o default é:

```text
platform = BR1
regional = AMERICAS
```

## Engenharia

- `reqwest::Client` reutilizado para connection pooling;
- timeout curto configurável;
- TCP keepalive;
- `X-Riot-Token` nunca é incluído em erros/logs;
- 404 de spectator vira `Ok(None)`;
- 429 vira erro tipado com `Retry-After`;
- contagem de histórico limitada a 1–100.

## Papel no projeto

A API complementa a percepção, mas não substitui o estado visual fino da partida. O `StateFusion` continuará distinguindo origem e confiança de cada campo.
