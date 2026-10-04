# Mapa do simulador TFT

Inventário integral do catálogo disponível. Regras pendentes continuam explícitas.

**Não comprova cobertura integral do jogo, treino de partidas completas ou prontidão do coach.**

Patch do pacote: 18.3. Catálogo de itens global; pertencimento ao set ainda não confirmado.

## Sistemas e contratos

| Sistema | Camada | Estado | O que falta |
|---|---|---|---|
| Tabuleiro, banco e coordenadas | núcleo | candidato | Calibrar cada layout/resolução, observação versus tabuleiro próprio |
| Tela → estado observado | percepção | parcial | Ground truth independente; Confiança/calibração por campo, validade temporal e oclusões; Menu, fila, loading, combate e planejamento; cortar cenas/POV |
| Captura Windows e transporte local | aplicativo | medição pendente | Teste sustentado com CPU/RAM/FPS e idade do frame; Separar atraso da captura, OCR, decisão, fila de voz |
| Identidade, formas e estrelas | núcleo + pacote | parcial | Cinco formas fora do catálogo; Quatro estrelas e prioridades de fusão/equipamento |
| Atributos de campeões | pacote | parcial | AD ausente de Kayle; Papéis e progressão por estrela; conflitos entre fontes |
| Habilidades, passivas e invocações | pacote | parcial | 52 programas bloqueados; 15 programas aguardam integração de função/tempo; Nenhuma habilidade validada por combate real |
| Alvos e movimento | núcleo + calibração | parcial | Prioridades por função e mudanças 18.2/18.3; Taunt e recálculo dinâmico de aggro |
| Tempo e agendamento | núcleo + calibração | laboratório | Tempos reais por campeão; Cadência de DOT, interrupção e ordem simultânea |
| Dano, cura, escudo e estados | núcleo | parcial | Overflow de crítico; Snapshot/dinâmico, autoria e interações por efeito; Calibrar todas as ordens de aplicação |
| Características e patamares | pacote | parcial | 28 características com patamares pendentes; Interações entre efeitos persistentes |
| Itens, receitas e inventário | pacote | parcial | Pool atual não verificado entre 3444 registros globais; 27 handlers candidatos; demais efeitos pendentes; Custo de oportunidade de guardar componentes |
| Aprimoramentos | pacote | não implementado | Catálogo elegível do patch; Handlers, probabilidades e interações |
| Fogos-fátuos e mecânica sazonal | pacote | não implementado | Catálogo integral e versões normal/aprimorada; Custos/efeitos e Major Polymorph desativado no hotfix |
| Ouro, XP, níveis e sequências | pacote | aproximação sintética | Tabelas sazonais exatas; Momento de liquidação e arredondamento |
| Loja e pool compartilhado | núcleo + pacote | parcial | Chances/tamanho do pool no patch; Loja transformada por Inferno, Riftbeast, Lux e Wisps |
| Rodadas e dano ao jogador | pacote | aproximação sintética | Dano real por estágio/sobreviventes; Histórico de pareamento, fantasmas e critérios de empate |
| Loot, PvE e carrossel | pacote | não implementado | Tabelas e probabilidades completas; Restrições de inventário e mecanismos de compensação |
| Estado entre combates | núcleo + pacote | parcial | Fusão/venda/morte e persistência por efeito; Estado transportável entre turnos do simulador |
| Decisões e busca | planejamento | parcial | Busca atual limitada a um combate; Compra/venda/rolar/XP/guardar item com economia futura; Belief state, múltiplos oponentes e MCTS de partidas completas |
| Treino e validação | treinamento | laboratório | Treino de partidas reais com motor completo; Generalização, calibração e regressão por patch; Três transições visuais revisadas não bastam para política |
| Dicas e voz | aplicativo | integração não validada | Rede deste laboratório não promovida ao HUD; Teste ponta a ponta da captura até texto/voz; Descartar conselhos vencidos; cache de áudio por voz/modelo/texto |
| Patch e procedência | dados | parcial | Perfil separado 18.3B e desativações posteriores; Pool sazonal completo e validação empírica |

## Habilidades e formas

| ID | Nome | Estado | Combate candidato | Pendências |
|---|---|---|---|---|
| DA_18_Akali_AD | Akali | blocked | não | AD/AP coefficient split; AP adaptor form and kill recast; burn conditional damage; DA_18_Inferno; DA_18_Adaptor; DA_18_Slayer |
| DA_18_Camille | Camille | blocked | não | 18.3 versus 18.3B AD coefficients conflict; shield AP scaling confirmation; DA_18_Coven; DA_18_Slayer |
| DA_18_Sentry | Cascalho | blocked | não | continuous mana-drain channel; Teal seasonal buff; DA_Riftbeast18; DA_18_Invoker |
| DA_Karma18 | Karma | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Blossom; Three half-second ticks and cast time are provisional. |
| DA_18_Kobuko | Kobuko | blocked | não | confirm HP/AP coefficients across stars; next-attack bash replacement; DA_18_Sprykin |
| DA_18_Leona | Leona | blocked | não | armor-scaling coefficient; 12-second resistance decay; DA_18_Solar |
| DA_18_Ornn | Ornn | blocked | não | cone geometry; blocked-damage forge progression and artifact rewards; DA_18_Elderwood |
| DA_18_Rakan | Rakan | blocked | não | decaying attack-speed curve and most-damage ally tie-break; DA_18_Fae |
| DA_18_RekSai | Rek'Sai | blocked | não | HP regeneration coefficients; regeneration tripling window; DA_18_Blackthorn |
| DA_Cinderling18 | Rubrivirim | blocked | não | AD/AP split for five leaves; Scarlet buff association; DA_Riftbeast18; DA_18_Hunter |
| DA_18_Varus | Varus | blocked | não | physical damage AD/AP split; piercing arrow collision/falloff; DA_18_Inferno |
| DA_18_Veigar | Veigar | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Blackthorn; DA_18_Sprykin; 0.89s cast/lock is a third-party timing claim, not a measured replay result.; Only published 1-3 star formulas enabled; 4-star low-health ratio differs. |
| DA_18_Xayah | Xayah | blocked | não | feather AD coefficient; armor reduction AP coefficient; DA_18_Elderwood; DA_18_Fae |
| DA_18_Yorick | Yorick | blocked | não | Spirit Walker statistics and taunt; physical damage AD coefficient; DA_18_Blossom; DA_18_Summoner |
| DA_18_Alistar | Alistar | blocked | não | heal HP/AP split; cleanse ordering and allied heal targeting; DA_18_Elderwood |
| DA_Scuttlecrab18 | Aronguejo | blocked | não | cleave attacks; Green buff proc limits; DA_Riftbeast18 |
| DA_18_Caitlyn | Caitlyn | blocked | não | third-attack headshot AD/AP coefficients; attack counter instead of normal mana; DA_18_Coven; DA_18_Hunter |
| DA_18_Elise | Elise | blocked | não | decaying AS curve; spider-form attack heal timing; DA_18_Coven |
| DA_Gromp18_AP | Grompe | blocked | não | AD adaptor form; Purple buff scaling and collision selection; DA_Riftbeast18; DA_18_Adaptor |
| DA_18_Kayle | Kayle | blocked | não | missing base attack damage in sealed catalog; star-dependent ascension and wave geometry; DA_18_Solar; Atributos ausentes: damage |
| DA_18_LeBlanc | LeBlanc | blocked | não | copy reward timing/pool/bench priority; 18.3 versus 18.3B copy chance; DA_18_Elderwood |
| DA_Murkwolf18 | Lobo Trevoguari | blocked | não | inconsistent rendered leap totals; Grey buff critical scaling; DA_Riftbeast18; DA_18_Slayer |
| DA_18_Sejuani | Sejuani | blocked | não | HP/AP shield coefficients; cone plus line overlap; DA_18_Solar |
| DA_18_Shen | Shen | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Inferno; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Nearby ally radius 2 and lowest-percent-health selection are provisional.; Buff damage scales with caster AP; ally still deals its own normal attack.; Tank damage-to-mana role is unresolved. |
| DA_18_Teemo | Teemo | blocked | não | 18.3 versus 18.3B mushroom damage; foraged mushroom probabilities and collection rewards; DA_18_Sprykin; DA_18_Invoker |
| DA_18_Warwick | Warwick | blocked | não | AD coefficient instead of displayed attack total; AP scaling of damage-based heal; DA_18_Blackthorn; DA_18_Slayer |
| DA_18_Yunara | Yunara | blocked | não | AD/AP coefficient split; dash position and split-projectile targeting; DA_18_Blossom; DA_18_Executioner |
| DA_18_Azir | Azir | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Blackthorn; DA_18_Executioner; DA_18_Summoner; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Soldiers are non-targetable attack commands in this program; independent soldier positioning remains unverified. |
| DA_18_Cassiopeia | Cassiopeia | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Coven; 425 at 1 star from official notes overrides supplemental 420; does not alter sealed source.; One-second ticks and cast time are provisional. |
| DA_18_Diana | Diana | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Lunar; DA_18_Slayer; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Six orbs distributed in deterministic round-robin order; exact order and travel require replay calibration.; Shield has no AP scaling marker in both supplemental sources.; Fighter stage AS and shield-dependent mana-lock timing are unresolved. |
| DA_Fiddlesticks18 | Fiddlesticks | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; One-second drain ticks are provisional; total heal is per cast, not per enemy.; Tank damage-to-mana role is unresolved. |
| DA_18_Hecarim | Hecarim | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Elderwood; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Tank damage-to-mana role is unresolved. |
| DA_18_KhaZix | Kha'Zix | blocked | não | 18.3 versus 18.3B damage; isolation and leap geometry; Rivals augment override; DA_18_Rival |
| DA_KogMaw18_AD | Kog'Maw | blocked | não | AD damage coefficient; AP adaptor DOT form; DA_18_Adaptor; DA_18_Invoker |
| DA_Krug18 | Krugue | blocked | não | Kruglette statistics and taunt; HP/AD scaling split; Slate death shield; DA_Riftbeast18 |
| DA_CrimsonRaptor18 | Mamãe Bicuda | blocked | não | Tiny Beak damage coefficient and ownership; Orange buff armor reduction; DA_Riftbeast18; DA_18_Summoner |
| DA_18_MasterYi_AD | Master Yi | blocked | não | AP adaptor form; double-strike timing and takedown movement; DA_18_Blossom; DA_18_Adaptor |
| DA_18_Rammus | Rammus | blocked | não | reflection damage scaling; taunt and shield-break ordering; DA_18_Sprykin |
| DA_18_Rengar | Rengar | blocked | não | AD coefficient; missing-health healing multiplier; DA_18_Rival |
| DA_18_Tristana | Tristana | blocked | não | AD coefficients; bomb transfer and attack counter; DA_18_Fae; DA_18_Sprykin; DA_18_Hunter |
| DA_Vi18 | Vi | blocked | não | passive heal HP coefficient; active attack-speed scaling; DA_Primal18 |
| DA_18_Ahri | Ahri | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Blossom; Cast time, center tie-break and linear falloff need replay validation. |
| DA_Amumu18 | Amumu | blocked | não | passive regeneration HP coefficient; burn stun multiplier; DA_18_Inferno |
| DA_18_Aphelios | Aphelios | blocked | não | AD coefficients; AS-dependent swipe count; split explosion; DA_18_Lunar |
| DA_Sentinel18 | Azuporã | blocked | não | HP/AP shield split; knockup line and mana reave; Blue buff; DA_Riftbeast18; DA_18_Invoker |
| DA_18_Ezreal | Ezreal | blocked | não | AD coefficients; fourth cast consumes accumulated ability AS; blink geometry; DA_18_Elderwood; DA_18_Executioner |
| DA_18_Lillia | Lillia | blocked | não | damage-triggered sleep wake; butterfly allocation; DA_18_Fae |
| DA_18_Malphite | Malphite | blocked | não | armor/AP wave scaling; shield-break and petrification; DA_18_Blackthorn; DA_18_Battlemage |
| DA_18_Morgana | Morgana | blocked | não | curse stacking damage semantics; moving versus fixed damage zone; DA_18_Coven; DA_18_Invoker |
| DA_Nidalee18_AP | Nidalee | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_Primal18; DA_18_Adaptor; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; This entry covers the AP form only. AD form and adaptor selection are separately blocked.; Role and empowered-attack mana lock need verification. |
| DA_Brambleback18 | Rubrivira | blocked | não | AD coefficients; leap on target death; Red buff burn and heal; DA_Riftbeast18; DA_18_Slayer |
| DA_18_Sett | Sett | blocked | não | heal HP/AP and damage AD/HP split; cast windup interruption; DA_18_Blossom |
| DA_18_Sivir | Sivir | blocked | não | AD coefficients; bounce path and kill extensions; DA_Primal18; DA_18_Hunter |
| DA_18_Soraka | Soraka | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Executioner; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Cross-caster mark sharing is not verified; laboratory uses caster-local marks. |
| DA_18_Zyra | Zyra | blocked | não | plant spawn geometry and attack cadence; summon targetability and owner-scaling snapshot; DA_18_ZyraUniqueTrait; DA_18_Summoner |
| DA_18_Alune | Alune | blocked | não | moon phase state and progression; full-moon damage allocation; DA_AluneUniqueTrait18; DA_18_Lunar |
| DA_18_Ashe | Ashe | blocked | não | AD and target-HP split; 18.3 versus 18.3B trail values; DA_18_Blossom; DA_18_Hunter |
| DA_18_ElderDragon | Dragão Ancião | blocked | não | transform sequence and breath coefficients; landing geometry and ignite; Elder execute buff; DA_18_ApexPredator; DA_Riftbeast18 |
| DA_Draven18 | Draven | blocked | não | AD coefficients; random target attacks; bleed consumption and outbound/return collisions; DA_DravenUniqueTrait18 |
| DA_18_GnarSmall | Gnar | blocked | não | rage instead of normal mana; Mega form displacement and lone-enemy execution; DA_18_Elderwood; DA_18_Sprykin |
| DA_18_Ivern | Ivern | candidate_not_replay_validated | sim, condicionado às sinergias | DA_18_Greenfather; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; After casting six times interpreted as cast 7 onward.; Lowest-percent-health ally choice is provisional; source only specifies number of allies.; Shield AP coefficients from TFTraits; TFTCodex contains unresolved placeholder. |
| DA_18_Kennen | Kennen | blocked | não | dynamic AP per burning enemy; dash geometry and split firestorm; DA_18_Inferno; DA_18_Executioner |
| DA_Lux18_Base | Lux | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Coven | Lux (Congregação das Bruxas) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Coven; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_Lux18_Blackthorn | Lux (Espinhos Negros) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Blackthorn; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Fae | Lux (Feérica) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Fae; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_Lux18_Blossom | Lux (Florescer) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Blossom; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Inferno | Lux (Inferno) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Inferno; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Moonbeam | Lux (Lunar) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Lunar; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Primal | Lux (Primordial) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_Primal18; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Elderwood | Lux (Sabugueiro) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Elderwood; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Lux_Sunbeam | Lux (Solar) | candidate_not_replay_validated | não | ability program available; mana role/timing integration unverified; DA_18_Solar; DA_18_LuxUniqueTrait; Cast, projectile timing and targeting tie-breaks are explicit laboratory assumptions; not replay validated.; Laser width 0.87, linear attenuation and equal-count direction tie-break are provisional.; Role verification remains required before full-fight compilation.; Elderwood health uses additive base-health percent; Fae heals per hit based on post-mitigation HP damage. |
| DA_18_Maokai | Maokai | blocked | não | blocked-damage threshold and sapling statistics; HP scaling in heal and damage; DA_18_Maokai_UniqueTrait |
| DA_Taric18 | Taric | blocked | não | paired-ally identity and trigger; shield HP/flat split conflicts with official patch; paired empowered attacks; DA_Emerald18 |
| Akali:AP | Akali | blocked | não | formula and form selection not bound |
| Gromp:AD | Gromp | blocked | não | formula and form selection not bound |
| KogMaw:AP | KogMaw | blocked | não | formula and form selection not bound |
| MasterYi:AP | MasterYi | blocked | não | formula and form selection not bound |
| Nidalee:AD | Nidalee | blocked | não | formula and form selection not bound |

## Características

| ID | Nome | Patamares candidatos | Dependências |
|---|---|---|---|
| DA_18_Adaptor | Adaptador | nenhum | Comparação AD/AP e normalização de unidades; Escolha de forma, empate, recálculo após itens e bônus; Todas as formas alternativas e interações |
| DA_Emerald18 | Aspecto Esmeralda | nenhum | Seleção do Taric mais forte e desempate; Vínculo persistente com aliado; transferência de escudo/cura |
| DA_18_LuxUniqueTrait | Avatar | nenhum | Conversão de variantes da loja e identidade única; Contribuição dupla somente da origem escolhida |
| DA_18_Executioner | Carrasco | 2 | Precisão e crítico no patamar 2 implementados como candidato; Patamares 3/4: base do sangramento, cadência, autoria e renovação |
| DA_DravenUniqueTrait18 | Caça-recompensas | nenhum | Todas as missões, limiares por estrela e recompensas; Escolha de missão e progresso persistente; Aplicar correções 18.3B sem contaminar perfil 18.3 base |
| DA_18_Hunter | Caçador | nenhum | AD por patamar com deltas oficiais; Tempo no mesmo alvo, reinício ao trocar e interação com controle |
| DA_Juggernaut18 | Colosso | 2, 4, 6 | Substituição do bônus de equipe pelo bônus do membro; Calibração de durabilidade e ordem de multiplicadores |
| DA_AluneUniqueTrait18 | Comunhão | nenhum | Fases da Lua e transições por conjuração; Bônus dinâmico de equipe e ordem de eventos |
| DA_18_Coven | Congregação das Bruxas | nenhum | Essência por eliminação/derrota e persistência; Tabela completa de recompensas, probabilidades e ofertas; Desativação do aprimoramento Dark Ritual no hotfix |
| DA_18_Maokai_UniqueTrait | Crescimento Antigo | nenhum | Distância da morte, dono mais forte e desempate; HP persistente, fusão, venda e cópias |
| DA_18_Caustic | Cáustico | 1 | Dano direto/periódico e redução de resistências; Renovação e prioridade do efeito mais forte implementadas; validar em replay |
| DA_18_ZyraUniqueTrait | Dama de Espinhos | nenhum | Contagem de plantas vivas por proprietário; Recalcular durabilidade ao invocar e morrer |
| DA_18_Defender | Defendente | 2, 4, 6 | Bônus de membro substitui equipe; Patamar 6 corrigido para 115; replay independente pendente |
| DA_18_Slayer | Devastador | nenhum | Vampirismo e amplificação condicionada ao HP do alvo; Limiar antes/depois do impacto e dano periódico |
| DA_18_Eclipse | Eclipse | nenhum | Catálogo sem limites numéricos válidos para o patamar; Condição de ativação, primeiro disparo e repetição; Alvo de menor HP, desempate e imunidade à execução |
| DA_18_Invoker | Emanador | nenhum | Semântica de soma/substituição e bônus próprio; Total de mana por patamar confrontado com patch; Regeneração durante bloqueio de mana e conjuração |
| DA_18_Spellweaver | Enfeitiçador | 2, 4, 6 | AP de equipe/membro e incremento por conjuração aliada; Validar instante de incremento, invocações e cópias |
| DA_18_Blackthorn | Espinhos Negros | nenhum | Casa de sacrifício e unidade elegível; Matriz de bônus por função/custo/estrela; Snapshot, remoção antes do combate, HP de equipe e escalas; Hotfix reduz amplificação do sacrifício AP de 14% para 12% |
| DA_Riftbeast18 | Fera do Rift | nenhum | Marca Alfa e bônus por criatura; Contador de combates e invasão da loja respeitando pool; Crescimento periódico e limite de equipe |
| DA_18_Fae | Feérico | nenhum | Atração por dano/cura/escudo efetivos; Limiares, Pixies douradas e ouro; Bônus por Pixie e cura ao cruzar limiar |
| DA_FloraFatalis18 | Flora Fatalis | 1, 2 | Eliminação versus assistência e atribuição; Mana e cura do aliado com menor HP; desempate |
| DA_18_Blossom | Florescer | nenhum | Aprimoramentos de cada Wisp e persistência após combate; Frequência na loja, custo, reembolso e limite por rodada; Condições dos patamares prismáticos |
| DA_18_Rapidfire | Fumegante | 2, 3, 4, 5 | Velocidade de ataque da equipe e acúmulos por ataque; Limite e distinção entre ataque básico e impacto de habilidade |
| DA_18_Inferno | Inferno | nenhum | Queimadura própria acumulável e ferimento; Cadência, renovação e autoria; Transformação de casas da loja, custo superior e pool |
| DA_18_Summoner | Invocador | nenhum | Invocações reais por proprietário e tipo; Vida/dano/ataques adicionais por patamar; Soldados de Azir têm representação parcial no motor |
| DA_18_Lunar | Lunar | nenhum | Adjacência inicial ou dinâmica e vizinhos únicos; Acúmulo entre múltiplas fontes e bônus dos membros |
| DA_18_Brawler | Lutador | 2, 4, 6 | Vida fixa da equipe e percentual dos membros; Ordem de aplicação e interação com itens/estrelas |
| DA_18_Battlemage | Monólito | nenhum | Contagem dinâmica de inimigos que miram o portador; Recalcular resistências ao trocar alvo e morrer |
| DA_18_Greenfather | Pai do Verde | nenhum | Sementes por combate/conjuração e persistência; Escolha/expansão de casas; ocupação e biomas; Efeitos de todos os biomas e transição |
| DA_18_ApexPredator | Predador Perfeito | nenhum | Ocupação de dois espaços na equipe; Contribuição de duas unidades para Riftbeast; Legalidade de compra/fusão e excesso de população |
| DA_Primal18 | Primordial | nenhum | Quatro bênçãos, efeitos e seleção; Escala dos dois patamares e persistência da escolha |
| DA_18_Rival | Rival | nenhum | Exclusividade/ativação conjunta por patamar; Eliminações compartilhadas e bônus contra rival; Evoluções do KhaZix; ouro e AD persistentes do Rengar |
| DA_18_Elderwood | Sabugueiro | nenhum | Unidades de planta posicionáveis e regras de ocupação; Dois campos numéricos sem nome resolvido; Atributos/habilidades das plantas e evolução por patamar |
| DA_18_Solar | Solar | nenhum | Contagem de identidades únicas com três estrelas; Escudo, dano adicional e conversão parcial em dano verdadeiro; Promoção temporária a quatro estrelas e ordem de eventos |
| DA_18_Vanguard | Vanguarda | 2, 4, 6 | Escudo inicial e gatilho único de HP; Durabilidade apenas com escudo; expiração e renovação |
| DA_18_Sprykin | Vivaz | nenhum | Escolha do cavaleiro e vínculo com BFF; Atributos e habilidades do BFF por estrela; Distribuição do efeito nos patamares 5/7; tooltip de guia mostra valor 0% suspeito |

## Itens e outros registros do catálogo global

O JSON contém os 3444 registros individualmente, com campos numéricos, receitas, estado e procedência.
Aprimoramentos, consumíveis e registros de sets antigos podem aparecer nesse catálogo. IDs não comprovam disponibilidade no patch.

## Limites de completude

- O inventário cobre cada registro do catálogo selado; o catálogo não contém todas as regras do jogo.
- O pacote executável é 18.3 base. Vídeos recentes podem incluir 18.3B e desativações de 28/09; não são automaticamente compatíveis.
- 3444 registros de itens são globais e incluem conteúdo histórico; falta validar disponibilidade e classificação no set atual.
- Cinco formas alternativas, quatro estrelas, invocações, aprimoramentos, Wisps, loot e tabelas de partida ainda têm lacunas.
- Nomes recuperados por hash não comprovam fórmula, escala, ordem de execução ou valor correto no patch.
- Trechos de guias e comentários são hipóteses estratégicas; não equivalem a partidas completas rotuladas ou regras oficiais.
- Vídeos foram inspecionados em trechos e transcrições. Nenhum VOD novo foi assistido integralmente ou validado como partida completa.
- Todas as validações de replay e prontidão permanecem falsas até haver evidência independente.

## Inventário suplementar online

Fontes suplementares ainda sem identidade de patch confirmada. Descrições não são handlers.

| Aprimoramento | Desativado na fonte | Descrição anterior disponível |
|---|---|---|
| [Advanced Loan](https://www.tftraits.com/augments/advanced-loan/) | não informado | sim, conferir identidade |
| [Advanced Loan+](https://www.tftraits.com/augments/advanced-loan-2/) | não informado | sim, conferir identidade |
| [Arcane Viktor-y](https://www.tftraits.com/augments/arcane-viktor-y/) | não informado | sim, conferir identidade |
| [Ascension](https://www.tftraits.com/augments/ascension/) | não informado | sim, conferir identidade |
| [Augmented Power](https://www.tftraits.com/augments/augmented-power/) | não informado | sim, conferir identidade |
| [Backline Blueprint](https://www.tftraits.com/augments/backline-blueprint/) | não informado | sim, conferir identidade |
| [Backup Bows](https://www.tftraits.com/augments/backup-bows/) | não informado | sim, conferir identidade |
| [Band of Thieves](https://www.tftraits.com/augments/band-of-thieves/) | não informado | sim, conferir identidade |
| [Band of Thieves II](https://www.tftraits.com/augments/band-of-thieves-ii/) | não informado | sim, conferir identidade |
| [Band of Thieves II+](https://www.tftraits.com/augments/band-of-thieves-ii-2/) | não informado | sim, conferir identidade |
| [Band of Thieves II++](https://www.tftraits.com/augments/band-of-thieves-ii-3/) | não informado | sim, conferir identidade |
| [Baron's Lair](https://www.tftraits.com/augments/barons-lair/) | não informado | sim, conferir identidade |
| [Beast Within](https://www.tftraits.com/augments/beast-within/) | não informado | sim, conferir identidade |
| [Beast Within+](https://www.tftraits.com/augments/beast-within-2/) | não informado | sim, conferir identidade |
| [Belt Overflow](https://www.tftraits.com/augments/belt-overflow/) | não informado | sim, conferir identidade |
| [Big Grab Bag](https://www.tftraits.com/augments/big-grab-bag/) | não informado | sim, conferir identidade |
| [Birthday Present](https://www.tftraits.com/augments/birthday-present/) | não informado | sim, conferir identidade |
| [Birthday Reunion](https://www.tftraits.com/augments/birthday-reunion/) | não informado | sim, conferir identidade |
| [Blossom's Call](https://www.tftraits.com/augments/blossoms-call/) | não informado | sim, conferir identidade |
| [Bodyguard Training](https://www.tftraits.com/augments/bodyguard-training/) | não informado | sim, conferir identidade |
| [Bonus Gifts](https://www.tftraits.com/augments/bonus-gifts/) | não informado | sim, conferir identidade |
| [Bonus Gifts+](https://www.tftraits.com/augments/bonus-gifts-2/) | não informado | sim, conferir identidade |
| [Booster Pack](https://www.tftraits.com/augments/booster-pack/) | não informado | sim, conferir identidade |
| [Booster Pack+](https://www.tftraits.com/augments/booster-pack-2/) | não informado | sim, conferir identidade |
| [Booster Pack++](https://www.tftraits.com/augments/booster-pack-3/) | não informado | sim, conferir identidade |
| [Boxing Lessons](https://www.tftraits.com/augments/boxing-lessons/) | não informado | sim, conferir identidade |
| [Branching Out](https://www.tftraits.com/augments/branching-out/) | não informado | sim, conferir identidade |
| [Branching Out+](https://www.tftraits.com/augments/branching-out-2/) | não informado | sim, conferir identidade |
| [Bronze For Life I](https://www.tftraits.com/augments/bronze-for-life-i/) | não informado | sim, conferir identidade |
| [Bronze For Life II](https://www.tftraits.com/augments/bronze-for-life-ii/) | não informado | sim, conferir identidade |
| [Build a Bud](https://www.tftraits.com/augments/build-a-bud/) | não informado | sim, conferir identidade |
| [Buried Treasures III](https://www.tftraits.com/augments/buried-treasures-iii/) | não informado | sim, conferir identidade |
| [Calculated Loss](https://www.tftraits.com/augments/calculated-loss/) | não informado | não |
| [Call To Chaos](https://www.tftraits.com/augments/call-to-chaos/) | não informado | sim, conferir identidade |
| [Called Shot](https://www.tftraits.com/augments/called-shot/) | não informado | sim, conferir identidade |
| [Capital Gains I](https://www.tftraits.com/augments/capital-gains-i/) | não informado | sim, conferir identidade |
| [Capital Gains II](https://www.tftraits.com/augments/capital-gains-ii/) | não informado | sim, conferir identidade |
| [Caretaker's Ally](https://www.tftraits.com/augments/caretakers-ally/) | não informado | sim, conferir identidade |
| [Caretaker's Favor](https://www.tftraits.com/augments/caretakers-favor/) | não informado | sim, conferir identidade |
| [Carve a Path](https://www.tftraits.com/augments/carve-a-path/) | não informado | sim, conferir identidade |
| [Celestial Blessing I](https://www.tftraits.com/augments/celestial-blessing-i/) | não informado | sim, conferir identidade |
| [Celestial Blessing II](https://www.tftraits.com/augments/celestial-blessing-ii/) | não informado | sim, conferir identidade |
| [Celestial Blessing III](https://www.tftraits.com/augments/celestial-blessing-iii/) | não informado | sim, conferir identidade |
| [Champ Delivery](https://www.tftraits.com/augments/champ-delivery/) | não informado | sim, conferir identidade |
| [Champ Delivery+](https://www.tftraits.com/augments/champ-delivery-2/) | não informado | sim, conferir identidade |
| [Champ Delivery++](https://www.tftraits.com/augments/champ-delivery-3/) | não informado | sim, conferir identidade |
| [Chosen of the Sun](https://www.tftraits.com/augments/chosen-of-the-sun/) | não informado | sim, conferir identidade |
| [Clear Mind](https://www.tftraits.com/augments/clear-mind/) | não informado | sim, conferir identidade |
| [Clockwork Accelerator](https://www.tftraits.com/augments/clockwork-accelerator/) | não informado | sim, conferir identidade |
| [Cluttered Mind](https://www.tftraits.com/augments/cluttered-mind/) | não informado | sim, conferir identidade |
| [Cognitive Overload](https://www.tftraits.com/augments/cognitive-overload/) | não informado | sim, conferir identidade |
| [Cognitive Tax](https://www.tftraits.com/augments/cognitive-tax/) | não informado | sim, conferir identidade |
| [Cognitive Tax+](https://www.tftraits.com/augments/cognitive-tax-2/) | não informado | sim, conferir identidade |
| [Comeback Story](https://www.tftraits.com/augments/comeback-story/) | não informado | sim, conferir identidade |
| [Commerce Core](https://www.tftraits.com/augments/commerce-core/) | não informado | sim, conferir identidade |
| [Component Buffet](https://www.tftraits.com/augments/component-buffet/) | não informado | sim, conferir identidade |
| [Component Quest](https://www.tftraits.com/augments/component-quest/) | não informado | sim, conferir identidade |
| [Construct a Companion](https://www.tftraits.com/augments/construct-a-companion/) | sim | não |
| [Consuming Flora](https://www.tftraits.com/augments/consuming-flora/) | não informado | sim, conferir identidade |
| [Cooking Pot](https://www.tftraits.com/augments/cooking-pot/) | não informado | sim, conferir identidade |
| [Coronation](https://www.tftraits.com/augments/coronation/) | não informado | sim, conferir identidade |
| [Corrosion](https://www.tftraits.com/augments/corrosion/) | não informado | sim, conferir identidade |
| [Coven Acolyte](https://www.tftraits.com/augments/coven-acolyte/) | não informado | sim, conferir identidade |
| [Crafted Crafting](https://www.tftraits.com/augments/crafted-crafting/) | não informado | sim, conferir identidade |
| [Cry Me a River](https://www.tftraits.com/augments/cry-me-a-river/) | não informado | sim, conferir identidade |
| [Cursed Crown](https://www.tftraits.com/augments/cursed-crown/) | sim | não |
| [Cybernetic Implants](https://www.tftraits.com/augments/cybernetic-implants/) | não informado | sim, conferir identidade |
| [Cybernetic Uplink](https://www.tftraits.com/augments/cybernetic-uplink/) | não informado | sim, conferir identidade |
| [Dark Ritual](https://www.tftraits.com/augments/dark-ritual/) | sim | sim, conferir identidade |
| [Deadlier Blades](https://www.tftraits.com/augments/deadlier-blades/) | não informado | sim, conferir identidade |
| [Deadlier Caps](https://www.tftraits.com/augments/deadlier-caps/) | não informado | sim, conferir identidade |
| [Dummify](https://www.tftraits.com/augments/dummify/) | não informado | sim, conferir identidade |
| [Duo Queue](https://www.tftraits.com/augments/duo-queue/) | não informado | sim, conferir identidade |
| [Early Learnings](https://www.tftraits.com/augments/early-learnings/) | não informado | sim, conferir identidade |
| [Electrocharge I](https://www.tftraits.com/augments/electrocharge-i/) | não informado | sim, conferir identidade |
| [Electrocharge II](https://www.tftraits.com/augments/electrocharge-ii/) | não informado | sim, conferir identidade |
| [Embiggen](https://www.tftraits.com/augments/embiggen/) | não informado | sim, conferir identidade |
| [Epic Rolldown](https://www.tftraits.com/augments/epic-rolldown/) | não informado | sim, conferir identidade |
| [Epoch](https://www.tftraits.com/augments/epoch/) | não informado | sim, conferir identidade |
| [Epoch+](https://www.tftraits.com/augments/epoch-2/) | não informado | sim, conferir identidade |
| [Exclusive Customization](https://www.tftraits.com/augments/exclusive-customization/) | não informado | sim, conferir identidade |
| [Expected Unexpectedness](https://www.tftraits.com/augments/expected-unexpectedness/) | não informado | sim, conferir identidade |
| [Expedition](https://www.tftraits.com/augments/expedition/) | não informado | sim, conferir identidade |
| [Explosive Growth](https://www.tftraits.com/augments/explosive-growth/) | não informado | sim, conferir identidade |
| [Explosive Growth+](https://www.tftraits.com/augments/explosive-growth-2/) | não informado | sim, conferir identidade |
| [Extra Buckles](https://www.tftraits.com/augments/extra-buckles/) | não informado | sim, conferir identidade |
| [Feeling Lucky](https://www.tftraits.com/augments/feeling-lucky/) | não informado | sim, conferir identidade |
| [Find Your Center](https://www.tftraits.com/augments/find-your-center/) | não informado | sim, conferir identidade |
| [Flame On](https://www.tftraits.com/augments/flame-on/) | não informado | sim, conferir identidade |
| [Flexible](https://www.tftraits.com/augments/flexible/) | não informado | sim, conferir identidade |
| [Flowing Tears](https://www.tftraits.com/augments/flowing-tears/) | não informado | sim, conferir identidade |
| [Focused Fire](https://www.tftraits.com/augments/focused-fire/) | não informado | sim, conferir identidade |
| [Forged In Strength](https://www.tftraits.com/augments/forged-in-strength/) | não informado | sim, conferir identidade |
| [FOURcing](https://www.tftraits.com/augments/fourcing/) | não informado | sim, conferir identidade |
| [Frontline Foundation](https://www.tftraits.com/augments/frontline-foundation/) | não informado | sim, conferir identidade |
| [Future Focused](https://www.tftraits.com/augments/future-focused/) | não informado | sim, conferir identidade |
| [Gain 21 Gold](https://www.tftraits.com/augments/gain-21-gold/) | não informado | sim, conferir identidade |
| [Giant and Mighty](https://www.tftraits.com/augments/giant-and-mighty/) | não informado | sim, conferir identidade |
| [Gilded Steel](https://www.tftraits.com/augments/gilded-steel/) | não informado | sim, conferir identidade |
| [Glass Cannon I](https://www.tftraits.com/augments/glass-cannon-i/) | não informado | sim, conferir identidade |
| [Glass Cannon II](https://www.tftraits.com/augments/glass-cannon-ii/) | não informado | sim, conferir identidade |
| [Going Long](https://www.tftraits.com/augments/going-long/) | não informado | sim, conferir identidade |
| [Gold Destiny](https://www.tftraits.com/augments/gold-destiny/) | não informado | sim, conferir identidade |
| [Gold Destiny+](https://www.tftraits.com/augments/gold-destiny-2/) | não informado | sim, conferir identidade |
| [Golden Gamble](https://www.tftraits.com/augments/golden-gamble/) | não informado | sim, conferir identidade |
| [Golden Gamble+](https://www.tftraits.com/augments/golden-gamble-2/) | não informado | sim, conferir identidade |
| [Golden Gamble++](https://www.tftraits.com/augments/golden-gamble-3/) | não informado | sim, conferir identidade |
| [Good For Something I](https://www.tftraits.com/augments/good-for-something-i/) | não informado | sim, conferir identidade |
| [Group Hug I](https://www.tftraits.com/augments/group-hug-i/) | não informado | sim, conferir identidade |
| [Group Hug II](https://www.tftraits.com/augments/group-hug-ii/) | não informado | sim, conferir identidade |
| [Hard Bargain](https://www.tftraits.com/augments/hard-bargain/) | não informado | sim, conferir identidade |
| [Hard Commit](https://www.tftraits.com/augments/hard-commit/) | não informado | sim, conferir identidade |
| [Healing Orbs I](https://www.tftraits.com/augments/healing-orbs-i/) | não informado | sim, conferir identidade |
| [Healing Orbs II](https://www.tftraits.com/augments/healing-orbs-ii/) | não informado | sim, conferir identidade |
| [Heart of Steel](https://www.tftraits.com/augments/heart-of-steel/) | não informado | sim, conferir identidade |
| [Hedge Fund](https://www.tftraits.com/augments/hedge-fund/) | não informado | sim, conferir identidade |
| [Heroic Grab Bag](https://www.tftraits.com/augments/heroic-grab-bag/) | não informado | sim, conferir identidade |
| [Heroic Grab Bag+](https://www.tftraits.com/augments/heroic-grab-bag-2/) | não informado | sim, conferir identidade |
| [Heroic Grab Bag++](https://www.tftraits.com/augments/heroic-grab-bag-3/) | não informado | sim, conferir identidade |
| [Hold the Line](https://www.tftraits.com/augments/hold-the-line/) | não informado | sim, conferir identidade |
| [Hustler](https://www.tftraits.com/augments/hustler/) | não informado | sim, conferir identidade |
| [Invested+](https://www.tftraits.com/augments/invested/) | não informado | sim, conferir identidade |
| [Invested++](https://www.tftraits.com/augments/invested-2/) | não informado | sim, conferir identidade |
| [Investment Strategy I](https://www.tftraits.com/augments/investment-strategy-i/) | não informado | sim, conferir identidade |
| [Investment Strategy II](https://www.tftraits.com/augments/investment-strategy-ii/) | não informado | sim, conferir identidade |
| [Iron Assets](https://www.tftraits.com/augments/iron-assets/) | não informado | sim, conferir identidade |
| [It's Me, Baby](https://www.tftraits.com/augments/its-me-baby/) | não informado | sim, conferir identidade |
| [Item Extraction](https://www.tftraits.com/augments/item-extraction/) | não informado | sim, conferir identidade |
| [Item Grab Bag I](https://www.tftraits.com/augments/item-grab-bag-i/) | não informado | sim, conferir identidade |
| [Jeweled Lotus I](https://www.tftraits.com/augments/jeweled-lotus-i/) | não informado | sim, conferir identidade |
| [Jeweled Lotus II](https://www.tftraits.com/augments/jeweled-lotus-ii/) | não informado | sim, conferir identidade |
| [Kick Start](https://www.tftraits.com/augments/kick-start/) | não informado | sim, conferir identidade |
| [Kingslayer](https://www.tftraits.com/augments/kingslayer/) | não informado | sim, conferir identidade |
| [Know Your Enemy](https://www.tftraits.com/augments/know-your-enemy/) | não informado | sim, conferir identidade |
| [Late Game Scaling](https://www.tftraits.com/augments/late-game-scaling/) | não informado | sim, conferir identidade |
| [Late Game Specialist](https://www.tftraits.com/augments/late-game-specialist/) | não informado | sim, conferir identidade |
| [Latent Forge](https://www.tftraits.com/augments/latent-forge/) | não informado | sim, conferir identidade |
| [Legion of Threes](https://www.tftraits.com/augments/legion-of-threes/) | não informado | sim, conferir identidade |
| [Level Up!](https://www.tftraits.com/augments/level-up/) | não informado | sim, conferir identidade |
| [Living Forge](https://www.tftraits.com/augments/living-forge/) | não informado | sim, conferir identidade |
| [Loaded Dice](https://www.tftraits.com/augments/loaded-dice/) | não informado | sim, conferir identidade |
| [Lucky Gloves](https://www.tftraits.com/augments/lucky-gloves/) | não informado | sim, conferir identidade |
| [Lucky Gloves+](https://www.tftraits.com/augments/lucky-gloves-2/) | não informado | sim, conferir identidade |
| [Luxury Subscription](https://www.tftraits.com/augments/luxury-subscription/) | não informado | sim, conferir identidade |
| [Magic Roll](https://www.tftraits.com/augments/magic-roll/) | não informado | sim, conferir identidade |
| [Makeshift Armor I](https://www.tftraits.com/augments/makeshift-armor-i/) | não informado | sim, conferir identidade |
| [Makeshift Armor II](https://www.tftraits.com/augments/makeshift-armor-ii/) | não informado | sim, conferir identidade |
| [Malicious Monetization](https://www.tftraits.com/augments/malicious-monetization/) | não informado | sim, conferir identidade |
| [Master of All Origins](https://www.tftraits.com/augments/master-of-all-origins/) | não informado | sim, conferir identidade |
| [Max Build](https://www.tftraits.com/augments/max-build/) | não informado | sim, conferir identidade |
| [Min-Max](https://www.tftraits.com/augments/min-max/) | não informado | sim, conferir identidade |
| [Missed Connections](https://www.tftraits.com/augments/missed-connections/) | não informado | sim, conferir identidade |
| [Money Hungry](https://www.tftraits.com/augments/money-hungry/) | não informado | sim, conferir identidade |
| [Money Hungry+](https://www.tftraits.com/augments/money-hungry-2/) | não informado | sim, conferir identidade |
| [Money Monsoon](https://www.tftraits.com/augments/money-monsoon/) | não informado | sim, conferir identidade |
| [Nature's Shelter](https://www.tftraits.com/augments/natures-shelter/) | não informado | sim, conferir identidade |
| [Nesting Anvils](https://www.tftraits.com/augments/nesting-anvils/) | não informado | sim, conferir identidade |
| [Nesting Anvils+](https://www.tftraits.com/augments/nesting-anvils-2/) | não informado | sim, conferir identidade |
| [Nesting Dolls](https://www.tftraits.com/augments/nesting-dolls/) | sim | sim, conferir identidade |
| [NO SCOUT NO PIVOT](https://www.tftraits.com/augments/no-scout-no-pivot/) | não informado | sim, conferir identidade |
| [Omega Riftbeast](https://www.tftraits.com/augments/omega-riftbeast/) | não informado | sim, conferir identidade |
| [One Buff Two Buff](https://www.tftraits.com/augments/one-buff-two-buff/) | não informado | sim, conferir identidade |
| [One, Two, Five!](https://www.tftraits.com/augments/one-two-five/) | não informado | sim, conferir identidade |
| [Ones Two Three](https://www.tftraits.com/augments/ones-two-three/) | não informado | sim, conferir identidade |
| [Pandora's Bench](https://www.tftraits.com/augments/pandoras-bench/) | não informado | sim, conferir identidade |
| [Pandora's Items I](https://www.tftraits.com/augments/pandoras-items-i/) | não informado | sim, conferir identidade |
| [Pandora's Items II](https://www.tftraits.com/augments/pandoras-items-ii/) | não informado | sim, conferir identidade |
| [Pandora's Items III](https://www.tftraits.com/augments/pandoras-items-iii/) | não informado | sim, conferir identidade |
| [Partial Ascension](https://www.tftraits.com/augments/partial-ascension/) | não informado | sim, conferir identidade |
| [Patience is a Virtue](https://www.tftraits.com/augments/patience-is-a-virtue/) | não informado | sim, conferir identidade |
| [Patient Study](https://www.tftraits.com/augments/patient-study/) | não informado | sim, conferir identidade |
| [Pilfer](https://www.tftraits.com/augments/pilfer/) | não informado | sim, conferir identidade |
| [Plot Armor](https://www.tftraits.com/augments/plot-armor/) | não informado | sim, conferir identidade |
| [Portable Forge](https://www.tftraits.com/augments/portable-forge/) | não informado | sim, conferir identidade |
| [Prismatic Destiny](https://www.tftraits.com/augments/prismatic-destiny/) | não informado | sim, conferir identidade |
| [Prismatic Destiny+](https://www.tftraits.com/augments/prismatic-destiny-2/) | não informado | sim, conferir identidade |
| [Prismatic Ticket](https://www.tftraits.com/augments/prismatic-ticket/) | não informado | sim, conferir identidade |
| [Promised Protection](https://www.tftraits.com/augments/promised-protection/) | não informado | sim, conferir identidade |
| [Quick Streaks](https://www.tftraits.com/augments/quick-streaks/) | não informado | sim, conferir identidade |
| [Radiant Rascal](https://www.tftraits.com/augments/radiant-rascal/) | não informado | sim, conferir identidade |
| [Radiant Relics](https://www.tftraits.com/augments/radiant-relics/) | não informado | sim, conferir identidade |
| [Recombobulator](https://www.tftraits.com/augments/recombobulator/) | não informado | sim, conferir identidade |
| [Replication](https://www.tftraits.com/augments/replication/) | não informado | sim, conferir identidade |
| [Residual Magic](https://www.tftraits.com/augments/residual-magic/) | não informado | sim, conferir identidade |
| [Residual Magic +](https://www.tftraits.com/augments/residual-magic-2/) | não informado | sim, conferir identidade |
| [Residual Magic ++](https://www.tftraits.com/augments/residual-magic-3/) | não informado | sim, conferir identidade |
| [Retribution](https://www.tftraits.com/augments/retribution/) | não informado | sim, conferir identidade |
| [Rolling For Days](https://www.tftraits.com/augments/rolling-for-days/) | não informado | sim, conferir identidade |
| [Salvage Bin](https://www.tftraits.com/augments/salvage-bin/) | não informado | sim, conferir identidade |
| [Salvage Bin+](https://www.tftraits.com/augments/salvage-bin-2/) | não informado | sim, conferir identidade |
| [Seraphim's Staff](https://www.tftraits.com/augments/seraphims-staff/) | não informado | sim, conferir identidade |
| [Shimmerscale Essence](https://www.tftraits.com/augments/shimmerscale-essence/) | não informado | sim, conferir identidade |
| [Shopping Spree](https://www.tftraits.com/augments/shopping-spree/) | não informado | sim, conferir identidade |
| [Silver Destiny](https://www.tftraits.com/augments/silver-destiny/) | não informado | sim, conferir identidade |
| [Silver Destiny+](https://www.tftraits.com/augments/silver-destiny-2/) | não informado | sim, conferir identidade |
| [Silver Destiny++](https://www.tftraits.com/augments/silver-destiny-3/) | não informado | sim, conferir identidade |
| [Silver Spoon](https://www.tftraits.com/augments/silver-spoon/) | não informado | sim, conferir identidade |
| [Slammin'](https://www.tftraits.com/augments/slammin/) | não informado | sim, conferir identidade |
| [Slammin'+](https://www.tftraits.com/augments/slammin-2/) | não informado | sim, conferir identidade |
| [Slice of Life](https://www.tftraits.com/augments/slice-of-life/) | não informado | sim, conferir identidade |
| [Slightly Magic Roll](https://www.tftraits.com/augments/slightly-magic-roll/) | não informado | sim, conferir identidade |
| [Small Furry Friend](https://www.tftraits.com/augments/small-furry-friend/) | não informado | sim, conferir identidade |
| [Small Grab Bag](https://www.tftraits.com/augments/small-grab-bag/) | não informado | sim, conferir identidade |
| [Solo Leveling](https://www.tftraits.com/augments/solo-leveling/) | não informado | sim, conferir identidade |
| [Solo Plate](https://www.tftraits.com/augments/solo-plate/) | não informado | sim, conferir identidade |
| [Soul Awakening](https://www.tftraits.com/augments/soul-awakening/) | não informado | sim, conferir identidade |
| [Speedy Double Kill](https://www.tftraits.com/augments/speedy-double-kill/) | não informado | sim, conferir identidade |
| [Spirit of Redemption](https://www.tftraits.com/augments/spirit-of-redemption/) | não informado | sim, conferir identidade |
| [Spreading Roots](https://www.tftraits.com/augments/spreading-roots/) | não informado | sim, conferir identidade |
| [Spreading Roots+](https://www.tftraits.com/augments/spreading-roots-2/) | não informado | sim, conferir identidade |
| [Staffsmith](https://www.tftraits.com/augments/staffsmith/) | não informado | sim, conferir identidade |
| [Stand United](https://www.tftraits.com/augments/stand-united/) | não informado | sim, conferir identidade |
| [Starring Up](https://www.tftraits.com/augments/starring-up/) | sim | não |
| [Subscription Service](https://www.tftraits.com/augments/subscription-service/) | sim | não |
| [Sun and Moon](https://www.tftraits.com/augments/sun-and-moon/) | não informado | sim, conferir identidade |
| [Sun and Moon+](https://www.tftraits.com/augments/sun-and-moon-2/) | não informado | sim, conferir identidade |
| [Sweet Treats](https://www.tftraits.com/augments/sweet-treats/) | não informado | sim, conferir identidade |
| [Sword Overflow](https://www.tftraits.com/augments/sword-overflow/) | não informado | sim, conferir identidade |
| [Swordsmith](https://www.tftraits.com/augments/swordsmith/) | não informado | sim, conferir identidade |
| [Tactician's Kitchen](https://www.tftraits.com/augments/tacticians-kitchen/) | não informado | sim, conferir identidade |
| [Team Building](https://www.tftraits.com/augments/team-building/) | não informado | sim, conferir identidade |
| [The Golden Dragon](https://www.tftraits.com/augments/the-golden-dragon/) | não informado | sim, conferir identidade |
| [The Golden Egg](https://www.tftraits.com/augments/the-golden-egg/) | não informado | sim, conferir identidade |
| [The Tower](https://www.tftraits.com/augments/the-tower/) | não informado | sim, conferir identidade |
| [The Trait Tree](https://www.tftraits.com/augments/the-trait-tree/) | não informado | sim, conferir identidade |
| [The Trait Tree+](https://www.tftraits.com/augments/the-trait-tree-2/) | não informado | sim, conferir identidade |
| [Time Skip](https://www.tftraits.com/augments/time-skip/) | não informado | sim, conferir identidade |
| [Tons of Stats!](https://www.tftraits.com/augments/tons-of-stats/) | não informado | não |
| [TONS of Stats!](https://www.tftraits.com/augments/tons-of-stats-2/) | não informado | não |
| [Trade Sector](https://www.tftraits.com/augments/trade-sector/) | não informado | sim, conferir identidade |
| [Trade Sector+](https://www.tftraits.com/augments/trade-sector-2/) | não informado | sim, conferir identidade |
| [Trait Ladder](https://www.tftraits.com/augments/trait-ladder/) | não informado | sim, conferir identidade |
| [Twin Guardians](https://www.tftraits.com/augments/twin-guardians/) | não informado | sim, conferir identidade |
| [U.R.F](https://www.tftraits.com/augments/urf/) | não informado | sim, conferir identidade |
| [Upward Mobility](https://www.tftraits.com/augments/upward-mobility/) | não informado | sim, conferir identidade |
| [Urf's Grab Bag](https://www.tftraits.com/augments/urfs-grab-bag/) | não informado | sim, conferir identidade |
| [Verticality I](https://www.tftraits.com/augments/verticality-i/) | não informado | sim, conferir identidade |
| [Verticality II](https://www.tftraits.com/augments/verticality-ii/) | não informado | sim, conferir identidade |
| [Verticality III](https://www.tftraits.com/augments/verticality-iii/) | não informado | sim, conferir identidade |
| [Wand Overflow](https://www.tftraits.com/augments/wand-overflow/) | não informado | sim, conferir identidade |
| [Warpath](https://www.tftraits.com/augments/warpath/) | não informado | sim, conferir identidade |
| [We Stick Together](https://www.tftraits.com/augments/we-stick-together/) | não informado | sim, conferir identidade |
| [Weight the Worth](https://www.tftraits.com/augments/weight-the-worth/) | não informado | sim, conferir identidade |
| [Wisp Rebate](https://www.tftraits.com/augments/wisp-rebate/) | não informado | sim, conferir identidade |
| [Wisp Rebate+](https://www.tftraits.com/augments/wisp-rebate-2/) | não informado | sim, conferir identidade |
| [Worth the Wait](https://www.tftraits.com/augments/worth-the-wait/) | não informado | sim, conferir identidade |
| [Worth the Wait II](https://www.tftraits.com/augments/worth-the-wait-ii/) | não informado | sim, conferir identidade |
| [Woven Magic](https://www.tftraits.com/augments/woven-magic/) | não informado | sim, conferir identidade |
| [Young and Wild and Free](https://www.tftraits.com/augments/young-and-wild-and-free/) | não informado | sim, conferir identidade |

| Fogo-fátuo | Preço observado | Dependências sugeridas pelo texto |
|---|---|---|
| Abandon Ship | 0 | economy, randomness, shop |
| Bark Armor | 0 | shield, timing, units |
| Beggar's Wisp | 0 | economy, randomness |
| Coin Flip | 0 | economy, randomness |
| Curio Cart | 0 | economy, items |
| Early Fix | 0 | items |
| Found Friend | 0 | units |
| Life Debt | 0 | economy, healing |
| Minor Polymorph | 0 | persistence, randomness, units |
| Peddler | 0 | economy, items, randomness |
| Polymorph | 0 | persistence, randomness, units |
| Prolific Power | 0 | damage, units |
| Salvager | 0 | economy, items |
| Sinister Deal | 0 | economy, healing |
| Stealthy | 0 | crowd_control, position, randomness, timing, units |
| Truce | 0 | economy |
| Verdant Vitality | 0 | healing, units |
| Backrow Star | 1 | position, randomness, timing, units |
| Big Boom | 1 | damage, healing, level |
| Blast Potion | 1 |  |
| Borrowed Gear | 1 | healing, items, timing, units |
| Bunch-o'-Belts | 1 |  |
| Crystal Ball | 1 |  |
| Essence Theft | 1 | timing |
| Fertilize | 1 | level |
| Flash Fire | 1 | randomness, shop |
| Flip Frenzy | 1 | economy, randomness |
| Forest Mage | 1 | shop |
| Golden Goose | 1 | damage, economy, units |
| Health Potion | 1 | healing |
| Hugify | 1 | healing, position |
| Hummingbird | 1 |  |
| Iron Core | 1 | healing, position, units |
| Killer's Regret | 1 | crowd_control, timing, units |
| Lightning Strike | 1 | damage, healing |
| Mana Potion | 1 | mana |
| Minor Gambit | 1 | economy, timing |
| Nature's Wrath | 1 | items, timing |
| Petrify Shields | 1 | shield, timing |
| Pocket Change | 1 | economy, units |
| Rain | 1 | mana |
| Search Party | 1 | shop, timing |
| Starfall | 1 | randomness, shop, timing, units |
| Take One With Ya | 1 | level |
| Tattered Armor | 1 | timing |
| Ultra Ascension | 1 | damage, timing |
| Aftershock | 2 | crowd_control, timing |
| Artifactinate | 2 | items |
| Barter | 2 | economy, timing, units |
| Blood Money | 2 | economy, units |
| Counterspell | 2 | mana |
| Cutpurse | 2 | economy, randomness, timing, units |
| Die Roll | 2 | economy, randomness |
| Downpour | 2 | mana |
| Freeroller | 2 | randomness, shop |
| Golden Road | 2 | economy, timing |
| Healing Pool | 2 | healing |
| Hero's Entrance | 2 | items, timing, units |
| Homing Fireflies | 2 | damage, mana |
| Improved Reach | 2 |  |
| Ironwood | 2 | damage, healing, units |
| Killing Frenzy | 2 | healing |
| Mana-Rich Soil | 2 | mana |
| Marksmen's Gale | 2 | persistence |
| Moonlight Ritual | 2 | timing, units |
| Nature's Ally | 2 | randomness, units |
| Petrified Dummy | 2 | healing, units |
| Phantom Armor | 2 |  |
| Phantom Emblem | 2 | items |
| Phantom Splash | 2 | timing, units |
| Plated Shields | 2 | shield, timing |
| Potioncraft | 2 |  |
| Propagate | 2 | units |
| Quicken | 2 | mana, timing, units |
| Regeneration | 2 | healing |
| Resistant | 2 | damage |
| Revenge | 2 | damage, persistence, units |
| Solitude's Cloak | 2 | damage, healing, position, units |
| Stand Alone | 2 | damage, healing, position, units |
| Sunfire Sorcery | 2 | damage, timing |
| Supercritical | 2 | damage |
| Terraforming | 2 | timing, units |
| Trophy Hunter | 2 | timing |
| Wrapped In Thorns | 2 | damage, position, timing |
| Yordle Spirit | 2 | randomness, timing |
| Barrier | 3 | shield, timing |
| Blaze | 3 | damage |
| Bulwark | 3 | healing, shield |
| Combust | 3 | damage, healing, level, units |
| Diversified | 3 | healing |
| Fellowship | 3 | damage, healing, position, shield, units |
| Giant's Aura | 3 | damage, healing |
| Heated Rivalry | 3 |  |
| Lightning Storm | 3 | damage, healing, timing |
| Major Gambit | 3 | economy, timing |
| Marksmen's Marks | 3 | randomness |
| Mercenary Force | 3 | damage, economy |
| Minor Blood Ritual | 3 | healing, units |
| Payday | 3 | economy, timing, units |
| Radiantize | 3 | items, randomness, timing |
| Ride the Wave | 3 | randomness, shop, timing, units |
| Rolling Bones | 3 | randomness, shop |
| Roly-Polys | 3 | randomness, shop, timing, units |
| Scrappy | 3 | items, timing, units |
| Slow Study | 3 | level, timing, units |
| Training Yard | 3 | items, randomness |
| Treetop Archers | 3 | damage, timing |
| Tremors | 3 | crowd_control, timing |
| Blood and Iron | 4 | items, units |
| Component Bounty | 4 | items, randomness, timing |
| Forest Twins | 4 | units |
| Giant Growth | 4 | healing, position |
| Good Loss | 4 | level, timing |
| Greater Chaos | 4 | economy, mana, randomness |
| Idle Craftsman | 4 | items |
| Infliction | 4 | damage, timing |
| Clone Companion | 5 | damage, units |
| Heroic Sacrifice | 5 | units |
| Blood Ritual | 6 | healing, units |
| Booster Shot | 6 | timing, units |
| Hand of Baron | 6 |  |
| Animate Shop | 8 | randomness, shop, timing |
| Hero of Prophecy | 35 | persistence, timing, units |
| All Fives | não informado | economy, randomness, shop, units |
| All Fours | não informado | economy, randomness, shop, units |
| All Ones | não informado | economy, randomness, shop, units |
| All Threes | não informado | economy, randomness, shop, units |
| All Twos | não informado | economy, randomness, shop, units |
| Border Village | não informado | randomness, shop, units |
| Doodad Bag | não informado | healing, persistence |
| Doodad Jar | não informado | healing, persistence |
| Doodad Sack | não informado | healing, persistence |
| Flow | não informado | crowd_control, timing, units |
| Hireling | não informado | items, units |
| Knick-Knack Bag | não informado | damage, persistence |
| Knick-Knack Jar | não informado | damage, persistence |
| Knick-Knack Sack | não informado | damage, persistence |
| Late Bloomer | não informado | items, units |
| Living Soil | não informado | crowd_control, timing |
| Lucky 7 | não informado | randomness, shop |
| Middle Path | não informado | randomness, shop, units |
| Moonrise | não informado | timing |
| Preppers | não informado | items, persistence, timing, units |
| Refreshing Light | não informado | randomness, shop, units |
| Starting Town | não informado | randomness, shop, units |
| Thingamajig Bag | não informado | mana, persistence |
| Thingamajig Jar | não informado | mana, persistence |
| Thingamajig Sack | não informado | mana, persistence |

Os 25 preços ausentes permanecem desconhecidos, sem preenchimento com zero.
Disponibilidade por estágio, fórmulas, probabilidades e interações ainda exigem confirmação.
As variantes de aprimoramentos com nomes iguais precisam de ID e regras de elegibilidade.
