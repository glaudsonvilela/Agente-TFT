# configs/roi

Perfis de regiões do TFT ficam aqui quando forem calibrados com screenshots/vídeos reais.

Não versionar coordenadas “estimadas”. Cada perfil deve informar:

- resolução de referência;
- escala da UI quando conhecida;
- versão do perfil;
- todas as ROIs;
- thresholds de mudança;
- origem/fixture usada para validação.

Exemplo de estrutura:

```json
{
  "profile_version": 1,
  "name": "nome-do-perfil",
  "reference_width": 1920,
  "reference_height": 1080,
  "rois": []
}
```

O array vazio acima é apenas um esqueleto e **não é um perfil operacional**.
