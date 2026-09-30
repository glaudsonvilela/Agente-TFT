use agente_tft_contracts::GameState;
use agente_tft_lobby_analysis::{
    analyze_unit_contestation, self_owned_copies, ContestingPlayer,
};
use agente_tft_tft_math::{
    estimate_roll_budget, interest_lost_by_spending, RollBudgetEstimate, UnitPoolSnapshot,
};
use agente_tft_tft_rules::{RuleSetError, TftRuleSet};
use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum StrategyAnalysisError {
    #[error("unit_id cannot be empty")]
    EmptyUnitId,
    #[error("target cost must be in [1,5]")]
    InvalidCost,
    #[error("tier_total_remaining must be >= target_remaining")]
    InvalidTierPool,
    #[error("TFT rules error: {0}")]
    Rules(#[from] RuleSetError),
    #[error("TFT math error: {0}")]
    Math(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct KnownPoolState {
    pub unit_total_copies: u16,
    pub self_owned_copies: u16,
    pub opponent_observed_copies: u16,
    pub other_known_removed_copies: u16,
    pub target_remaining: u16,
    /// Total remaining copies across every unit of this cost tier.
    /// This must come from a separately validated pool accounting layer.
    pub tier_total_remaining: u16,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RollWindowFact {
    pub budget_gold: u16,
    pub shops_seen: u32,
    pub probability_at_least_one: f64,
    pub expected_target_copies: f64,
    pub interest_lost: u16,
    pub ending_gold_before_other_spend: u16,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TargetRollAnalysis {
    pub unit_id: String,
    pub cost: u8,
    pub level: u8,
    pub current_gold: u16,
    pub current_hp: Option<u16>,
    pub pool: KnownPoolState,
    pub contesting_players: Vec<ContestingPlayer>,
    pub roll_windows: Vec<RollWindowFact>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TargetRollInput<'a> {
    pub state: &'a GameState,
    pub rules: &'a TftRuleSet,
    pub unit_id: &'a str,
    pub cost: u8,
    pub tier_total_remaining: u16,
    pub other_known_removed_copies: u16,
    pub budgets_gold: &'a [u16],
    pub include_current_shop: bool,
}

pub fn analyze_target_roll(
    input: TargetRollInput<'_>,
) -> Result<TargetRollAnalysis, StrategyAnalysisError> {
    let unit_id = input.unit_id.trim();
    if unit_id.is_empty() {
        return Err(StrategyAnalysisError::EmptyUnitId);
    }
    if !(1..=5).contains(&input.cost) {
        return Err(StrategyAnalysisError::InvalidCost);
    }

    input.rules.validate()?;

    let level = input
        .state
        .player
        .level
        .as_ref()
        .map(|value| value.value)
        .ok_or_else(|| StrategyAnalysisError::Math("player level is unknown".into()))?;

    let current_gold = input
        .state
        .player
        .gold
        .as_ref()
        .map(|value| value.value)
        .ok_or_else(|| StrategyAnalysisError::Math("player gold is unknown".into()))?;

    let current_hp = input.state.player.hp.as_ref().map(|value| value.value);

    let unit_total_copies = input.rules.unit_total_copies(input.cost)?;
    let self_owned = self_owned_copies(input.state, unit_id);
    let contestation = analyze_unit_contestation(input.state, unit_id);
    let opponent_observed = contestation.observed_opponent_copies;

    let unit_pool = UnitPoolSnapshot {
        unit_total_copies,
        self_owned_copies: self_owned,
        opponent_observed_copies: opponent_observed,
        other_known_removed_copies: input.other_known_removed_copies,
    };
    let target_remaining = unit_pool.target_remaining();

    if input.tier_total_remaining < target_remaining {
        return Err(StrategyAnalysisError::InvalidTierPool);
    }

    let shop_input = input.rules.shop_hit_input(
        level,
        input.cost,
        input.tier_total_remaining,
        target_remaining,
    )?;

    let mut budgets = input.budgets_gold.to_vec();
    budgets.sort_unstable();
    budgets.dedup();

    let mut roll_windows = Vec::with_capacity(budgets.len());
    for budget in budgets {
        let effective_budget = budget.min(current_gold);
        let estimate: RollBudgetEstimate = estimate_roll_budget(
            shop_input,
            effective_budget,
            input.rules.roll_cost_gold,
            input.include_current_shop,
        )
        .map_err(|error| StrategyAnalysisError::Math(error.to_string()))?;

        roll_windows.push(RollWindowFact {
            budget_gold: effective_budget,
            shops_seen: estimate.shops_seen,
            probability_at_least_one: estimate.probability_at_least_one,
            expected_target_copies: estimate.expected_target_copies,
            interest_lost: interest_lost_by_spending(
                current_gold,
                effective_budget,
                input.rules.economy,
            ),
            ending_gold_before_other_spend: current_gold.saturating_sub(effective_budget),
        });
    }

    Ok(TargetRollAnalysis {
        unit_id: unit_id.to_string(),
        cost: input.cost,
        level,
        current_gold,
        current_hp,
        pool: KnownPoolState {
            unit_total_copies,
            self_owned_copies: self_owned,
            opponent_observed_copies: opponent_observed,
            other_known_removed_copies: input.other_known_removed_copies,
            target_remaining,
            tier_total_remaining: input.tier_total_remaining,
        },
        contesting_players: contestation.contesting_players,
        roll_windows,
    })
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use agente_tft_contracts::{
        Confidence, GameState, ObservationSource, Observed, OpponentState, PlayerState,
        UnitInstance,
    };
    use agente_tft_tft_math::EconomyRules;
    use agente_tft_tft_rules::{ShopOdds, TftRuleSet, RULESET_SCHEMA_VERSION};

    use super::*;

    fn observed<T>(value: T) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(1.0).unwrap(),
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

    fn state() -> GameState {
        let mut state = GameState::empty(0);
        state.player = PlayerState {
            gold: Some(observed(50)),
            hp: Some(observed(31)),
            level: Some(observed(7)),
            board: vec![unit("X", 1)],
            bench: vec![unit("X", 2)],
            ..PlayerState::default()
        };
        state.lobby = vec![OpponentState {
            player_id: "p2".into(),
            display_name: Some("Player 2".into()),
            hp: None,
            level: None,
            board: vec![unit("X", 2)],
            last_seen_ms: 100,
            confidence: Confidence::new(1.0).unwrap(),
        }];
        state
    }

    fn rules() -> TftRuleSet {
        TftRuleSet {
            schema_version: RULESET_SCHEMA_VERSION,
            patch: "fixture".into(),
            set: "fixture".into(),
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
            source: Some("fixture".into()),
            source_hash: None,
        }
    }

    #[test]
    fn analysis_uses_observed_contestation_and_own_copies() {
        let state = state();
        let rules = rules();
        let result = analyze_target_roll(TargetRollInput {
            state: &state,
            rules: &rules,
            unit_id: "X",
            cost: 4,
            tier_total_remaining: 70,
            other_known_removed_copies: 0,
            budgets_gold: &[10, 20],
            include_current_shop: true,
        })
        .unwrap();

        // self: 1★ + 2★ = 4; Player 2: 2★ = 3; cost-4 total fixture = 10.
        assert_eq!(result.pool.self_owned_copies, 4);
        assert_eq!(result.pool.opponent_observed_copies, 3);
        assert_eq!(result.pool.target_remaining, 3);
        assert_eq!(result.contesting_players[0].player_id, "p2");
        assert_eq!(result.roll_windows.len(), 2);
        assert!(result.roll_windows[1].probability_at_least_one
            > result.roll_windows[0].probability_at_least_one);
    }

    #[test]
    fn budget_is_capped_at_current_gold() {
        let state = state();
        let rules = rules();
        let result = analyze_target_roll(TargetRollInput {
            state: &state,
            rules: &rules,
            unit_id: "X",
            cost: 4,
            tier_total_remaining: 70,
            other_known_removed_copies: 0,
            budgets_gold: &[100],
            include_current_shop: false,
        })
        .unwrap();

        assert_eq!(result.roll_windows[0].budget_gold, 50);
        assert_eq!(result.roll_windows[0].ending_gold_before_other_spend, 0);
    }

    #[test]
    fn invalid_tier_pool_is_rejected() {
        let state = state();
        let rules = rules();
        let error = analyze_target_roll(TargetRollInput {
            state: &state,
            rules: &rules,
            unit_id: "X",
            cost: 4,
            tier_total_remaining: 2,
            other_known_removed_copies: 0,
            budgets_gold: &[10],
            include_current_shop: false,
        })
        .unwrap_err();

        assert_eq!(error, StrategyAnalysisError::InvalidTierPool);
    }
}
