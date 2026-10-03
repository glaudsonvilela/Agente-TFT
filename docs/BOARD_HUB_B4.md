# B4 — primeiro sinal visual do inventário

O objetivo completo do hub é observar unidades, posição nas células, itens
equipados e itens no inventário. O B4 inicia pela faixa visual do inventário no
layout Match001 de 1920×1080. Ele registra presença de ícones, vazio aparente e
desconhecido, sem atribuir nomes nem atualizar `GameState`.

## Evidência disponível

O ensaio B3 nos mesmos 40 JPEGs gerou 148 caixas neurais, mas nenhum item,
identidade ou ponto no chão confirmado. A inferência CPU teve p50 de 8.311,5 ms
por imagem. Esses dados não justificam integrar o detector aberto ao loop ao vivo.

No B4, a faixa da esquerda foi inspecionada nos 40 JPEGs existentes. O primeiro
espaço mostra um ícone de pilha com contador e **não é tratado como item**.
Os nove espaços seguintes têm recortes interiores fixos neste perfil. A âncora
laranja do primeiro espaço precisa aparecer antes de interpretar os demais.
O algoritmo mede apenas a fração de pixels claros no recorte interno; a faixa
entre os limites de ícone e vazio produz `unknown`.

Resultado de desenvolvimento no mesmo lote, sem rótulos independentes:

- painel localizado em 37/40 imagens; três imagens de desktop/transição
  ficaram `unavailable`;
- nos 333 espaços elegíveis: 39 `icon_candidate`, 291 `empty_appearance`,
  três `unknown`;
- `item_id` permanece `null` em todos os espaços;
- nenhum resultado é promovido a inventário semântico ou decisão.

Essas contagens medem cobertura visual **neste replay**, não precisão de item.
As mesmas imagens serviram para escolher os limites. Um novo replay e rótulos
independentes são necessários antes de declarar acurácia ou ativação.

## Uso local

```bash
python3 -m training.board_hub_inventory \
  --profile configs/ui/match001-inventory-v1.json \
  --image /caminho/para/um/frame.jpg
```

O comando exige Pillow para abrir JPEG; a função `observe` e os contratos de
teste usam somente bytes RGB. A saída é uma observação diagnóstica JSON.

## Próximos gates

1. Criar anotações verificadas de espaços/itens de um replay distinto.
2. Reconhecer o ícone pelo catálogo do set/patch, preservando `unknown` quando
   houver ambiguidade, contador ou item fora do catálogo.
3. Localizar base da unidade e validar associação à célula; identificar
   campeão e estrelas em amostras independentes.
4. Detectar os ícones equipados e associá-los à mesma instância de unidade.
5. Confirmar temporalmente a transição inventário → unidade antes de preencher
   `GameState` e liberar recomendações de item/posicionamento.
