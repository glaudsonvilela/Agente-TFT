# visual-match

Classificador visual local e leve para prototipar reconhecimento de campeões/itens.

Ele reduz uma imagem a um descritor normalizado e compara templates por similaridade de cosseno.

Importante:

- `similarity` e `margin` são **scores crus**, não probabilidades;
- o crate não inventa `Confidence`;
- calibração estatística deve ser feita depois em dataset real;
- um modelo ONNX poderá substituir esse backend sem alterar o contrato superior.

Uso previsto:

```text
CommunityDragon portrait
       ↓
descriptor index

shop slot / board crop
       ↓
descriptor
       ↓
top-1 + top-2 + margin
       ↓
calibration/gate
       ↓
unit_id
```
