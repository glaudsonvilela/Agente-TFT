//! Registro de pecas TFT por jogador. Recebe observacoes de OCR/detector;
//! nao controla o mouse nem captura a tela. Compila sem dependencias externas.
use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct Champion {
    pub name: String,
    pub cost: u8,
    pub pool_identity: Option<String>, // None para invocacoes/pecas fora da loja.
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Place {
    Bench(u8),
    Board { row: u8, col: u8 },
}

/// Associa a seta dourada na borda direita a uma linha do placar.
/// Entrada: pixels RGB ja decodificados em 1920x1080 e linhas localizadas
/// pelo leitor do placar. Resultado visual candidato; confirme em outro
/// quadro da mesma arena antes de usar em `confirm_inspection`.
pub fn arrow_owner_candidate(rgb: &[u8], width: usize, height: usize,
                             scoreboard_rows: &[(String, usize)]) -> Option<String> {
    if width != 1920 || height != 1080 || rgb.len() != width * height * 3 {
        return None;
    }
    let mut ranked = Vec::new();
    for (player, center_y) in scoreboard_rows {
        let mut gold = 0_usize;
        for y in center_y.saturating_sub(22)..(*center_y + 23).min(height) {
            for x in width - 16..width {
                let offset = (y * width + x) * 3;
                let (r, g, b) = (u16::from(rgb[offset]), u16::from(rgb[offset + 1]),
                                 u16::from(rgb[offset + 2]));
                if r > 130 && g > 85 && r * 2 > b * 3 && g * 4 > b * 5 {
                    gold += 1;
                }
            }
        }
        ranked.push((gold, player));
    }
    ranked.sort_by(|a, b| b.0.cmp(&a.0));
    let (best, owner) = ranked.first()?;
    let second = ranked.get(1).map_or(0, |row| row.0);
    if *best >= 140 && *best >= second * 2 {
        Some((*owner).clone())
    } else {
        None
    }
}

/// Mantem o dono da arena por no maximo 1,5 s quando o painel cobre a seta.
/// Uma mudanca de camera invalida imediatamente o dono anterior.
#[derive(Default)]
pub struct ArenaOwnerTracker {
    confirmed: Option<String>,
    pending: Option<(String, u8)>,
    last_arrow_ms: Option<u64>,
}

impl ArenaOwnerTracker {
    pub fn update(&mut self, arrow_candidate: Option<&str>, now_ms: u64,
                  camera_changed: bool) -> Option<&str> {
        if camera_changed || self.last_arrow_ms.is_some_and(|last| now_ms < last) {
            *self = Self::default();
        }
        if let Some(name) = arrow_candidate {
            self.last_arrow_ms = Some(now_ms);
            if self.confirmed.as_deref() == Some(name) {
                self.pending = None;
            } else {
                self.confirmed = None;
                let votes = match &self.pending {
                    Some((old, count)) if old == name => count.saturating_add(1),
                    _ => 1,
                };
                if votes >= 2 {
                    self.confirmed = Some(name.to_owned());
                    self.pending = None;
                } else {
                    self.pending = Some((name.to_owned(), votes));
                }
            }
        } else if self.last_arrow_ms.is_some_and(|last| now_ms - last > 1500) {
            self.confirmed = None;
            self.pending = None;
        }
        self.confirmed.as_deref()
    }
}

#[derive(Clone, Debug)]
pub struct Piece {
    pub player: String,
    pub track: u64,
    pub champion: Option<String>,     // Somente identidade confirmada.
    pub visual_guess: Option<String>, // Palpite; nunca vira confirmacao sozinho.
    pub stars: u8,
    pub stars_verified: bool,
    pub place: Place,
    pub items: Vec<String>,
    pub last_scan: u64,
    pub active: bool,
}

pub struct Registry {
    pub catalog: HashMap<String, Champion>,
    pub pieces: HashMap<(String, u64), Piece>,
    open_scans: HashMap<String, u64>,
}

impl Registry {
    pub fn new(catalog: Vec<Champion>) -> Self {
        Self {
            catalog: catalog.into_iter().map(|c| (c.name.clone(), c)).collect(),
            pieces: HashMap::new(),
            open_scans: HashMap::new(),
        }
    }

    /// `scan` e o instante monotonicamente crescente da visita, em ms.
    pub fn begin_scan(&mut self, player: &str, scan: u64) -> Result<(), &'static str> {
        if self.open_scans.contains_key(player) {
            return Err("visita anterior ainda aberta");
        }
        self.open_scans.insert(player.to_owned(), scan);
        Ok(())
    }

    fn require_scan(&self, player: &str, scan: u64) -> Result<(), &'static str> {
        if self.open_scans.get(player) != Some(&scan) {
            return Err("visita do jogador nao esta aberta");
        }
        Ok(())
    }

    /// Registra todas as barras/pecas vistas, com ou sem nome.
    pub fn observe(&mut self, player: &str, scan: u64, track: u64, place: Place,
                   stars: u8, stars_verified: bool, items: Vec<String>, guess: Option<&str>)
                   -> Result<(), &'static str> {
        self.require_scan(player, scan)?;
        if !(1..=3).contains(&stars) {
            return Err("estrelas fora do intervalo suportado");
        }
        if let Some(name) = guess {
            if !self.catalog.contains_key(name) {
                return Err("palpite fora do catalogo");
            }
        }
        let key = (player.to_owned(), track);
        let piece = self.pieces.entry(key).or_insert_with(|| Piece {
            player: player.to_owned(), track, champion: None,
            visual_guess: None, stars, stars_verified, place: place.clone(),
            items: Vec::new(),
            last_scan: scan, active: true,
        });
        piece.place = place;
        piece.stars = stars;
        piece.stars_verified = stars_verified;
        piece.items = items;
        piece.last_scan = scan;
        piece.active = true;
        piece.visual_guess = guess.map(str::to_owned);
        Ok(())
    }

    /// Compra propria: exatamente uma carta desapareceu, uma nova trilha entrou
    /// no banco e o ouro caiu pelo custo daquela carta.
    pub fn confirm_purchase(&mut self, player: &str, scan: u64,
                            disappeared_cards: &[String], new_tracks: &[u64],
                            gold_before: i32, gold_after: i32)
                            -> Result<(), &'static str> {
        self.require_scan(player, scan)?;
        if disappeared_cards.len() != 1 || new_tracks.len() != 1 {
            return Err("compra ambigua");
        }
        let name = &disappeared_cards[0];
        let cost = self.catalog.get(name).ok_or("carta fora do catalogo")?.cost;
        if gold_before - gold_after != i32::from(cost) {
            return Err("ouro nao confirma a compra");
        }
        let piece = self.pieces.get_mut(&(player.to_owned(), new_tracks[0]))
            .ok_or("nova peca nao observada")?;
        if piece.last_scan != scan || !matches!(piece.place, Place::Bench(_)) {
            return Err("nova peca nao esta no banco desta visita");
        }
        if piece.champion.as_ref().is_some_and(|old| old != name) {
            return Err("compra contradiz identidade anterior");
        }
        piece.champion = Some(name.clone());
        Ok(())
    }

    /// A seta dourada identifica o dono da arena. O chamador tambem deve
    /// demonstrar que a peca selecionada pertence a ele (planejamento ou
    /// lado de combate confirmado), pois uma arena pode conter dois times.
    /// Um painel antigo pode sobreviver a uma troca de camera: exigir que
    /// a arena seja a mesma e que o painel tenha atualizado apos a selecao.
    /// Duas leituras em quadros diferentes precisam concordar.
    pub fn confirm_inspection(&mut self, player: &str, scan: u64,
                              golden_arrow_owner: &str, resident_unit_confirmed: bool,
                              same_arena_since_arrow: bool, panel_updated_after_selection: bool,
                              selected_track: u64, observed_track: u64,
                              first_read: &str, second_read: &str)
                              -> Result<(), &'static str> {
        self.require_scan(player, scan)?;
        if golden_arrow_owner != player || !resident_unit_confirmed {
            return Err("dono da arena ou lado da peca nao confirmado");
        }
        if !same_arena_since_arrow || !panel_updated_after_selection {
            return Err("troca de arena ou painel antigo");
        }
        if selected_track != observed_track {
            return Err("painel nao corresponde a peca selecionada");
        }
        let first = self.resolve_name(first_read).ok_or("primeira leitura sem nome unico")?;
        let second = self.resolve_name(second_read).ok_or("segunda leitura sem nome unico")?;
        if first != second {
            return Err("leituras do painel discordam");
        }
        let piece = self.pieces.get_mut(&(player.to_owned(), observed_track))
            .ok_or("peca selecionada nao observada")?;
        if piece.last_scan != scan {
            return Err("peca nao observada nesta visita");
        }
        if piece.champion.as_ref().is_some_and(|old| old != &first) {
            return Err("painel contradiz identidade anterior");
        }
        piece.champion = Some(first);
        Ok(())
    }

    fn resolve_name(&self, raw: &str) -> Option<String> {
        let clean = raw.split_whitespace().collect::<Vec<_>>().join(" ");
        let matches: Vec<_> = self.catalog.keys()
            .filter(|name| name.to_lowercase() == clean.to_lowercase()).collect();
        if matches.len() == 1 { Some(matches[0].clone()) } else { None }
    }

    /// So uma visita completa pode retirar pecas antigas do registro ativo.
    pub fn finish_scan(&mut self, player: &str, scan: u64)
                       -> Result<(), &'static str> {
        self.require_scan(player, scan)?;
        for piece in self.pieces.values_mut().filter(|p| p.player == player) {
            if piece.last_scan != scan { piece.active = false; }
        }
        self.open_scans.remove(player);
        Ok(())
    }

    pub fn shown_name(&self, player: &str, track: u64) -> Option<String> {
        let piece = self.pieces.get(&(player.to_owned(), track))?;
        if let Some(name) = &piece.champion { return Some(name.clone()); }
        piece.visual_guess.as_ref().map(|name| format!("{name}?"))
    }

    /// Limite inferior de copias vistas e confirmadas, sem duplicar a mesma
    /// trilha entre banco e tabuleiro. Identidades nao vistas ficam fora da conta.
    pub fn known_pool_copies(&self, now_ms: u64, max_age_ms: u64)
                             -> HashMap<String, u32> {
        let mut copies = HashMap::new();
        for piece in self.pieces.values().filter(|p| p.active && p.stars_verified &&
                now_ms >= p.last_scan && now_ms - p.last_scan <= max_age_ms) {
            let Some(name) = &piece.champion else { continue };
            let Some(identity) = self.catalog.get(name).and_then(|c| c.pool_identity.as_ref())
                else { continue };
            *copies.entry(identity.clone()).or_insert(0) += 3_u32.pow(u32::from(piece.stars - 1));
        }
        copies
    }

    /// P(um campeao na proxima casa da loja), condicionado a tratar todas as
    /// copias nao observadas como ainda disponiveis. Nao e probabilidade real
    /// quando adversarios/bancos nao foram vistos recentemente.
    pub fn conditional_shop_odds(&self, now_ms: u64, max_age_ms: u64,
                                 level_odds: [f64; 5], pool_per_cost: [u32; 5])
                                 -> HashMap<String, f64> {
        let known = self.known_pool_copies(now_ms, max_age_ms);
        let mut remaining = HashMap::new();
        let mut tier_total = [0_u32; 5];
        for champion in self.catalog.values() {
            let Some(identity) = &champion.pool_identity else { continue };
            let tier = usize::from(champion.cost.saturating_sub(1));
            if tier >= 5 || remaining.contains_key(identity) { continue; }
            let left = pool_per_cost[tier].saturating_sub(*known.get(identity).unwrap_or(&0));
            remaining.insert(identity.clone(), (tier, left));
            tier_total[tier] += left;
        }
        remaining.into_iter().map(|(identity, (tier, left))| {
            let p = if tier_total[tier] == 0 { 0.0 } else {
                level_odds[tier] * f64::from(left) / f64::from(tier_total[tier])
            };
            (identity, p)
        }).collect()
    }
}

fn main() {
    // Substitua pelos campeoes, tamanhos de pool e chances do patch ativo.
    let mut registry = Registry::new(vec![
        Champion { name: "Morgana".into(), cost: 4, pool_identity: Some("Morgana".into()) },
        Champion { name: "Kayle".into(), cost: 4, pool_identity: Some("Kayle".into()) },
    ]);
    registry.begin_scan("rival-1", 1).unwrap();
    registry.observe("rival-1", 1, 42, Place::Bench(2), 2, true, vec![],
                     Some("Kayle")).unwrap();
    registry.confirm_inspection("rival-1", 1, "rival-1", true, true, true, 42, 42,
                                "Morgana", "Morgana").unwrap();
    registry.finish_scan("rival-1", 1).unwrap();
    println!("nome: {:?}", registry.shown_name("rival-1", 42));
    println!("copias observadas: {:?}", registry.known_pool_copies(1, 10_000));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scan_moves_and_pool_do_not_double_count() {
        let mut r = Registry::new(vec![Champion { name: "Morgana".into(), cost: 4,
            pool_identity: Some("Morgana".into()) }]);
        r.begin_scan("enemy", 1).unwrap();
        r.observe("enemy", 1, 7, Place::Bench(0), 2, true, vec![], None).unwrap();
        assert!(r.confirm_inspection("enemy", 1, "enemy", true, true, true, 8, 7,
                                     "Morgana", "Morgana").is_err());
        assert!(r.confirm_inspection("enemy", 1, "self", true, true, true, 7, 7,
                                     "Morgana", "Morgana").is_err());
        assert!(r.confirm_inspection("enemy", 1, "enemy", false, true, true, 7, 7,
                                     "Morgana", "Morgana").is_err());
        assert!(r.confirm_inspection("enemy", 1, "enemy", true, false, true, 7, 7,
                                     "Morgana", "Morgana").is_err());
        assert!(r.confirm_inspection("enemy", 1, "enemy", true, true, false, 7, 7,
                                     "Morgana", "Morgana").is_err());
        r.confirm_inspection("enemy", 1, "enemy", true, true, true, 7, 7,
                             "Morgana", "Morgana").unwrap();
        r.finish_scan("enemy", 1).unwrap();
        r.begin_scan("enemy", 2).unwrap();
        r.observe("enemy", 2, 7, Place::Board { row: 1, col: 3 }, 2, true,
                  vec![], None).unwrap();
        r.finish_scan("enemy", 2).unwrap();
        assert_eq!(r.known_pool_copies(2, 10)["Morgana"], 3);
        r.begin_scan("enemy", 3).unwrap();
        r.finish_scan("enemy", 3).unwrap();
        assert!(r.known_pool_copies(3, 10).get("Morgana").is_none());
    }

    #[test]
    fn guess_does_not_become_confirmed_identity() {
        let mut r = Registry::new(vec![Champion { name: "Kayle".into(), cost: 4,
            pool_identity: Some("Kayle".into()) }]);
        r.begin_scan("enemy", 1).unwrap();
        r.observe("enemy", 1, 9, Place::Bench(1), 1, false,
                  vec![], Some("Kayle")).unwrap();
        r.finish_scan("enemy", 1).unwrap();
        assert_eq!(r.shown_name("enemy", 9).as_deref(), Some("Kayle?"));
        assert!(r.known_pool_copies(1, 10).is_empty());
    }

    #[test]
    fn inspection_records_enemy_board_and_bench_under_same_player() {
        let mut r = Registry::new(vec![
            Champion { name: "Morgana".into(), cost: 4,
                pool_identity: Some("Morgana".into()) },
            Champion { name: "Kayle".into(), cost: 4,
                pool_identity: Some("Kayle".into()) },
        ]);
        r.begin_scan("player-2", 100).unwrap();
        r.observe("player-2", 100, 11, Place::Board { row: 2, col: 3 },
                  1, true, vec![], None).unwrap();
        r.observe("player-2", 100, 12, Place::Bench(4),
                  2, true, vec![], None).unwrap();
        r.confirm_inspection("player-2", 100, "player-2", true, true, true,
                             11, 11, "Morgana", "Morgana").unwrap();
        r.confirm_inspection("player-2", 100, "player-2", true, true, true,
                             12, 12, "Kayle", "Kayle").unwrap();
        r.finish_scan("player-2", 100).unwrap();
        assert_eq!(r.shown_name("player-2", 11).as_deref(), Some("Morgana"));
        assert_eq!(r.shown_name("player-2", 12).as_deref(), Some("Kayle"));
        assert_eq!(r.known_pool_copies(100, 1000)["Morgana"], 1);
        assert_eq!(r.known_pool_copies(100, 1000)["Kayle"], 3);
    }

    #[test]
    fn purchase_and_conditional_shop_math_use_confirmed_copies() {
        let mut r = Registry::new(vec![
            Champion { name: "Morgana".into(), cost: 4,
                pool_identity: Some("Morgana".into()) },
            Champion { name: "Kayle".into(), cost: 4,
                pool_identity: Some("Kayle".into()) },
        ]);
        r.begin_scan("self", 100).unwrap();
        r.observe("self", 100, 1, Place::Bench(0), 1, true, vec![], None).unwrap();
        let card = vec!["Morgana".to_owned()];
        assert!(r.confirm_purchase("self", 100, &card, &[1], 50, 45).is_err());
        r.confirm_purchase("self", 100, &card, &[1], 50, 46).unwrap();
        r.finish_scan("self", 100).unwrap();
        r.begin_scan("enemy", 100).unwrap();
        r.observe("enemy", 100, 2, Place::Board { row: 0, col: 0 },
                  2, true, vec![], None).unwrap();
        r.confirm_inspection("enemy", 100, "enemy", true, true, true, 2, 2,
                             "Morgana", "Morgana").unwrap();
        r.finish_scan("enemy", 100).unwrap();
        assert_eq!(r.known_pool_copies(100, 10)["Morgana"], 4);
        let odds = r.conditional_shop_odds(100, 10, [0.0, 0.0, 0.0, 0.2, 0.8],
                                           [30, 25, 18, 10, 9]);
        assert!((odds["Morgana"] - 0.075).abs() < 1e-12);
        assert!(r.known_pool_copies(111, 10).is_empty());
    }

    #[test]
    fn gold_arrow_associates_owner_without_confusing_avatar_ring() {
        let (width, height) = (1920_usize, 1080_usize);
        let mut rgb = vec![0_u8; width * height * 3];
        for (center, pixels) in [(610_usize, 220_usize), (530, 50)] {
            for n in 0..pixels {
                let x = width - 16 + n % 16;
                let y = center - 20 + n / 16;
                let offset = (y * width + x) * 3;
                rgb[offset..offset + 3].copy_from_slice(&[190, 150, 60]);
            }
        }
        let rows = vec![("self".to_owned(), 530), ("Gustavo0410".to_owned(), 610)];
        assert_eq!(arrow_owner_candidate(&rgb, width, height, &rows).as_deref(),
                   Some("Gustavo0410"));
        assert_eq!(arrow_owner_candidate(&rgb[..100], width, height, &rows), None);
    }

    #[test]
    fn arena_owner_survives_brief_occlusion_but_not_camera_cut() {
        let mut owner = ArenaOwnerTracker::default();
        assert_eq!(owner.update(Some("Gustavo0410"), 1000, false), None);
        assert_eq!(owner.update(Some("Gustavo0410"), 1200, false), Some("Gustavo0410"));
        assert_eq!(owner.update(None, 1400, false), Some("Gustavo0410"));
        assert_eq!(owner.update(None, 1500, true), None);
        assert_eq!(owner.update(None, 1600, false), None);
        assert_eq!(owner.update(Some("bolapresidente"), 1700, false), None);
        assert_eq!(owner.update(Some("bolapresidente"), 1900, false), Some("bolapresidente"));
        assert_eq!(owner.update(None, 3501, false), None);
    }
}
