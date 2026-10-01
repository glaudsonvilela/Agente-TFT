use agente_tft_perception_health::{
    PerceptionHealthSnapshot, PerceptionHealthState,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const PROMOTION_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum PromotionError {
    #[error("invalid promotion policy: {0}")]
    InvalidPolicy(&'static str),
    #[error("active and candidate profile ids must be non-empty and different")]
    InvalidProfiles,
    #[error("active and candidate health streams must describe the same subsystem/field")]
    StreamMismatch,
    #[error("promotion observation is out of order")]
    OutOfOrder,
    #[error("promotion decision is not a promotion proposal")]
    NotPromotionProposal,
    #[error("post-promotion observation does not match the promoted profile")]
    PromotedProfileMismatch,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PromotionPolicy {
    pub min_comparable_samples: usize,
    pub promote_after_good_windows: u32,
    pub reject_after_bad_windows: u32,
    pub require_active_degraded: bool,
    pub min_candidate_coverage_rate: f32,
    pub min_candidate_confidence_p50: f32,
    pub min_candidate_anchor_similarity_p50: f32,
    pub min_operational_score_gain: f32,
    pub max_error_rate_regression: f32,
    pub max_conflict_rate_regression: f32,
    pub max_confidence_p50_drop: f32,
    pub max_anchor_similarity_drop: f32,
    pub coverage_weight: f32,
    pub confidence_weight: f32,
    pub anchor_weight: f32,
}

impl Default for PromotionPolicy {
    fn default() -> Self {
        Self {
            min_comparable_samples: 30,
            promote_after_good_windows: 5,
            reject_after_bad_windows: 3,
            require_active_degraded: true,
            min_candidate_coverage_rate: 0.85,
            min_candidate_confidence_p50: 0.70,
            min_candidate_anchor_similarity_p50: 0.70,
            min_operational_score_gain: 0.05,
            max_error_rate_regression: 0.01,
            max_conflict_rate_regression: 0.01,
            max_confidence_p50_drop: 0.03,
            max_anchor_similarity_drop: 0.05,
            coverage_weight: 0.40,
            confidence_weight: 0.30,
            anchor_weight: 0.30,
        }
    }
}

impl PromotionPolicy {
    pub fn validate(&self) -> Result<(), PromotionError> {
        if self.min_comparable_samples == 0 {
            return Err(PromotionError::InvalidPolicy(
                "min_comparable_samples must be > 0",
            ));
        }
        if self.promote_after_good_windows == 0 || self.reject_after_bad_windows == 0 {
            return Err(PromotionError::InvalidPolicy(
                "promotion/rejection hysteresis must be > 0",
            ));
        }
        for value in [
            self.min_candidate_coverage_rate,
            self.min_candidate_confidence_p50,
            self.min_operational_score_gain,
            self.max_error_rate_regression,
            self.max_conflict_rate_regression,
            self.max_confidence_p50_drop,
            self.max_anchor_similarity_drop,
        ] {
            if !finite_unit(value) {
                return Err(PromotionError::InvalidPolicy(
                    "rates/margins must be finite and inside [0,1]",
                ));
            }
        }
        if !self.min_candidate_anchor_similarity_p50.is_finite()
            || !(-1.0..=1.0).contains(&self.min_candidate_anchor_similarity_p50)
        {
            return Err(PromotionError::InvalidPolicy(
                "anchor threshold must be finite and inside [-1,1]",
            ));
        }
        for weight in [
            self.coverage_weight,
            self.confidence_weight,
            self.anchor_weight,
        ] {
            if !weight.is_finite() || weight < 0.0 {
                return Err(PromotionError::InvalidPolicy(
                    "score weights must be finite and nonnegative",
                ));
            }
        }
        if self.coverage_weight + self.confidence_weight + self.anchor_weight
            <= f32::EPSILON
        {
            return Err(PromotionError::InvalidPolicy(
                "at least one score weight must be positive",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShadowComparisonWindow {
    pub observed_at_ms: u64,
    pub active_profile_id: String,
    pub candidate_profile_id: String,
    pub active_health: PerceptionHealthSnapshot,
    pub candidate_health: PerceptionHealthSnapshot,
    pub active_anchor_similarity_p50: f32,
    pub candidate_anchor_similarity_p50: f32,
    pub active_anchor_errors: usize,
    pub candidate_anchor_errors: usize,
}

impl ShadowComparisonWindow {
    pub fn validate(&self) -> Result<(), PromotionError> {
        if self.active_profile_id.trim().is_empty()
            || self.candidate_profile_id.trim().is_empty()
            || self.active_profile_id == self.candidate_profile_id
        {
            return Err(PromotionError::InvalidProfiles);
        }
        if self.active_health.stream.subsystem != self.candidate_health.stream.subsystem
            || self.active_health.stream.field != self.candidate_health.stream.field
        {
            return Err(PromotionError::StreamMismatch);
        }
        for value in [
            self.active_anchor_similarity_p50,
            self.candidate_anchor_similarity_p50,
        ] {
            if !value.is_finite() || !(-1.0..=1.0).contains(&value) {
                return Err(PromotionError::InvalidPolicy(
                    "window anchor similarity must be finite and inside [-1,1]",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PromotionReason {
    InsufficientSamples,
    ActiveWarmingUp,
    CandidateWarmingUp,
    ActiveStillHealthy,
    CandidateNotHealthy,
    CandidateCoverage,
    CandidateConfidenceP50,
    CandidateAnchorSimilarityP50,
    CandidateAnchorErrors,
    ErrorRateRegression,
    ConflictRateRegression,
    ConfidenceP50Regression,
    AnchorSimilarityRegression,
    InsufficientOperationalGain,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PromotionAction {
    Hold,
    ProposePromotion,
    RejectCandidate,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PromotionDecision {
    pub schema_version: u32,
    pub observed_at_ms: u64,
    pub active_profile_id: String,
    pub candidate_profile_id: String,
    pub action: PromotionAction,
    pub reasons: Vec<PromotionReason>,
    pub consecutive_good_windows: u32,
    pub consecutive_bad_windows: u32,
    pub active_operational_score: Option<f32>,
    pub candidate_operational_score: Option<f32>,
    pub operational_score_gain: Option<f32>,
    pub active_health: PerceptionHealthSnapshot,
    pub candidate_health: PerceptionHealthSnapshot,
    pub active_anchor_similarity_p50: f32,
    pub candidate_anchor_similarity_p50: f32,
    pub note: String,
}

#[derive(Debug, Clone)]
pub struct PromotionGate {
    policy: PromotionPolicy,
    tracked_candidate: Option<String>,
    consecutive_good_windows: u32,
    consecutive_bad_windows: u32,
    last_observed_at_ms: Option<u64>,
    terminal: Option<PromotionDecision>,
}

impl PromotionGate {
    pub fn new(policy: PromotionPolicy) -> Result<Self, PromotionError> {
        policy.validate()?;
        Ok(Self {
            policy,
            tracked_candidate: None,
            consecutive_good_windows: 0,
            consecutive_bad_windows: 0,
            last_observed_at_ms: None,
            terminal: None,
        })
    }

    pub fn policy(&self) -> &PromotionPolicy {
        &self.policy
    }

    pub fn reset(&mut self) {
        self.tracked_candidate = None;
        self.consecutive_good_windows = 0;
        self.consecutive_bad_windows = 0;
        self.last_observed_at_ms = None;
        self.terminal = None;
    }

    pub fn observe(
        &mut self,
        window: ShadowComparisonWindow,
    ) -> Result<PromotionDecision, PromotionError> {
        window.validate()?;

        if self.tracked_candidate.as_deref() != Some(window.candidate_profile_id.as_str()) {
            self.tracked_candidate = Some(window.candidate_profile_id.clone());
            self.consecutive_good_windows = 0;
            self.consecutive_bad_windows = 0;
            self.last_observed_at_ms = None;
            self.terminal = None;
        }

        if let Some(last) = self.last_observed_at_ms {
            if window.observed_at_ms < last {
                return Err(PromotionError::OutOfOrder);
            }
        }
        self.last_observed_at_ms = Some(window.observed_at_ms);

        if let Some(decision) = &self.terminal {
            return Ok(decision.clone());
        }

        let evaluation = evaluate_window(&self.policy, &window);
        match evaluation.class {
            WindowClass::NotReady | WindowClass::Neutral => {
                self.consecutive_good_windows = 0;
                self.consecutive_bad_windows = 0;
            }
            WindowClass::Good => {
                self.consecutive_good_windows =
                    self.consecutive_good_windows.saturating_add(1);
                self.consecutive_bad_windows = 0;
            }
            WindowClass::Bad => {
                self.consecutive_bad_windows =
                    self.consecutive_bad_windows.saturating_add(1);
                self.consecutive_good_windows = 0;
            }
        }

        let action = if evaluation.class == WindowClass::Good
            && self.consecutive_good_windows >= self.policy.promote_after_good_windows
        {
            PromotionAction::ProposePromotion
        } else if evaluation.class == WindowClass::Bad
            && self.consecutive_bad_windows >= self.policy.reject_after_bad_windows
        {
            PromotionAction::RejectCandidate
        } else {
            PromotionAction::Hold
        };

        let decision = PromotionDecision {
            schema_version: PROMOTION_SCHEMA_VERSION,
            observed_at_ms: window.observed_at_ms,
            active_profile_id: window.active_profile_id,
            candidate_profile_id: window.candidate_profile_id,
            action,
            reasons: evaluation.reasons,
            consecutive_good_windows: self.consecutive_good_windows,
            consecutive_bad_windows: self.consecutive_bad_windows,
            active_operational_score: evaluation.active_score,
            candidate_operational_score: evaluation.candidate_score,
            operational_score_gain: evaluation.score_gain,
            active_health: window.active_health,
            candidate_health: window.candidate_health,
            active_anchor_similarity_p50: window.active_anchor_similarity_p50,
            candidate_anchor_similarity_p50: window.candidate_anchor_similarity_p50,
            note: "operational shadow gate only; not recognition accuracy or profile activation".into(),
        };

        if action != PromotionAction::Hold {
            self.terminal = Some(decision.clone());
        }

        Ok(decision)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WindowClass {
    NotReady,
    Neutral,
    Good,
    Bad,
}

struct WindowEvaluation {
    class: WindowClass,
    reasons: Vec<PromotionReason>,
    active_score: Option<f32>,
    candidate_score: Option<f32>,
    score_gain: Option<f32>,
}

fn evaluate_window(
    policy: &PromotionPolicy,
    window: &ShadowComparisonWindow,
) -> WindowEvaluation {
    let mut reasons = Vec::new();

    if window.active_health.metrics.samples < policy.min_comparable_samples
        || window.candidate_health.metrics.samples < policy.min_comparable_samples
    {
        reasons.push(PromotionReason::InsufficientSamples);
    }
    if window.active_health.state == PerceptionHealthState::WarmingUp {
        reasons.push(PromotionReason::ActiveWarmingUp);
    }
    if window.candidate_health.state == PerceptionHealthState::WarmingUp {
        reasons.push(PromotionReason::CandidateWarmingUp);
    }
    if !reasons.is_empty() {
        return WindowEvaluation {
            class: WindowClass::NotReady,
            reasons,
            active_score: None,
            candidate_score: None,
            score_gain: None,
        };
    }

    if policy.require_active_degraded
        && matches!(window.active_health.state, PerceptionHealthState::Healthy)
    {
        reasons.push(PromotionReason::ActiveStillHealthy);
    }

    let mut hard_bad = false;
    if !matches!(window.candidate_health.state, PerceptionHealthState::Healthy) {
        reasons.push(PromotionReason::CandidateNotHealthy);
        hard_bad = true;
    }

    let active_coverage = window.active_health.metrics.coverage_rate.unwrap_or(0.0);
    let candidate_coverage = window.candidate_health.metrics.coverage_rate.unwrap_or(0.0);
    let active_confidence = window.active_health.metrics.confidence_p50.unwrap_or(0.0);
    let candidate_confidence = window.candidate_health.metrics.confidence_p50.unwrap_or(0.0);
    let active_errors = window.active_health.metrics.error_rate.unwrap_or(0.0);
    let candidate_errors = window.candidate_health.metrics.error_rate.unwrap_or(0.0);
    let active_conflicts = window.active_health.metrics.conflict_rate.unwrap_or(0.0);
    let candidate_conflicts = window.candidate_health.metrics.conflict_rate.unwrap_or(0.0);

    if candidate_coverage < policy.min_candidate_coverage_rate {
        reasons.push(PromotionReason::CandidateCoverage);
        hard_bad = true;
    }
    if candidate_confidence < policy.min_candidate_confidence_p50 {
        reasons.push(PromotionReason::CandidateConfidenceP50);
        hard_bad = true;
    }
    if window.candidate_anchor_similarity_p50 < policy.min_candidate_anchor_similarity_p50 {
        reasons.push(PromotionReason::CandidateAnchorSimilarityP50);
        hard_bad = true;
    }
    if window.candidate_anchor_errors > 0 {
        reasons.push(PromotionReason::CandidateAnchorErrors);
        hard_bad = true;
    }
    if candidate_errors - active_errors > policy.max_error_rate_regression {
        reasons.push(PromotionReason::ErrorRateRegression);
        hard_bad = true;
    }
    if candidate_conflicts - active_conflicts > policy.max_conflict_rate_regression {
        reasons.push(PromotionReason::ConflictRateRegression);
        hard_bad = true;
    }
    if active_confidence - candidate_confidence > policy.max_confidence_p50_drop {
        reasons.push(PromotionReason::ConfidenceP50Regression);
        hard_bad = true;
    }
    if window.active_anchor_similarity_p50 - window.candidate_anchor_similarity_p50
        > policy.max_anchor_similarity_drop
    {
        reasons.push(PromotionReason::AnchorSimilarityRegression);
        hard_bad = true;
    }

    let active_score = operational_score(
        policy,
        active_coverage,
        active_confidence,
        window.active_anchor_similarity_p50,
    );
    let candidate_score = operational_score(
        policy,
        candidate_coverage,
        candidate_confidence,
        window.candidate_anchor_similarity_p50,
    );
    let score_gain = candidate_score - active_score;

    if hard_bad {
        return WindowEvaluation {
            class: WindowClass::Bad,
            reasons,
            active_score: Some(active_score),
            candidate_score: Some(candidate_score),
            score_gain: Some(score_gain),
        };
    }

    if policy.require_active_degraded
        && matches!(window.active_health.state, PerceptionHealthState::Healthy)
    {
        return WindowEvaluation {
            class: WindowClass::Neutral,
            reasons,
            active_score: Some(active_score),
            candidate_score: Some(candidate_score),
            score_gain: Some(score_gain),
        };
    }

    if score_gain < policy.min_operational_score_gain {
        reasons.push(PromotionReason::InsufficientOperationalGain);
        WindowEvaluation {
            class: WindowClass::Neutral,
            reasons,
            active_score: Some(active_score),
            candidate_score: Some(candidate_score),
            score_gain: Some(score_gain),
        }
    } else {
        WindowEvaluation {
            class: WindowClass::Good,
            reasons,
            active_score: Some(active_score),
            candidate_score: Some(candidate_score),
            score_gain: Some(score_gain),
        }
    }
}

fn operational_score(
    policy: &PromotionPolicy,
    coverage: f32,
    confidence: f32,
    anchor_similarity: f32,
) -> f32 {
    let anchor = ((anchor_similarity + 1.0) / 2.0).clamp(0.0, 1.0);
    let total = policy.coverage_weight + policy.confidence_weight + policy.anchor_weight;
    ((coverage * policy.coverage_weight
        + confidence * policy.confidence_weight
        + anchor * policy.anchor_weight)
        / total)
        .clamp(0.0, 1.0)
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActivationRecord {
    pub schema_version: u32,
    pub activation_id: String,
    pub activated_at_ms: u64,
    pub previous_profile_id: String,
    pub promoted_profile_id: String,
    pub baseline_health: PerceptionHealthSnapshot,
    pub baseline_anchor_similarity_p50: f32,
    pub source_decision: PromotionDecision,
    pub note: String,
}

impl ActivationRecord {
    pub fn from_promotion(
        activation_id: impl Into<String>,
        decision: PromotionDecision,
    ) -> Result<Self, PromotionError> {
        if decision.action != PromotionAction::ProposePromotion {
            return Err(PromotionError::NotPromotionProposal);
        }
        let activation_id = activation_id.into();
        if activation_id.trim().is_empty() {
            return Err(PromotionError::InvalidProfiles);
        }
        Ok(Self {
            schema_version: PROMOTION_SCHEMA_VERSION,
            activation_id,
            activated_at_ms: decision.observed_at_ms,
            previous_profile_id: decision.active_profile_id.clone(),
            promoted_profile_id: decision.candidate_profile_id.clone(),
            baseline_health: decision.candidate_health.clone(),
            baseline_anchor_similarity_p50: decision.candidate_anchor_similarity_p50,
            source_decision: decision,
            note: "activation receipt for audit/rollback; profile write occurs outside the gate".into(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RollbackPolicy {
    pub min_comparable_samples: usize,
    pub rollback_after_bad_windows: u32,
    pub max_coverage_drop: f32,
    pub max_unknown_rate_increase: f32,
    pub max_error_rate_increase: f32,
    pub max_conflict_rate_increase: f32,
    pub max_confidence_p50_drop: f32,
    pub max_anchor_similarity_drop: f32,
}

impl Default for RollbackPolicy {
    fn default() -> Self {
        Self {
            min_comparable_samples: 20,
            rollback_after_bad_windows: 3,
            max_coverage_drop: 0.15,
            max_unknown_rate_increase: 0.15,
            max_error_rate_increase: 0.02,
            max_conflict_rate_increase: 0.02,
            max_confidence_p50_drop: 0.10,
            max_anchor_similarity_drop: 0.10,
        }
    }
}

impl RollbackPolicy {
    pub fn validate(&self) -> Result<(), PromotionError> {
        if self.min_comparable_samples == 0 || self.rollback_after_bad_windows == 0 {
            return Err(PromotionError::InvalidPolicy(
                "rollback samples/hysteresis must be > 0",
            ));
        }
        for value in [
            self.max_coverage_drop,
            self.max_unknown_rate_increase,
            self.max_error_rate_increase,
            self.max_conflict_rate_increase,
            self.max_confidence_p50_drop,
            self.max_anchor_similarity_drop,
        ] {
            if !finite_unit(value) {
                return Err(PromotionError::InvalidPolicy(
                    "rollback margins must be finite and inside [0,1]",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RollbackReason {
    InsufficientSamples,
    PromotedNotHealthy,
    CoverageDrop,
    UnknownRateIncrease,
    ErrorRateIncrease,
    ConflictRateIncrease,
    ConfidenceP50Drop,
    AnchorSimilarityDrop,
    AnchorErrors,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RollbackAction {
    Hold,
    ProposeRollback,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PostPromotionWindow {
    pub observed_at_ms: u64,
    pub profile_id: String,
    pub health: PerceptionHealthSnapshot,
    pub anchor_similarity_p50: f32,
    pub anchor_errors: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RollbackDecision {
    pub schema_version: u32,
    pub observed_at_ms: u64,
    pub activation_id: String,
    pub previous_profile_id: String,
    pub promoted_profile_id: String,
    pub action: RollbackAction,
    pub reasons: Vec<RollbackReason>,
    pub consecutive_bad_windows: u32,
    pub current_health: PerceptionHealthSnapshot,
    pub baseline_health: PerceptionHealthSnapshot,
    pub current_anchor_similarity_p50: f32,
    pub baseline_anchor_similarity_p50: f32,
    pub note: String,
}

#[derive(Debug, Clone)]
pub struct RollbackGuard {
    policy: RollbackPolicy,
    activation: ActivationRecord,
    consecutive_bad_windows: u32,
    last_observed_at_ms: Option<u64>,
    terminal: Option<RollbackDecision>,
}

impl RollbackGuard {
    pub fn new(
        activation: ActivationRecord,
        policy: RollbackPolicy,
    ) -> Result<Self, PromotionError> {
        policy.validate()?;
        Ok(Self {
            policy,
            activation,
            consecutive_bad_windows: 0,
            last_observed_at_ms: None,
            terminal: None,
        })
    }

    pub fn observe(
        &mut self,
        window: PostPromotionWindow,
    ) -> Result<RollbackDecision, PromotionError> {
        if window.profile_id != self.activation.promoted_profile_id {
            return Err(PromotionError::PromotedProfileMismatch);
        }
        if !window.anchor_similarity_p50.is_finite()
            || !(-1.0..=1.0).contains(&window.anchor_similarity_p50)
        {
            return Err(PromotionError::InvalidPolicy(
                "rollback anchor similarity must be finite and inside [-1,1]",
            ));
        }
        if let Some(last) = self.last_observed_at_ms {
            if window.observed_at_ms < last {
                return Err(PromotionError::OutOfOrder);
            }
        }
        self.last_observed_at_ms = Some(window.observed_at_ms);

        if let Some(decision) = &self.terminal {
            return Ok(decision.clone());
        }

        let reasons = rollback_reasons(&self.policy, &self.activation, &window);
        let not_ready = reasons == [RollbackReason::InsufficientSamples];
        let bad = !reasons.is_empty() && !not_ready;

        if bad {
            self.consecutive_bad_windows = self.consecutive_bad_windows.saturating_add(1);
        } else {
            self.consecutive_bad_windows = 0;
        }

        let action = if bad
            && self.consecutive_bad_windows >= self.policy.rollback_after_bad_windows
        {
            RollbackAction::ProposeRollback
        } else {
            RollbackAction::Hold
        };

        let decision = RollbackDecision {
            schema_version: PROMOTION_SCHEMA_VERSION,
            observed_at_ms: window.observed_at_ms,
            activation_id: self.activation.activation_id.clone(),
            previous_profile_id: self.activation.previous_profile_id.clone(),
            promoted_profile_id: self.activation.promoted_profile_id.clone(),
            action,
            reasons,
            consecutive_bad_windows: self.consecutive_bad_windows,
            current_health: window.health,
            baseline_health: self.activation.baseline_health.clone(),
            current_anchor_similarity_p50: window.anchor_similarity_p50,
            baseline_anchor_similarity_p50: self.activation.baseline_anchor_similarity_p50,
            note: "rollback proposal only; does not mutate the profile registry".into(),
        };

        if action == RollbackAction::ProposeRollback {
            self.terminal = Some(decision.clone());
        }

        Ok(decision)
    }
}

fn rollback_reasons(
    policy: &RollbackPolicy,
    activation: &ActivationRecord,
    window: &PostPromotionWindow,
) -> Vec<RollbackReason> {
    if window.health.metrics.samples < policy.min_comparable_samples {
        return vec![RollbackReason::InsufficientSamples];
    }

    let baseline = &activation.baseline_health.metrics;
    let current = &window.health.metrics;
    let mut reasons = Vec::new();

    if !matches!(window.health.state, PerceptionHealthState::Healthy) {
        reasons.push(RollbackReason::PromotedNotHealthy);
    }
    if baseline.coverage_rate.unwrap_or(0.0) - current.coverage_rate.unwrap_or(0.0)
        > policy.max_coverage_drop
    {
        reasons.push(RollbackReason::CoverageDrop);
    }
    if current.unknown_rate.unwrap_or(0.0) - baseline.unknown_rate.unwrap_or(0.0)
        > policy.max_unknown_rate_increase
    {
        reasons.push(RollbackReason::UnknownRateIncrease);
    }
    if current.error_rate.unwrap_or(0.0) - baseline.error_rate.unwrap_or(0.0)
        > policy.max_error_rate_increase
    {
        reasons.push(RollbackReason::ErrorRateIncrease);
    }
    if current.conflict_rate.unwrap_or(0.0) - baseline.conflict_rate.unwrap_or(0.0)
        > policy.max_conflict_rate_increase
    {
        reasons.push(RollbackReason::ConflictRateIncrease);
    }
    if baseline.confidence_p50.unwrap_or(0.0) - current.confidence_p50.unwrap_or(0.0)
        > policy.max_confidence_p50_drop
    {
        reasons.push(RollbackReason::ConfidenceP50Drop);
    }
    if activation.baseline_anchor_similarity_p50 - window.anchor_similarity_p50
        > policy.max_anchor_similarity_drop
    {
        reasons.push(RollbackReason::AnchorSimilarityDrop);
    }
    if window.anchor_errors > 0 {
        reasons.push(RollbackReason::AnchorErrors);
    }

    reasons
}

fn finite_unit(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

#[cfg(test)]
mod tests {
    use agente_tft_perception_health::{
        PerceptionHealthMetrics, PerceptionStreamId,
    };

    use super::*;

    fn health(
        profile: &str,
        state: PerceptionHealthState,
        samples: usize,
        coverage: f32,
        confidence: f32,
        unknown: f32,
        conflict: f32,
        error: f32,
    ) -> PerceptionHealthSnapshot {
        let accepted = ((coverage * samples as f32).round() as usize).min(samples);
        PerceptionHealthSnapshot {
            schema_version: 1,
            stream: PerceptionStreamId::new("hud", "stage", profile).unwrap(),
            evaluated_at_ms: 100,
            state,
            metrics: PerceptionHealthMetrics {
                samples,
                accepted,
                unknown: ((unknown * samples as f32).round() as usize).min(samples),
                conflicts: ((conflict * samples as f32).round() as usize).min(samples),
                errors: ((error * samples as f32).round() as usize).min(samples),
                coverage_rate: Some(coverage),
                unknown_rate: Some(unknown),
                conflict_rate: Some(conflict),
                error_rate: Some(error),
                confidence_count: accepted,
                confidence_p50: Some(confidence),
                confidence_p95: Some(confidence),
                last_sample_ms: Some(100),
                last_accepted_ms: Some(100),
                staleness_ms: Some(0),
            },
            drift_reasons: vec![],
            consecutive_bad_windows: 0,
            consecutive_good_windows: 1,
            baseline: None,
            note: "fixture".into(),
        }
    }

    fn policy() -> PromotionPolicy {
        PromotionPolicy {
            min_comparable_samples: 10,
            promote_after_good_windows: 3,
            reject_after_bad_windows: 2,
            require_active_degraded: true,
            min_candidate_coverage_rate: 0.80,
            min_candidate_confidence_p50: 0.70,
            min_candidate_anchor_similarity_p50: 0.70,
            min_operational_score_gain: 0.05,
            max_error_rate_regression: 0.01,
            max_conflict_rate_regression: 0.01,
            max_confidence_p50_drop: 0.03,
            max_anchor_similarity_drop: 0.05,
            coverage_weight: 0.4,
            confidence_weight: 0.3,
            anchor_weight: 0.3,
        }
    }

    fn good_window(at: u64) -> ShadowComparisonWindow {
        ShadowComparisonWindow {
            observed_at_ms: at,
            active_profile_id: "active-v4".into(),
            candidate_profile_id: "candidate-shift".into(),
            active_health: health(
                "active-v4",
                PerceptionHealthState::Degraded,
                30,
                0.55,
                0.90,
                0.45,
                0.0,
                0.0,
            ),
            candidate_health: health(
                "candidate-shift",
                PerceptionHealthState::Healthy,
                30,
                0.95,
                0.92,
                0.05,
                0.0,
                0.0,
            ),
            active_anchor_similarity_p50: 0.55,
            candidate_anchor_similarity_p50: 0.96,
            active_anchor_errors: 0,
            candidate_anchor_errors: 0,
        }
    }

    #[test]
    fn promotion_requires_persistent_good_windows() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        assert_eq!(
            gate.observe(good_window(100)).unwrap().action,
            PromotionAction::Hold
        );
        assert_eq!(
            gate.observe(good_window(200)).unwrap().action,
            PromotionAction::Hold
        );
        let promoted = gate.observe(good_window(300)).unwrap();
        assert_eq!(promoted.action, PromotionAction::ProposePromotion);
        assert_eq!(promoted.consecutive_good_windows, 3);
        assert!(promoted.operational_score_gain.unwrap() >= 0.05);
        assert!(promoted.note.contains("not recognition accuracy"));
    }

    #[test]
    fn active_healthy_blocks_unnecessary_promotion() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        let mut window = good_window(100);
        window.active_health.state = PerceptionHealthState::Healthy;
        for at in [100, 200, 300, 400] {
            window.observed_at_ms = at;
            let decision = gate.observe(window.clone()).unwrap();
            assert_eq!(decision.action, PromotionAction::Hold);
            assert!(decision.reasons.contains(&PromotionReason::ActiveStillHealthy));
        }
    }

    #[test]
    fn unknown_reduction_alone_is_not_enough_when_anchor_regresses() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        let mut window = good_window(100);
        window.active_anchor_similarity_p50 = 0.95;
        window.candidate_anchor_similarity_p50 = 0.75;
        for at in [100, 200] {
            window.observed_at_ms = at;
            let decision = gate.observe(window.clone()).unwrap();
            if at == 200 {
                assert_eq!(decision.action, PromotionAction::RejectCandidate);
                assert!(decision
                    .reasons
                    .contains(&PromotionReason::AnchorSimilarityRegression));
            }
        }
    }

    #[test]
    fn persistent_candidate_errors_reject_candidate() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        let mut window = good_window(100);
        window.candidate_health.metrics.error_rate = Some(0.10);
        window.candidate_health.metrics.errors = 3;
        for at in [100, 200] {
            window.observed_at_ms = at;
            let decision = gate.observe(window.clone()).unwrap();
            if at == 200 {
                assert_eq!(decision.action, PromotionAction::RejectCandidate);
                assert!(decision.reasons.contains(&PromotionReason::ErrorRateRegression));
            }
        }
    }

    #[test]
    fn insufficient_samples_do_not_count_as_bad_windows() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        let mut window = good_window(100);
        window.candidate_health.metrics.samples = 3;
        window.active_health.metrics.samples = 3;
        for at in [100, 200, 300] {
            window.observed_at_ms = at;
            let decision = gate.observe(window.clone()).unwrap();
            assert_eq!(decision.action, PromotionAction::Hold);
            assert_eq!(decision.consecutive_bad_windows, 0);
            assert!(decision.reasons.contains(&PromotionReason::InsufficientSamples));
        }
    }

    #[test]
    fn changing_candidate_resets_hysteresis() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        gate.observe(good_window(100)).unwrap();
        gate.observe(good_window(200)).unwrap();
        let mut other = good_window(300);
        other.candidate_profile_id = "candidate-other".into();
        other.candidate_health.stream =
            PerceptionStreamId::new("hud", "stage", "candidate-other").unwrap();
        let decision = gate.observe(other).unwrap();
        assert_eq!(decision.action, PromotionAction::Hold);
        assert_eq!(decision.consecutive_good_windows, 1);
    }

    fn promoted_decision() -> PromotionDecision {
        let mut gate = PromotionGate::new(policy()).unwrap();
        gate.observe(good_window(100)).unwrap();
        gate.observe(good_window(200)).unwrap();
        gate.observe(good_window(300)).unwrap()
    }

    #[test]
    fn activation_requires_a_promotion_proposal() {
        let mut hold = promoted_decision();
        hold.action = PromotionAction::Hold;
        assert!(ActivationRecord::from_promotion("activation-1", hold).is_err());
        assert!(ActivationRecord::from_promotion(
            "activation-1",
            promoted_decision()
        )
        .is_ok());
    }

    #[test]
    fn rollback_requires_persistent_post_promotion_degradation() {
        let activation =
            ActivationRecord::from_promotion("activation-1", promoted_decision()).unwrap();
        let mut guard = RollbackGuard::new(
            activation,
            RollbackPolicy {
                min_comparable_samples: 10,
                rollback_after_bad_windows: 2,
                ..RollbackPolicy::default()
            },
        )
        .unwrap();

        let degraded = health(
            "candidate-shift",
            PerceptionHealthState::Degraded,
            30,
            0.60,
            0.75,
            0.40,
            0.0,
            0.0,
        );
        let first = guard
            .observe(PostPromotionWindow {
                observed_at_ms: 400,
                profile_id: "candidate-shift".into(),
                health: degraded.clone(),
                anchor_similarity_p50: 0.70,
                anchor_errors: 0,
            })
            .unwrap();
        assert_eq!(first.action, RollbackAction::Hold);

        let second = guard
            .observe(PostPromotionWindow {
                observed_at_ms: 500,
                profile_id: "candidate-shift".into(),
                health: degraded,
                anchor_similarity_p50: 0.70,
                anchor_errors: 0,
            })
            .unwrap();
        assert_eq!(second.action, RollbackAction::ProposeRollback);
        assert!(second.reasons.contains(&RollbackReason::PromotedNotHealthy));
        assert!(second.note.contains("does not mutate"));
    }

    #[test]
    fn healthy_post_promotion_windows_do_not_rollback() {
        let activation =
            ActivationRecord::from_promotion("activation-1", promoted_decision()).unwrap();
        let mut guard = RollbackGuard::new(
            activation,
            RollbackPolicy {
                min_comparable_samples: 10,
                rollback_after_bad_windows: 2,
                ..RollbackPolicy::default()
            },
        )
        .unwrap();

        for at in [400, 500, 600] {
            let decision = guard
                .observe(PostPromotionWindow {
                    observed_at_ms: at,
                    profile_id: "candidate-shift".into(),
                    health: health(
                        "candidate-shift",
                        PerceptionHealthState::Healthy,
                        30,
                        0.95,
                        0.92,
                        0.05,
                        0.0,
                        0.0,
                    ),
                    anchor_similarity_p50: 0.96,
                    anchor_errors: 0,
                })
                .unwrap();
            assert_eq!(decision.action, RollbackAction::Hold);
            assert_eq!(decision.consecutive_bad_windows, 0);
        }
    }

    #[test]
    fn promotion_and_rollback_records_round_trip_json() {
        let promotion = promoted_decision();
        let activation =
            ActivationRecord::from_promotion("activation-1", promotion.clone()).unwrap();
        let p = serde_json::to_string(&promotion).unwrap();
        let a = serde_json::to_string(&activation).unwrap();
        assert_eq!(serde_json::from_str::<PromotionDecision>(&p).unwrap(), promotion);
        assert_eq!(serde_json::from_str::<ActivationRecord>(&a).unwrap(), activation);
    }

    #[test]
    fn out_of_order_shadow_window_is_rejected() {
        let mut gate = PromotionGate::new(policy()).unwrap();
        gate.observe(good_window(200)).unwrap();
        assert!(matches!(
            gate.observe(good_window(100)),
            Err(PromotionError::OutOfOrder)
        ));
    }
}
