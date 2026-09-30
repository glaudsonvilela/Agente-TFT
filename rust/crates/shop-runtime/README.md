# shop-runtime

Liga percepção da loja ao `StateFusion`.

Proteção principal: **snapshot parcial não entra no GameState**.

```text
frame
 ↓
perception-shop
 ↓
5/5 slots reconhecidos e calibrados?
 ├─ não → diagnóstico apenas
 └─ sim
      ↓
 temporal consensus
      ↓
 GameState.shop
      ↓
 ShopChanged
```

Isso impede que um slot incerto seja interpretado como ausência de unidade ou como mudança real da loja.
