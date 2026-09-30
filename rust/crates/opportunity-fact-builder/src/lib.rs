use std::collections::BTreeSet;

use agente_tft_board_strength::BoardStrengthEngine;
use agente_tft_contracts::{Confidence, GameState};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_lobby_analysis::{
    analyze_unit_contestation, self_owned_copies,
};
use agente_tft_opportunity_engine::{
    BuyOpportunityFact, LevelOpportunityFact, OpportunityFacts,
    RollOpportunityFact, ScoutOpportunityFact,
};
use agente_tft_strategy_analysis::{
    analyze_target_roll, StrategyAnalysisError, TargetRollInput,
};
use agente_tft_tft_rules::{RuleSetError, TftRuleSet};
use agente_tft_trait_core::TraitCatalog;
use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum FactBuildError {
    #[error("ruleset error: {0}")]
    Rules(#[from] RuleSetError),
    #[error("strategy analysis error: {0}")]
    Strategy(String),
    #[error("state patch {state} does not match rules patch {rules}")]
    PatchMismatch { state: String, rules: String },
    #[error("state set {state} does not match rules set {rules}")]
    SetMismatch { state: String, rules: String },
    #[error("pool accounting confidence must be finite and in [0,1]")]
    InvalidPoolConfidence,
}

impl From<StrategyAnalysisError> for FactBuildError {
    fn from(value: StrategyAnalysisError) -> Self {
        Self::Strategy(value.to_string())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct FactBuilderConfig {
    pub roll_budgets_gold: Vec<u16>,
    pub include_max_affordable_budget: bool,
    pub min_owned_copies_for_roll_target: u16,
    pub include_current_shop_in_roll_math: bool,
    /// Maximum number of sequential higher levels to consider in one state.
    pub max_level_targets: usize,
    /// Explicit confidence applied to probability calculations that depend on
    /// observed pool accounting. This is a caller-owned calibration knob.
    pub pool_accounting_confidence: f32,
    pub scout_stale_after_ms: u64,
    pub scout_full_value_age_ms: u64,
}

impl Default for FactBuilderConfig {
    fn default() -> Self {
        Self {
            roll_budgets_gold: vec![2, 6, 10, 20, 30],
            include_max_affordable_budget: true,
            min_owned_copies_for_roll_target: 1,
            include_current_shop_in_roll_math: false,
            max_level_targets: 3,
            pool_accounting_confidence: 0.80,
            scout_stale_after_ms: 8_000,
            scout_full_value_age_ms: 30_000,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RollTargetDiagnostic {
    pub unit_id: String,
    pub unit_name: String,
    pub cost: u8,
    pub owned_copies: u16,
    pub copies_needed_for_next_upgrade: u16,
    pub target_stars: u8,
    pub observed_opponent_copies: u16,
    pub known_tier_remaining: u16,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct LevelBoardPlanDiagnostic {
    pub target_level: u8,
    pub added_instance_ids: Vec<String>,
    pub added_unit_ids: Vec<String>,
    pub normalized_gain: f32,
    pub confidence: f32,
    pub closed_breakpoints: Vec<String>,
    pub searched_combinations: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BuildDiagnostics {
    pub unknown_shop_unit_ids: Vec<String>,
    pub unknown_owned_unit_ids: Vec<String>,
    pub unaffordable_shop_slots: Vec<u8>,
    pub skipped_fully_upgraded_units: Vec<String>,
    pub roll_targets: Vec<RollTargetDiagnostic>,
    pub roll_targets_blocked_by_shop: Vec<String>,
    pub xp_rules_available: bool,
    pub unaffordable_level_targets: Vec<u8>,
    pub level_board_plans: Vec<LevelBoardPlanDiagnostic>,
}

impl Default for BuildDiagnostics {
    fn default() -> Self {
        Self {
            unknown_shop_unit_ids: Vec::new(),
            unknown_owned_unit_ids: Vec::new(),
            unaffordable_shop_slots: Vec::new(),
            skipped_fully_upgraded_units: Vec::new(),
            roll_targets: Vec::new(),
            roll_targets_blocked_by_shop: Vec::new(),
            xp_rules_available: false,
            unaffordable_level_targets: Vec::new(),
            level_board_plans: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct OpportunityFactBuild {
    pub facts: OpportunityFacts,
    pub diagnostics: BuildDiagnostics,
}

pub struct OpportunityFactBuilder {
    config: FactBuilderConfig,
}

impl OpportunityFactBuilder {
    pub fn new(config: FactBuilderConfig) -> Result<Self, FactBuildError> {
        if !config.pool_accounting_confidence.is_finite()
            || !(0.0..=1.0).contains(&config.pool_accounting_confidence)
        {
            return Err(FactBuildError::InvalidPoolConfidence);
        }

        Ok(Self { config })
    }

    pub fn build(
        &self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        now_ms: u64,
    ) -> Result<OpportunityFactBuild, FactBuildError> {
        rules.validate()?;
        validate_rule_context(state, rules)?;

        let mut facts = OpportunityFacts::default();
        let mut diagnostics = BuildDiagnostics::default();

        self.build_buy_facts(
            state,
            catalog,
            &mut facts,
            &mut diagnostics,
        )?;

        self.build_roll_facts(
            state,
            rules,
            catalog,
            &mut facts,
            &mut diagnostics,
        )?;

        self.build_level_facts(
            state,
            rules,
            &mut facts,
            &mut diagnostics,
        )?;

        self.build_scout_facts(
            state,
            now_ms,
            &mut facts,
        );

        Ok(OpportunityFactBuild {
            facts,
            diagnostics,
        })
    }

    pub fn build_with_board_strength(
        &self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
        now_ms: u64,
    ) -> Result<OpportunityFactBuild, FactBuildError> {
        let mut result = self.build(
            state,
            rules,
            catalog,
            now_ms,
        )?;

        self.enrich_level_board_gain(
            state,
            catalog,
            traits,
            board_strength,
            &mut result.facts,
            &mut result.diagnostics,
        );

        Ok(result)
    }

    fn enrich_level_board_gain(
        &self,
        state: &GameState,
        catalog: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
        facts: &mut OpportunityFacts,
        diagnostics: &mut BuildDiagnostics,
    ) {
        for fact in &mut facts.levels {
            let plan = board_strength.best_bench_additions(
                &state.player.board,
                &state.player.bench,
                fact.slots_gained as usize,
                Some(fact.target_level),
                catalog,
                traits,
                fact.confidence,
            );

            fact.expected_board_gain = Some(plan.normalized_gain);
            fact.confidence = min_confidence(
                fact.confidence,
                plan.confidence,
            );

            diagnostics.level_board_plans.push(
                LevelBoardPlanDiagnostic {
                    target_level: fact.target_level,
                    added_instance_ids: plan.added_instance_ids,
                    added_unit_ids: plan.added_unit_ids,
                    normalized_gain: plan.normalized_gain,
                    confidence: plan.confidence.value(),
                    closed_breakpoints: plan
                        .closed_breakpoints
                        .into_iter()
                        .map(|value| {
                            format!(
                                "{}:{}",
                                value.trait_name,
                                value.breakpoint
                            )
                        })
                        .collect(),
                    searched_combinations: plan.searched_combinations,
                },
            );
        }

        diagnostics
            .level_board_plans
            .sort_by_key(|plan| plan.target_level);
    }

    fn build_buy_facts(
        &self,
        state: &GameState,
        catalog: &UnitCatalog,
        facts: &mut OpportunityFacts,
        diagnostics: &mut BuildDiagnostics,
    ) -> Result<(), FactBuildError> {
        let current_gold = state
            .player
            .gold
            .as_ref()
            .map(|value| value.value);

        for observed_slot in &state.player.shop {
            let Some(unit_id) = observed_slot.value.unit_id.as_deref() else {
                continue;
            };

            let Some(cost) = catalog.cost(unit_id) else {
                diagnostics
                    .unknown_shop_unit_ids
                    .push(unit_id.to_string());
                continue;
            };

            if current_gold.is_some_and(|gold| gold < cost as u16) {
                diagnostics
                    .unaffordable_shop_slots
                    .push(observed_slot.value.slot);
                continue;
            }

            let owned = self_owned_copies(state, unit_id);
            let closes_upgrade = purchase_closes_upgrade(owned);
            let contested = analyze_unit_contestation(
                state,
                unit_id,
            )
            .observed_opponent_copies;

            let confidence = min_confidence(
                state.overall_confidence,
                observed_slot.confidence,
            );

            facts.buys.push(BuyOpportunityFact {
                shop_slot: observed_slot.value.slot,
                unit_id: unit_id.to_string(),
                gold_cost: cost as u16,
                closes_upgrade,
                contested_copies: Some(contested),
                confidence,
            });
        }

        facts.buys.sort_by_key(|fact| fact.shop_slot);
        diagnostics.unknown_shop_unit_ids.sort();
        diagnostics.unknown_shop_unit_ids.dedup();
        diagnostics.unaffordable_shop_slots.sort_unstable();
        diagnostics.unaffordable_shop_slots.dedup();
        Ok(())
    }

    fn build_roll_facts(
        &self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        facts: &mut OpportunityFacts,
        diagnostics: &mut BuildDiagnostics,
    ) -> Result<(), FactBuildError> {
        let Some(current_gold) = state.player.gold.as_ref().map(|value| value.value) else {
            return Ok(());
        };
        if current_gold < rules.roll_cost_gold {
            return Ok(());
        }

        let mut owned_unit_ids: BTreeSet<String> = state
            .player
            .board
            .iter()
            .chain(state.player.bench.iter())
            .map(|unit| unit.unit_id.clone())
            .collect();

        // Units currently visible in shop are also valid targets only when we
        // already own at least one copy; do not invent a reroll line from a
        // random unowned shop unit.
        for slot in &state.player.shop {
            if let Some(unit_id) = &slot.value.unit_id {
                if self_owned_copies(state, unit_id) > 0 {
                    owned_unit_ids.insert(unit_id.clone());
                }
            }
        }

        let budgets = self.roll_budgets(
            current_gold,
            rules.roll_cost_gold,
        );

        for unit_id in owned_unit_ids {
            let owned = self_owned_copies(state, &unit_id);
            if owned < self.config.min_owned_copies_for_roll_target {
                continue;
            }

            let Some(definition) = catalog.unit(&unit_id) else {
                diagnostics
                    .unknown_owned_unit_ids
                    .push(unit_id);
                continue;
            };

            let visible_affordable_copy = state.player.shop.iter().any(|slot| {
                slot.value.unit_id.as_deref() == Some(unit_id.as_str())
                    && current_gold >= definition.cost as u16
            });
            if visible_affordable_copy {
                diagnostics
                    .roll_targets_blocked_by_shop
                    .push(unit_id);
                continue;
            }

            let Some((target_stars, target_copies)) =
                next_upgrade_threshold(owned)
            else {
                diagnostics
                    .skipped_fully_upgraded_units
                    .push(unit_id);
                continue;
            };

            let known_tier_remaining = known_tier_remaining(
                state,
                rules,
                catalog,
                definition.cost,
            )?;

            let opponent_copies = analyze_unit_contestation(
                state,
                &unit_id,
            )
            .observed_opponent_copies;

            let analysis = analyze_target_roll(TargetRollInput {
                state,
                rules,
                unit_id: &unit_id,
                cost: definition.cost,
                tier_total_remaining: known_tier_remaining,
                other_known_removed_copies: 0,
                budgets_gold: &budgets,
                include_current_shop:
                    self.config.include_current_shop_in_roll_math,
            })?;

            let copies_needed = target_copies.saturating_sub(owned);
            diagnostics.roll_targets.push(
                RollTargetDiagnostic {
                    unit_id: unit_id.clone(),
                    unit_name: definition.name.clone(),
                    cost: definition.cost,
                    owned_copies: owned,
                    copies_needed_for_next_upgrade: copies_needed,
                    target_stars,
                    observed_opponent_copies: opponent_copies,
                    known_tier_remaining,
                },
            );

            let pool_confidence = Confidence::new(
                state
                    .overall_confidence
                    .value()
                    .min(self.config.pool_accounting_confidence),
            )
            .expect("validated confidence inputs remain valid");

            for window in analysis.roll_windows {
                if window.budget_gold < rules.roll_cost_gold {
                    continue;
                }

                facts.rolls.push(RollOpportunityFact {
                    budget_gold: window.budget_gold,
                    stop_condition: Some(format!(
                        "Pare quando {} chegar a {}★; faltam {} cópia(s).",
                        definition.name,
                        target_stars,
                        copies_needed,
                    )),
                    target_unit_id: Some(unit_id.clone()),
                    probability_at_least_one: Some(
                        window.probability_at_least_one as f32,
                    ),
                    expected_target_copies: Some(
                        window.expected_target_copies as f32,
                    ),
                    interest_lost: Some(window.interest_lost),
                    contested_copies: Some(opponent_copies),
                    confidence: pool_confidence,
                });
            }
        }

        facts.rolls.sort_by(|a, b| {
            a.target_unit_id
                .cmp(&b.target_unit_id)
                .then_with(|| a.budget_gold.cmp(&b.budget_gold))
        });

        diagnostics.unknown_owned_unit_ids.sort();
        diagnostics.unknown_owned_unit_ids.dedup();
        diagnostics.skipped_fully_upgraded_units.sort();
        diagnostics.skipped_fully_upgraded_units.dedup();
        diagnostics.roll_targets_blocked_by_shop.sort();
        diagnostics.roll_targets_blocked_by_shop.dedup();
        diagnostics.roll_targets.sort_by(|a, b| {
            a.unit_id.cmp(&b.unit_id)
        });

        Ok(())
    }

    fn build_level_facts(
        &self,
        state: &GameState,
        rules: &TftRuleSet,
        facts: &mut OpportunityFacts,
        diagnostics: &mut BuildDiagnostics,
    ) -> Result<(), FactBuildError> {
        diagnostics.xp_rules_available = rules.xp_rules_available();
        if !rules.xp_rules_available() || self.config.max_level_targets == 0 {
            return Ok(());
        }

        let (Some(level), Some(xp), Some(gold)) = (
            state.player.level.as_ref(),
            state.player.xp.as_ref(),
            state.player.gold.as_ref(),
        ) else {
            return Ok(());
        };

        let confidence = Confidence::new(
            state
                .overall_confidence
                .value()
                .min(level.confidence.value())
                .min(xp.confidence.value())
                .min(gold.confidence.value()),
        )
        .expect("minimum of valid confidences remains valid");

        let current_level = level.value;
        let current_xp = xp.value;
        let current_gold = gold.value;

        for step in 1..=self.config.max_level_targets {
            let Ok(step_u8) = u8::try_from(step) else {
                break;
            };
            let Some(target_level) =
                current_level.checked_add(step_u8)
            else {
                break;
            };

            let gold_cost = match rules.gold_to_level(
                current_level,
                current_xp,
                target_level,
            ) {
                Ok(Some(cost)) => cost,
                Ok(None) => break,
                Err(RuleSetError::MissingXpThreshold(_)) => break,
                Err(error) => return Err(error.into()),
            };

            // A zero-cost transition should be reflected by the next observed
            // GameState rather than recommending a redundant LEVEL action.
            if gold_cost == 0 {
                continue;
            }

            if gold_cost > current_gold {
                diagnostics
                    .unaffordable_level_targets
                    .push(target_level);
                continue;
            }

            facts.levels.push(LevelOpportunityFact {
                target_level,
                gold_cost,
                expected_board_gain: None,
                slots_gained: target_level.saturating_sub(current_level),
                confidence,
            });
        }

        facts.levels.sort_by_key(|fact| fact.target_level);
        diagnostics.unaffordable_level_targets.sort_unstable();
        diagnostics.unaffordable_level_targets.dedup();
        Ok(())
    }

    fn build_scout_facts(
        &self,
        state: &GameState,
        now_ms: u64,
        facts: &mut OpportunityFacts,
    ) {
        for opponent in &state.lobby {
            let age_ms = now_ms.saturating_sub(opponent.last_seen_ms);
            if age_ms < self.config.scout_stale_after_ms {
                continue;
            }

            let age_span = self
                .config
                .scout_full_value_age_ms
                .saturating_sub(self.config.scout_stale_after_ms)
                .max(1);
            let stale_age = age_ms
                .saturating_sub(self.config.scout_stale_after_ms);

            let age_factor =
                (stale_age as f32 / age_span as f32).clamp(0.0, 1.0);
            let confidence_gap =
                (1.0 - opponent.confidence.value()).clamp(0.0, 1.0);

            let uncertainty_reduction =
                (age_factor * 0.70 + confidence_gap * 0.30)
                    .clamp(0.0, 1.0);

            if uncertainty_reduction <= 0.0 {
                continue;
            }

            facts.scouts.push(ScoutOpportunityFact {
                player_id: opponent.player_id.clone(),
                uncertainty_reduction,
                confidence: state.overall_confidence,
            });
        }

        facts.scouts.sort_by(|a, b| {
            b.uncertainty_reduction
                .total_cmp(&a.uncertainty_reduction)
                .then_with(|| a.player_id.cmp(&b.player_id))
        });
    }

    fn roll_budgets(
        &self,
        current_gold: u16,
        roll_cost: u16,
    ) -> Vec<u16> {
        let mut budgets: Vec<u16> = self
            .config
            .roll_budgets_gold
            .iter()
            .copied()
            .filter(|budget| *budget >= roll_cost)
            .map(|budget| budget.min(current_gold))
            .filter(|budget| *budget >= roll_cost)
            .collect();

        if self.config.include_max_affordable_budget {
            let max_affordable =
                current_gold - (current_gold % roll_cost);
            if max_affordable >= roll_cost {
                budgets.push(max_affordable);
            }
        }

        budgets.sort_unstable();
        budgets.dedup();
        budgets
    }
}

fn validate_rule_context(
    state: &GameState,
    rules: &TftRuleSet,
) -> Result<(), FactBuildError> {
    if let Some(patch) = &state.patch {
        if patch != &rules.patch {
            return Err(FactBuildError::PatchMismatch {
                state: patch.clone(),
                rules: rules.patch.clone(),
            });
        }
    }

    if let Some(set) = &state.set {
        if set != &rules.set {
            return Err(FactBuildError::SetMismatch {
                state: set.clone(),
                rules: rules.set.clone(),
            });
        }
    }

    Ok(())
}

fn min_confidence(a: Confidence, b: Confidence) -> Confidence {
    Confidence::new(a.value().min(b.value()))
        .expect("minimum of valid confidences is valid")
}

fn purchase_closes_upgrade(owned_copies: u16) -> bool {
    (owned_copies < 3 && owned_copies.saturating_add(1) >= 3)
        || (owned_copies < 9
            && owned_copies >= 3
            && owned_copies.saturating_add(1) >= 9)
}

fn next_upgrade_threshold(
    owned_copies: u16,
) -> Option<(u8, u16)> {
    if owned_copies < 3 {
        Some((2, 3))
    } else if owned_copies < 9 {
        Some((3, 9))
    } else {
        None
    }
}

fn known_tier_remaining(
    state: &GameState,
    rules: &TftRuleSet,
    catalog: &UnitCatalog,
    cost: u8,
) -> Result<u16, FactBuildError> {
    let units = catalog.units_at_cost(cost);
    if units.is_empty() {
        return Ok(0);
    }

    let per_unit = rules.unit_total_copies(cost)? as u32;
    let initial = per_unit.saturating_mul(units.len() as u32);

    let known_removed = units.iter().fold(0u32, |total, unit_id| {
        let own = self_owned_copies(state, unit_id) as u32;
        let opponents = analyze_unit_contestation(
            state,
            unit_id,
        )
        .observed_opponent_copies as u32;
        total.saturating_add(own).saturating_add(opponents)
    });

    Ok(initial
        .saturating_sub(known_removed)
        .min(u16::MAX as u32) as u16)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use agente_tft_contracts::{
        ObservationSource, Observed, OpponentState, PlayerState, ShopSlot,
        UnitInstance,
    };
    use agente_tft_tft_math::EconomyRules;
    use agente_tft_tft_rules::{
        ShopOdds, RULESET_SCHEMA_VERSION,
    };

    use super::*;

    fn observed<T>(value: T, confidence: f32) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(confidence).unwrap(),
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

    fn catalog() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "set": {
                    "key": "TFTSet18",
                    "number": 18,
                    "name": "Set 18"
                },
                "champions": [
                    {"api_name": "A", "name": "Alpha", "cost": 4, "traits": []},
                    {"api_name": "B", "name": "Beta", "cost": 4, "traits": []},
                    {"api_name": "C", "name": "Gamma", "cost": 4, "traits": []},
                    {"api_name": "D", "name": "Delta", "cost": 4, "traits": []},
                    {"api_name": "E", "name": "Epsilon", "cost": 1, "traits": []}
                ]
            })
            .to_string(),
        )
        .unwrap()
    }

    fn trait_catalog() -> TraitCatalog {
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

    fn rules() -> TftRuleSet {
        TftRuleSet {
            schema_version: RULESET_SCHEMA_VERSION,
            patch: "18.3b".into(),
            set: "TFTSet18".into(),
            shop_slots: 5,
            roll_cost_gold: 2,
            economy: EconomyRules::default(),
            shop_odds_by_level: BTreeMap::from([(
                7,
                ShopOdds {
                    by_cost: [0.19, 0.30, 0.40, 0.10, 0.01],
                },
            )]),
            unit_pool_copies_by_cost: BTreeMap::from([
                (1, 30),
                (2, 25),
                (3, 18),
                (4, 10),
                (5, 9),
            ]),
            xp_purchase_cost_gold: 4,
            xp_per_purchase: 4,
            xp_required_to_next_level: BTreeMap::from([
                (7, 36),
                (8, 68),
            ]),
            source: Some("fixture".into()),
            source_hash: None,
        }
    }

    fn state() -> GameState {
        let mut state = GameState::empty(100);
        state.patch = Some("18.3b".into());
        state.set = Some("TFTSet18".into());
        state.overall_confidence = Confidence::new(0.95).unwrap();
        state.player = PlayerState {
            hp: Some(observed(31u16, 0.95)),
            gold: Some(observed(48u16, 0.95)),
            level: Some(observed(7u8, 0.95)),
            xp: Some(observed(20u16, 0.94)),
            board: vec![unit("A", 2), unit("B", 1)],
            bench: vec![unit("B", 1)],
            shop: vec![
                observed(
                    ShopSlot {
                        slot: 0,
                        unit_id: Some("B".into()),
                    },
                    0.90,
                ),
                observed(
                    ShopSlot {
                        slot: 1,
                        unit_id: Some("A".into()),
                    },
                    0.92,
                ),
            ],
            ..PlayerState::default()
        };
        state.lobby = vec![OpponentState {
            player_id: "p2".into(),
            display_name: Some("P2".into()),
            hp: None,
            level: None,
            board: vec![unit("A", 1), unit("C", 2)],
            last_seen_ms: 1_000,
            confidence: Confidence::new(0.70).unwrap(),
        }];
        state
    }

    fn roll_state() -> GameState {
        let mut state = state();
        state.player.shop.clear();
        state
    }

    #[test]
    fn generates_buy_facts_and_detects_upgrade_close() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig::default()).unwrap();

        let result = builder
            .build(&state(), &rules(), &catalog(), 10_000)
            .unwrap();

        assert_eq!(result.facts.buys.len(), 2);

        let buy_b = result
            .facts
            .buys
            .iter()
            .find(|fact| fact.unit_id == "B")
            .unwrap();
        // B1★ + B1★ = 2 copies, buying one closes B2★.
        assert!(buy_b.closes_upgrade);
        assert_eq!(buy_b.gold_cost, 4);
    }

    #[test]
    fn visible_affordable_target_blocks_roll_until_bought() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig {
                roll_budgets_gold: vec![10, 20],
                include_max_affordable_budget: false,
                ..FactBuilderConfig::default()
            })
            .unwrap();

        let result = builder
            .build(&state(), &rules(), &catalog(), 10_000)
            .unwrap();

        // B is already visible and affordable in slot 0.
        assert!(result
            .facts
            .buys
            .iter()
            .any(|fact| fact.unit_id == "B"));
        assert!(result
            .diagnostics
            .roll_targets_blocked_by_shop
            .contains(&"B".to_string()));
        assert!(!result
            .facts
            .rolls
            .iter()
            .any(|fact| fact.target_unit_id.as_deref() == Some("B")));
    }

    #[test]
    fn generates_roll_windows_for_owned_upgrade_targets() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig {
                roll_budgets_gold: vec![10, 20],
                include_max_affordable_budget: false,
                ..FactBuilderConfig::default()
            })
            .unwrap();

        let result = builder
            .build(&roll_state(), &rules(), &catalog(), 10_000)
            .unwrap();

        // A is already 2★ => target 3★; B has two 1★ copies => target 2★.
        assert_eq!(result.diagnostics.roll_targets.len(), 2);
        assert_eq!(result.facts.rolls.len(), 4);

        let b20 = result
            .facts
            .rolls
            .iter()
            .find(|fact| {
                fact.target_unit_id.as_deref() == Some("B")
                    && fact.budget_gold == 20
            })
            .unwrap();

        assert!(b20.probability_at_least_one.unwrap() > 0.0);
        assert_eq!(b20.contested_copies, Some(0));
        assert!(b20.stop_condition.as_ref().unwrap().contains("Beta"));
    }

    #[test]
    fn known_tier_pool_subtracts_visible_owned_and_opponent_copies() {
        let remaining = known_tier_remaining(
            &state(),
            &rules(),
            &catalog(),
            4,
        )
        .unwrap();

        // Four cost-4 units * 10 = 40 initial.
        // Own: A2★=3, B1★+B1★=2 => 5.
        // Opponents: A1★=1, C2★=3 => 4.
        assert_eq!(remaining, 31);
    }

    #[test]
    fn generates_affordable_level_opportunity_from_rules() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig::default()).unwrap();

        let result = builder
            .build(&state(), &rules(), &catalog(), 10_000)
            .unwrap();

        let level8 = result
            .facts
            .levels
            .iter()
            .find(|fact| fact.target_level == 8)
            .unwrap();

        // Fixture: 36 XP needed from level 7, already have 20.
        // Need 16 XP = four purchases × 4g = 16g.
        assert_eq!(level8.gold_cost, 16);
        assert_eq!(level8.slots_gained, 1);
        assert_eq!(level8.confidence.value(), 0.94);

        // Level 9 needs 84g in this fixture and is not affordable at 48g.
        assert!(!result
            .facts
            .levels
            .iter()
            .any(|fact| fact.target_level == 9));
        assert!(result
            .diagnostics
            .unaffordable_level_targets
            .contains(&9));
    }

    #[test]
    fn absent_xp_rules_generate_no_level_fact() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig::default()).unwrap();
        let mut rules = rules();
        rules.xp_purchase_cost_gold = 0;
        rules.xp_per_purchase = 0;
        rules.xp_required_to_next_level.clear();

        let result = builder
            .build(&state(), &rules, &catalog(), 10_000)
            .unwrap();

        assert!(result.facts.levels.is_empty());
        assert!(!result.diagnostics.xp_rules_available);
    }

    #[test]
    fn board_strength_enriches_level_fact_conservatively() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig::default()).unwrap();
        let strength = BoardStrengthEngine::new(
            agente_tft_board_strength::BoardStrengthConfig::default(),
        )
        .unwrap();

        let result = builder
            .build_with_board_strength(
                &state(),
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                10_000,
            )
            .unwrap();

        let level8 = result
            .facts
            .levels
            .iter()
            .find(|fact| fact.target_level == 8)
            .unwrap();

        assert!(level8.expected_board_gain.is_some());
        assert!(level8.confidence.value() <= 0.55);
        assert!(result
            .diagnostics
            .level_board_plans
            .iter()
            .any(|plan| plan.target_level == 8));
    }

    #[test]
    fn stale_opponent_generates_scout_fact() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig::default()).unwrap();

        let result = builder
            .build(&state(), &rules(), &catalog(), 40_000)
            .unwrap();

        assert_eq!(result.facts.scouts.len(), 1);
        assert_eq!(result.facts.scouts[0].player_id, "p2");
        assert!(result.facts.scouts[0].uncertainty_reduction > 0.0);
    }

    #[test]
    fn fresh_opponent_does_not_generate_scout_fact() {
        let builder =
            OpportunityFactBuilder::new(FactBuilderConfig::default()).unwrap();

        let result = builder
            .build(&state(), &rules(), &catalog(), 5_000)
            .unwrap();

        assert!(result.facts.scouts.is_empty());
    }

    #[test]
    fn rules_patch_mismatch_is_rejected() {
        let mut state = state();
        state.patch = Some("18.4".into());

        let error = OpportunityFactBuilder::new(
            FactBuilderConfig::default(),
        )
        .unwrap()
        .build(&state, &rules(), &catalog(), 1_000)
        .unwrap_err();

        assert!(matches!(error, FactBuildError::PatchMismatch { .. }));
    }
}
