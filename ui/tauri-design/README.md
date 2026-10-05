# Agente TFT — proposta de interface Tauri

Protótipo navegável de design. Não executa captura, inferência, conexão com BigBANANA nem instalação. Dados ilustrativos aparecem identificados. O instalador representa estados e não reinicia o computador.

## Abrir

Na raiz do repositório:

```sh
python3 -m http.server 4178 --bind 127.0.0.1 --directory ui/tauri-design
```

- Estúdio: http://127.0.0.1:4178/
- Mapa: http://127.0.0.1:4178/#map
- Instalador independente: http://127.0.0.1:4178/?installer=1#installer
- Apresentação sem limite vertical: http://127.0.0.1:4178/?presentation=1#studio

## Mapa de telas

| Tela | Função |
| --- | --- |
| Estúdio | Seleção de fonte, prévia, formação e coach sempre acessível |
| Tabuleiro | Posições, banco e inventário separados |
| Catálogo | Campeões e itens com busca e detalhes |
| Simulador | Alternativas e execuções identificadas |
| Aprendizado | Dataset, treino, validação, revisão e promoção |
| Histórico | Decisão, contexto e explicação |
| Preferências | Movimento, foco, voz e identidade |
| Mapa | Navegação e arquitetura proposta |

O instalador tem boas-vindas, verificação, download, configuração, reinício e conclusão. Os controles de erro e retomada são demonstrações. Na implementação, o progresso deverá vir do serviço de instalação, com retomada persistente após reinício e mensagens específicas para cada falha.

## Identidade aprovada

Pengu estrategista, com elmo prateado, capa azul e peça hexagonal violeta. O usuário aprovou a nova pose. `assets/agente-pengu.png` é a arte mestre com transparência; `icons/icon.ico` é o ícone Windows, acompanhado de PNGs e ICNS. Prompt e origem em `assets/LOGO-PROVENANCE.txt`.

Paleta: Obsidian #14151d, Surface #242632, Violet #9984ff, Mint #7fe0bc e Gold #ddbd7d. Tipografia Manrope local. Superfícies escuras, contraste hierárquico, destaque violeta nas ações e dourado na economia. Animações de entrada, órbita e mascote respeitam movimento reduzido e a preferência manual.

## Integração prevista

- Rust no Windows: captura, redução da prévia, apresentação e controles locais.
- Tauri: navegação, coach, estado dos serviços e preferências.
- Motor local/BigBANANA: decisões e experimentos com versão, tempo da observação e confiança rastreáveis.

Manter a prévia independente da análise. Fila limitada ao quadro mais recente, descarte de quadros antigos, métricas de captura e apresentação separadas. Não transportar vídeo como eventos JSON. Avaliar transporte binário/canal ou superfície nativa, medindo cópias e latência no Windows antes de escolher. Atualizar métricas visuais em frequência baixa; animações decorativas devem pausar em segundo plano. Esta prévia não comprova FPS ou consumo do aplicativo final.

Geometria do tabuleiro, HP e ouro ficam separados dos catálogos versionados por patch. O relatório de 10 mil cenários trata de recursos e não de partidas completas. O gráfico de aprendizado é ilustrativo. A amostra F1 é histórica, não uma integração de voz ao vivo.

## Assets e créditos

Artes de campeões e itens: Riot Data Dragon, catálogo já fixado pelo projeto. Pengu: Riot Games / League of Legends Wiki. URLs e hashes em `assets/sources.json`; Manrope sob OFL em `assets/FONT-LICENSE.txt`.

Amostra F1: pacote anterior do projeto, `HM45_REPLAY_F1.wav`, release `hm45-lab-0.6.1-20261004` no GitHub. Os logos oficiais de TFT em `assets/tft-*.png` são referências originais e não são carregados na interface devido ao tamanho de suas telas transparentes.

O exportador de ícones usa Pillow somente durante desenvolvimento. A interface não depende de Python, Pillow ou serviços externos para navegar. Abrir a prévia não altera a instalação HM4.5 existente.

Referências técnicas: https://v2.tauri.app/start/frontend/ e https://v2.tauri.app/develop/calling-frontend/.
