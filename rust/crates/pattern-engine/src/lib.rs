use std::collections::BTreeMap;

use agente_tft_contracts::Action;
use agente_tft_opportunity_engine::OpportunityCandidate;
use agente_tft_opportunity_runtime::CompleteOpportunityCycle;
use agente_tft_remote_training_protocol::{
    TrainingJobResult,
    TrainingJobStatus,
};
use agente_tft_shadow_player::ShadowTransition;
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


#[derive(
    Debug,
    Clone,
    Copy,
    PartialEq,
    Eq,
    PartialOrd,
    Ord,
    Serialize,
    Deserialize,
)]
#[serde(rename_all = "snake_case")]
pub enum OpportunitySignal {
    Utility,
    Confidence,
    ImmediateBoardGain,
    UpgradeValue,
    HpPreservation,
    EconomyValue,
    ContestUrgency,
    Flexibility,
    InformationValue,
    ExternalMetaPrior,
    Uncertainty,
}

#[derive(
    Debug,
    Clone,
    PartialEq,
    Eq,
    PartialOrd,
    Ord,
    Serialize,
    Deserialize,
)]
pub struct SignalKey {
    pub action: ActionClass,
    pub signal: OpportunitySignal,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct SignalCorrelationStats {
    pub samples: u64,
    sum_signal: f64,
    sum_reward: f64,
    sum_signal_sq: f64,
    sum_reward_sq: f64,
    sum_cross: f64,
}

impl SignalCorrelationStats {
    pub fn observe(&mut self, signal: f32, reward: f32) -> bool {
        if !signal.is_finite() || !reward.is_finite() {
            return false;
        }

        let x = signal as f64;
        let y = reward as f64;

        self.samples = self.samples.saturating_add(1);
        self.sum_signal += x;
        self.sum_reward += y;
        self.sum_signal_sq += x * x;
        self.sum_reward_sq += y * y;
        self.sum_cross += x * y;
        true
    }

    pub fn mean_signal(&self) -> Option<f32> {
        if self.samples == 0 {
            None
        } else {
            Some((self.sum_signal / self.samples as f64) as f32)
        }
    }

    pub fn mean_reward(&self) -> Option<f32> {
        if self.samples == 0 {
            None
        } else {
            Some((self.sum_reward / self.samples as f64) as f32)
        }
    }

    pub fn correlation(&self) -> Option<f32> {
        if self.samples < 2 {
            return None;
        }

        let n = self.samples as f64;
        let numerator =
            n * self.sum_cross - self.sum_signal * self.sum_reward;
        let signal_term =
            n * self.sum_signal_sq - self.sum_signal * self.sum_signal;
        let reward_term =
            n * self.sum_reward_sq - self.sum_reward * self.sum_reward;

        if signal_term <= f64::EPSILON || reward_term <= f64::EPSILON {
            return None;
        }

        let denominator = (signal_term * reward_term).sqrt();
        let value = (numerator / denominator).clamp(-1.0, 1.0);
        Some(value as f32)
    }
}



#[derive(
    Debug,
    Clone,
    Copy,
    PartialEq,
    Eq,
    PartialOrd,
    Ord,
    Serialize,
    Deserialize,
)]
#[serde(rename_all = "snake_case")]
pub enum EvaluatorDiagnosticMetric {
    ItemStructuralGain,
    ItemBeforeScore,
    ItemAfterScore,
    PivotBoardDelta,
    PivotTransitionCost,
    PivotReplacementRatio,
    PivotMissingRatio,
    PositionExposureBefore,
    PositionExposureAfter,
    PositionExposureGain,
    PositionObservedCoverage,
    SellBenchOccupancy,
}

#[derive(
    Debug,
    Clone,
    PartialEq,
    Eq,
    PartialOrd,
    Ord,
    Serialize,
    Deserialize,
)]
pub struct DiagnosticSignalKey {
    pub action: ActionClass,
    pub metric: EvaluatorDiagnosticMetric,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DiagnosticFeedbackIngest {
    pub action_supported: bool,
    pub metrics_seen: u32,
    pub metrics_accepted: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct EvaluatorFeedbackEngine {
    stats: BTreeMap<SignalKey, SignalCorrelationStats>,
    #[serde(default)]
    diagnostic_stats: BTreeMap<DiagnosticSignalKey, SignalCorrelationStats>,
}

impl EvaluatorFeedbackEngine {
    pub fn observe_candidate(
        &mut self,
        candidate: &OpportunityCandidate,
        realized_reward: f32,
    ) -> bool {
        if !realized_reward.is_finite() {
            return false;
        }

        let action = ActionClass::from(&candidate.action);
        let signals = [
            (OpportunitySignal::Utility, candidate.utility),
            (
                OpportunitySignal::Confidence,
                candidate.confidence.value(),
            ),
            (
                OpportunitySignal::ImmediateBoardGain,
                candidate.vector.immediate_board_gain,
            ),
            (
                OpportunitySignal::UpgradeValue,
                candidate.vector.upgrade_value,
            ),
            (
                OpportunitySignal::HpPreservation,
                candidate.vector.hp_preservation,
            ),
            (
                OpportunitySignal::EconomyValue,
                candidate.vector.economy_value,
            ),
            (
                OpportunitySignal::ContestUrgency,
                candidate.vector.contest_urgency,
            ),
            (
                OpportunitySignal::Flexibility,
                candidate.vector.flexibility,
            ),
            (
                OpportunitySignal::InformationValue,
                candidate.vector.information_value,
            ),
            (
                OpportunitySignal::ExternalMetaPrior,
                candidate.vector.external_meta_prior,
            ),
            (
                OpportunitySignal::Uncertainty,
                candidate.vector.uncertainty,
            ),
        ];

        for (signal, value) in signals {
            self.stats
                .entry(SignalKey {
                    action,
                    signal,
                })
                .or_default()
                .observe(value, realized_reward);
        }

        true
    }

    pub fn stats(
        &self,
        action: ActionClass,
        signal: OpportunitySignal,
    ) -> Option<&SignalCorrelationStats> {
        self.stats.get(&SignalKey { action, signal })
    }

    pub fn ranked_correlations(
        &self,
        action: ActionClass,
        min_samples: u64,
    ) -> Vec<(OpportunitySignal, &SignalCorrelationStats)> {
        let mut values: Vec<_> = self
            .stats
            .iter()
            .filter(|(key, stats)| {
                key.action == action
                    && stats.samples >= min_samples
                    && stats.correlation().is_some()
            })
            .map(|(key, stats)| (key.signal, stats))
            .collect();

        values.sort_by(|(signal_a, stats_a), (signal_b, stats_b)| {
            let a = stats_a
                .correlation()
                .unwrap_or(0.0)
                .abs();
            let b = stats_b
                .correlation()
                .unwrap_or(0.0)
                .abs();

            b.total_cmp(&a)
                .then_with(|| signal_a.cmp(signal_b))
        });

        values
    }

    pub fn all(
        &self,
    ) -> &BTreeMap<SignalKey, SignalCorrelationStats> {
        &self.stats
    }
}




impl EvaluatorFeedbackEngine {
    pub fn observe_complete_cycle_action(
        &mut self,
        cycle: &CompleteOpportunityCycle,
        action: &Action,
        realized_reward: f32,
    ) -> DiagnosticFeedbackIngest {
        let mut summary = DiagnosticFeedbackIngest::default();

        if !realized_reward.is_finite() {
            return summary;
        }

        let action_class = ActionClass::from(action);

        let mut observe = |metric: EvaluatorDiagnosticMetric, value: f32| {
            summary.metrics_seen = summary.metrics_seen.saturating_add(1);
            if !value.is_finite() {
                return;
            }

            if self
                .diagnostic_stats
                .entry(DiagnosticSignalKey {
                    action: action_class,
                    metric,
                })
                .or_default()
                .observe(value, realized_reward)
            {
                summary.metrics_accepted =
                    summary.metrics_accepted.saturating_add(1);
            }
        };

        match action {
            Action::EquipItem {
                item_id,
                unit_instance_id,
            } => {
                if let Some(value) = cycle.item_evaluations.iter().find(
                    |evaluation| {
                        evaluation.fact.item_id == *item_id
                            && evaluation.fact.unit_instance_id
                                == *unit_instance_id
                    },
                ) {
                    summary.action_supported = true;
                    observe(
                        EvaluatorDiagnosticMetric::ItemStructuralGain,
                        value.structural_gain,
                    );
                    observe(
                        EvaluatorDiagnosticMetric::ItemBeforeScore,
                        value.before_score,
                    );
                    observe(
                        EvaluatorDiagnosticMetric::ItemAfterScore,
                        value.after_score,
                    );
                }
            }
            Action::Pivot { target } => {
                if let Some(value) = cycle.pivot_evaluations.iter().find(
                    |evaluation| evaluation.fact.target == *target,
                ) {
                    summary.action_supported = true;

                    let board_delta =
                        value.transition_board_score - value.current_board_score;
                    let replacement_ratio = if value.board_capacity == 0 {
                        0.0
                    } else {
                        value.replacement_count as f32
                            / value.board_capacity as f32
                    };
                    let total_target_units =
                        value.target_owned_unit_ids.len()
                            + value.missing_unit_ids.len();
                    let missing_ratio = if total_target_units == 0 {
                        0.0
                    } else {
                        value.missing_unit_ids.len() as f32
                            / total_target_units as f32
                    };

                    observe(
                        EvaluatorDiagnosticMetric::PivotBoardDelta,
                        board_delta,
                    );
                    observe(
                        EvaluatorDiagnosticMetric::PivotTransitionCost,
                        value.fact.transition_cost,
                    );
                    observe(
                        EvaluatorDiagnosticMetric::PivotReplacementRatio,
                        replacement_ratio,
                    );
                    observe(
                        EvaluatorDiagnosticMetric::PivotMissingRatio,
                        missing_ratio,
                    );
                }
            }
            Action::Position { moves } => {
                if let Some(diagnostic) =
                    cycle.matchup_positioning.as_ref()
                {
                    let ids: std::collections::BTreeSet<&str> = moves
                        .iter()
                        .map(|movement| movement.unit_instance_id.as_str())
                        .collect();

                    let selected: Vec<_> = diagnostic
                        .measurements
                        .iter()
                        .filter(|measurement| {
                            ids.contains(measurement.unit_instance_id.as_str())
                        })
                        .collect();

                    if !selected.is_empty() {
                        summary.action_supported = true;

                        let count = selected.len() as f32;
                        let before = selected
                            .iter()
                            .map(|value| value.before)
                            .sum::<f32>()
                            / count;
                        let after = selected
                            .iter()
                            .map(|value| value.after)
                            .sum::<f32>()
                            / count;
                        let gain = selected
                            .iter()
                            .map(|value| value.normalized_gain)
                            .sum::<f32>()
                            / count;
                        let coverage =
                            if diagnostic.observed_opponent_units == 0 {
                                0.0
                            } else {
                                diagnostic.usable_opponent_units as f32
                                    / diagnostic.observed_opponent_units as f32
                            };

                        observe(
                            EvaluatorDiagnosticMetric::PositionExposureBefore,
                            before,
                        );
                        observe(
                            EvaluatorDiagnosticMetric::PositionExposureAfter,
                            after,
                        );
                        observe(
                            EvaluatorDiagnosticMetric::PositionExposureGain,
                            gain,
                        );
                        observe(
                            EvaluatorDiagnosticMetric::PositionObservedCoverage,
                            coverage,
                        );
                    }
                }
            }
            Action::Sell { .. } => {
                if let Some(diagnostic) = cycle.sell_diagnostic.as_ref() {
                    summary.action_supported = true;
                    observe(
                        EvaluatorDiagnosticMetric::SellBenchOccupancy,
                        diagnostic.bench_occupancy_ratio,
                    );
                }
            }
            _ => {}
        }

        summary
    }

    pub fn diagnostic_stats(
        &self,
        action: ActionClass,
        metric: EvaluatorDiagnosticMetric,
    ) -> Option<&SignalCorrelationStats> {
        self.diagnostic_stats.get(
            &DiagnosticSignalKey { action, metric },
        )
    }

    pub fn ranked_diagnostic_correlations(
        &self,
        action: ActionClass,
        min_samples: u64,
    ) -> Vec<(EvaluatorDiagnosticMetric, &SignalCorrelationStats)> {
        let mut values: Vec<_> = self
            .diagnostic_stats
            .iter()
            .filter(|(key, stats)| {
                key.action == action
                    && stats.samples >= min_samples
                    && stats.correlation().is_some()
            })
            .map(|(key, stats)| (key.metric, stats))
            .collect();

        values.sort_by(|(metric_a, stats_a), (metric_b, stats_b)| {
            let a = stats_a.correlation().unwrap_or(0.0).abs();
            let b = stats_b.correlation().unwrap_or(0.0).abs();

            b.total_cmp(&a)
                .then_with(|| metric_a.cmp(metric_b))
        });

        values
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ShadowFeedbackIngest {
    pub accepted: bool,
    pub skipped_missing_reward: bool,
    pub skipped_non_finite_reward: bool,
    pub skipped_action_not_in_shortlist: bool,
}

impl EvaluatorFeedbackEngine {
    pub fn observe_shadow_transition(
        &mut self,
        shortlist: &[OpportunityCandidate],
        transition: &ShadowTransition,
    ) -> ShadowFeedbackIngest {
        let mut summary = ShadowFeedbackIngest::default();

        let Some(reward) = transition.reward else {
            summary.skipped_missing_reward = true;
            return summary;
        };

        if !reward.is_finite() {
            summary.skipped_non_finite_reward = true;
            return summary;
        }

        let Some(candidate) = shortlist
            .iter()
            .find(|candidate| candidate.action == transition.action)
        else {
            summary.skipped_action_not_in_shortlist = true;
            return summary;
        };

        summary.accepted = self.observe_candidate(
            candidate,
            reward,
        );
        summary
    }
}



#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct CompleteShadowFeedbackIngest {
    pub base: ShadowFeedbackIngest,
    pub diagnostics: DiagnosticFeedbackIngest,
}

impl EvaluatorFeedbackEngine {
    pub fn observe_complete_shadow_transition(
        &mut self,
        cycle: &CompleteOpportunityCycle,
        transition: &ShadowTransition,
    ) -> CompleteShadowFeedbackIngest {
        let base = self.observe_shadow_transition(
            &cycle.cycle.report.shortlist,
            transition,
        );

        let diagnostics = match (base.accepted, transition.reward) {
            (true, Some(reward)) if reward.is_finite() => {
                self.observe_complete_cycle_action(
                    cycle,
                    &transition.action,
                    reward,
                )
            }
            _ => DiagnosticFeedbackIngest::default(),
        };

        CompleteShadowFeedbackIngest {
            base,
            diagnostics,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SwarmFeedbackIngest {
    pub outcomes_seen: u32,
    pub outcomes_accepted: u32,
    pub skipped_invalid_index: u32,
    pub skipped_non_finite_reward: u32,
    pub skipped_zero_samples: u32,
    pub skipped_non_completed_job: bool,
}

impl EvaluatorFeedbackEngine {
    pub fn observe_swarm_result(
        &mut self,
        shortlist: &[OpportunityCandidate],
        result: &TrainingJobResult,
    ) -> SwarmFeedbackIngest {
        let mut summary = SwarmFeedbackIngest::default();

        if result.status != TrainingJobStatus::Completed {
            summary.skipped_non_completed_job = true;
            return summary;
        }

        for outcome in &result.outcomes {
            summary.outcomes_seen =
                summary.outcomes_seen.saturating_add(1);

            if outcome.samples == 0 {
                summary.skipped_zero_samples =
                    summary.skipped_zero_samples.saturating_add(1);
                continue;
            }

            if !outcome.reward_mean.is_finite() {
                summary.skipped_non_finite_reward =
                    summary.skipped_non_finite_reward.saturating_add(1);
                continue;
            }

            let Some(candidate) =
                shortlist.get(outcome.action_index as usize)
            else {
                summary.skipped_invalid_index =
                    summary.skipped_invalid_index.saturating_add(1);
                continue;
            };

            if self.observe_candidate(
                candidate,
                outcome.reward_mean,
            ) {
                summary.outcomes_accepted =
                    summary.outcomes_accepted.saturating_add(1);
            }
        }

        summary
    }
}



#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct CompleteSwarmFeedbackIngest {
    pub base: SwarmFeedbackIngest,
    pub diagnostic_actions_seen: u32,
    pub diagnostic_actions_supported: u32,
    pub diagnostic_metrics_accepted: u32,
}

impl EvaluatorFeedbackEngine {
    pub fn observe_complete_swarm_result(
        &mut self,
        cycle: &CompleteOpportunityCycle,
        result: &TrainingJobResult,
    ) -> CompleteSwarmFeedbackIngest {
        let base = self.observe_swarm_result(
            &cycle.cycle.report.shortlist,
            result,
        );

        let mut summary = CompleteSwarmFeedbackIngest {
            base,
            ..CompleteSwarmFeedbackIngest::default()
        };

        if result.status != TrainingJobStatus::Completed {
            return summary;
        }

        for outcome in &result.outcomes {
            if outcome.samples == 0
                || !outcome.reward_mean.is_finite()
            {
                continue;
            }

            let Some(candidate) = cycle
                .cycle
                .report
                .shortlist
                .get(outcome.action_index as usize)
            else {
                continue;
            };

            summary.diagnostic_actions_seen =
                summary.diagnostic_actions_seen.saturating_add(1);

            let diagnostics = self.observe_complete_cycle_action(
                cycle,
                &candidate.action,
                outcome.reward_mean,
            );

            if diagnostics.action_supported {
                summary.diagnostic_actions_supported =
                    summary.diagnostic_actions_supported.saturating_add(1);
            }
            summary.diagnostic_metrics_accepted =
                summary.diagnostic_metrics_accepted
                    .saturating_add(diagnostics.metrics_accepted);
        }

        summary
    }
}



#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "source", content = "feature", rename_all = "snake_case")]
pub enum CalibrationFeature {
    Opportunity(OpportunitySignal),
    Diagnostic(EvaluatorDiagnosticMetric),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CalibrationEntry {
    pub action: ActionClass,
    pub feature: CalibrationFeature,
    pub samples: u64,
    pub mean_signal: Option<f32>,
    pub mean_reward: Option<f32>,
    pub correlation: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CalibrationReport {
    pub min_samples: u64,
    pub min_abs_correlation: f32,
    pub entries: Vec<CalibrationEntry>,
    pub ready_for_weight_review: bool,
}

impl EvaluatorFeedbackEngine {
    pub fn calibration_report(
        &self,
        min_samples: u64,
        min_abs_correlation: f32,
    ) -> CalibrationReport {
        let threshold = if min_abs_correlation.is_finite() {
            min_abs_correlation.abs().clamp(0.0, 1.0)
        } else {
            1.0
        };
        let required_samples = min_samples.max(2);

        let mut entries = Vec::new();

        for (key, stats) in &self.stats {
            if stats.samples < required_samples {
                continue;
            }
            let Some(correlation) = stats.correlation() else {
                continue;
            };
            if correlation.abs() < threshold {
                continue;
            }

            entries.push(CalibrationEntry {
                action: key.action,
                feature: CalibrationFeature::Opportunity(key.signal),
                samples: stats.samples,
                mean_signal: stats.mean_signal(),
                mean_reward: stats.mean_reward(),
                correlation,
            });
        }

        for (key, stats) in &self.diagnostic_stats {
            if stats.samples < required_samples {
                continue;
            }
            let Some(correlation) = stats.correlation() else {
                continue;
            };
            if correlation.abs() < threshold {
                continue;
            }

            entries.push(CalibrationEntry {
                action: key.action,
                feature: CalibrationFeature::Diagnostic(key.metric),
                samples: stats.samples,
                mean_signal: stats.mean_signal(),
                mean_reward: stats.mean_reward(),
                correlation,
            });
        }

        entries.sort_by(|a, b| {
            b.correlation
                .abs()
                .total_cmp(&a.correlation.abs())
                .then_with(|| b.samples.cmp(&a.samples))
                .then_with(|| a.action.cmp(&b.action))
                .then_with(|| calibration_feature_key(&a.feature)
                    .cmp(&calibration_feature_key(&b.feature)))
        });

        CalibrationReport {
            min_samples: required_samples,
            min_abs_correlation: threshold,
            ready_for_weight_review: !entries.is_empty(),
            entries,
        }
    }
}

fn calibration_feature_key(
    feature: &CalibrationFeature,
) -> String {
    match feature {
        CalibrationFeature::Opportunity(signal) => {
            format!("opportunity:{signal:?}")
        }
        CalibrationFeature::Diagnostic(metric) => {
            format!("diagnostic:{metric:?}")
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

    fn opportunity_candidate(
        upgrade_value: f32,
        economy_value: f32,
        reward_proxy: f32,
    ) -> OpportunityCandidate {
        use agente_tft_contracts::{Confidence, Evidence};
        use agente_tft_opportunity_engine::{
            OpportunityTier, OpportunityVector,
        };

        OpportunityCandidate {
            action: Action::Roll {
                budget_gold: 20,
                stop_condition: None,
            },
            tier: OpportunityTier::Tactical,
            utility: reward_proxy,
            confidence: Confidence::new(0.90).unwrap(),
            vector: OpportunityVector {
                upgrade_value,
                economy_value,
                ..OpportunityVector::default()
            },
            evidence: vec![Evidence {
                code: "fixture".into(),
                detail: "fixture".into(),
            }],
        }
    }

    #[test]
    fn diagnostic_feedback_tracks_item_structural_gain() {
        use agente_tft_contracts::{
            Confidence, DecisionPacket,
        };
        use agente_tft_item_strength::ItemStrengthEvaluation;
        use agente_tft_opportunity_engine::{
            ItemOpportunityFact, OpportunityDelta, OpportunityReport,
        };
        use agente_tft_opportunity_fact_builder::OpportunityFactBuild;
        use agente_tft_opportunity_runtime::{
            CompleteOpportunityCycle, OpportunityCycle,
        };

        let action = Action::EquipItem {
            item_id: "ITEM_1".into(),
            unit_instance_id: "A-1".into(),
        };

        let item_fact = ItemOpportunityFact {
            item_id: "ITEM_1".into(),
            unit_instance_id: "A-1".into(),
            strength_gain: 0.25,
            flexibility_cost: 0.0,
            external_meta_prior: 0.0,
            confidence: Confidence::new(0.35).unwrap(),
        };

        let complete = CompleteOpportunityCycle {
            fact_build: OpportunityFactBuild {
                facts: Default::default(),
                diagnostics: Default::default(),
            },
            cycle: OpportunityCycle {
                report: OpportunityReport {
                    state_revision: 7,
                    evaluated_at_ms: 100,
                    all: vec![],
                    shortlist: vec![],
                },
                delta: OpportunityDelta {
                    previous_revision: None,
                    current_revision: 7,
                    added: vec![action.clone()],
                    removed: vec![],
                    top_changed: true,
                    previous_top: None,
                    current_top: Some(action.clone()),
                    material_utility_shifts: vec![],
                },
                decision: DecisionPacket::new(
                    7,
                    action.clone(),
                    Confidence::new(0.90).unwrap(),
                    vec![],
                    vec![],
                ),
                remote_shortlist: vec![],
                should_refresh_ui: true,
                should_remote_evaluate: true,
            },
            item_evaluations: vec![ItemStrengthEvaluation {
                fact: item_fact,
                before_score: 0.40,
                after_score: 0.65,
                structural_gain: 0.25,
                target_on_board: true,
                item_available: true,
                target_had_free_slot: true,
            }],
            pivot_evaluations: vec![],
            sell_diagnostic: None,
            matchup_opponent_id: None,
            matchup_opponent_found: false,
            matchup_positioning: None,
        };

        let mut engine = EvaluatorFeedbackEngine::default();
        let rows = [
            (0.10_f32, 0.10_f32),
            (0.30, 0.30),
            (0.60, 0.60),
        ];

        for (gain, reward) in rows {
            let mut sample = complete.clone();
            sample.item_evaluations[0].structural_gain = gain;
            sample.item_evaluations[0].fact.strength_gain = gain;
            sample.item_evaluations[0].after_score =
                sample.item_evaluations[0].before_score + gain;

            let summary = engine.observe_complete_cycle_action(
                &sample,
                &action,
                reward,
            );
            assert!(summary.action_supported);
            assert_eq!(summary.metrics_accepted, 3);
        }

        let corr = engine
            .diagnostic_stats(
                ActionClass::EquipItem,
                EvaluatorDiagnosticMetric::ItemStructuralGain,
            )
            .unwrap()
            .correlation()
            .unwrap();

        assert!(corr > 0.99);
    }

    #[test]
    fn complete_shadow_feedback_updates_diagnostics() {
        use agente_tft_contracts::{
            Confidence, DecisionPacket,
        };
        use agente_tft_item_strength::ItemStrengthEvaluation;
        use agente_tft_opportunity_engine::{
            ItemOpportunityFact, OpportunityDelta, OpportunityReport,
            OpportunityTier, OpportunityVector,
        };
        use agente_tft_opportunity_fact_builder::OpportunityFactBuild;
        use agente_tft_opportunity_runtime::{
            CompleteOpportunityCycle, OpportunityCycle,
        };

        let action = Action::EquipItem {
            item_id: "ITEM_1".into(),
            unit_instance_id: "A-1".into(),
        };

        let candidate = OpportunityCandidate {
            action: action.clone(),
            tier: OpportunityTier::Micro,
            utility: 0.50,
            confidence: Confidence::new(0.90).unwrap(),
            vector: OpportunityVector {
                immediate_board_gain: 0.25,
                ..OpportunityVector::default()
            },
            evidence: vec![],
        };

        let complete = CompleteOpportunityCycle {
            fact_build: OpportunityFactBuild {
                facts: Default::default(),
                diagnostics: Default::default(),
            },
            cycle: OpportunityCycle {
                report: OpportunityReport {
                    state_revision: 7,
                    evaluated_at_ms: 100,
                    all: vec![candidate.clone()],
                    shortlist: vec![candidate],
                },
                delta: OpportunityDelta {
                    previous_revision: None,
                    current_revision: 7,
                    added: vec![action.clone()],
                    removed: vec![],
                    top_changed: true,
                    previous_top: None,
                    current_top: Some(action.clone()),
                    material_utility_shifts: vec![],
                },
                decision: DecisionPacket::new(
                    7,
                    action.clone(),
                    Confidence::new(0.90).unwrap(),
                    vec![],
                    vec![],
                ),
                remote_shortlist: vec![],
                should_refresh_ui: true,
                should_remote_evaluate: true,
            },
            item_evaluations: vec![ItemStrengthEvaluation {
                fact: ItemOpportunityFact {
                    item_id: "ITEM_1".into(),
                    unit_instance_id: "A-1".into(),
                    strength_gain: 0.25,
                    flexibility_cost: 0.0,
                    external_meta_prior: 0.0,
                    confidence: Confidence::new(0.35).unwrap(),
                },
                before_score: 0.40,
                after_score: 0.65,
                structural_gain: 0.25,
                target_on_board: true,
                item_available: true,
                target_had_free_slot: true,
            }],
            pivot_evaluations: vec![],
            sell_diagnostic: None,
            matchup_opponent_id: None,
            matchup_opponent_found: false,
            matchup_positioning: None,
        };

        let transition = ShadowTransition {
            before_revision: 7,
            action,
            simulated_state: agente_tft_contracts::GameState::empty(200),
            reward: Some(0.80),
            metrics: serde_json::json!({}),
        };

        let mut engine = EvaluatorFeedbackEngine::default();
        let summary = engine.observe_complete_shadow_transition(
            &complete,
            &transition,
        );

        assert!(summary.base.accepted);
        assert!(summary.diagnostics.action_supported);
        assert_eq!(summary.diagnostics.metrics_accepted, 3);

        assert_eq!(
            engine
                .diagnostic_stats(
                    ActionClass::EquipItem,
                    EvaluatorDiagnosticMetric::ItemStructuralGain,
                )
                .unwrap()
                .samples,
            1
        );
    }

    #[test]
    fn calibration_report_requires_samples_and_orders_by_signal() {
        let mut engine = EvaluatorFeedbackEngine::default();

        let rows = [
            (0.10, 0.90, 0.10),
            (0.40, 0.60, 0.40),
            (0.70, 0.30, 0.70),
            (1.00, 0.00, 1.00),
        ];

        for (upgrade, economy, reward) in rows {
            let candidate =
                opportunity_candidate(upgrade, economy, reward);
            engine.observe_candidate(&candidate, reward);
        }

        let report = engine.calibration_report(4, 0.80);

        assert!(report.ready_for_weight_review);
        assert!(!report.entries.is_empty());
        assert!(report.entries.iter().all(|entry| {
            entry.samples >= 4
                && entry.correlation.abs() >= 0.80
        }));

        for window in report.entries.windows(2) {
            assert!(
                window[0].correlation.abs()
                    >= window[1].correlation.abs()
            );
        }

        let strict = engine.calibration_report(10, 0.80);
        assert!(!strict.ready_for_weight_review);
        assert!(strict.entries.is_empty());
    }

    #[test]
    fn evaluator_feedback_measures_signal_reward_correlation() {
        let mut engine = EvaluatorFeedbackEngine::default();

        let rows = [
            (0.10, 0.90, 0.10),
            (0.40, 0.60, 0.40),
            (0.70, 0.30, 0.70),
            (1.00, 0.00, 1.00),
        ];

        for (upgrade, economy, reward) in rows {
            let candidate =
                opportunity_candidate(upgrade, economy, reward);
            assert!(engine.observe_candidate(
                &candidate,
                reward,
            ));
        }

        let upgrade = engine
            .stats(
                ActionClass::Roll,
                OpportunitySignal::UpgradeValue,
            )
            .unwrap()
            .correlation()
            .unwrap();

        let economy = engine
            .stats(
                ActionClass::Roll,
                OpportunitySignal::EconomyValue,
            )
            .unwrap()
            .correlation()
            .unwrap();

        assert!(upgrade > 0.99);
        assert!(economy < -0.99);
    }

    #[test]
    fn evaluator_feedback_keeps_action_classes_separate() {
        let mut engine = EvaluatorFeedbackEngine::default();

        let roll = opportunity_candidate(0.8, 0.2, 0.8);
        engine.observe_candidate(&roll, 0.8);

        let mut hold = opportunity_candidate(0.0, 0.9, 0.4);
        hold.action = Action::HoldEcon;
        engine.observe_candidate(&hold, 0.4);

        assert_eq!(
            engine
                .stats(
                    ActionClass::Roll,
                    OpportunitySignal::UpgradeValue,
                )
                .unwrap()
                .samples,
            1
        );
        assert_eq!(
            engine
                .stats(
                    ActionClass::HoldEcon,
                    OpportunitySignal::UpgradeValue,
                )
                .unwrap()
                .samples,
            1
        );
    }

    #[test]
    fn non_finite_feedback_is_rejected() {
        let mut engine = EvaluatorFeedbackEngine::default();
        let candidate = opportunity_candidate(0.8, 0.2, 0.8);

        assert!(!engine.observe_candidate(
            &candidate,
            f32::NAN,
        ));
        assert!(engine.all().is_empty());
    }

    #[test]
    fn shadow_transition_updates_feedback_for_matching_candidate() {
        let candidate = opportunity_candidate(
            0.75,
            0.25,
            0.75,
        );

        let transition = ShadowTransition {
            before_revision: 7,
            action: candidate.action.clone(),
            simulated_state: agente_tft_contracts::GameState::empty(100),
            reward: Some(0.80),
            metrics: serde_json::json!({}),
        };

        let mut engine = EvaluatorFeedbackEngine::default();
        let ingest = engine.observe_shadow_transition(
            &[candidate],
            &transition,
        );

        assert!(ingest.accepted);
        assert!(!ingest.skipped_missing_reward);

        assert_eq!(
            engine
                .stats(
                    ActionClass::Roll,
                    OpportunitySignal::UpgradeValue,
                )
                .unwrap()
                .samples,
            1
        );
    }

    #[test]
    fn shadow_transition_without_reward_is_rejected() {
        let candidate = opportunity_candidate(
            0.75,
            0.25,
            0.75,
        );

        let transition = ShadowTransition {
            before_revision: 7,
            action: candidate.action.clone(),
            simulated_state: agente_tft_contracts::GameState::empty(100),
            reward: None,
            metrics: serde_json::json!({}),
        };

        let mut engine = EvaluatorFeedbackEngine::default();
        let ingest = engine.observe_shadow_transition(
            &[candidate],
            &transition,
        );

        assert!(!ingest.accepted);
        assert!(ingest.skipped_missing_reward);
        assert!(engine.all().is_empty());
    }

    #[test]
    fn swarm_result_updates_feedback_from_action_indices() {
        use agente_tft_remote_training_protocol::{
            ActionOutcome,
            TrainingJobResult,
            TrainingJobStatus,
            REMOTE_TRAINING_PROTOCOL_VERSION,
        };

        let shortlist = vec![
            opportunity_candidate(0.20, 0.80, 0.20),
            opportunity_candidate(0.80, 0.20, 0.80),
        ];

        let result = TrainingJobResult {
            protocol_version: REMOTE_TRAINING_PROTOCOL_VERSION,
            session_id: "s1".into(),
            job_id: "j1".into(),
            episode_id: "e1".into(),
            status: TrainingJobStatus::Completed,
            completed_at_ms: 1000,
            simulator_version: "fixture".into(),
            policy_version: "fixture".into(),
            outcomes: vec![
                ActionOutcome {
                    action_index: 0,
                    placement_mean: None,
                    placement_p25: None,
                    placement_p75: None,
                    top4_rate: None,
                    first_rate: None,
                    hp_mean_after_horizon: None,
                    gold_mean_after_horizon: None,
                    reward_mean: 0.20,
                    reward_stddev: 0.01,
                    samples: 128,
                },
                ActionOutcome {
                    action_index: 1,
                    placement_mean: None,
                    placement_p25: None,
                    placement_p75: None,
                    top4_rate: None,
                    first_rate: None,
                    hp_mean_after_horizon: None,
                    gold_mean_after_horizon: None,
                    reward_mean: 0.80,
                    reward_stddev: 0.01,
                    samples: 128,
                },
            ],
            metrics: serde_json::json!({}),
            error: None,
        };

        let mut engine = EvaluatorFeedbackEngine::default();
        let ingest = engine.observe_swarm_result(
            &shortlist,
            &result,
        );

        assert_eq!(ingest.outcomes_seen, 2);
        assert_eq!(ingest.outcomes_accepted, 2);
        assert_eq!(ingest.skipped_invalid_index, 0);

        let correlation = engine
            .stats(
                ActionClass::Roll,
                OpportunitySignal::UpgradeValue,
            )
            .unwrap()
            .correlation()
            .unwrap();

        assert!(correlation > 0.99);
    }

    #[test]
    fn swarm_feedback_rejects_bad_indices_and_non_completed_jobs() {
        use agente_tft_remote_training_protocol::{
            ActionOutcome,
            TrainingJobResult,
            TrainingJobStatus,
            REMOTE_TRAINING_PROTOCOL_VERSION,
        };

        let shortlist = vec![
            opportunity_candidate(0.50, 0.50, 0.50),
        ];

        let mut result = TrainingJobResult {
            protocol_version: REMOTE_TRAINING_PROTOCOL_VERSION,
            session_id: "s1".into(),
            job_id: "j1".into(),
            episode_id: "e1".into(),
            status: TrainingJobStatus::Running,
            completed_at_ms: 1000,
            simulator_version: "fixture".into(),
            policy_version: "fixture".into(),
            outcomes: vec![],
            metrics: serde_json::json!({}),
            error: None,
        };

        let mut engine = EvaluatorFeedbackEngine::default();
        let running = engine.observe_swarm_result(
            &shortlist,
            &result,
        );
        assert!(running.skipped_non_completed_job);

        result.status = TrainingJobStatus::Completed;
        result.outcomes = vec![ActionOutcome {
            action_index: 99,
            placement_mean: None,
            placement_p25: None,
            placement_p75: None,
            top4_rate: None,
            first_rate: None,
            hp_mean_after_horizon: None,
            gold_mean_after_horizon: None,
            reward_mean: 0.2,
            reward_stddev: 0.0,
            samples: 64,
        }];

        let invalid = engine.observe_swarm_result(
            &shortlist,
            &result,
        );
        assert_eq!(invalid.skipped_invalid_index, 1);
        assert_eq!(invalid.outcomes_accepted, 0);
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
        assert!(
            (stats.mean_human_minus_recommended_reward.unwrap() - (-0.10)).abs() < 1e-6
        );
        assert!(
            (stats.mean_shadow_minus_recommended_reward.unwrap() - 0.10).abs() < 1e-6
        );
        assert!(
            (stats.mean_counterfactual_minus_recommended_reward.unwrap() - 0.20).abs() < 1e-6
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
