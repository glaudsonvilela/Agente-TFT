use agente_tft_contracts::{Action, GameState};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum ShadowError {
    #[error("shadow session is not initialized")]
    NotInitialized,
    #[error("real state revision moved backwards")]
    RevisionRegression,
    #[error("simulator error: {0}")]
    Simulator(String),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShadowTransition {
    pub before_revision: u64,
    pub action: Action,
    pub simulated_state: GameState,
    pub reward: Option<f32>,
    #[serde(default)]
    pub metrics: serde_json::Value,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct DivergenceSummary {
    pub hp_changed: bool,
    pub gold_changed: bool,
    pub level_changed: bool,
    pub stage_changed: bool,
    pub board_changed: bool,
    pub bench_changed: bool,
    pub shop_changed: bool,
    pub lobby_changed: bool,
}

impl DivergenceSummary {
    pub const fn any(self) -> bool {
        self.hp_changed
            || self.gold_changed
            || self.level_changed
            || self.stage_changed
            || self.board_changed
            || self.bench_changed
            || self.shop_changed
            || self.lobby_changed
    }

    pub fn changed_fields(self) -> usize {
        [
            self.hp_changed,
            self.gold_changed,
            self.level_changed,
            self.stage_changed,
            self.board_changed,
            self.bench_changed,
            self.shop_changed,
            self.lobby_changed,
        ]
        .into_iter()
        .filter(|value| *value)
        .count()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReconciliationRecord {
    pub real_revision: u64,
    pub simulated_revision_before_reset: u64,
    pub divergence: DivergenceSummary,
}

pub trait ShadowSimulator {
    fn reset_to(&mut self, state: &GameState) -> Result<(), String>;

    fn apply_action(
        &mut self,
        state: &GameState,
        action: &Action,
    ) -> Result<ShadowTransition, String>;
}

pub struct ShadowPlayer<S> {
    simulator: S,
    real_checkpoint: Option<GameState>,
    simulated_state: Option<GameState>,
    history: Vec<ShadowTransition>,
    reconciliations: Vec<ReconciliationRecord>,
}

impl<S> ShadowPlayer<S>
where
    S: ShadowSimulator,
{
    pub fn new(simulator: S) -> Self {
        Self {
            simulator,
            real_checkpoint: None,
            simulated_state: None,
            history: Vec::new(),
            reconciliations: Vec::new(),
        }
    }

    pub fn initialize(&mut self, real_state: GameState) -> Result<(), ShadowError> {
        self.simulator
            .reset_to(&real_state)
            .map_err(ShadowError::Simulator)?;
        self.real_checkpoint = Some(real_state.clone());
        self.simulated_state = Some(real_state);
        self.history.clear();
        self.reconciliations.clear();
        Ok(())
    }

    pub fn current_state(&self) -> Option<&GameState> {
        self.simulated_state.as_ref()
    }

    pub fn history(&self) -> &[ShadowTransition] {
        &self.history
    }

    pub fn reconciliations(&self) -> &[ReconciliationRecord] {
        &self.reconciliations
    }

    pub fn step(&mut self, action: &Action) -> Result<&ShadowTransition, ShadowError> {
        let state = self
            .simulated_state
            .as_ref()
            .ok_or(ShadowError::NotInitialized)?;

        let transition = self
            .simulator
            .apply_action(state, action)
            .map_err(ShadowError::Simulator)?;

        self.simulated_state = Some(transition.simulated_state.clone());
        self.history.push(transition);
        Ok(self.history.last().expect("transition was just pushed"))
    }

    pub fn reconcile(
        &mut self,
        real_state: GameState,
    ) -> Result<ReconciliationRecord, ShadowError> {
        let previous_real = self
            .real_checkpoint
            .as_ref()
            .ok_or(ShadowError::NotInitialized)?;

        if real_state.revision < previous_real.revision {
            return Err(ShadowError::RevisionRegression);
        }

        let simulated = self
            .simulated_state
            .as_ref()
            .ok_or(ShadowError::NotInitialized)?;

        let record = ReconciliationRecord {
            real_revision: real_state.revision,
            simulated_revision_before_reset: simulated.revision,
            divergence: divergence(simulated, &real_state),
        };

        self.simulator
            .reset_to(&real_state)
            .map_err(ShadowError::Simulator)?;

        self.real_checkpoint = Some(real_state.clone());
        self.simulated_state = Some(real_state);
        self.reconciliations.push(record.clone());
        Ok(record)
    }
}

pub fn divergence(simulated: &GameState, real: &GameState) -> DivergenceSummary {
    DivergenceSummary {
        hp_changed: observed_value(&simulated.player.hp) != observed_value(&real.player.hp),
        gold_changed: observed_value(&simulated.player.gold) != observed_value(&real.player.gold),
        level_changed: observed_value(&simulated.player.level) != observed_value(&real.player.level),
        stage_changed: observed_value(&simulated.player.stage) != observed_value(&real.player.stage),
        board_changed: simulated.player.board != real.player.board,
        bench_changed: simulated.player.bench != real.player.bench,
        shop_changed: semantic_shop(simulated) != semantic_shop(real),
        lobby_changed: simulated.lobby != real.lobby,
    }
}

fn observed_value<T: PartialEq>(
    value: &Option<agente_tft_contracts::Observed<T>>,
) -> Option<&T> {
    value.as_ref().map(|observed| &observed.value)
}

fn semantic_shop(state: &GameState) -> Vec<(u8, Option<String>)> {
    let mut result: Vec<_> = state
        .player
        .shop
        .iter()
        .map(|slot| (slot.value.slot, slot.value.unit_id.clone()))
        .collect();
    result.sort_by_key(|(slot, _)| *slot);
    result
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{
        Confidence, MatchPhase, ObservationSource, Observed, PlayerState,
    };

    use super::*;

    #[derive(Default)]
    struct FakeSimulator;

    impl ShadowSimulator for FakeSimulator {
        fn reset_to(&mut self, _state: &GameState) -> Result<(), String> {
            Ok(())
        }

        fn apply_action(
            &mut self,
            state: &GameState,
            action: &Action,
        ) -> Result<ShadowTransition, String> {
            let mut next = state.clone();
            next.revision = next.revision.saturating_add(1);

            if let Action::Roll { budget_gold, .. } = action {
                if let Some(gold) = &mut next.player.gold {
                    gold.value = gold.value.saturating_sub(*budget_gold);
                }
            }

            Ok(ShadowTransition {
                before_revision: state.revision,
                action: action.clone(),
                simulated_state: next,
                reward: Some(0.25),
                metrics: serde_json::json!({}),
            })
        }
    }

    fn observed<T>(value: T) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(1.0).unwrap(),
            source: ObservationSource::Simulator,
            observed_at_ms: 100,
        }
    }

    fn state(revision: u64, gold: u16) -> GameState {
        let mut state = GameState::empty(100);
        state.revision = revision;
        state.phase = MatchPhase::Planning;
        state.player = PlayerState {
            gold: Some(observed(gold)),
            ..PlayerState::default()
        };
        state
    }

    #[test]
    fn shadow_step_advances_simulated_state() {
        let mut player = ShadowPlayer::new(FakeSimulator);
        player.initialize(state(7, 50)).unwrap();

        let transition = player
            .step(&Action::Roll {
                budget_gold: 20,
                stop_condition: None,
            })
            .unwrap();

        assert_eq!(transition.before_revision, 7);
        assert_eq!(
            transition.simulated_state.player.gold.as_ref().unwrap().value,
            30
        );
        assert_eq!(player.history().len(), 1);
    }

    #[test]
    fn reconciliation_resets_to_real_state_and_records_divergence() {
        let mut player = ShadowPlayer::new(FakeSimulator);
        player.initialize(state(7, 50)).unwrap();
        player
            .step(&Action::Roll {
                budget_gold: 20,
                stop_condition: None,
            })
            .unwrap();

        let record = player.reconcile(state(8, 44)).unwrap();

        assert!(record.divergence.gold_changed);
        assert_eq!(record.divergence.changed_fields(), 1);
        assert_eq!(
            player.current_state().unwrap().player.gold.as_ref().unwrap().value,
            44
        );
    }

    #[test]
    fn revision_regression_is_rejected() {
        let mut player = ShadowPlayer::new(FakeSimulator);
        player.initialize(state(7, 50)).unwrap();

        assert_eq!(
            player.reconcile(state(6, 50)).unwrap_err(),
            ShadowError::RevisionRegression
        );
    }
}
