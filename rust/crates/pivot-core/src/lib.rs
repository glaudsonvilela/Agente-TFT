use std::collections::{BTreeMap, BTreeSet};

use agente_tft_board_strength::{BoardStrengthEngine, BoardStrengthEstimate};
use agente_tft_contracts::{Confidence, GameState, UnitInstance};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_meta_hints::CompTransitionCandidate;
use agente_tft_opportunity_engine::PivotOpportunityFact;
use agente_tft_trait_core::TraitCatalog;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum PivotError {
    #[error("transition cost weights must be finite, non-negative and not both zero")]
    InvalidWeights,
    #[error("confidence cap must be in [0,1]")]
    InvalidConfidenceCap,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PivotConfig {
    pub missing_units_weight: f32,
    pub replacements_weight: f32,
    pub confidence_cap: f32,
}

impl Default for PivotConfig {
    fn default() -> Self {
        Self {
            missing_units_weight: 0.70,
            replacements_weight: 0.30,
            confidence_cap: 0.55,
        }
    }
}

impl PivotConfig {
    pub fn validate(self) -> Result<(), PivotError> {
        let weights = [
            self.missing_units_weight,
            self.replacements_weight,
        ];

        if weights.iter().any(|value| !value.is_finite() || *value < 0.0)
            || weights.iter().all(|value| *value == 0.0)
        {
            return Err(PivotError::InvalidWeights);
        }

        if !self.confidence_cap.is_finite()
            || !(0.0..=1.0).contains(&self.confidence_cap)
        {
            return Err(PivotError::InvalidConfidenceCap);
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PivotEvaluation {
    pub fact: PivotOpportunityFact,
    pub current_board_score: f32,
    pub transition_board_score: f32,
    pub transition_board_instance_ids: Vec<String>,
    pub target_owned_unit_ids: Vec<String>,
    pub missing_unit_ids: Vec<String>,
    pub retained_off_comp_instance_ids: Vec<String>,
    pub removed_instance_ids: Vec<String>,
    pub replacement_count: usize,
    pub board_capacity: usize,
}

pub struct PivotEvaluator {
    config: PivotConfig,
}

impl PivotEvaluator {
    pub fn new(config: PivotConfig) -> Result<Self, PivotError> {
        config.validate()?;
        Ok(Self { config })
    }

    pub fn evaluate(
        &self,
        state: &GameState,
        candidate: &CompTransitionCandidate,
        units: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
    ) -> PivotEvaluation {
        let capacity = state
            .player
            .level
            .as_ref()
            .map(|value| value.value as usize)
            .unwrap_or_else(|| state.player.board.len())
            .max(state.player.board.len());

        let target_set: BTreeSet<&str> =
            candidate.unit_ids.iter().map(String::as_str).collect();

        let before = board_strength.evaluate(
            &state.player.board,
            state.player.level.as_ref().map(|value| value.value),
            units,
            traits,
            state.overall_confidence,
        );

        let transition_board = build_reachable_transition_board(
            &state.player.board,
            &state.player.bench,
            &target_set,
            capacity,
            units,
        );

        let after = board_strength.evaluate(
            &transition_board,
            state.player.level.as_ref().map(|value| value.value),
            units,
            traits,
            state.overall_confidence,
        );

        let transition_ids: BTreeSet<&str> = transition_board
            .iter()
            .map(|unit| unit.instance_id.as_str())
            .collect();

        let removed_instance_ids: Vec<String> = state
            .player
            .board
            .iter()
            .filter(|unit| !transition_ids.contains(unit.instance_id.as_str()))
            .map(|unit| unit.instance_id.clone())
            .collect();

        let retained_off_comp_instance_ids: Vec<String> = transition_board
            .iter()
            .filter(|unit| !target_set.contains(unit.unit_id.as_str()))
            .map(|unit| unit.instance_id.clone())
            .collect();

        let target_owned_unit_ids: Vec<String> = transition_board
            .iter()
            .filter(|unit| target_set.contains(unit.unit_id.as_str()))
            .map(|unit| unit.unit_id.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();

        let missing_ratio = if candidate.unit_ids.is_empty() {
            1.0
        } else {
            candidate.missing_unit_ids.len() as f32
                / candidate.unit_ids.len() as f32
        };

        let replacement_count = removed_instance_ids.len();
        let replacement_ratio = if capacity == 0 {
            0.0
        } else {
            replacement_count as f32 / capacity as f32
        };

        let weight_sum =
            self.config.missing_units_weight + self.config.replacements_weight;
        let transition_cost = (
            missing_ratio * self.config.missing_units_weight
                + replacement_ratio * self.config.replacements_weight
        ) / weight_sum;

        let immediate_gain =
            (after.score - before.score).clamp(-1.0, 1.0);

        // Overlap with already-owned target units is a structural flexibility
        // signal: more owned pieces means more options to continue the line.
        let flexibility_after = candidate.overlap_ratio.clamp(0.0, 1.0);

        let confidence = Confidence::new(
            before
                .confidence
                .value()
                .min(after.confidence.value())
                .min(self.config.confidence_cap),
        )
        .expect("bounded pivot confidence is valid");

        PivotEvaluation {
            fact: PivotOpportunityFact {
                target: candidate.name.clone(),
                immediate_gain,
                transition_cost: transition_cost.clamp(0.0, 1.0),
                flexibility_after,
                meta_comp_id: Some(candidate.comp_id.clone()),
                confidence,
            },
            current_board_score: before.score,
            transition_board_score: after.score,
            transition_board_instance_ids: transition_board
                .iter()
                .map(|unit| unit.instance_id.clone())
                .collect(),
            target_owned_unit_ids,
            missing_unit_ids: candidate.missing_unit_ids.clone(),
            retained_off_comp_instance_ids,
            removed_instance_ids,
            replacement_count,
            board_capacity: capacity,
        }
    }
}

fn build_reachable_transition_board(
    board: &[UnitInstance],
    bench: &[UnitInstance],
    target_set: &BTreeSet<&str>,
    capacity: usize,
    units: &UnitCatalog,
) -> Vec<UnitInstance> {
    if capacity == 0 {
        return Vec::new();
    }

    let mut selected = Vec::<UnitInstance>::new();
    let mut selected_ids = BTreeSet::<String>::new();

    let mut target_owned: Vec<&UnitInstance> = board
        .iter()
        .chain(bench.iter())
        .filter(|unit| target_set.contains(unit.unit_id.as_str()))
        .collect();

    target_owned.sort_by(|a, b| {
        structural_unit_priority(b, units)
            .cmp(&structural_unit_priority(a, units))
            .then_with(|| a.instance_id.cmp(&b.instance_id))
    });

    for unit in target_owned {
        if selected.len() >= capacity {
            break;
        }
        if selected_ids.insert(unit.instance_id.clone()) {
            selected.push(unit.clone());
        }
    }

    // Keep current off-comp board units as temporary fillers rather than
    // pretending missing comp pieces already exist.
    for unit in board {
        if selected.len() >= capacity {
            break;
        }
        if selected_ids.insert(unit.instance_id.clone()) {
            selected.push(unit.clone());
        }
    }

    selected
}

fn structural_unit_priority(
    unit: &UnitInstance,
    units: &UnitCatalog,
) -> (u8, u8, usize) {
    let cost = units.cost(&unit.unit_id).unwrap_or(0);
    (
        unit.stars.clamp(1, 4),
        cost,
        unit.items.len(),
    )
}

pub fn evaluate_comp_candidates(
    state: &GameState,
    candidates: &[CompTransitionCandidate],
    units: &UnitCatalog,
    traits: &TraitCatalog,
    board_strength: &BoardStrengthEngine,
    evaluator: &PivotEvaluator,
) -> Vec<PivotEvaluation> {
    let mut result: Vec<_> = candidates
        .iter()
        .map(|candidate| {
            evaluator.evaluate(
                state,
                candidate,
                units,
                traits,
                board_strength,
            )
        })
        .collect();

    result.sort_by(|a, b| {
        b.fact
            .immediate_gain
            .total_cmp(&a.fact.immediate_gain)
            .then_with(|| {
                a.fact
                    .transition_cost
                    .total_cmp(&b.fact.transition_cost)
            })
            .then_with(|| a.fact.target.cmp(&b.fact.target))
    });

    result
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use agente_tft_board_strength::{
        BoardStrengthConfig, BoardStrengthEngine,
    };
    use agente_tft_contracts::{
        ObservationSource, Observed, PlayerState,
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

    fn unit(id: &str, stars: u8) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-{stars}"),
            unit_id: id.into(),
            stars,
            position: None,
            items: vec![],
        }
    }

    fn units() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "champions": [
                    {"api_name": "A", "name": "A", "cost": 1, "traits": ["Void"]},
                    {"api_name": "B", "name": "B", "cost": 2, "traits": ["Void"]},
                    {"api_name": "C", "name": "C", "cost": 4, "traits": ["Warden"]},
                    {"api_name": "D", "name": "D", "cost": 5, "traits": ["Warden"]},
                    {"api_name": "X", "name": "X", "cost": 1, "traits": []}
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
                        "api_name": "T_VOID",
                        "name": "Void",
                        "effects": [
                            {"min_units": 2}
                        ]
                    },
                    {
                        "api_name": "T_WARDEN",
                        "name": "Warden",
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
            level: Some(observed(3u8)),
            board: vec![
                unit("A", 2),
                unit("X", 1),
                unit("C", 1),
            ],
            bench: vec![
                unit("B", 1),
                unit("D", 1),
            ],
            ..PlayerState::default()
        };
        state
    }

    fn candidate() -> CompTransitionCandidate {
        CompTransitionCandidate {
            comp_id: "comp-abcd".into(),
            name: "ABCD".into(),
            unit_ids: vec![
                "A".into(),
                "B".into(),
                "C".into(),
                "D".into(),
            ],
            own_units_present: vec![
                "A".into(),
                "B".into(),
                "C".into(),
                "D".into(),
            ],
            missing_unit_ids: vec![],
            overlap_ratio: 1.0,
            observed_contested_copies: 0,
            meta_strength_prior: 0.2,
            frequency: Some(0.1),
            sample_size: Some(1000),
        }
    }

    #[test]
    fn transition_board_uses_owned_target_units_without_inventing_missing_units() {
        let mut candidate = candidate();
        candidate.missing_unit_ids = vec!["D".into()];
        candidate.own_units_present = vec![
            "A".into(),
            "B".into(),
            "C".into(),
        ];
        candidate.overlap_ratio = 0.75;

        let evaluator = PivotEvaluator::new(PivotConfig::default()).unwrap();
        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let evaluation = evaluator.evaluate(
            &state(),
            &candidate,
            &units(),
            &traits(),
            &strength,
        );

        assert!(!evaluation
            .transition_board_instance_ids
            .iter()
            .any(|id| id.starts_with("D-") && !state().player.bench.iter().any(|u| &u.instance_id == id)));

        assert_eq!(
            evaluation.fact.meta_comp_id.as_deref(),
            Some("comp-abcd")
        );
        assert!(evaluation.fact.transition_cost > 0.0);
    }

    #[test]
    fn owned_bench_target_can_replace_off_comp_board_unit() {
        let evaluator = PivotEvaluator::new(PivotConfig::default()).unwrap();
        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let evaluation = evaluator.evaluate(
            &state(),
            &candidate(),
            &units(),
            &traits(),
            &strength,
        );

        assert!(evaluation
            .transition_board_instance_ids
            .iter()
            .any(|id| id.starts_with("B-")));
        assert!(!evaluation
            .transition_board_instance_ids
            .iter()
            .any(|id| id.starts_with("X-")));
    }

    #[test]
    fn confidence_remains_structurally_capped() {
        let evaluator = PivotEvaluator::new(PivotConfig::default()).unwrap();
        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let evaluation = evaluator.evaluate(
            &state(),
            &candidate(),
            &units(),
            &traits(),
            &strength,
        );

        assert!(evaluation.fact.confidence.value() <= 0.55);
    }

    #[test]
    fn invalid_config_is_rejected() {
        assert_eq!(
            PivotEvaluator::new(PivotConfig {
                missing_units_weight: -1.0,
                ..PivotConfig::default()
            })
            .err()
            .unwrap(),
            PivotError::InvalidWeights
        );
    }
}
