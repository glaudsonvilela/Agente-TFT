# Agente TFT — inferência local + aprendizado central no BigBANANA

## Decisão oficial

A rede neural **continua no software instalado** para inferência rápida durante a
partida. O servidor BigBANANA é o centro de aprendizado: recebe evidências das
partidas, melhora a rede, valida challengers e publica novas versões aprovadas
para os clientes.

O objetivo é não depender da CPU/GPU do computador de cada usuário para a IA se
autoaperfeiçoar, sem sacrificar latência nem exigir internet para cada inferência.

## Durante a partida

```
TFT no Windows
      ↓
captura local
      ↓
rede neural aprovada instalada localmente
      ↓
GameState / coach / HUD
```

Os pesos ficam congelados enquanto a partida está acontecendo.

Se o servidor estiver temporariamente indisponível, o software continua usando a
última versão aprovada já instalada.

## Depois da partida

```
sessão local selada
      ↓
upload resumível de evidências
      ↓
BigBANANA
      ↓
supervisão autônoma
gold / silver / quarantine
      ↓
treino central de challenger
      ↓
validação contra champion
      ↓
shadow / holdout
      ↓
modelo aprovado e versionado
```

O treinamento pesado acontece no servidor, não no PC do usuário.

## Distribuição de uma rede melhor

```
BigBANANA publica manifest do champion
      ↓
software consulta atualização fora da partida
      ↓
compara versão/hash
      ↓
baixa pacote do novo modelo
      ↓
verifica SHA-256 + metadados
      ↓
instala atomicamente
      ↓
nova partida usa o novo champion local
```

A troca de modelo nunca acontece no meio da partida.

O software guarda a versão anterior aprovada para rollback caso o novo pacote
falhe na inicialização ou nos checks locais.

## Cliente Windows / Linux local

Continua responsável por:

- captura;
- inferência neural local;
- OCR e geometria;
- HUD/coach;
- memória curta da partida;
- gravação/selagem das evidências;
- upload pós-partida;
- atualização segura do modelo aprovado.

Não é responsável por:

- treinamento pesado;
- seleção de challenger global;
- dataset global;
- promoção definitiva do modelo.

## BigBANANA

É responsável por:

- dataset central de partidas;
- provenance e deduplicação;
- auto-supervisão;
- treinamento de challengers;
- validação e shadow;
- registro do champion;
- publicação do pacote de modelo aprovado;
- histórico de versões e rollback.

## Regra de segurança

Predição do modelo nunca se transforma sozinha em verdade de treino. Continuam
valendo os gates gold/silver/quarantine já definidos no projeto.

## Benefício

Quanto mais instalações jogarem e enviarem partidas válidas, mais material o
BigBANANA recebe para melhorar o modelo central. Depois de aprovada, a nova rede
é distribuída para todas as instalações sem exigir que cada PC faça treinamento.


## Atualização automática sem interação

O jogador não precisa aprovar atualização de rede neural.

O cliente consulta o BigBANANA automaticamente ao iniciar e novamente após cada
partida concluída. Se houver um champion aprovado mais novo:

1. baixa o pacote em segundo plano;
2. valida versão, compatibilidade e SHA-256;
3. mantém a partida atual usando o modelo já carregado;
4. ativa o novo modelo somente quando o cliente estiver ocioso;
5. realiza troca atômica;
6. preserva as duas versões anteriores;
7. se o novo modelo falhar ao carregar ou no health-check inicial, faz rollback
   automático para o último champion válido.

Sem internet, o software continua funcionando com o último modelo aprovado já
instalado.

Não existe botão "Atualizar IA" no caminho normal do jogador.
