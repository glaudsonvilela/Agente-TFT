# HUD Mapper HM3 Runtime

HM3 é o executável leve usado durante a sessão. O objetivo principal é ver e mapear a HUD ao vivo, coletar exemplos naturais e medir o custo do caminho. Replay e treinamento não fazem parte deste executável.

## Uso

Escolha explicitamente um monitor ou janela no HM3. A opção Detectar TFT usa somente o título visível como sugestão. Selecione o deployment-candidate.json L2/L3 e mantenha candidate-model.onnx da mesma execução ao lado. Escolha uma pasta de resultados e inicie.

A aba HUD ao vivo / geometria alterna entre captura bruta, mapa neural com geometria e leituras/OCR. A imagem, os recortes e as caixas exibidos pertencem ao mesmo frame_id. Clique em uma região para inspecionar o recorte original e a proveniência. Congelar a inspeção não pausa a coleta.

## Performance

O hot path trabalha em memória: captura Rust residente -> RGB -> filas latest -> ONNX/leitores -> UI. PNGs e recortes são persistência assíncrona, amostrada e limitada.

A rede e os leitores têm filas de capacidade 1; a captura não espera OCR. Resolução diferente de 1920x1080 é recusada pelos leitores Match001 antes de chamar OCR. Em 1920x1080, uma leitura pode ser reutilizada somente quando o frame RGB completo é byte a byte idêntico, a geometria não mudou e o dado original tem no máximo 750 ms. Não se usam recortes aproximados como prova de que todos os leitores receberiam os mesmos pixels. A origem e a idade do resultado ficam explícitas. B1 permanece fora desse cache. No padrão de leitura de 1 Hz, a janela de 750 ms normalmente já expirou; isso não promete eliminar o custo do OCR.

O empacotamento preserva as DLLs privadas junto do Tesseract, remove apenas cópias idênticas sem outro importador PE e exclui dados de teste do ONNX. A cópia compactada é novamente executada nos testes Windows, inclusive OCR com PATH restrito, instalação e prévia.

A aba Performance mostra frames, substituições de fila, inferência ONNX, leitores, cache exato, métricas da captura e amostras salvas.

## Escopo neural e limites

A rede L2/L3 continua especializada nos envelopes de banco e loja. Ouro, nível, XP, stage, HP, loja e controles usam os leitores existentes. Itens, augments, identidade/estrelas e células de chão não são inventados: permanecem não estabelecidos enquanto não houver observação validada.

A captura usa nosso processo Rust para enumeração, buffers D3D11, readback, conversão e transporte, sobre Windows.Graphics.Capture. Não usa PrintScreen, Ferramenta de Captura, OBS, FFmpeg, driver próprio, injeção, memória do jogo ou input automation. Isso não é uma promessa de aprovação Riot/Vanguard.

Comece em SDR e 1920x1080 para os perfis atuais. Outros cenários são úteis para coleta, mas não recebem escala inventada.

## Entrega leve

O runtime não contém FFmpeg, replay, PyTorch ou treinador. São gerados:

- AgenteTFT-HUD-HM3-Runtime-Windows-x64.zip — pacote portátil.
- AgenteTFT-HUD-HM3-Setup.exe — instalador por usuário com compressão LZMA2.
- HM3_PACKAGE_REPORT.json — tamanhos e hashes.

O treinamento permanece separado e é executado após a sessão, nunca durante o mapeamento.
