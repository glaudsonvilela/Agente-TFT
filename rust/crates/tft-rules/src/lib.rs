use std::collections::BTreeMap;

use agente_tft_tft_math::{EconomyRules, ShopHitInput, TierPoolSnapshot};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const RULESET_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error, PartialEq)]
pub enum RuleSetError {
    #[error("ruleset schema version is unsupported")]
    UnsupportedSchemaVersion,
    #[error("patch cannot be empty")]
    EmptyPatch,
    #[error("set cannot be empty")]
    EmptySet,
    #[error("shop_slots must be greater than zero")]
    InvalidShopSlots,
    #[error("roll_cost_gold must be greater than zero")]
    InvalidRollCost,
    #[error("shop odds for level {level} must contain finite probabilities in [0,1] summing to 1")]
    InvalidShopOdds { level: u8 },
    #[error("cost tier {cost} must be between 1 and 5")]
    InvalidCostTier { cost: u8 },
    #[error("pool copies for cost tier {cost} must be greater than zero")]
    InvalidPoolCopies { cost: u8 },
    #[error("no shop odds configured for level {0}")]
    MissingLevel(u8),
    #[error("no pool copy count configured for cost tier {0}")]
    MissingCost(u8),
    #[error("XP purchase cost and XP per purchase must both be > 0 when XP rules are configured")]
    InvalidXpPurchase,
    #[error("XP threshold for level {level} must be > 0")]
    InvalidXpThreshold { level: u8 },
    #[error("no XP threshold configured for level {0}")]
    MissingXpThreshold(u8),
    #[error("target level must be greater than current level")]
    InvalidTargetLevel,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ShopOdds {
    /// Index 0 is cost 1, index 4 is cost 5.
    pub by_cost: [f64; 5],
}

impl ShopOdds {
    pub fn validate(self, level: u8) -> Result<(), RuleSetError> {
        if self
            .by_cost
            .iter()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
        {
            return Err(RuleSetError::InvalidShopOdds { level });
        }

        let total: f64 = self.by_cost.iter().sum();
        if (total - 1.0).abs() > 1e-6 {
            return Err(RuleSetError::InvalidShopOdds { level });
        }

        Ok(())
    }

    pub fn probability_for_cost(self, cost: u8) -> Result<f64, RuleSetError> {
        if !(1..=5).contains(&cost) {
            return Err(RuleSetError::InvalidCostTier { cost });
        }
        Ok(self.by_cost[(cost - 1) as usize])
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TftRuleSet {
    pub schema_version: u32,
    pub patch: String,
    pub set: String,
    pub shop_slots: u8,
    pub roll_cost_gold: u16,
    pub economy: EconomyRules,
    pub shop_odds_by_level: BTreeMap<u8, ShopOdds>,
    pub unit_pool_copies_by_cost: BTreeMap<u8, u16>,
    #[serde(default)]
    pub xp_purchase_cost_gold: u16,
    #[serde(default)]
    pub xp_per_purchase: u16,
    /// XP required to advance from the keyed level to the next level.
    #[serde(default)]
    pub xp_required_to_next_level: BTreeMap<u8, u16>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub source_hash: Option<String>,
}

impl TftRuleSet {
    pub fn validate(&self) -> Result<(), RuleSetError> {
        if self.schema_version != RULESET_SCHEMA_VERSION {
            return Err(RuleSetError::UnsupportedSchemaVersion);
        }
        if self.patch.trim().is_empty() {
            return Err(RuleSetError::EmptyPatch);
        }
        if self.set.trim().is_empty() {
            return Err(RuleSetError::EmptySet);
        }
        if self.shop_slots == 0 {
            return Err(RuleSetError::InvalidShopSlots);
        }
        if self.roll_cost_gold == 0 {
            return Err(RuleSetError::InvalidRollCost);
        }

        for (&level, &odds) in &self.shop_odds_by_level {
            odds.validate(level)?;
        }

        for (&cost, &copies) in &self.unit_pool_copies_by_cost {
            if !(1..=5).contains(&cost) {
                return Err(RuleSetError::InvalidCostTier { cost });
            }
            if copies == 0 {
                return Err(RuleSetError::InvalidPoolCopies { cost });
            }
        }

        let xp_rules_present = self.xp_purchase_cost_gold > 0
            || self.xp_per_purchase > 0
            || !self.xp_required_to_next_level.is_empty();

        if xp_rules_present {
            if self.xp_purchase_cost_gold == 0 || self.xp_per_purchase == 0 {
                return Err(RuleSetError::InvalidXpPurchase);
            }
            for (&level, &required) in &self.xp_required_to_next_level {
                if required == 0 {
                    return Err(RuleSetError::InvalidXpThreshold { level });
                }
            }
        }

        Ok(())
    }

    pub fn tier_probability(&self, level: u8, cost: u8) -> Result<f64, RuleSetError> {
        let odds = self
            .shop_odds_by_level
            .get(&level)
            .copied()
            .ok_or(RuleSetError::MissingLevel(level))?;

        odds.probability_for_cost(cost)
    }

    pub fn unit_total_copies(&self, cost: u8) -> Result<u16, RuleSetError> {
        if !(1..=5).contains(&cost) {
            return Err(RuleSetError::InvalidCostTier { cost });
        }
        self.unit_pool_copies_by_cost
            .get(&cost)
            .copied()
            .ok_or(RuleSetError::MissingCost(cost))
    }

    pub fn xp_rules_available(&self) -> bool {
        self.xp_purchase_cost_gold > 0
            && self.xp_per_purchase > 0
            && !self.xp_required_to_next_level.is_empty()
    }

    pub fn gold_to_level(
        &self,
        current_level: u8,
        current_xp: u16,
        target_level: u8,
    ) -> Result<Option<u16>, RuleSetError> {
        if target_level <= current_level {
            return Err(RuleSetError::InvalidTargetLevel);
        }
        if !self.xp_rules_available() {
            return Ok(None);
        }

        let mut total_xp_needed: u32 = 0;
        for level in current_level..target_level {
            let required = self
                .xp_required_to_next_level
                .get(&level)
                .copied()
                .ok_or(RuleSetError::MissingXpThreshold(level))?;

            let needed = if level == current_level {
                required.saturating_sub(current_xp)
            } else {
                required
            };

            total_xp_needed = total_xp_needed.saturating_add(needed as u32);
        }

        if total_xp_needed == 0 {
            return Ok(Some(0));
        }

        let xp_per_purchase = self.xp_per_purchase as u32;
        let purchases = total_xp_needed
            .saturating_add(xp_per_purchase - 1)
            / xp_per_purchase;
        let gold = purchases
            .saturating_mul(self.xp_purchase_cost_gold as u32)
            .min(u16::MAX as u32) as u16;

        Ok(Some(gold))
    }

    pub fn shop_hit_input(
        &self,
        level: u8,
        cost: u8,
        tier_total_remaining: u16,
        target_remaining: u16,
    ) -> Result<ShopHitInput, RuleSetError> {
        Ok(ShopHitInput {
            target_tier_probability: self.tier_probability(level, cost)?,
            pool: TierPoolSnapshot {
                total_remaining: tier_total_remaining,
                target_remaining,
            },
            shop_slots: self.shop_slots,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> TftRuleSet {
        TftRuleSet {
            schema_version: RULESET_SCHEMA_VERSION,
            patch: "test-patch".into(),
            set: "test-set".into(),
            shop_slots: 5,
            roll_cost_gold: 2,
            economy: EconomyRules::default(),
            shop_odds_by_level: BTreeMap::from([
                (
                    7,
                    ShopOdds {
                        by_cost: [0.19, 0.30, 0.40, 0.10, 0.01],
                    },
                ),
            ]),
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

    #[test]
    fn fixture_is_valid() {
        fixture().validate().unwrap();
    }

    #[test]
    fn resolves_probability_by_level_and_cost() {
        let rules = fixture();
        assert!((rules.tier_probability(7, 3).unwrap() - 0.40).abs() < 1e-10);
    }

    #[test]
    fn creates_math_input_without_hardcoding_odds_in_math_engine() {
        let rules = fixture();
        let input = rules.shop_hit_input(7, 4, 80, 6).unwrap();

        assert_eq!(input.shop_slots, 5);
        assert!((input.target_tier_probability - 0.10).abs() < 1e-10);
        assert_eq!(input.pool.total_remaining, 80);
        assert_eq!(input.pool.target_remaining, 6);
    }

    #[test]
    fn calculates_gold_to_level_from_patch_rules() {
        let rules = fixture();

        assert_eq!(
            rules.gold_to_level(7, 20, 8).unwrap(),
            Some(16)
        );
        assert_eq!(
            rules.gold_to_level(7, 20, 9).unwrap(),
            Some(84)
        );
    }

    #[test]
    fn missing_xp_rules_return_none_instead_of_guessing() {
        let mut rules = fixture();
        rules.xp_purchase_cost_gold = 0;
        rules.xp_per_purchase = 0;
        rules.xp_required_to_next_level.clear();

        assert_eq!(
            rules.gold_to_level(7, 20, 8).unwrap(),
            None
        );
    }

    #[test]
    fn invalid_probability_sum_is_rejected() {
        let mut rules = fixture();
        rules.shop_odds_by_level.insert(
            8,
            ShopOdds {
                by_cost: [0.2, 0.2, 0.2, 0.2, 0.3],
            },
        );

        assert_eq!(
            rules.validate().unwrap_err(),
            RuleSetError::InvalidShopOdds { level: 8 }
        );
    }

    #[test]
    fn missing_level_is_explicit() {
        let rules = fixture();
        assert_eq!(
            rules.tier_probability(9, 4).unwrap_err(),
            RuleSetError::MissingLevel(9)
        );
    }
}
