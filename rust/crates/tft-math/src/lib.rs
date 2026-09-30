use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum MathError {
    #[error("probability must be finite and between 0 and 1")]
    InvalidProbability,
    #[error("target copies cannot exceed total copies remaining in the cost tier")]
    InvalidPool,
    #[error("shop slots must be greater than zero")]
    InvalidShopSlots,
    #[error("roll cost must be greater than zero")]
    InvalidRollCost,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnitPoolSnapshot {
    pub unit_total_copies: u16,
    pub self_owned_copies: u16,
    pub opponent_observed_copies: u16,
    pub other_known_removed_copies: u16,
}

impl UnitPoolSnapshot {
    pub fn target_remaining(self) -> u16 {
        self.unit_total_copies.saturating_sub(
            self.self_owned_copies
                .saturating_add(self.opponent_observed_copies)
                .saturating_add(self.other_known_removed_copies),
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct TierPoolSnapshot {
    /// Total remaining copies across every unit of the target cost tier.
    pub total_remaining: u16,
    /// Remaining copies of the target unit within that tier.
    pub target_remaining: u16,
}

impl TierPoolSnapshot {
    pub fn validate(self) -> Result<(), MathError> {
        if self.target_remaining > self.total_remaining {
            return Err(MathError::InvalidPool);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ShopHitInput {
    /// Probability that one shop slot rolls the target unit's cost tier.
    pub target_tier_probability: f64,
    pub pool: TierPoolSnapshot,
    pub shop_slots: u8,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ShopHitEstimate {
    pub probability_at_least_one: f64,
    pub expected_target_copies: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct RollBudgetEstimate {
    pub shops_seen: u32,
    pub probability_at_least_one: f64,
    pub expected_target_copies: f64,
}

pub fn estimate_single_shop(input: ShopHitInput) -> Result<ShopHitEstimate, MathError> {
    validate_probability(input.target_tier_probability)?;
    input.pool.validate()?;

    if input.shop_slots == 0 {
        return Err(MathError::InvalidShopSlots);
    }

    if input.pool.total_remaining == 0 || input.pool.target_remaining == 0 {
        return Ok(ShopHitEstimate {
            probability_at_least_one: 0.0,
            expected_target_copies: 0.0,
        });
    }

    let n = input.shop_slots as u32;
    let q = input.target_tier_probability;
    let mut probability_no_target = 0.0_f64;

    for tier_slots in 0..=n {
        let probability_tier_slot_count =
            binomial_probability(n, tier_slots, q);

        let no_target_given_tier_slots = hypergeometric_no_target(
            input.pool.total_remaining as u32,
            input.pool.target_remaining as u32,
            tier_slots,
        );

        probability_no_target += probability_tier_slot_count * no_target_given_tier_slots;
    }

    let probability_at_least_one = (1.0 - probability_no_target).clamp(0.0, 1.0);

    // Linearity of expectation does not require independent slots.
    let target_share =
        input.pool.target_remaining as f64 / input.pool.total_remaining as f64;
    let expected_target_copies = n as f64 * q * target_share;

    Ok(ShopHitEstimate {
        probability_at_least_one,
        expected_target_copies,
    })
}

/// Estimate repeated shops assuming the observed pool state remains unchanged between shops.
///
/// This is appropriate for comparing "roll now vs. don't roll" under a stable-pool snapshot.
/// Once target copies are purchased, callers should recompute from the new pool state.
pub fn estimate_roll_budget(
    input: ShopHitInput,
    roll_budget_gold: u16,
    roll_cost_gold: u16,
    include_current_shop: bool,
) -> Result<RollBudgetEstimate, MathError> {
    if roll_cost_gold == 0 {
        return Err(MathError::InvalidRollCost);
    }

    let per_shop = estimate_single_shop(input)?;
    let paid_shops = (roll_budget_gold / roll_cost_gold) as u32;
    let shops_seen = paid_shops + u32::from(include_current_shop);

    if shops_seen == 0 {
        return Ok(RollBudgetEstimate {
            shops_seen,
            probability_at_least_one: 0.0,
            expected_target_copies: 0.0,
        });
    }

    let probability_at_least_one =
        1.0 - (1.0 - per_shop.probability_at_least_one).powi(shops_seen as i32);

    Ok(RollBudgetEstimate {
        shops_seen,
        probability_at_least_one: probability_at_least_one.clamp(0.0, 1.0),
        expected_target_copies: per_shop.expected_target_copies * shops_seen as f64,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct EconomyRules {
    pub gold_per_interest_step: u16,
    pub max_interest: u16,
}

impl Default for EconomyRules {
    fn default() -> Self {
        Self {
            gold_per_interest_step: 10,
            max_interest: 5,
        }
    }
}

pub fn interest_for_gold(gold: u16, rules: EconomyRules) -> u16 {
    if rules.gold_per_interest_step == 0 {
        return 0;
    }

    (gold / rules.gold_per_interest_step).min(rules.max_interest)
}

pub fn interest_lost_by_spending(
    current_gold: u16,
    spend_gold: u16,
    rules: EconomyRules,
) -> u16 {
    let before = interest_for_gold(current_gold, rules);
    let after = interest_for_gold(current_gold.saturating_sub(spend_gold), rules);
    before.saturating_sub(after)
}

fn validate_probability(value: f64) -> Result<(), MathError> {
    if value.is_finite() && (0.0..=1.0).contains(&value) {
        Ok(())
    } else {
        Err(MathError::InvalidProbability)
    }
}

fn binomial_probability(n: u32, k: u32, p: f64) -> f64 {
    if k > n {
        return 0.0;
    }

    combination(n, k) * p.powi(k as i32) * (1.0 - p).powi((n - k) as i32)
}

/// Probability of drawing zero target copies from a tier pool without replacement.
///
/// If more tier slots are requested than copies exist in the tier, the impossible
/// part of the distribution contributes zero probability.
fn hypergeometric_no_target(total: u32, target: u32, draws: u32) -> f64 {
    if draws == 0 {
        return 1.0;
    }
    if total == 0 || draws > total {
        return 0.0;
    }

    let non_target = total.saturating_sub(target);
    if draws > non_target {
        return 0.0;
    }

    combination(non_target, draws) / combination(total, draws)
}

fn combination(n: u32, k: u32) -> f64 {
    if k > n {
        return 0.0;
    }

    let k = k.min(n - k);
    if k == 0 {
        return 1.0;
    }

    let mut result = 1.0_f64;
    for i in 1..=k {
        result *= (n - k + i) as f64 / i as f64;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(q: f64, total: u16, target: u16) -> ShopHitInput {
        ShopHitInput {
            target_tier_probability: q,
            pool: TierPoolSnapshot {
                total_remaining: total,
                target_remaining: target,
            },
            shop_slots: 5,
        }
    }

    #[test]
    fn unit_pool_snapshot_saturates_at_zero() {
        let pool = UnitPoolSnapshot {
            unit_total_copies: 10,
            self_owned_copies: 3,
            opponent_observed_copies: 9,
            other_known_removed_copies: 0,
        };
        assert_eq!(pool.target_remaining(), 0);
    }

    #[test]
    fn all_slots_same_tier_matches_hypergeometric_result() {
        let estimate = estimate_single_shop(input(1.0, 10, 2)).unwrap();

        // P(no target) = C(8,5)/C(10,5) = 56/252.
        let expected = 1.0 - 56.0 / 252.0;
        assert!((estimate.probability_at_least_one - expected).abs() < 1e-10);
    }

    #[test]
    fn zero_tier_probability_means_zero_hit_chance() {
        let estimate = estimate_single_shop(input(0.0, 30, 4)).unwrap();
        assert_eq!(estimate.probability_at_least_one, 0.0);
        assert_eq!(estimate.expected_target_copies, 0.0);
    }

    #[test]
    fn zero_target_remaining_means_zero_hit_chance() {
        let estimate = estimate_single_shop(input(0.35, 30, 0)).unwrap();
        assert_eq!(estimate.probability_at_least_one, 0.0);
    }

    #[test]
    fn repeated_shops_raise_hit_probability() {
        let one = estimate_single_shop(input(0.25, 80, 8)).unwrap();
        let rolls = estimate_roll_budget(input(0.25, 80, 8), 20, 2, true).unwrap();

        assert_eq!(rolls.shops_seen, 11);
        assert!(rolls.probability_at_least_one > one.probability_at_least_one);
    }

    #[test]
    fn interest_loss_is_calculated_from_configurable_rules() {
        let rules = EconomyRules::default();
        assert_eq!(interest_for_gold(50, rules), 5);
        assert_eq!(interest_for_gold(39, rules), 3);
        assert_eq!(interest_lost_by_spending(50, 12, rules), 2);
    }

    #[test]
    fn invalid_pool_is_rejected() {
        let error = estimate_single_shop(input(0.25, 3, 4)).unwrap_err();
        assert_eq!(error, MathError::InvalidPool);
    }

    #[test]
    fn invalid_probability_is_rejected() {
        let error = estimate_single_shop(input(1.1, 30, 4)).unwrap_err();
        assert_eq!(error, MathError::InvalidProbability);
    }
}
