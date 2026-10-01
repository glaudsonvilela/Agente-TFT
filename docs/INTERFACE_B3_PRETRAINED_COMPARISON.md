# B3 — B1 versus detector visual pré-treinado, com comparação automática

## Pedido e base

O usuário solicitou testar o detector visual em conjunto com a referência B1 e receber somente os resultados comparativos. B2 geométrico já existe no main `e0ff8427a2b088d935b3acc325d615d9f015837a`; permanece intocado. Esta entrega tem outro identificador para não sobrescrever B2 ou confundir os experimentos. S4 continua referência de desenvolvimento da loja; S5 experimental. HP continua com seus bloqueios.

## Detector real, não outro nome para as heurísticas B1

Grounding DINO tiny, `IDEA-Research/grounding-dino-tiny`, revisão imutável `478dad0f5e1ad32707ddb2216e4a96a821277167`. Pesos Safetensors SHA-256 `1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3`, aproximadamente 689 MB. Fonte do autor, modelo de detecção de vocabulário aberto; a model card indica Apache-2.0. Não é um modelo ajustado/validado para TFT.

Prompt congelado: `a video game character. a creature. a game piece.`. Um forward por imagem sobre o mesmo `scan_rect` B1; a área inclui banco e tabuleiro. Não depende de B1 encontrar barras ou corresponder à arena. Não consulta prelabels, campeão esperado, item, HP, timestamps ou contagens para escolher respostas. Sem busca retrospectiva de prompts/limiares, sem treinamento e sem substituição automática da referência.

O teste roda localmente em Python/PyTorch CPU, quatro threads, sem CUDA, ONNX ou integração por frame com o Rust. Isso é laboratório de adequação antes de uma integração otimizada, NÃO uma promessa de tempo real. Os pesos públicos são baixados uma vez; nenhuma imagem é enviada a um provedor. Somente arquivos de dados explicitamente permitidos são baixados da revisão fixada; nenhum `.bin`/pickle ou Python remoto. Na inferência, `local_files_only=True`, `trust_remote_code=False`, `use_safetensors=True`; kernels personalizados estão desativados.

## Comparação que realmente fazemos

1. Verificar os selos/hash do relatório B1, manifesto e perfil; exigir exatamente o mesmo conjunto de imagens/timestamps, incluindo imagens sem HUD.
2. Exigir o executável B1 original por SHA-256, sem recompilação nem sobrescrita.
3. Executar novamente esse binário e comparar TODO o bloco `read` de cada frame com B1 histórico. Qualquer diferença impede continuar.
4. Carregar o modelo real e inferir em cada imagem, decodificada pelo mesmo comando FFmpeg usado no B1. As imagens são decodificadas separadamente nos dois caminhos; NÃO alegamos compartilhar um único tensor decodificado com o binário B1. Registrar o hash RGB usado pelo novo detector.
5. Guardar caixas, escores brutos, frases, recorte, supressões NMS e relações espaciais com barras/espaços B1. Os escores não são probabilidades calibradas de acerto no TFT.
6. Gerar relatório, eventos por frame, comparação compacta e HTML com os dois resultados sobrepostos. Verificar novamente fontes e pesos antes de selar.

B1 gera barras; o modelo gera caixas de objetos. Esses alvos não são equivalentes. A comparação mede coocorrência espacial, propostas exclusivas, conflitos potenciais com a referência vazia, disponibilidade e custo. NÃO calcula acurácia, falsos positivos/negativos ou vencedor sem referência independente. Uma barra pode ficar acima da caixa corporal; não haver sobreposição não prova erro. Uma caixa pode intersectar vários espaços do banco; isso NÃO conta como várias unidades. Nada é alocado a uma célula pelo centro ou ponto inferior da caixa. `occupancy` e identidade continuam desconhecidos no comparativo. Detectar zero caixas não significa banco vazio.

A avaliação não usa o B1 como rótulo. Não alega que o modelo supera B1 por retornar mais caixas. A recomendação inicial é manter em shadow; resultado ruim também é um resultado válido de adequação.

## Execução única

```bash
bash scripts/probe_match001_board_detector.sh \
  "telemetry/data/match-001-board-b1.BlHCOHWx"
```

Antes de downloads, faz o preflight do B1. Cria ambiente Python isolado em `telemetry/data/board3-runtime/venv`, com versões explícitas, PyTorch CPU separado do índice oficial. Não modifica Python global, ambiente do agente, bancos A14–A16 ou binários. O primeiro setup baixa dependências e pesos (mais que os 689 MB do modelo sozinho). Exige 4 GiB de disco e 3 GiB de memória disponível; esses mínimos não garantem performance. Timeout de 30 min para setup, 60 min para o experimento e 180 s para a releitura B1. Uma execução B3 por vez. Após interrupção não publica COMPLETE nem promove resultados parciais.

Saída exclusiva `telemetry/data/match-001-board-b3.XXXXXXXX/run/`:
- `report.json`: resultado completo e proveniência;
- `comparison.txt`: resumo pronto para enviar;
- `events.jsonl`: frames processados, preservados se houver interrupção;
- `viewer.html`: original, barras B1 e caixas neurais, sem servidor/CDN;
- `model.json`, `manifest.json`, `detector-policy.json`, `regression.json` e `COMPLETE.json`;
- `FAILED.json` em falha após início do processamento, sem afirmar conclusão.

Imagens/pré-labels não saem do computador. O modelo não é retreinado na execução. Tesseract continua no projeto para texto, mas NÃO é executado novamente: o teste atual compara duas fontes de presença, não dois reconhecedores de texto. Loja/HP permanecem inalterados.

## Revisão e testes

24 testes de contratos Python rodam sem modelos/downloads: pin, prompt, limiares, caixas inválidas, NMS, orçamento, ausência diferente de vazio, sobreposição diferente de identidade, comparação integral B1, agregados e nenhuma promoção. A revisão semântica cobre os arquivos novos e integrações; a revisão estrutural existente roda na árvore inteira. Os 22 apontamentos históricos não são declarados resolvidos.

Workflow separado `Board detector pretrained` instala o mesmo ambiente do comando, compila o B1 para teste, cria PNGs sintéticos, gera um relatório B1 real e executa a comparação com pesos reais do Grounding DINO. Verifica carregamento, forward, hashes, ausência de Tesseract, relatório/visor, preservação B1 e rejeição de imagem alterada. Não usa resultado de mocks para declarar inferência neural nem métricas semânticas. O CI geral continua sem necessidade de baixar modelos.

No ambiente de edição não há acesso DNS à internet, nem Transformers ou os pesos instalados. Os testes locais não equivalem ao teste nativo. Resultado real do workflow será registrado no PR. A medição nos 40 JPEGs do usuário continua pendente, sem estimar previamente quantas unidades serão encontradas.

## Geometria/3D

A ideia do usuário foi preservada como etapa futura: projeção do plano do tabuleiro e ponto de apoio estimado podem complementar a percepção visual. B3 não reconstrói profundidade ou malhas 3D. Não altera a geometria para melhorar retroativamente o comparativo. Depois da medição, decidir entre adaptar/treinar um detector, integrar geometria ou rejeitar esta candidata. Identidades sazonais, estrelas, itens, atributos e estado integrado seguem no plano local; BigBANANA e vídeos externos continuam adiados.

## Referências técnicas

- Autor/modelo: https://huggingface.co/IDEA-Research/grounding-dino-tiny/tree/478dad0f5e1ad32707ddb2216e4a96a821277167
- Pesos/checksum: https://huggingface.co/IDEA-Research/grounding-dino-tiny/blob/478dad0f5e1ad32707ddb2216e4a96a821277167/model.safetensors
- API Transformers: https://huggingface.co/docs/transformers/v4.57.1/model_doc/grounding-dino
- PyTorch CPU: https://pytorch.org/get-started/previous-versions/
