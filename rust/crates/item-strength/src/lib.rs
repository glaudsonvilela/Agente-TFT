use agente_tft_board_strength::BoardStrengthEngine;
use agente_tft_contracts::{Confidence, GameState};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_opportunity_engine::ItemOpportunityFact;
use agente_tft_trait_core::TraitCatalog;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum ItemStrengthError {
    #[error("confidence_cap must be finite and in [0,1]")]
    InvalidConfidenceCap,
    #[error("max_items_per_unit must be > 0")]
    InvalidItemLimit,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ItemStrengthConfig {
    /// Structural evaluator confidence is intentionally capped until calibrated
    /// against combat outcomes.
    pub confidence_cap: f32,
    pub max_items_per_unit: usize,
}

impl Default for ItemStrengthConfig {
    fn default() -> Self {
        Self {
            confidence_cap: 0.35,
            max_items_per_unit: 3,
        }
    }
}

impl ItemStrengthConfig {
    pub fn validate(self) -> Result<(), ItemStrengthError> {
        if !self.confidence_cap.is_finite()
            || !(0.0..=1.0).contains(&self.confidence_cap)
        {
            return Err(ItemStrengthError::InvalidConfidenceCap);
        }
        if self.max_items_per_unit == 0 {
            return Err(ItemStrengthError::InvalidItemLimit);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemStrengthEvaluation {
    pub fact: ItemOpportunityFact,
    pub before_score: f32,
    pub after_score: f32,
    pub structural_gain: f32,
    pub target_on_board: bool,
    pub item_available: bool,
    pub target_had_free_slot: bool,
}

pub struct ItemStrengthEvaluator {
    config: ItemStrengthConfig,
}

impl ItemStrengthEvaluator {
    pub fn new(config: ItemStrengthConfig) -> Result<Self, ItemStrengthError> {
        config.validate()?;
        Ok(Self { config })
    }

    pub fn evaluate(
        &self,
        state: &GameState,
        base_fact: &ItemOpportunityFact,
        units: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
    ) -> ItemStrengthEvaluation {
        let item_available = state
            .player
            .items
            .iter()
            .any(|item| item == &base_fact.item_id);

        let target_index = state
            .player
            .board
            .iter()
            .position(|unit| unit.instance_id == base_fact.unit_instance_id);

        let target_on_board = target_index.is_some();

        let target_had_free_slot = target_index
            .and_then(|index| state.player.board.get(index))
            .map(|unit| unit.items.len() < self.config.max_items_per_unit)
            .unwrap_or(false);

        let level = state.player.level.as_ref().map(|value| value.value);

        let before = board_strength.evaluate(
            &state.player.board,
            level,
            units,
            traits,
            state.overall_confidence,
        );

        if !item_available || !target_on_board || !target_had_free_slot {
            return ItemStrengthEvaluation {
                fact: ItemOpportunityFact {
                    item_id: base_fact.item_id.clone(),
                    unit_instance_id: base_fact.unit_instance_id.clone(),
                    strength_gain: 0.0,
                    flexibility_cost: base_fact.flexibility_cost,
                    external_meta_prior: base_fact.external_meta_prior,
                    confidence: Confidence::new(
                        base_fact
                            .confidence
                            .value()
                            .min(before.confidence.value())
                            .min(self.config.confidence_cap),
                    )
                    .expect("bounded confidence remains valid"),
                },
                before_score: before.score,
                after_score: before.score,
                structural_gain: 0.0,
                target_on_board,
                item_available,
                target_had_free_slot,
            };
        }

        let mut candidate_board = state.player.board.clone();
        let index = target_index.expect("target_on_board was true");
        candidate_board[index]
            .items
            .push(base_fact.item_id.clone());

        let after = board_strength.evaluate(
            &candidate_board,
            level,
            units,
            traits,
            state.overall_confidence,
        );

        let structural_gain =
            (after.score - before.score).clamp(0.0, 1.0);

        let confidence = Confidence::new(
            base_fact
                .confidence
                .value()
                .min(before.confidence.value())
                .min(after.confidence.value())
                .min(self.config.confidence_cap),
        )
        .expect("bounded confidence remains valid");

        ItemStrengthEvaluation {
            fact: ItemOpportunityFact {
                item_id: base_fact.item_id.clone(),
                unit_instance_id: base_fact.unit_instance_id.clone(),
                strength_gain: structural_gain,
                flexibility_cost: base_fact.flexibility_cost,
                external_meta_prior: base_fact.external_meta_prior,
                confidence,
            },
            before_score: before.score,
            after_score: after.score,
            structural_gain,
            target_on_board,
            item_available,
            target_had_free_slot,
        }
    }
}

pub fn evaluate_item_facts(
    state: &GameState,
    facts: &[ItemOpportunityFact],
    units: &UnitCatalog,
    traits: &TraitCatalog,
    board_strength: &BoardStrengthEngine,
    evaluator: &ItemStrengthEvaluator,
) -> Vec<ItemStrengthEvaluation> {
    let mut values: Vec<_> = facts
        .iter()
        .map(|fact| {
            evaluator.evaluate(
                state,
                fact,
                units,
                traits,
                board_strength,
            )
        })
        .collect();

    values.sort_by(|a, b| {
        b.fact
            .strength_gain
            .total_cmp(&a.fact.strength_gain)
            .then_with(|| {
                b.fact
                    .external_meta_prior
                    .total_cmp(&a.fact.external_meta_prior)
            })
            .then_with(|| {
                a.fact
                    .unit_instance_id
                    .cmp(&b.fact.unit_instance_id)
            })
            .then_with(|| a.fact.item_id.cmp(&b.fact.item_id))
    });

    values
}

#[cfg(test)]
mod tests {
    use agente_tft_board_strength::{
        BoardStrengthConfig, BoardStrengthEngine,
    };
    use agente_tft_contracts::{
        ObservationSource, Observed, PlayerState, UnitInstance,
    };

    use super::*;

    fn observed<T>(value: T) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(0.95).unwrap(),
            source: ObservationSource::Simulator,
            observed_at_ms: 100,
        }
    }

    fn units() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "champions": [
                    {
                        "api_name": "A",
                        "name": "A",
                        "cost": 4,
                        "traits": []
                    }
                ]
            })
            .to_string(),
        )
        .unwrap()
    }

    fn traits() -> TraitCatalog {
        TraitCatalog::from_json_str(
            &serde_json::json!({
                "traits": [
                    {
                        "api_name": "T_DUMMY",
                        "name": "Dummy",
                        "effects": [
                            {"min_units": 2}
                        ]
                    }
                ]
            })
            .to_string(),
        )
        .unwrap()
    }

    fn state() -> GameState {
        let mut state = GameState::empty(100);
        state.overall_confidence = Confidence::new(0.95).unwrap();
        state.player = PlayerState {
            level: Some(observed(1u8)),
            items: vec!["ITEM_1".into()],
            board: vec![UnitInstance {
                instance_id: "A-1".into(),
                unit_id: "A".into(),
                stars: 2,
                position: None,
                items: vec![],
            }],
            ..PlayerState::default()
        };
        state
    }

    fn base_fact() -> ItemOpportunityFact {
        ItemOpportunityFact {
            item_id: "ITEM_1".into(),
            unit_instance_id: "A-1".into(),
            strength_gain: 0.0,
            flexibility_cost: 0.0,
            external_meta_prior: 0.08,
            confidence: Confidence::new(0.45).unwrap(),
        }
    }

    #[test]
    fn owned_item_on_board_target_gets_structural_gain() {
        let engine =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();
        let evaluator =
            ItemStrengthEvaluator::new(ItemStrengthConfig::default()).unwrap();

        let result = evaluator.evaluate(
            &state(),
            &base_fact(),
            &units(),
            &traits(),
            &engine,
        );

        assert!(result.item_available);
        assert!(result.target_on_board);
        assert!(result.target_had_free_slot);
        assert!(result.structural_gain > 0.0);
        assert_eq!(result.fact.external_meta_prior, 0.08);
        assert!(result.fact.confidence.value() <= 0.35);
    }

    #[test]
    fn missing_item_does_not_invent_strength_gain() {
        let engine =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();
        let evaluator =
            ItemStrengthEvaluator::new(ItemStrengthConfig::default()).unwrap();

        let mut state = state();
        state.player.items.clear();

        let result = evaluator.evaluate(
            &state,
            &base_fact(),
            &units(),
            &traits(),
            &engine,
        );

        assert!(!result.item_available);
        assert_eq!(result.structural_gain, 0.0);
        assert_eq!(result.after_score, result.before_score);
    }

    #[test]
    fn full_item_slots_do_not_generate_local_gain() {
        let engine =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();
        let evaluator =
            ItemStrengthEvaluator::new(ItemStrengthConfig::default()).unwrap();

        let mut state = state();
        state.player.board[0].items = vec![
            "I1".into(),
            "I2".into(),
            "I3".into(),
        ];

        let result = evaluator.evaluate(
            &state,
            &base_fact(),
            &units(),
            &traits(),
            &engine,
        );

        assert!(!result.target_had_free_slot);
        assert_eq!(result.structural_gain, 0.0);
    }

    #[test]
    fn bench_target_is_not_claimed_as_immediate_board_gain() {
        let engine =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();
        let evaluator =
            ItemStrengthEvaluator::new(ItemStrengthConfig::default()).unwrap();

        let mut state = state();
        let unit = state.player.board.remove(0);
        state.player.bench.push(unit);

        let result = evaluator.evaluate(
            &state,
            &base_fact(),
            &units(),
            &traits(),
            &engine,
        );

        assert!(!result.target_on_board);
        assert_eq!(result.structural_gain, 0.0);
    }
}
