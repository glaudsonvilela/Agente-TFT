//! Conditional economy branches. These are arithmetic consequences of supplied
//! coefficients, not forecasts of a fight or training labels from a video.
use agente_tft_tft_math::interest_for_gold;
use agente_tft_tft_rules::TftRuleSet;
use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum BranchError {
    #[error("observed patch and ruleset patch differ")]
    PatchMismatch,
    #[error("invalid or unavailable economy rules")]
    InvalidRules,
    #[error("action costs more gold than available")]
    Unaffordable,
    #[error("economy arithmetic overflow")]
    Overflow,
    #[error("eliminated player has no planning branch")]
    Eliminated,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct EconomySnapshot {
    pub gold: u16,
    pub hp: u16,
    pub level: u8,
    pub xp: u16,
    /// Positive for wins, negative for losses, zero for no active streak.
    pub streak: i16,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct StreakTier {
    pub min_results: u16,
    pub bonus_gold: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OrdinaryPvpRules {
    pub base_income: u16,
    pub win_gold: u16,
    pub stage_base_damage: u16,
    pub damage_per_survivor: u16,
    /// Coefficients must be reviewed for the observed patch by the caller.
    pub streak_tiers: Vec<StreakTier>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EconomyChoice {
    Hold,
    Roll {
        times: u16,
    },
    BuyXp {
        purchases: u16,
    },
    /// Only the gold proceeds are projected. The altered board is not simulated.
    SellObserved {
        proceeds: u16,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutcomeCondition {
    Win,
    Loss,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ConditionalReceipt {
    pub condition: OutcomeCondition,
    pub gold_after_action: u16,
    pub level_after_action: u8,
    pub xp_after_action: u16,
    pub gold_after_round: u16,
    pub hp_after_round: u16,
    pub streak_after: i16,
    pub win_gold: u16,
    pub interest_gold: u16,
    pub streak_gold: u16,
    pub base_income_gold: u16,
    pub damage: u16,
    pub eliminated: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EconomyBranch {
    pub action: EconomyChoice,
    pub win: ConditionalReceipt,
    pub loss: ConditionalReceipt,
    pub scope: &'static str,
    pub real_match_outcome_known: bool,
    pub board_and_combat_effects_simulated: bool,
    pub runtime_promoted: bool,
}

fn validate(round: &OrdinaryPvpRules, rules: &TftRuleSet) -> Result<(), BranchError> {
    rules.validate().map_err(|_| BranchError::InvalidRules)?;
    if rules.economy.gold_per_interest_step == 0 || round.streak_tiers.is_empty() {
        return Err(BranchError::InvalidRules);
    }
    let mut previous = 0;
    for tier in &round.streak_tiers {
        if tier.min_results <= previous {
            return Err(BranchError::InvalidRules);
        }
        previous = tier.min_results;
    }
    Ok(())
}

fn after_action(
    snapshot: EconomySnapshot,
    action: EconomyChoice,
    rules: &TftRuleSet,
) -> Result<(u16, u8, u16), BranchError> {
    let gold = snapshot.gold;
    let level = snapshot.level;
    let xp = snapshot.xp;
    let amount = match action {
        EconomyChoice::Hold => return Ok((gold, level, xp)),
        EconomyChoice::Roll { times } => u32::from(times) * u32::from(rules.roll_cost_gold),
        EconomyChoice::BuyXp { purchases } if rules.xp_rules_available() => {
            u32::from(purchases) * u32::from(rules.xp_purchase_cost_gold)
        }
        EconomyChoice::BuyXp { .. } => return Err(BranchError::InvalidRules),
        EconomyChoice::SellObserved { proceeds } => {
            return gold
                .checked_add(proceeds)
                .map(|new_gold| (new_gold, level, xp))
                .ok_or(BranchError::Overflow)
        }
    };
    if amount > u32::from(gold) {
        return Err(BranchError::Unaffordable);
    }
    let new_gold = gold - amount as u16;
    if let EconomyChoice::BuyXp { purchases } = action {
        let mut new_level = level;
        let mut new_xp = u32::from(xp) + u32::from(purchases) * u32::from(rules.xp_per_purchase);
        loop {
            let threshold = rules
                .xp_required_to_next_level
                .get(&new_level)
                .copied()
                .ok_or(BranchError::InvalidRules)?;
            if new_xp < u32::from(threshold) {
                break;
            }
            new_xp -= u32::from(threshold);
            new_level = new_level.checked_add(1).ok_or(BranchError::Overflow)?;
            if new_xp == 0 && !rules.xp_required_to_next_level.contains_key(&new_level) {
                break;
            }
        }
        return Ok((
            new_gold,
            new_level,
            u16::try_from(new_xp).map_err(|_| BranchError::Overflow)?,
        ));
    }
    Ok((new_gold, level, xp))
}

fn receipt(
    snapshot: EconomySnapshot,
    gold_after_action: u16,
    level_after_action: u8,
    xp_after_action: u16,
    outcome: OutcomeCondition,
    enemy_survivors: u16,
    rules: &TftRuleSet,
    round: &OrdinaryPvpRules,
) -> Result<ConditionalReceipt, BranchError> {
    let sign = if outcome == OutcomeCondition::Win {
        1
    } else {
        -1
    };
    let streak_after = if snapshot.streak.signum() == sign {
        snapshot
            .streak
            .checked_add(sign)
            .ok_or(BranchError::Overflow)?
    } else {
        sign
    };
    let damage = if outcome == OutcomeCondition::Loss {
        round
            .stage_base_damage
            .checked_add(
                enemy_survivors
                    .checked_mul(round.damage_per_survivor)
                    .ok_or(BranchError::Overflow)?,
            )
            .ok_or(BranchError::Overflow)?
    } else {
        0
    };
    let hp_after_round = snapshot.hp.saturating_sub(damage);
    let eliminated = hp_after_round == 0;
    let win_gold = if outcome == OutcomeCondition::Win {
        round.win_gold
    } else {
        0
    };
    let gold_before_interest = gold_after_action
        .checked_add(win_gold)
        .ok_or(BranchError::Overflow)?;
    let interest_gold = if eliminated {
        0
    } else {
        interest_for_gold(gold_before_interest, rules.economy)
    };
    let streak_gold = if eliminated {
        0
    } else {
        round
            .streak_tiers
            .iter()
            .filter(|tier| streak_after.unsigned_abs() >= tier.min_results)
            .map(|tier| tier.bonus_gold)
            .last()
            .unwrap_or(0)
    };
    let base_income_gold = if eliminated { 0 } else { round.base_income };
    let gold_after_round = gold_before_interest
        .checked_add(interest_gold)
        .and_then(|value| value.checked_add(streak_gold))
        .and_then(|value| value.checked_add(base_income_gold))
        .ok_or(BranchError::Overflow)?;
    Ok(ConditionalReceipt {
        condition: outcome,
        gold_after_action,
        level_after_action,
        xp_after_action,
        gold_after_round,
        hp_after_round,
        streak_after,
        win_gold,
        interest_gold,
        streak_gold,
        base_income_gold,
        damage,
        eliminated,
    })
}

/// Compares the same observed state and conditional outcome across choices.
/// It deliberately returns no "best action": counterfactual win probability,
/// future board power, special income, and hidden pool state are unknown.
pub fn project_ordinary_pvp_branches(
    observed_patch: &str,
    snapshot: EconomySnapshot,
    rules: &TftRuleSet,
    round: &OrdinaryPvpRules,
    actions: &[EconomyChoice],
    enemy_survivors_if_loss: u16,
) -> Result<Vec<EconomyBranch>, BranchError> {
    if observed_patch != rules.patch {
        return Err(BranchError::PatchMismatch);
    }
    if snapshot.hp == 0 {
        return Err(BranchError::Eliminated);
    }
    validate(round, rules)?;
    if let Some(threshold) = rules.xp_required_to_next_level.get(&snapshot.level) {
        if snapshot.xp >= *threshold {
            return Err(BranchError::InvalidRules);
        }
    }
    actions
        .iter()
        .copied()
        .map(|action| {
            let (gold, level, xp) = after_action(snapshot, action, rules)?;
            Ok(EconomyBranch {
                action,
                win: receipt(
                    snapshot,
                    gold,
                    level,
                    xp,
                    OutcomeCondition::Win,
                    0,
                    rules,
                    round,
                )?,
                loss: receipt(
                    snapshot,
                    gold,
                    level,
                    xp,
                    OutcomeCondition::Loss,
                    enemy_survivors_if_loss,
                    rules,
                    round,
                )?,
                scope: "conditional_ordinary_pvp_economy",
                real_match_outcome_known: false,
                board_and_combat_effects_simulated: false,
                runtime_promoted: false,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_tft_math::EconomyRules;
    use agente_tft_tft_rules::{ShopOdds, RULESET_SCHEMA_VERSION};
    use std::collections::BTreeMap;

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
            unit_pool_copies_by_cost: BTreeMap::from([(1, 30)]),
            xp_purchase_cost_gold: 4,
            xp_per_purchase: 4,
            xp_required_to_next_level: BTreeMap::from([(7, 56), (8, 68)]),
            source: Some("fixture".into()),
            source_hash: None,
        }
    }

    fn round() -> OrdinaryPvpRules {
        OrdinaryPvpRules {
            base_income: 5,
            win_gold: 1,
            stage_base_damage: 7,
            damage_per_survivor: 1,
            streak_tiers: vec![
                StreakTier {
                    min_results: 2,
                    bonus_gold: 1,
                },
                StreakTier {
                    min_results: 5,
                    bonus_gold: 2,
                },
                StreakTier {
                    min_results: 6,
                    bonus_gold: 3,
                },
            ],
        }
    }

    #[test]
    fn same_outcome_exposes_interest_and_loss_streak_tradeoff() {
        let result = project_ordinary_pvp_branches(
            "fixture",
            EconomySnapshot {
                gold: 50,
                hp: 20,
                level: 7,
                xp: 0,
                streak: -4,
            },
            &rules(),
            &round(),
            &[
                EconomyChoice::Hold,
                EconomyChoice::Roll { times: 1 },
                EconomyChoice::SellObserved { proceeds: 3 },
            ],
            2,
        )
        .unwrap();
        assert_eq!(result[0].loss.gold_after_round, 62); // 50+5 interest+2 streak+5 base
        assert_eq!(result[0].loss.hp_after_round, 11); // stage 7 + two survivors
        assert_eq!(result[0].loss.streak_after, -5);
        assert_eq!(result[1].loss.gold_after_round, 59); // 48+4 interest+2+5
        assert_eq!(result[2].loss.gold_after_round, 65); // sold 3; board effect unknown
        assert!(!result[2].board_and_combat_effects_simulated);
        assert_eq!(result[0].win.streak_after, 1);
        assert_eq!(result[0].win.streak_gold, 0);
        assert!(!result[0].real_match_outcome_known);
    }

    #[test]
    fn lethal_loss_gets_no_future_income() {
        let result = project_ordinary_pvp_branches(
            "fixture",
            EconomySnapshot {
                gold: 30,
                hp: 8,
                level: 7,
                xp: 0,
                streak: -4,
            },
            &rules(),
            &round(),
            &[EconomyChoice::Hold],
            2,
        )
        .unwrap();
        assert_eq!(result[0].loss.hp_after_round, 0);
        assert_eq!(result[0].loss.gold_after_round, 30);
        assert!(result[0].loss.eliminated);
    }

    #[test]
    fn xp_branch_crosses_level_without_guessing_shop_contents() {
        let result = project_ordinary_pvp_branches(
            "fixture",
            EconomySnapshot {
                gold: 20,
                hp: 30,
                level: 7,
                xp: 54,
                streak: 0,
            },
            &rules(),
            &round(),
            &[EconomyChoice::BuyXp { purchases: 1 }],
            1,
        )
        .unwrap();
        assert_eq!(result[0].win.gold_after_action, 16);
        assert_eq!(result[0].win.level_after_action, 8);
        assert_eq!(result[0].win.xp_after_action, 2);
        assert!(!result[0].board_and_combat_effects_simulated);
    }

    #[test]
    fn refuses_wrong_patch_and_unaffordable_action() {
        let snapshot = EconomySnapshot {
            gold: 3,
            hp: 20,
            level: 7,
            xp: 0,
            streak: 0,
        };
        assert_eq!(
            project_ordinary_pvp_branches(
                "18.4B",
                snapshot,
                &rules(),
                &round(),
                &[EconomyChoice::Hold],
                0
            )
            .unwrap_err(),
            BranchError::PatchMismatch
        );
        assert_eq!(
            project_ordinary_pvp_branches(
                "fixture",
                snapshot,
                &rules(),
                &round(),
                &[EconomyChoice::BuyXp { purchases: 1 }],
                0
            )
            .unwrap_err(),
            BranchError::Unaffordable
        );
    }
}
