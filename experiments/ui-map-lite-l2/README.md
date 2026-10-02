# UI-Map Lite L2 — localização espacial e avaliação pareada

Experimento local complementar ao Agente TFT. **Não ativa mapas nos leitores.**
Não modifica o L1, B1/B2/B3, S4, Tesseract, catálogos, pesos estratégicos ou bancos A14–A16.

## Mudança funcional

O L1 usava uma cabeça densa global. O L2 gera quatro mapas espaciais de 80×48:
canto superior esquerdo/inferior direito do envelope do banco e da loja. Uma expectativa
espacial normalizada converte os mapas em coordenadas. Duas saídas estimam visibilidade.
Não há texto, categorias de campeões nem modelo pré-treinado. Entrada RGB 320×192.
A arquitetura tem **27.726 parâmetros treináveis**, versus 192.778 do L1.

Cada coordenada é representada dentro da imagem. Ordem e tamanho continuam sendo
verificados: não ordenar cantos invertidos nem prender caixas erradas à borda. As
saídas são envelopes de desenvolvimento, **não pontos de contato dos campeões nem
marcos semânticos universais da interface**.

## Uma decisão para teste e execução

`common.decisions` é usado pela avaliação, visor e runtime. O relatório distingue:
`visibility_above_threshold`, `geometry_valid`, `accepted_as_coarse` e os campos de
uso (`map_usable_by_readers=false`, `narrow_ocr_crop_safe=false`).
`accepted_visible/accepted_hidden` exigem visibilidade **e** geometria. A métrica antiga
L1 apenas por visibilidade não é reinterpretada como aceite de produção.

O limiar de visibilidade anterior foi preservado, não calibrado estatisticamente.
Não ajustamos os limiares para transformar o lote de teste em aprovação.

## Dados e comparação

`configs/plan.json` fixa 10 imagens-fonte de treino, 2 de validação e 4 de teste,
todas da MESMA gravação. Todas as sementes têm SHA-256; arquivos e bytes não podem
se repetir entre divisões. Os 300.000 ms usados como teste no L1 continuam fora do
treino L2. As regiões originais são as mesmas sementes do L1, não verdade independente.

65% dos exemplos usam transformação da cena inteira; os demais usam recortes com
contexto/contorno suavizado. Oclusões e cortes são gerados explicitamente. O treino
usa renderização reduzida e o teste renderização nativa seguida de redução; essa
diferença de reamostragem é deliberadamente registrada. A transformação da cena inteira
reduz o atalho de costuras, mas ambos os grupos continuam artificiais. Nenhum resultado
prova precisão em interfaces naturalmente modificadas. Todas as imagens naturais
recebem propostas sem rótulo de correção.

Treinamento limitado a 1.400 passos, batch 12, duas threads. Seleção apenas pela
validação. Depois de congelar os pesos, avalia 192 exemplos gerados com 4 fontes de
teste. O **mesmo conjunto de pixels** vai a:

- modelo L1 já treinado e preservado;
- L2 espacial;
- L2 espacial com refinamento;
- mapa fixo, como referência não adaptativa.

As métricas são separadas por distribuição (`whole_scene` / `context_paste`). Não
comparamos diretamente estes erros com os números históricos em outra distribuição.
O L1 não é retreinado. Esse teste mede uma arquitetura + dados novos, não uma ablação
que isola exclusivamente o efeito da arquitetura.

## Refinamento local limitado

`refine.py` procura bordas na imagem RGB original, em até 12 px de cada lado proposto,
com suporte, separação de picos e limite de mudança do tamanho. Não recebe alvos,
números de OCR ou coordenadas corretas do teste. Só aplica quando os quatro lados
passam. Caso contrário, mantém a proposta aproximada e registra a causa.

Uma borda visual pode ser decoração, não borda do painel. O relatório mede melhoras
E pioras após o refinamento; não escolhe retroativamente o resultado mais próximo do
alvo. O refinamento não autoriza um mapa e não força a recuperação de caixas ruins.

## Execução no SSD

```
bash AGENTE_TFT_UI_MAP_LITE_L2_INSTALAR.sh
```

O instalador autocontido verifica a montagem ext4 pelo helper PR30 e UUID confirmado.
Destino padrão: `/mnt/sherlock-ssd/Agente-TFT/ui-map-lite-l2`.
Reutiliza o PyTorch do B3 e ONNX/ORT do L1 **sem instalar ou atualizar pacotes**.
Requer os dois ambientes existentes e a mesma ABI Python.

O último L1 completo é escolhido pela data do diretório, nunca pelo seu resultado.
A linha `LITE2_BASELINE` mostra a seleção. Pode-se indicar explicitamente:

```
UI_MAP_L1_RUN="/caminho/do/L1/run" bash AGENTE_TFT_UI_MAP_LITE_L2_INSTALAR.sh
```

Os arquivos da referência precisam passar pelo selo do L1; uma referência corrompida
não é ignorada em favor de outra. O L2 registra os hashes de código, entradas e pesos,
verifica-os ao final e utiliza diretórios novos. Interrupções retêm evidências e não
retentam infinitamente. Não há exclusão, formatação, alteração de fstab ou sudo.

O script executa a revisão estrutural do clone existente e os testes L2; os
apontamentos históricos não são dados como resolvidos. Exporta ONNX opset 17 e exige
16 comparações numéricas PyTorch/ONNX. Um processo separado sem Torch processa os 40
originais e mede 120 forwards percorrendo todos eles após aquecimento. O preparo de
imagem, decisão/refinamento e tempo total são medidos separadamente. Não é captura
contínua, 120 imagens independentes ou integração Rust.

Saídas: `LITE2_SUMMARY`, `LITE2_RUNTIME_SUMMARY`, `LITE2_COMPARISON`, `LITE2_VIEWER`.
Enviar `comparison.txt`. Detalhes, pesos, modelo, histórico, seeds, visor e selos ficam
no SSD. `FAILED.json` ou erro de exportação não significa modelo promovido.

## Estado e continuidade

Modelo treinável e avaliado; sem aprendizado online, adaptação a patches garantida,
serviço de servidor ou ligação nativa Rust. O passo posterior depende da precisão:
melhorar os dados/referências antes de ativar o mapa, depois integrar frame compartilhado,
coleta controlada, treino de candidatas e ativação/reversão. Não renomear uma inferência
como aprendizado contínuo.

O arquivo `UI_MAP_LITE_L2_GIT.patch` acrescenta somente
`experiments/ui-map-lite-l2/` para publicação posterior; não foi aplicado automaticamente.
A biblioteca `legacy_l1` é uma cópia congelada de cinco arquivos do pacote L1, usada
somente para reproduzir seu modelo. O runtime L2 não a importa.

Referências técnicas de exportação (consultadas na implementação):
- https://docs.pytorch.org/docs/stable/onnx.html
- https://onnxruntime.ai/docs/performance/tune-performance/threading.html

Detalhes da execução local e limitações: `VALIDACAO_LOCAL_UI_MAP_LITE_L2.json`.
