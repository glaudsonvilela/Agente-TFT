use std::collections::BTreeMap;

use agente_tft_contracts::Action;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionClass {
    Buy,
    SkipBuy,
    Sell,
    Roll,
    Level,
    HoldEcon,
    EquipItem,
    ChooseAugment,
    Pivot,
    PartialPivot,
    Position,
    Scout,
    Wait,
}

impl From<&Action> for ActionClass {
    fn from(action: &Action) -> Self {
        match action {
            Action::Buy { .. } => Self::Buy,
            Action::SkipBuy { .. } => Self::SkipBuy,
            Action::Sell { .. } => Self::Sell,
            Action::Roll { .. } => Self::Roll,
            Action::Level { .. } => Self::Level,
            Action::HoldEcon => Self::HoldEcon,
            Action::EquipItem { .. } => Self::EquipItem,
            Action::ChooseAugment { .. } => Self::ChooseAugment,
            Action::Pivot { .. } => Self::Pivot,
            Action::PartialPivot { .. } => Self::PartialPivot,
            Action::Position { .. } => Self::Position,
            Action::Scout { .. } => Self::Scout,
            Action::Wait => Self::Wait,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct PatternContext {
    pub stage: Option<String>,
    pub level: Option<u8>,
    pub hp_bucket: Option<u16>,
    pub gold_bucket: Option<u16>,
    pub contested_copies_bucket: Option<u16>,
}

impl PatternContext {
    pub fn from_values(
        stage: Option<String>,
        level: Option<u8>,
        hp: Option<u16>,
        gold: Option<u16>,
        contested_copies: Option<u16>,
    ) -> Self {
        Self {
            stage,
            level,
            hp_bucket: hp.map(|value| bucket(value, 10)),
            gold_bucket: gold.map(|value| bucket(value, 10)),
            contested_copies_bucket: contested_copies.map(|value| bucket(value, 3)),
        }
    }
}

fn bucket(value: u16, size: u16) -> u16 {
    if size == 0 {
        return value;
    }
    (value / size) * size
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PatternSample {
    pub episode_id: String,
    pub state_revision: u64,
    pub context: PatternContext,
    pub recommended_action: Action,
    pub human_action: Option<Action>,
    pub shadow_action: Option<Action>,
    pub recommended_reward: Option<f32>,
    pub human_reward: Option<f32>,
    pub shadow_reward: Option<f32>,
    pub counterfactual_best_action: Option<Action>,
    pub counterfactual_best_reward: Option<f32>,
    pub placement: Option<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct PatternKey {
    pub context: PatternContext,
    pub recommended_action: ActionClass,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct PatternStats {
    pub samples: u64,
    pub human_action_observed: u64,
    pub human_agreed_with_recommendation: u64,
    pub shadow_action_observed: u64,
    pub shadow_agreed_with_recommendation: u64,
    pub reward_pairs_human_vs_recommended: u64,
    pub reward_pairs_shadow_vs_recommended: u64,
    pub reward_pairs_counterfactual_vs_recommended: u64,
    pub mean_human_minus_recommended_reward: Option<f32>,
    pub mean_shadow_minus_recommended_reward: Option<f32>,
    pub mean_counterfactual_minus_recommended_reward: Option<f32>,
    pub placement_samples: u64,
    pub mean_placement: Option<f32>,

    #[serde(skip)]
    human_reward_delta_sum: f64,
    #[serde(skip)]
    shadow_reward_delta_sum: f64,
    #[serde(skip)]
    counterfactual_reward_delta_sum: f64,
    #[serde(skip)]
    placement_sum: u64,
}

impl PatternStats {
    fn observe(&mut self, sample: &PatternSample) {
        self.samples = self.samples.saturating_add(1);

        if let Some(human) = &sample.human_action {
            self.human_action_observed = self.human_action_observed.saturating_add(1);
            if ActionClass::from(human) == ActionClass::from(&sample.recommended_action) {
                self.human_agreed_with_recommendation =
                    self.human_agreed_with_recommendation.saturating_add(1);
            }
        }

        if let Some(shadow) = &sample.shadow_action {
            self.shadow_action_observed = self.shadow_action_observed.saturating_add(1);
            if ActionClass::from(shadow) == ActionClass::from(&sample.recommended_action) {
                self.shadow_agreed_with_recommendation =
                    self.shadow_agreed_with_recommendation.saturating_add(1);
            }
        }

        if let (Some(recommended), Some(human)) =
            (sample.recommended_reward, sample.human_reward)
        {
            self.reward_pairs_human_vs_recommended =
                self.reward_pairs_human_vs_recommended.saturating_add(1);
            self.human_reward_delta_sum += (human - recommended) as f64;
            self.mean_human_minus_recommended_reward = Some(
                (self.human_reward_delta_sum
                    / self.reward_pairs_human_vs_recommended as f64) as f32,
            );
        }

        if let (Some(recommended), Some(shadow)) =
            (sample.recommended_reward, sample.shadow_reward)
        {
            self.reward_pairs_shadow_vs_recommended =
                self.reward_pairs_shadow_vs_recommended.saturating_add(1);
            self.shadow_reward_delta_sum += (shadow - recommended) as f64;
            self.mean_shadow_minus_recommended_reward = Some(
                (self.shadow_reward_delta_sum
                    / self.reward_pairs_shadow_vs_recommended as f64) as f32,
            );
        }

        if let (Some(recommended), Some(counterfactual)) = (
            sample.recommended_reward,
            sample.counterfactual_best_reward,
        ) {
            self.reward_pairs_counterfactual_vs_recommended =
                self.reward_pairs_counterfactual_vs_recommended.saturating_add(1);
            self.counterfactual_reward_delta_sum += (counterfactual - recommended) as f64;
            self.mean_counterfactual_minus_recommended_reward = Some(
                (self.counterfactual_reward_delta_sum
                    / self.reward_pairs_counterfactual_vs_recommended as f64) as f32,
            );
        }

        if let Some(placement) = sample.placement {
            self.placement_samples = self.placement_samples.saturating_add(1);
            self.placement_sum = self.placement_sum.saturating_add(placement as u64);
            self.mean_placement =
                Some(self.placement_sum as f32 / self.placement_samples as f32);
        }
    }

    pub fn human_agreement_rate(&self) -> Option<f32> {
        if self.human_action_observed == 0 {
            None
        } else {
            Some(
                self.human_agreed_with_recommendation as f32
                    / self.human_action_observed as f32,
            )
        }
    }

    pub fn shadow_agreement_rate(&self) -> Option<f32> {
        if self.shadow_action_observed == 0 {
            None
        } else {
            Some(
                self.shadow_agreed_with_recommendation as f32
                    / self.shadow_action_observed as f32,
            )
        }
    }
}

#[derive(Debug, Default)]
pub struct PatternEngine {
    stats: BTreeMap<PatternKey, PatternStats>,
}

impl PatternEngine {
    pub fn observe(&mut self, sample: PatternSample) -> PatternKey {
        let key = PatternKey {
            context: sample.context.clone(),
            recommended_action: ActionClass::from(&sample.recommended_action),
        };
        self.stats.entry(key.clone()).or_default().observe(&sample);
        key
    }

    pub fn stats(&self, key: &PatternKey) -> Option<&PatternStats> {
        self.stats.get(key)
    }

    pub fn all(&self) -> &BTreeMap<PatternKey, PatternStats> {
        &self.stats
    }

    pub fn ranked_by_samples(&self) -> Vec<(&PatternKey, &PatternStats)> {
        let mut values: Vec<_> = self.stats.iter().collect();
        values.sort_by(|(key_a, stats_a), (key_b, stats_b)| {
            stats_b
                .samples
                .cmp(&stats_a.samples)
                .then_with(|| key_a.cmp(key_b))
        });
        values
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(
        recommended: Action,
        human: Option<Action>,
        shadow: Option<Action>,
    ) -> PatternSample {
        PatternSample {
            episode_id: "e1".into(),
            state_revision: 7,
            context: PatternContext::from_values(
                Some("4-2".into()),
                Some(7),
                Some(31),
                Some(48),
                Some(4),
            ),
            recommended_action: recommended,
            human_action: human,
            shadow_action: shadow,
            recommended_reward: Some(0.20),
            human_reward: Some(0.10),
            shadow_reward: Some(0.30),
            counterfactual_best_action: Some(Action::Roll {
                budget_gold: 20,
                stop_condition: None,
            }),
            counterfactual_best_reward: Some(0.40),
            placement: Some(5),
        }
    }

    #[test]
    fn context_is_bucketed_deterministically() {
        let context = PatternContext::from_values(
            Some("4-2".into()),
            Some(7),
            Some(31),
            Some(48),
            Some(4),
        );
        assert_eq!(context.hp_bucket, Some(30));
        assert_eq!(context.gold_bucket, Some(40));
        assert_eq!(context.contested_copies_bucket, Some(3));
    }

    #[test]
    fn tracks_human_and_shadow_agreement() {
        let mut engine = PatternEngine::default();
        let key = engine.observe(sample(
            Action::Roll {
                budget_gold: 20,
                stop_condition: None,
            },
            Some(Action::HoldEcon),
            Some(Action::Roll {
                budget_gold: 10,
                stop_condition: None,
            }),
        ));

        let stats = engine.stats(&key).unwrap();
        assert_eq!(stats.samples, 1);
        assert_eq!(stats.human_agreement_rate(), Some(0.0));
        assert_eq!(stats.shadow_agreement_rate(), Some(1.0));
        assert_eq!(
            stats.mean_human_minus_recommended_reward,
            Some(-0.10)
        );
        assert_eq!(
            stats.mean_shadow_minus_recommended_reward,
            Some(0.10)
        );
        assert_eq!(
            stats.mean_counterfactual_minus_recommended_reward,
            Some(0.20)
        );
    }

    #[test]
    fn same_context_accumulates_samples() {
        let mut engine = PatternEngine::default();
        let action = Action::HoldEcon;

        let key = engine.observe(sample(
            action.clone(),
            Some(action.clone()),
            Some(action.clone()),
        ));
        engine.observe(sample(
            action.clone(),
            Some(action.clone()),
            Some(action),
        ));

        assert_eq!(engine.stats(&key).unwrap().samples, 2);
        assert_eq!(engine.stats(&key).unwrap().human_agreement_rate(), Some(1.0));
    }
}
