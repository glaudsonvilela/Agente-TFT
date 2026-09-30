use agente_tft_contracts::{
    Confidence, GameEventKind, GameState, MatchPhase, Observed, OpponentState, PlayerState,
    ShopSlot, UnitInstance,
};
use agente_tft_perception_core::{ConsensusConfig, TemporalConsensus};
use agente_tft_state_engine::diff_event_kinds;

#[derive(Debug, Clone, Default, PartialEq)]
pub struct HudObservationBatch {
    pub observed_at_ms: u64,
    pub hp: Option<Observed<u16>>,
    pub gold: Option<Observed<u16>>,
    pub level: Option<Observed<u8>>,
    pub xp: Option<Observed<u16>>,
    pub stage: Option<Observed<String>>,
}


#[derive(Debug, Clone)]
pub struct ShopObservationBatch {
    pub observed_at_ms: u64,
    pub slots: Vec<Observed<ShopSlot>>,
}

#[derive(Debug, Clone)]
struct ShopPending {
    signature: Vec<(u8, Option<String>)>,
    confirmations: u8,
    last_seen_ms: u64,
    best_min_confidence: f32,
    best_slots: Vec<Observed<ShopSlot>>,
}

#[derive(Debug)]
struct ShopGate {
    config: ConsensusConfig,
    pending: Option<ShopPending>,
}

impl ShopGate {
    fn new(config: ConsensusConfig) -> Self {
        Self {
            config: ConsensusConfig {
                min_confidence: config.min_confidence.clamp(0.0, 1.0),
                confirmations: config.confirmations.max(1),
                max_gap_ms: config.max_gap_ms,
            },
            pending: None,
        }
    }

    fn observe(
        &mut self,
        batch: ShopObservationBatch,
    ) -> Option<Vec<Observed<ShopSlot>>> {
        if batch.slots.is_empty() {
            return None;
        }

        let mut seen = std::collections::BTreeSet::new();
        if batch.slots.iter().any(|slot| !seen.insert(slot.value.slot)) {
            return None;
        }

        let min_confidence = batch
            .slots
            .iter()
            .map(|slot| slot.confidence.value())
            .fold(1.0_f32, f32::min);

        if min_confidence < self.config.min_confidence {
            return None;
        }

        let signature = semantic_shop(&batch.slots);
        let should_reset = self
            .pending
            .as_ref()
            .map(|pending| {
                pending.signature != signature
                    || batch
                        .observed_at_ms
                        .saturating_sub(pending.last_seen_ms)
                        > self.config.max_gap_ms
            })
            .unwrap_or(true);

        if should_reset {
            self.pending = Some(ShopPending {
                signature,
                confirmations: 1,
                last_seen_ms: batch.observed_at_ms,
                best_min_confidence: min_confidence,
                best_slots: batch.slots,
            });
        } else if let Some(pending) = &mut self.pending {
            pending.confirmations = pending.confirmations.saturating_add(1);
            pending.last_seen_ms = batch.observed_at_ms;
            if min_confidence >= pending.best_min_confidence {
                pending.best_min_confidence = min_confidence;
                pending.best_slots = batch.slots;
            }
        }

        let pending = self.pending.as_ref()?;
        if pending.confirmations >= self.config.confirmations {
            Some(sorted_shop(pending.best_slots.clone()))
        } else {
            None
        }
    }

    fn reset(&mut self) {
        self.pending = None;
    }
}

fn semantic_shop(slots: &[Observed<ShopSlot>]) -> Vec<(u8, Option<String>)> {
    let mut signature: Vec<_> = slots
        .iter()
        .map(|slot| (slot.value.slot, slot.value.unit_id.clone()))
        .collect();
    signature.sort_by_key(|(slot, _)| *slot);
    signature
}

fn sorted_shop(mut slots: Vec<Observed<ShopSlot>>) -> Vec<Observed<ShopSlot>> {
    slots.sort_by_key(|slot| slot.value.slot);
    slots
}


#[derive(Debug, Clone)]
pub struct OpponentObservationBatch {
    pub player_id: String,
    pub display_name: Option<String>,
    pub hp: Option<Observed<u16>>,
    pub level: Option<Observed<u8>>,
    pub board: Vec<Observed<UnitInstance>>,
    pub complete_board: bool,
    pub observed_at_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct UnitSemanticKey {
    row: u8,
    col: u8,
    unit_id: String,
    stars: u8,
    items: Vec<String>,
}

#[derive(Debug, Clone)]
struct OpponentPending {
    signature: Vec<UnitSemanticKey>,
    confirmations: u8,
    last_seen_ms: u64,
    best_min_confidence: f32,
    best: OpponentObservationBatch,
    emitted: bool,
}

#[derive(Debug)]
struct OpponentGate {
    config: ConsensusConfig,
    pending: Option<OpponentPending>,
}

impl OpponentGate {
    fn new(config: ConsensusConfig) -> Self {
        Self {
            config: ConsensusConfig {
                min_confidence: config.min_confidence.clamp(0.0, 1.0),
                confirmations: config.confirmations.max(1),
                max_gap_ms: config.max_gap_ms,
            },
            pending: None,
        }
    }

    fn observe(
        &mut self,
        batch: OpponentObservationBatch,
    ) -> Option<OpponentObservationBatch> {
        if !batch.complete_board || batch.player_id.trim().is_empty() {
            return None;
        }

        let min_confidence = opponent_batch_confidence(&batch);
        if min_confidence < self.config.min_confidence {
            return None;
        }

        let signature = semantic_units(&batch.board);
        let should_reset = self
            .pending
            .as_ref()
            .map(|pending| {
                pending.signature != signature
                    || batch
                        .observed_at_ms
                        .saturating_sub(pending.last_seen_ms)
                        > self.config.max_gap_ms
            })
            .unwrap_or(true);

        if should_reset {
            self.pending = Some(OpponentPending {
                signature,
                confirmations: 1,
                last_seen_ms: batch.observed_at_ms,
                best_min_confidence: min_confidence,
                best: batch,
                emitted: false,
            });
        } else if let Some(pending) = &mut self.pending {
            pending.confirmations = pending.confirmations.saturating_add(1);
            pending.last_seen_ms = batch.observed_at_ms;
            if min_confidence >= pending.best_min_confidence {
                pending.best_min_confidence = min_confidence;
                pending.best = batch;
            }
        }

        let pending = self.pending.as_mut()?;
        if pending.confirmations < self.config.confirmations || pending.emitted {
            return None;
        }

        pending.emitted = true;
        Some(pending.best.clone())
    }
}

fn semantic_units(units: &[Observed<UnitInstance>]) -> Vec<UnitSemanticKey> {
    let mut result: Vec<_> = units
        .iter()
        .map(|observed| {
            let mut items = observed.value.items.clone();
            items.sort();
            UnitSemanticKey {
                row: observed.value.position.map(|p| p.row).unwrap_or(u8::MAX),
                col: observed.value.position.map(|p| p.col).unwrap_or(u8::MAX),
                unit_id: observed.value.unit_id.clone(),
                stars: observed.value.stars,
                items,
            }
        })
        .collect();

    result.sort_by(|a, b| {
        (a.row, a.col, &a.unit_id, a.stars, &a.items)
            .cmp(&(b.row, b.col, &b.unit_id, b.stars, &b.items))
    });
    result
}

fn opponent_batch_confidence(batch: &OpponentObservationBatch) -> f32 {
    let mut values = Vec::new();
    values.extend(batch.board.iter().map(|unit| unit.confidence.value()));
    if let Some(hp) = &batch.hp {
        values.push(hp.confidence.value());
    }
    if let Some(level) = &batch.level {
        values.push(level.confidence.value());
    }

    if values.is_empty() {
        0.0
    } else {
        values.into_iter().fold(1.0_f32, f32::min)
    }
}

fn opponent_state_from_batch(batch: OpponentObservationBatch) -> OpponentState {
    let confidence = Confidence::new(opponent_batch_confidence(&batch))
        .unwrap_or_default();
    let mut board: Vec<_> = batch.board.into_iter().map(|unit| unit.value).collect();
    board.sort_by(|a, b| {
        let a_pos = a.position.map(|p| (p.row, p.col)).unwrap_or((u8::MAX, u8::MAX));
        let b_pos = b.position.map(|p| (p.row, p.col)).unwrap_or((u8::MAX, u8::MAX));
        a_pos.cmp(&b_pos).then_with(|| a.unit_id.cmp(&b.unit_id))
    });

    OpponentState {
        player_id: batch.player_id,
        display_name: batch.display_name,
        hp: batch.hp,
        level: batch.level,
        board,
        last_seen_ms: batch.observed_at_ms,
        confidence,
    }
}

#[derive(Debug)]
struct HudGates {
    hp: TemporalConsensus<u16>,
    gold: TemporalConsensus<u16>,
    level: TemporalConsensus<u8>,
    xp: TemporalConsensus<u16>,
    stage: TemporalConsensus<String>,
}

impl HudGates {
    fn new(config: ConsensusConfig) -> Self {
        Self {
            hp: TemporalConsensus::new(config),
            gold: TemporalConsensus::new(config),
            level: TemporalConsensus::new(config),
            xp: TemporalConsensus::new(config),
            stage: TemporalConsensus::new(config),
        }
    }
}

#[derive(Debug)]
pub struct StateFusion {
    state: GameState,
    hud: HudGates,
    shop: ShopGate,
    opponents: std::collections::HashMap<String, OpponentGate>,
}

impl StateFusion {
    pub fn new(now_ms: u64, consensus: ConsensusConfig) -> Self {
        Self {
            state: GameState::empty(now_ms),
            hud: HudGates::new(consensus),
            shop: ShopGate::new(consensus),
            opponents: std::collections::HashMap::new(),
        }
    }

    pub fn state(&self) -> &GameState {
        &self.state
    }

    pub fn set_match_context(
        &mut self,
        match_id: Option<String>,
        patch: Option<String>,
        set: Option<String>,
    ) -> Vec<GameEventKind> {
        let previous = self.state.clone();
        let mut changed = false;

        if self.state.match_id != match_id {
            self.state.match_id = match_id;
            changed = true;
        }
        if self.state.patch != patch {
            self.state.patch = patch;
            changed = true;
        }
        if self.state.set != set {
            self.state.set = set;
            changed = true;
        }

        if changed {
            self.state.revision = self.state.revision.saturating_add(1);
        }

        diff_event_kinds(&previous, &self.state)
    }

    pub fn set_phase(&mut self, phase: MatchPhase, now_ms: u64) -> Vec<GameEventKind> {
        if self.state.phase == phase {
            self.state.observed_at_ms = self.state.observed_at_ms.max(now_ms);
            return Vec::new();
        }

        let previous = self.state.clone();
        self.state.phase = phase;
        self.state.observed_at_ms = self.state.observed_at_ms.max(now_ms);
        self.state.revision = self.state.revision.saturating_add(1);

        diff_event_kinds(&previous, &self.state)
    }

    pub fn apply_hud(&mut self, batch: HudObservationBatch) -> Vec<GameEventKind> {
        let previous = self.state.clone();
        let mut semantic_change = false;

        if let Some(candidate) = batch.hp {
            if let Some(stable) = self.hud.hp.observe(candidate) {
                semantic_change |= assign_observed(&mut self.state.player.hp, stable);
            }
        }

        if let Some(candidate) = batch.gold {
            if let Some(stable) = self.hud.gold.observe(candidate) {
                semantic_change |= assign_observed(&mut self.state.player.gold, stable);
            }
        }

        if let Some(candidate) = batch.level {
            if let Some(stable) = self.hud.level.observe(candidate) {
                semantic_change |= assign_observed(&mut self.state.player.level, stable);
            }
        }

        if let Some(candidate) = batch.xp {
            if let Some(stable) = self.hud.xp.observe(candidate) {
                semantic_change |= assign_observed(&mut self.state.player.xp, stable);
            }
        }

        if let Some(candidate) = batch.stage {
            if let Some(stable) = self.hud.stage.observe(candidate) {
                semantic_change |= assign_observed(&mut self.state.player.stage, stable);
            }
        }

        self.state.observed_at_ms = self.state.observed_at_ms.max(batch.observed_at_ms);

        if semantic_change {
            self.state.revision = self.state.revision.saturating_add(1);
        }

        diff_event_kinds(&previous, &self.state)
    }



    pub fn apply_shop(&mut self, batch: ShopObservationBatch) -> Vec<GameEventKind> {
        let previous = self.state.clone();
        let observed_at_ms = batch.observed_at_ms;

        let Some(stable_slots) = self.shop.observe(batch) else {
            self.state.observed_at_ms = self.state.observed_at_ms.max(observed_at_ms);
            return Vec::new();
        };

        let semantic_change =
            semantic_shop(&self.state.player.shop) != semantic_shop(&stable_slots);

        if semantic_change {
            self.state.player.shop = stable_slots;
            self.state.revision = self.state.revision.saturating_add(1);
        } else {
            // Refresh metadata/confidence without creating a semantic revision.
            self.state.player.shop = stable_slots;
        }

        self.state.observed_at_ms = self.state.observed_at_ms.max(observed_at_ms);
        diff_event_kinds(&previous, &self.state)
    }

    pub fn reset_hud_consensus(&mut self) {
        self.hud.hp.reset();
        self.hud.gold.reset();
        self.hud.level.reset();
        self.hud.xp.reset();
        self.hud.stage.reset();
        self.shop.reset();
    }



    pub fn apply_opponent(
        &mut self,
        batch: OpponentObservationBatch,
        consensus: ConsensusConfig,
    ) -> Vec<GameEventKind> {
        let player_id = batch.player_id.clone();
        let gate = self
            .opponents
            .entry(player_id.clone())
            .or_insert_with(|| OpponentGate::new(consensus));

        let Some(stable) = gate.observe(batch) else {
            return Vec::new();
        };

        let previous = self.state.clone();
        let next = opponent_state_from_batch(stable);

        match self
            .state
            .lobby
            .iter_mut()
            .find(|opponent| opponent.player_id == player_id)
        {
            Some(existing) => *existing = next,
            None => self.state.lobby.push(next),
        }

        self.state
            .lobby
            .sort_by(|a, b| a.player_id.cmp(&b.player_id));
        self.state.observed_at_ms = self
            .state
            .observed_at_ms
            .max(
                self.state
                    .lobby
                    .iter()
                    .find(|opponent| opponent.player_id == player_id)
                    .map(|opponent| opponent.last_seen_ms)
                    .unwrap_or(self.state.observed_at_ms),
            );
        self.state.revision = self.state.revision.saturating_add(1);

        diff_event_kinds(&previous, &self.state)
    }

    pub fn reset_opponent_consensus(&mut self, player_id: Option<&str>) {
        match player_id {
            Some(player_id) => {
                self.opponents.remove(player_id);
            }
            None => self.opponents.clear(),
        }
    }

    pub fn replace_player_state(&mut self, player: PlayerState, now_ms: u64) -> Vec<GameEventKind> {
        let previous = self.state.clone();

        if self.state.player == player {
            self.state.observed_at_ms = self.state.observed_at_ms.max(now_ms);
            return Vec::new();
        }

        self.state.player = player;
        self.state.observed_at_ms = self.state.observed_at_ms.max(now_ms);
        self.state.revision = self.state.revision.saturating_add(1);

        diff_event_kinds(&previous, &self.state)
    }
}

fn assign_observed<T: PartialEq>(slot: &mut Option<Observed<T>>, value: Observed<T>) -> bool {
    let semantic_change = slot
        .as_ref()
        .map(|current| current.value != value.value)
        .unwrap_or(true);

    match slot {
        None => *slot = Some(value),
        Some(current) => {
            if semantic_change
                || value.observed_at_ms > current.observed_at_ms
                || value.confidence.value() > current.confidence.value()
            {
                *current = value;
            }
        }
    }

    semantic_change
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{
        Confidence, GameEventKind, ObservationSource, Observed,
    };

    use super::*;

    fn obs<T>(value: T, confidence: f32, at: u64) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(confidence).unwrap(),
            source: ObservationSource::Vision,
            observed_at_ms: at,
        }
    }

    fn fusion() -> StateFusion {
        StateFusion::new(
            0,
            ConsensusConfig {
                min_confidence: 0.80,
                confirmations: 2,
                max_gap_ms: 500,
            },
        )
    }

    #[test]
    fn single_hud_read_does_not_enter_state() {
        let mut fusion = fusion();

        let events = fusion.apply_hud(HudObservationBatch {
            observed_at_ms: 100,
            gold: Some(obs(50, 0.95, 100)),
            ..HudObservationBatch::default()
        });

        assert!(events.is_empty());
        assert!(fusion.state().player.gold.is_none());
        assert_eq!(fusion.state().revision, 0);
    }

    #[test]
    fn repeated_hud_read_is_promoted() {
        let mut fusion = fusion();

        fusion.apply_hud(HudObservationBatch {
            observed_at_ms: 100,
            gold: Some(obs(50, 0.90, 100)),
            ..HudObservationBatch::default()
        });

        fusion.apply_hud(HudObservationBatch {
            observed_at_ms: 150,
            gold: Some(obs(50, 0.96, 150)),
            ..HudObservationBatch::default()
        });

        assert_eq!(fusion.state().player.gold.as_ref().unwrap().value, 50);
        assert_eq!(fusion.state().revision, 1);
    }

    #[test]
    fn low_confidence_noise_does_not_replace_stable_value() {
        let mut fusion = fusion();

        for at in [100, 150] {
            fusion.apply_hud(HudObservationBatch {
                observed_at_ms: at,
                gold: Some(obs(50, 0.95, at)),
                ..HudObservationBatch::default()
            });
        }

        for at in [200, 250, 300] {
            fusion.apply_hud(HudObservationBatch {
                observed_at_ms: at,
                gold: Some(obs(43, 0.50, at)),
                ..HudObservationBatch::default()
            });
        }

        assert_eq!(fusion.state().player.gold.as_ref().unwrap().value, 50);
    }

    #[test]
    fn stable_gold_change_emits_event() {
        let mut fusion = fusion();

        for at in [100, 150] {
            fusion.apply_hud(HudObservationBatch {
                observed_at_ms: at,
                gold: Some(obs(50, 0.95, at)),
                ..HudObservationBatch::default()
            });
        }

        fusion.apply_hud(HudObservationBatch {
            observed_at_ms: 200,
            gold: Some(obs(48, 0.93, 200)),
            ..HudObservationBatch::default()
        });

        let events = fusion.apply_hud(HudObservationBatch {
            observed_at_ms: 250,
            gold: Some(obs(48, 0.94, 250)),
            ..HudObservationBatch::default()
        });

        assert!(events.iter().any(|event| matches!(
            event,
            GameEventKind::GoldChanged { from: 50, to: 48 }
        )));
    }

    #[test]
    fn phase_transition_emits_combat_started() {
        let mut fusion = fusion();
        fusion.set_phase(MatchPhase::Planning, 100);

        let events = fusion.set_phase(MatchPhase::Combat, 200);

        assert!(events
            .iter()
            .any(|event| matches!(event, GameEventKind::CombatStarted)));
    }
}
