# riot-api-inspect

CLI para testar a integração oficial Riot no Ubuntu, sem precisar ter TFT instalado.

## Uso

```bash
export RIOT_API_KEY='RGAPI-...'

cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-riot-api-inspect -- \
  "Seu Game Name" BR1 5
```

A saída mostra:

- conta resolvida por Riot ID;
- fingerprint do PUUID;
- roteamento usado;
- se existe partida TFT ativa;
- metadados básicos da sessão ativa;
- últimos IDs de partidas.

A API key nunca é impressa e o PUUID completo também não.

Development API keys da Riot expiram regularmente; erro de autenticação é reportado de forma curta.
