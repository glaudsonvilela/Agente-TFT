use std::collections::{BTreeMap, BTreeSet};

use agente_tft_contracts::{Confidence, UnitInstance};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_synergy_core::{
    board_trait_state, ClosedTraitBreakpoint, TraitActivation,
};
use agente_tft_trait_core::TraitCatalog;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum BoardStrengthError {
    #[error("board-strength config values must be finite")]
    NonFiniteConfig,
    #[error("board-strength component weights must be >= 0 and at least one must be > 0")]
    InvalidWeights,
    #[error("confidence_cap must be in [0,1]")]
    InvalidConfidenceCap,
    #[error("star multipliers must be finite and > 0")]
    InvalidStarMultipliers,
    #[error("max_search_slots must be in [1,4]")]
    InvalidSearchSlots,
    #[error("max_combinations must be > 0")]
    InvalidCombinationLimit,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct BoardStrengthConfig {
    pub material_weight: f32,
    pub occupancy_weight: f32,
    pub item_weight: f32,
    pub synergy_weight: f32,
    /// Baseline structural model confidence is deliberately capped until
    /// calibrated against simulation / outcomes.
    pub confidence_cap: f32,
    /// Multipliers for 1★, 2★, 3★ and 4★.
    pub star_multipliers: [f32; 4],
    /// Exhaustive bench search is intentionally bounded.
    pub max_search_slots: usize,
    pub max_combinations: usize,
}

impl Default for BoardStrengthConfig {
    fn default() -> Self {
        Self {
            material_weight: 0.45,
            occupancy_weight: 0.15,
            item_weight: 0.15,
            synergy_weight: 0.25,
            confidence_cap: 0.55,
            star_multipliers: [1.0, 1.8, 3.2, 5.0],
            max_search_slots: 3,
            max_combinations: 512,
        }
    }
}

impl BoardStrengthConfig {
    pub fn validate(self) -> Result<(), BoardStrengthError> {
        let weights = [
            self.material_weight,
            self.occupancy_weight,
            self.item_weight,
            self.synergy_weight,
        ];

        if weights
            .iter()
            .chain(std::iter::once(&self.confidence_cap))
            .chain(self.star_multipliers.iter())
            .any(|value| !value.is_finite())
        {
            return Err(BoardStrengthError::NonFiniteConfig);
        }

        if weights.iter().any(|value| *value < 0.0)
            || weights.iter().all(|value| *value == 0.0)
        {
            return Err(BoardStrengthError::InvalidWeights);
        }

        if !(0.0..=1.0).contains(&self.confidence_cap) {
            return Err(BoardStrengthError::InvalidConfidenceCap);
        }

        if self.star_multipliers.iter().any(|value| *value <= 0.0) {
            return Err(BoardStrengthError::InvalidStarMultipliers);
        }

        if !(1..=4).contains(&self.max_search_slots) {
            return Err(BoardStrengthError::InvalidSearchSlots);
        }

        if self.max_combinations == 0 {
            return Err(BoardStrengthError::InvalidCombinationLimit);
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardStrengthFeatures {
    pub board_units: usize,
    pub known_units: usize,
    pub unknown_unit_ids: Vec<String>,
    pub equipped_items: usize,
    pub active_traits: usize,
    pub active_breakpoints: usize,
    pub material_quality: Option<f32>,
    pub occupancy_ratio: Option<f32>,
    pub item_density: f32,
    pub synergy_density: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardStrengthEstimate {
    /// Structural ranking score in [0,1], not combat win probability.
    pub score: f32,
    pub confidence: Confidence,
    pub features: BoardStrengthFeatures,
    pub trait_state: Vec<TraitActivation>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardAdditionPlan {
    pub added_instance_ids: Vec<String>,
    pub added_unit_ids: Vec<String>,
    pub before_score: f32,
    pub after_score: f32,
    pub normalized_gain: f32,
    pub confidence: Confidence,
    pub closed_breakpoints: Vec<ClosedTraitBreakpoint>,
    pub searched_combinations: usize,
}

pub struct BoardStrengthEngine {
    config: BoardStrengthConfig,
}

impl BoardStrengthEngine {
    pub fn new(config: BoardStrengthConfig) -> Result<Self, BoardStrengthError> {
        config.validate()?;
        Ok(Self { config })
    }

    pub fn config(&self) -> BoardStrengthConfig {
        self.config
    }

    pub fn evaluate(
        &self,
        board: &[UnitInstance],
        level: Option<u8>,
        units: &UnitCatalog,
        traits: &TraitCatalog,
        source_confidence: Confidence,
    ) -> BoardStrengthEstimate {
        let trait_state = board_trait_state(board, units, traits);

        let mut unknown = BTreeSet::new();
        let mut material_sum = 0.0_f32;
        let mut known_units = 0usize;
        let max_star_multiplier = self
            .config
            .star_multipliers
            .iter()
            .copied()
            .fold(0.0_f32, f32::max)
            .max(f32::EPSILON);

        for instance in board {
            let Some(definition) = units.unit(&instance.unit_id) else {
                unknown.insert(instance.unit_id.clone());
                continue;
            };

            let stars = instance.stars.clamp(1, 4) as usize;
            let star_multiplier = self.config.star_multipliers[stars - 1];
            let cost_quality = definition.cost as f32 / 5.0;
            let star_quality = star_multiplier / max_star_multiplier;

            material_sum += (cost_quality * star_quality).clamp(0.0, 1.0);
            known_units += 1;
        }

        let material_quality = if known_units == 0 {
            None
        } else {
            Some((material_sum / known_units as f32).clamp(0.0, 1.0))
        };

        let occupancy_ratio = level.and_then(|level| {
            if level == 0 {
                None
            } else {
                Some((board.len() as f32 / level as f32).clamp(0.0, 1.0))
            }
        });

        let equipped_items = board
            .iter()
            .map(|unit| unit.items.len())
            .sum::<usize>();
        let item_capacity = board.len().saturating_mul(3);
        let item_density = if item_capacity == 0 {
            0.0
        } else {
            (equipped_items as f32 / item_capacity as f32).clamp(0.0, 1.0)
        };

        let active_traits = trait_state
            .iter()
            .filter(|value| value.active_breakpoint.is_some())
            .count();

        let active_breakpoints = trait_state
            .iter()
            .map(|activation| {
                traits
                    .breakpoints(&activation.trait_id)
                    .unwrap_or_default()
                    .into_iter()
                    .filter(|breakpoint| *breakpoint <= activation.unit_count)
                    .count()
            })
            .sum::<usize>();

        // Structural density, not trait power. A board with several closed
        // breakpoints scores higher, but no trait-specific numeric effect is
        // invented here.
        let synergy_denominator = board.len().max(1) as f32;
        let synergy_density =
            (active_breakpoints as f32 / synergy_denominator).clamp(0.0, 1.0);

        let features = BoardStrengthFeatures {
            board_units: board.len(),
            known_units,
            unknown_unit_ids: unknown.into_iter().collect(),
            equipped_items,
            active_traits,
            active_breakpoints,
            material_quality,
            occupancy_ratio,
            item_density,
            synergy_density,
        };

        let score = self.weighted_score(&features);

        let knowledge_coverage = if board.is_empty() {
            1.0
        } else {
            known_units as f32 / board.len() as f32
        };

        let confidence_value = source_confidence
            .value()
            .min(self.config.confidence_cap)
            * knowledge_coverage.clamp(0.0, 1.0);

        let confidence = Confidence::new(confidence_value.clamp(0.0, 1.0))
            .expect("clamped structural confidence is valid");

        BoardStrengthEstimate {
            score,
            confidence,
            features,
            trait_state,
        }
    }

    pub fn best_bench_additions(
        &self,
        board: &[UnitInstance],
        bench: &[UnitInstance],
        slots_gained: usize,
        level_after: Option<u8>,
        units: &UnitCatalog,
        traits: &TraitCatalog,
        source_confidence: Confidence,
    ) -> BoardAdditionPlan {
        let before = self.evaluate(
            board,
            level_after.map(|value| {
                value.saturating_sub(slots_gained.min(u8::MAX as usize) as u8)
            }),
            units,
            traits,
            source_confidence,
        );

        let usable_slots = slots_gained
            .min(self.config.max_search_slots)
            .min(bench.len());

        if usable_slots == 0 || bench.is_empty() {
            return BoardAdditionPlan {
                added_instance_ids: vec![],
                added_unit_ids: vec![],
                before_score: before.score,
                after_score: before.score,
                normalized_gain: 0.0,
                confidence: before.confidence,
                closed_breakpoints: vec![],
                searched_combinations: 0,
            };
        }

        let before_traits = board_trait_state(board, units, traits);
        let mut best_score = before.score;
        let mut best_indices = Vec::new();
        let mut best_estimate = before.clone();
        let mut searched = 0usize;
        let mut current = Vec::new();

        for target_size in 1..=usable_slots {
            search_combinations(
                bench.len(),
                target_size,
                0,
                &mut current,
                &mut |indices| {
                    if searched >= self.config.max_combinations {
                        return false;
                    }
                    searched += 1;

                    let mut candidate_board = board.to_vec();
                    for index in indices {
                        candidate_board.push(bench[*index].clone());
                    }

                    let estimate = self.evaluate(
                        &candidate_board,
                        level_after,
                        units,
                        traits,
                        source_confidence,
                    );

                    let candidate_ids: Vec<_> = indices
                        .iter()
                        .map(|index| bench[*index].instance_id.as_str())
                        .collect();
                    let best_ids: Vec<_> = best_indices
                        .iter()
                        .map(|index: &usize| bench[*index].instance_id.as_str())
                        .collect();

                    let better = estimate.score > best_score + 1e-6
                        || ((estimate.score - best_score).abs() <= 1e-6
                            && (!indices.is_empty()
                                && (best_indices.is_empty()
                                    || candidate_ids < best_ids)));

                    if better {
                        best_score = estimate.score;
                        best_indices = indices.to_vec();
                        best_estimate = estimate;
                    }

                    true
                },
            );

            if searched >= self.config.max_combinations {
                break;
            }
        }

        let mut after_board = board.to_vec();
        for index in &best_indices {
            after_board.push(bench[*index].clone());
        }

        let after_traits = board_trait_state(&after_board, units, traits);
        let closed_breakpoints =
            closed_breakpoints_between(&before_traits, &after_traits, traits);

        BoardAdditionPlan {
            added_instance_ids: best_indices
                .iter()
                .map(|index| bench[*index].instance_id.clone())
                .collect(),
            added_unit_ids: best_indices
                .iter()
                .map(|index| bench[*index].unit_id.clone())
                .collect(),
            before_score: before.score,
            after_score: best_estimate.score,
            normalized_gain: (best_estimate.score - before.score).clamp(0.0, 1.0),
            confidence: min_confidence(before.confidence, best_estimate.confidence),
            closed_breakpoints,
            searched_combinations: searched,
        }
    }

    fn weighted_score(&self, features: &BoardStrengthFeatures) -> f32 {
        let mut weighted = 0.0_f32;
        let mut total_weight = 0.0_f32;

        if let Some(value) = features.material_quality {
            weighted += value * self.config.material_weight;
            total_weight += self.config.material_weight;
        }

        if let Some(value) = features.occupancy_ratio {
            weighted += value * self.config.occupancy_weight;
            total_weight += self.config.occupancy_weight;
        }

        weighted += features.item_density * self.config.item_weight;
        total_weight += self.config.item_weight;

        weighted += features.synergy_density * self.config.synergy_weight;
        total_weight += self.config.synergy_weight;

        if total_weight <= f32::EPSILON {
            0.0
        } else {
            (weighted / total_weight).clamp(0.0, 1.0)
        }
    }
}

fn closed_breakpoints_between(
    before: &[TraitActivation],
    after: &[TraitActivation],
    traits: &TraitCatalog,
) -> Vec<ClosedTraitBreakpoint> {
    let before_map: BTreeMap<_, _> = before
        .iter()
        .map(|activation| (activation.trait_id.as_str(), activation.unit_count))
        .collect();

    let mut result = Vec::new();

    for activation in after {
        let before_count = before_map
            .get(activation.trait_id.as_str())
            .copied()
            .unwrap_or(0);

        let Some(definition) = traits.trait_by_id(&activation.trait_id) else {
            continue;
        };

        for breakpoint in definition.breakpoints() {
            if before_count < breakpoint && activation.unit_count >= breakpoint {
                result.push(ClosedTraitBreakpoint {
                    trait_id: activation.trait_id.clone(),
                    trait_name: activation.trait_name.clone(),
                    from_count: before_count,
                    to_count: activation.unit_count,
                    breakpoint,
                });
            }
        }
    }

    result.sort_by(|a, b| {
        a.trait_id
            .cmp(&b.trait_id)
            .then_with(|| a.breakpoint.cmp(&b.breakpoint))
    });
    result
}

fn min_confidence(a: Confidence, b: Confidence) -> Confidence {
    Confidence::new(a.value().min(b.value()))
        .expect("minimum of valid confidence values remains valid")
}

fn search_combinations<F>(
    n: usize,
    target_size: usize,
    start: usize,
    current: &mut Vec<usize>,
    callback: &mut F,
) -> bool
where
    F: FnMut(&[usize]) -> bool,
{
    if current.len() == target_size {
        return callback(current);
    }

    let remaining_needed = target_size - current.len();
    if n.saturating_sub(start) < remaining_needed {
        return true;
    }

    for index in start..n {
        current.push(index);
        if !search_combinations(n, target_size, index + 1, current, callback) {
            current.pop();
            return false;
        }
        current.pop();
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unit(id: &str, stars: u8, items: &[&str]) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-{stars}-{}", items.len()),
            unit_id: id.into(),
            stars,
            position: None,
            items: items.iter().map(|value| value.to_string()).collect(),
        }
    }

    fn units() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "champions": [
                    {"api_name": "A", "name": "A", "cost": 1, "traits": ["Void"]},
                    {"api_name": "B", "name": "B", "cost": 2, "traits": ["Warden"]},
                    {"api_name": "C", "name": "C", "cost": 2, "traits": ["Void"]},
                    {"api_name": "D", "name": "D", "cost": 5, "traits": []}
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
                            {"min_units": 2},
                            {"min_units": 4}
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

    #[test]
    fn structural_score_is_bounded_and_confidence_is_capped() {
        let engine = BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();
        let board = vec![
            unit("A", 2, &["I1", "I2"]),
            unit("B", 1, &[]),
        ];

        let estimate = engine.evaluate(
            &board,
            Some(2),
            &units(),
            &traits(),
            Confidence::new(0.95).unwrap(),
        );

        assert!((0.0..=1.0).contains(&estimate.score));
        assert_eq!(estimate.features.board_units, 2);
        assert_eq!(estimate.features.known_units, 2);
        assert_eq!(estimate.features.equipped_items, 2);
        assert!(estimate.confidence.value() <= 0.55);
    }

    #[test]
    fn unknown_units_reduce_model_confidence() {
        let engine = BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();
        let board = vec![
            unit("A", 1, &[]),
            unit("UNKNOWN", 1, &[]),
        ];

        let estimate = engine.evaluate(
            &board,
            Some(2),
            &units(),
            &traits(),
            Confidence::new(1.0).unwrap(),
        );

        assert_eq!(estimate.features.known_units, 1);
        assert_eq!(estimate.features.unknown_unit_ids, vec!["UNKNOWN"]);
        assert!((estimate.confidence.value() - 0.275).abs() < 1e-6);
    }

    #[test]
    fn best_bench_addition_can_prefer_trait_breakpoint() {
        let config = BoardStrengthConfig {
            material_weight: 0.15,
            occupancy_weight: 0.10,
            item_weight: 0.0,
            synergy_weight: 0.75,
            ..BoardStrengthConfig::default()
        };
        let engine = BoardStrengthEngine::new(config).unwrap();

        let board = vec![unit("A", 1, &[])];
        let bench = vec![
            unit("C", 1, &[]), // closes Void 2
            unit("D", 1, &[]), // expensive, no synergy
        ];

        let plan = engine.best_bench_additions(
            &board,
            &bench,
            1,
            Some(2),
            &units(),
            &traits(),
            Confidence::new(0.95).unwrap(),
        );

        assert_eq!(plan.added_unit_ids, vec!["C"]);
        assert!(plan.normalized_gain > 0.0);
        assert!(plan
            .closed_breakpoints
            .iter()
            .any(|value| value.trait_name == "Void" && value.breakpoint == 2));
    }

    #[test]
    fn bench_search_is_bounded() {
        let engine = BoardStrengthEngine::new(BoardStrengthConfig {
            max_search_slots: 2,
            max_combinations: 2,
            ..BoardStrengthConfig::default()
        })
        .unwrap();

        let board = vec![unit("A", 1, &[])];
        let bench = vec![
            unit("B", 1, &[]),
            unit("C", 1, &[]),
            unit("D", 1, &[]),
        ];

        let plan = engine.best_bench_additions(
            &board,
            &bench,
            2,
            Some(3),
            &units(),
            &traits(),
            Confidence::new(0.95).unwrap(),
        );

        assert!(plan.searched_combinations <= 2);
    }

    #[test]
    fn invalid_config_is_rejected() {
        let error = BoardStrengthEngine::new(BoardStrengthConfig {
            confidence_cap: 1.5,
            ..BoardStrengthConfig::default()
        })
        .err()
        .unwrap();

        assert_eq!(error, BoardStrengthError::InvalidConfidenceCap);
    }
}
