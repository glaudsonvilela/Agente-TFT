use std::collections::BTreeMap;

use agente_tft_contracts::{Confidence, GameState, UnitInstance};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_lobby_analysis::{
    copies_represented_by_stars, self_owned_copies,
};
use agente_tft_opportunity_engine::SellOpportunityFact;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum SellError {
    #[error("bench_capacity must be > 0")]
    InvalidBenchCapacity,
    #[error("economy_scale_gold must be > 0")]
    InvalidEconomyScale,
    #[error("min_bench_occupancy_ratio and confidence_cap must be in [0,1]")]
    InvalidBoundedConfig,
    #[error("sell rule cost must be in [1,5] and stars in [1,4]")]
    InvalidSellRule,
    #[error("sell value must be > 0")]
    InvalidSellValue,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct SellValueRule {
    pub cost: u8,
    pub stars: u8,
    pub gold: u16,
}

impl SellValueRule {
    pub fn validate(self) -> Result<(), SellError> {
        if !(1..=5).contains(&self.cost)
            || !(1..=4).contains(&self.stars)
        {
            return Err(SellError::InvalidSellRule);
        }
        if self.gold == 0 {
            return Err(SellError::InvalidSellValue);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SellConfig {
    pub bench_capacity: usize,
    pub economy_scale_gold: u16,
    pub min_bench_occupancy_ratio: f32,
    pub confidence_cap: f32,
    pub preserve_upgrade_material: bool,
    pub skip_itemized_bench_units: bool,
    pub sell_values: Vec<SellValueRule>,
}

impl SellConfig {
    pub fn validate(&self) -> Result<(), SellError> {
        if self.bench_capacity == 0 {
            return Err(SellError::InvalidBenchCapacity);
        }
        if self.economy_scale_gold == 0 {
            return Err(SellError::InvalidEconomyScale);
        }
        if !self.min_bench_occupancy_ratio.is_finite()
            || !self.confidence_cap.is_finite()
            || !(0.0..=1.0).contains(&self.min_bench_occupancy_ratio)
            || !(0.0..=1.0).contains(&self.confidence_cap)
        {
            return Err(SellError::InvalidBoundedConfig);
        }
        for rule in &self.sell_values {
            rule.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SellDiagnostic {
    pub bench_occupancy_ratio: f32,
    pub unknown_unit_ids: Vec<String>,
    pub missing_sell_rules: Vec<(u8, u8)>,
    pub skipped_upgrade_material: Vec<String>,
    pub skipped_itemized_units: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SellEvaluation {
    pub facts: Vec<SellOpportunityFact>,
    pub diagnostic: SellDiagnostic,
}

pub struct SellEvaluator {
    config: SellConfig,
    values: BTreeMap<(u8, u8), u16>,
}

impl SellEvaluator {
    pub fn new(config: SellConfig) -> Result<Self, SellError> {
        config.validate()?;
        let values = config
            .sell_values
            .iter()
            .map(|rule| ((rule.cost, rule.stars), rule.gold))
            .collect();

        Ok(Self {
            config,
            values,
        })
    }

    pub fn evaluate(
        &self,
        state: &GameState,
        catalog: &UnitCatalog,
    ) -> SellEvaluation {
        let occupancy_ratio =
            (state.player.bench.len() as f32
                / self.config.bench_capacity as f32)
                .clamp(0.0, 1.0);

        let mut diagnostic = SellDiagnostic {
            bench_occupancy_ratio: occupancy_ratio,
            unknown_unit_ids: Vec::new(),
            missing_sell_rules: Vec::new(),
            skipped_upgrade_material: Vec::new(),
            skipped_itemized_units: Vec::new(),
        };

        if occupancy_ratio < self.config.min_bench_occupancy_ratio {
            return SellEvaluation {
                facts: Vec::new(),
                diagnostic,
            };
        }

        let mut facts = Vec::new();

        for unit in &state.player.bench {
            let Some(cost) = catalog.cost(&unit.unit_id) else {
                diagnostic.unknown_unit_ids.push(unit.unit_id.clone());
                continue;
            };

            if self.config.skip_itemized_bench_units
                && !unit.items.is_empty()
            {
                diagnostic
                    .skipped_itemized_units
                    .push(unit.instance_id.clone());
                continue;
            }

            if self.config.preserve_upgrade_material
                && has_other_owned_copies(state, unit)
            {
                diagnostic
                    .skipped_upgrade_material
                    .push(unit.instance_id.clone());
                continue;
            }

            let stars = unit.stars.clamp(1, 4);
            let Some(gold) = self.values.get(&(cost, stars)).copied() else {
                diagnostic.missing_sell_rules.push((cost, stars));
                continue;
            };

            let economy_value =
                (gold as f32 / self.config.economy_scale_gold as f32)
                    .clamp(0.0, 1.0);

            // Selling a bench unit does not change current board strength.
            let board_strength_loss = 0.0;

            // The more pressured the bench, the more valuable one freed slot is.
            let flexibility_gain = occupancy_ratio;

            let confidence = Confidence::new(
                state
                    .overall_confidence
                    .value()
                    .min(self.config.confidence_cap),
            )
            .expect("bounded sell confidence remains valid");

            facts.push(SellOpportunityFact {
                unit_instance_id: unit.instance_id.clone(),
                economy_value,
                board_strength_loss,
                flexibility_gain,
                confidence,
            });
        }

        facts.sort_by(|a, b| {
            b.flexibility_gain
                .total_cmp(&a.flexibility_gain)
                .then_with(|| b.economy_value.total_cmp(&a.economy_value))
                .then_with(|| a.unit_instance_id.cmp(&b.unit_instance_id))
        });

        diagnostic.unknown_unit_ids.sort();
        diagnostic.unknown_unit_ids.dedup();
        diagnostic.missing_sell_rules.sort();
        diagnostic.missing_sell_rules.dedup();
        diagnostic.skipped_upgrade_material.sort();
        diagnostic.skipped_upgrade_material.dedup();
        diagnostic.skipped_itemized_units.sort();
        diagnostic.skipped_itemized_units.dedup();

        SellEvaluation {
            facts,
            diagnostic,
        }
    }
}

fn has_other_owned_copies(
    state: &GameState,
    unit: &UnitInstance,
) -> bool {
    let total = self_owned_copies(state, &unit.unit_id);
    let represented = copies_represented_by_stars(unit.stars);
    total > represented
}

#[cfg(test)]
mod tests {
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

    fn unit(id: &str, stars: u8, items: &[&str]) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-{stars}-{}", items.len()),
            unit_id: id.into(),
            stars,
            position: None,
            items: items.iter().map(|value| value.to_string()).collect(),
        }
    }

    fn catalog() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "champions": [
                    {"api_name": "A", "name": "A", "cost": 1, "traits": []},
                    {"api_name": "B", "name": "B", "cost": 4, "traits": []}
                ]
            })
            .to_string(),
        )
        .unwrap()
    }

    fn config() -> SellConfig {
        SellConfig {
            bench_capacity: 4,
            economy_scale_gold: 10,
            min_bench_occupancy_ratio: 0.75,
            confidence_cap: 0.50,
            preserve_upgrade_material: true,
            skip_itemized_bench_units: true,
            sell_values: vec![
                SellValueRule {
                    cost: 1,
                    stars: 1,
                    gold: 1,
                },
                SellValueRule {
                    cost: 4,
                    stars: 1,
                    gold: 4,
                },
            ],
        }
    }

    fn state() -> GameState {
        let mut state = GameState::empty(100);
        state.overall_confidence = Confidence::new(0.95).unwrap();
        state.player = PlayerState {
            gold: Some(observed(10u16)),
            bench: vec![
                unit("A", 1, &[]),
                unit("B", 1, &[]),
                unit("UNKNOWN", 1, &[]),
                unit("A", 1, &["ITEM"]),
            ],
            ..PlayerState::default()
        };
        state
    }

    #[test]
    fn full_bench_generates_conservative_sell_fact() {
        let evaluator = SellEvaluator::new(config()).unwrap();
        let mut state = state();

        // Keep only one A copy so upgrade-material safeguard does not block it.
        state.player.bench.retain(|unit| {
            unit.instance_id != "A-1-1"
        });
        state.player.bench.push(unit("B", 1, &[]));

        let result = evaluator.evaluate(&state, &catalog());

        assert!(result.facts.iter().any(|fact| {
            fact.unit_instance_id.starts_with("A-1-0")
        }));
        assert!(result
            .facts
            .iter()
            .all(|fact| fact.board_strength_loss == 0.0));
        assert!(result
            .facts
            .iter()
            .all(|fact| fact.confidence.value() <= 0.50));
    }

    #[test]
    fn duplicate_upgrade_material_is_preserved() {
        let evaluator = SellEvaluator::new(config()).unwrap();
        let result = evaluator.evaluate(&state(), &catalog());

        assert!(result
            .diagnostic
            .skipped_upgrade_material
            .iter()
            .any(|id| id.starts_with("A-1")));
    }

    #[test]
    fn itemized_bench_unit_is_skipped() {
        let evaluator = SellEvaluator::new(config()).unwrap();
        let mut state = state();
        state.player.bench = vec![
            unit("B", 1, &["ITEM"]),
            unit("UNKNOWN", 1, &[]),
            unit("UNKNOWN", 1, &[]),
            unit("UNKNOWN", 1, &[]),
        ];

        let result = evaluator.evaluate(&state, &catalog());

        assert!(result
            .diagnostic
            .skipped_itemized_units
            .iter()
            .any(|id| id.starts_with("B-1")));
    }

    #[test]
    fn low_bench_pressure_generates_no_sell_fact() {
        let evaluator = SellEvaluator::new(config()).unwrap();
        let mut state = state();
        state.player.bench.truncate(2);

        let result = evaluator.evaluate(&state, &catalog());
        assert!(result.facts.is_empty());
    }

    #[test]
    fn no_sell_value_is_invented() {
        let mut config = config();
        config.sell_values.clear();

        let evaluator = SellEvaluator::new(config).unwrap();
        let mut state = state();
        state.player.bench = vec![
            unit("B", 1, &[]),
            unit("UNKNOWN", 1, &[]),
            unit("UNKNOWN", 1, &[]),
            unit("UNKNOWN", 1, &[]),
        ];

        let result = evaluator.evaluate(&state, &catalog());
        assert!(result.facts.is_empty());
        assert!(result
            .diagnostic
            .missing_sell_rules
            .contains(&(4, 1)));
    }
}
