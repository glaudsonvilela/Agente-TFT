use std::collections::{BTreeMap, VecDeque};

use agente_tft_contracts::Confidence;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const PERCEPTION_HEALTH_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum PerceptionHealthError {
    #[error("perception stream fields cannot be empty")]
    EmptyStreamField,
    #[error("perception stream fields are too long")]
    StreamFieldTooLong,
    #[error("invalid perception health policy: {0}")]
    InvalidPolicy(&'static str),
    #[error("invalid perception baseline: {0}")]
    InvalidBaseline(&'static str),
    #[error("out-of-order perception sample: {observed_at_ms} < {last_seen_ms}")]
    OutOfOrderSample {
        observed_at_ms: u64,
        last_seen_ms: u64,
    },
}

#[derive(
    Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize,
)]
pub struct PerceptionStreamId {
    pub subsystem: String,
    pub field: String,
    pub profile_id: String,
}

impl PerceptionStreamId {
    pub fn new(
        subsystem: impl Into<String>,
        field: impl Into<String>,
        profile_id: impl Into<String>,
    ) -> Result<Self, PerceptionHealthError> {
        let value = Self {
            subsystem: subsystem.into(),
            field: field.into(),
            profile_id: profile_id.into(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), PerceptionHealthError> {
        let parts = [&self.subsystem, &self.field, &self.profile_id];
        if parts.iter().any(|part| part.trim().is_empty()) {
            return Err(PerceptionHealthError::EmptyStreamField);
        }
        if parts.iter().any(|part| part.len() > 120) {
            return Err(PerceptionHealthError::StreamFieldTooLong);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum PerceptionOutcome {
    Accepted { confidence: Confidence },
    Unknown,
    Conflict,
    Error,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerceptionSample {
    pub stream: PerceptionStreamId,
    pub observed_at_ms: u64,
    pub outcome: PerceptionOutcome,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerceptionBaseline {
    pub samples: u64,
    pub unknown_rate: f32,
    pub conflict_rate: f32,
    pub error_rate: f32,
    pub confidence_p50: Option<f32>,
}

impl PerceptionBaseline {
    pub fn validate(&self) -> Result<(), PerceptionHealthError> {
        for value in [self.unknown_rate, self.conflict_rate, self.error_rate] {
            if !finite_rate(value) {
                return Err(PerceptionHealthError::InvalidBaseline(
                    "rates must be finite and inside [0,1]",
                ));
            }
        }
        if let Some(value) = self.confidence_p50 {
            if !finite_rate(value) {
                return Err(PerceptionHealthError::InvalidBaseline(
                    "confidence_p50 must be finite and inside [0,1]",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerceptionHealthPolicy {
    pub window_capacity: usize,
    pub min_samples: usize,
    pub baseline_min_samples: u64,
    pub max_unknown_rate: f32,
    pub max_conflict_rate: f32,
    pub max_error_rate: f32,
    pub min_confidence_p50: f32,
    pub max_staleness_ms: u64,
    pub max_unknown_rate_delta_from_baseline: f32,
    pub max_conflict_rate_delta_from_baseline: f32,
    pub max_error_rate_delta_from_baseline: f32,
    pub max_confidence_p50_drop_from_baseline: f32,
    pub degrade_after_bad_windows: u32,
    pub recover_after_good_windows: u32,
}

impl Default for PerceptionHealthPolicy {
    fn default() -> Self {
        Self {
            window_capacity: 60,
            min_samples: 12,
            baseline_min_samples: 30,
            max_unknown_rate: 0.20,
            max_conflict_rate: 0.05,
            max_error_rate: 0.05,
            min_confidence_p50: 0.70,
            max_staleness_ms: 5_000,
            max_unknown_rate_delta_from_baseline: 0.15,
            max_conflict_rate_delta_from_baseline: 0.05,
            max_error_rate_delta_from_baseline: 0.05,
            max_confidence_p50_drop_from_baseline: 0.10,
            degrade_after_bad_windows: 3,
            recover_after_good_windows: 5,
        }
    }
}

impl PerceptionHealthPolicy {
    pub fn validate(&self) -> Result<(), PerceptionHealthError> {
        if self.window_capacity == 0 {
            return Err(PerceptionHealthError::InvalidPolicy(
                "window_capacity must be > 0",
            ));
        }
        if self.min_samples == 0 || self.min_samples > self.window_capacity {
            return Err(PerceptionHealthError::InvalidPolicy(
                "min_samples must be inside 1..=window_capacity",
            ));
        }
        for value in [
            self.max_unknown_rate,
            self.max_conflict_rate,
            self.max_error_rate,
            self.min_confidence_p50,
            self.max_unknown_rate_delta_from_baseline,
            self.max_conflict_rate_delta_from_baseline,
            self.max_error_rate_delta_from_baseline,
            self.max_confidence_p50_drop_from_baseline,
        ] {
            if !finite_rate(value) {
                return Err(PerceptionHealthError::InvalidPolicy(
                    "rates and confidence thresholds must be finite and inside [0,1]",
                ));
            }
        }
        if self.max_staleness_ms == 0 {
            return Err(PerceptionHealthError::InvalidPolicy(
                "max_staleness_ms must be > 0",
            ));
        }
        if self.degrade_after_bad_windows == 0 || self.recover_after_good_windows == 0 {
            return Err(PerceptionHealthError::InvalidPolicy(
                "hysteresis counters must be > 0",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PerceptionHealthState {
    WarmingUp,
    Healthy,
    Degraded,
    Stale,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DriftReason {
    UnknownRate,
    ConflictRate,
    ErrorRate,
    ConfidenceP50,
    BaselineUnknownRateDelta,
    BaselineConflictRateDelta,
    BaselineErrorRateDelta,
    BaselineConfidenceP50Drop,
    StaleAcceptedObservation,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerceptionHealthMetrics {
    pub samples: usize,
    pub accepted: usize,
    pub unknown: usize,
    pub conflicts: usize,
    pub errors: usize,
    pub coverage_rate: Option<f32>,
    pub unknown_rate: Option<f32>,
    pub conflict_rate: Option<f32>,
    pub error_rate: Option<f32>,
    pub confidence_count: usize,
    pub confidence_p50: Option<f32>,
    pub confidence_p95: Option<f32>,
    pub last_sample_ms: Option<u64>,
    pub last_accepted_ms: Option<u64>,
    pub staleness_ms: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PerceptionHealthSnapshot {
    pub schema_version: u32,
    pub stream: PerceptionStreamId,
    pub evaluated_at_ms: u64,
    pub state: PerceptionHealthState,
    pub metrics: PerceptionHealthMetrics,
    pub drift_reasons: Vec<DriftReason>,
    pub consecutive_bad_windows: u32,
    pub consecutive_good_windows: u32,
    pub baseline: Option<PerceptionBaseline>,
    pub note: String,
}

#[derive(Debug, Clone, Copy)]
struct Point {
    at_ms: u64,
    outcome: PerceptionOutcome,
}

#[derive(Debug)]
struct Tracker {
    points: VecDeque<Point>,
    state: PerceptionHealthState,
    bad_windows: u32,
    good_windows: u32,
    last_sample_ms: Option<u64>,
    last_accepted_ms: Option<u64>,
}

impl Default for Tracker {
    fn default() -> Self {
        Self {
            points: VecDeque::new(),
            state: PerceptionHealthState::WarmingUp,
            bad_windows: 0,
            good_windows: 0,
            last_sample_ms: None,
            last_accepted_ms: None,
        }
    }
}

#[derive(Debug)]
pub struct PerceptionHealthMonitor {
    policy: PerceptionHealthPolicy,
    baselines: BTreeMap<PerceptionStreamId, PerceptionBaseline>,
    trackers: BTreeMap<PerceptionStreamId, Tracker>,
}

impl PerceptionHealthMonitor {
    pub fn new(policy: PerceptionHealthPolicy) -> Result<Self, PerceptionHealthError> {
        policy.validate()?;
        Ok(Self {
            policy,
            baselines: BTreeMap::new(),
            trackers: BTreeMap::new(),
        })
    }

    pub fn policy(&self) -> &PerceptionHealthPolicy {
        &self.policy
    }

    pub fn set_baseline(
        &mut self,
        stream: PerceptionStreamId,
        baseline: PerceptionBaseline,
    ) -> Result<(), PerceptionHealthError> {
        stream.validate()?;
        baseline.validate()?;
        self.baselines.insert(stream, baseline);
        Ok(())
    }

    pub fn clear_baseline(&mut self, stream: &PerceptionStreamId) {
        self.baselines.remove(stream);
    }

    pub fn observe(
        &mut self,
        sample: PerceptionSample,
    ) -> Result<PerceptionHealthSnapshot, PerceptionHealthError> {
        sample.stream.validate()?;
        let baseline = self.baselines.get(&sample.stream).cloned();
        let tracker = self.trackers.entry(sample.stream.clone()).or_default();

        if let Some(last_seen_ms) = tracker.last_sample_ms {
            if sample.observed_at_ms < last_seen_ms {
                return Err(PerceptionHealthError::OutOfOrderSample {
                    observed_at_ms: sample.observed_at_ms,
                    last_seen_ms,
                });
            }
        }

        tracker.last_sample_ms = Some(sample.observed_at_ms);
        if matches!(sample.outcome, PerceptionOutcome::Accepted { .. }) {
            tracker.last_accepted_ms = Some(sample.observed_at_ms);
        }
        tracker.points.push_back(Point {
            at_ms: sample.observed_at_ms,
            outcome: sample.outcome,
        });
        while tracker.points.len() > self.policy.window_capacity {
            tracker.points.pop_front();
        }

        let metrics = metrics(tracker, sample.observed_at_ms);
        let reasons = reasons(&self.policy, baseline.as_ref(), &metrics);
        update_state(&self.policy, tracker, &metrics, &reasons);

        Ok(snapshot(
            sample.stream,
            sample.observed_at_ms,
            tracker,
            metrics,
            reasons,
            baseline,
            &self.policy,
        ))
    }

    pub fn snapshot(
        &self,
        stream: &PerceptionStreamId,
        now_ms: u64,
    ) -> Option<PerceptionHealthSnapshot> {
        let tracker = self.trackers.get(stream)?;
        let baseline = self.baselines.get(stream).cloned();
        let metrics = metrics(tracker, now_ms);
        let reasons = reasons(&self.policy, baseline.as_ref(), &metrics);
        Some(snapshot(
            stream.clone(),
            now_ms,
            tracker,
            metrics,
            reasons,
            baseline,
            &self.policy,
        ))
    }

    pub fn snapshots(&self, now_ms: u64) -> Vec<PerceptionHealthSnapshot> {
        self.trackers
            .keys()
            .filter_map(|stream| self.snapshot(stream, now_ms))
            .collect()
    }
}

fn update_state(
    policy: &PerceptionHealthPolicy,
    tracker: &mut Tracker,
    metrics: &PerceptionHealthMetrics,
    reasons: &[DriftReason],
) {
    let stale = reasons.contains(&DriftReason::StaleAcceptedObservation);
    if stale {
        tracker.state = PerceptionHealthState::Stale;
        tracker.bad_windows = tracker.bad_windows.saturating_add(1);
        tracker.good_windows = 0;
        return;
    }

    if metrics.samples < policy.min_samples {
        tracker.state = PerceptionHealthState::WarmingUp;
        tracker.bad_windows = 0;
        tracker.good_windows = 0;
        return;
    }

    if reasons.is_empty() {
        tracker.bad_windows = 0;
        tracker.good_windows = tracker.good_windows.saturating_add(1);
        if tracker.state != PerceptionHealthState::Healthy {
            if tracker.good_windows >= policy.recover_after_good_windows
                || tracker.state == PerceptionHealthState::WarmingUp
            {
                tracker.state = PerceptionHealthState::Healthy;
            }
        }
    } else {
        tracker.good_windows = 0;
        tracker.bad_windows = tracker.bad_windows.saturating_add(1);
        if tracker.bad_windows >= policy.degrade_after_bad_windows {
            tracker.state = PerceptionHealthState::Degraded;
        }
    }
}

fn snapshot(
    stream: PerceptionStreamId,
    now_ms: u64,
    tracker: &Tracker,
    metrics: PerceptionHealthMetrics,
    reasons: Vec<DriftReason>,
    baseline: Option<PerceptionBaseline>,
    policy: &PerceptionHealthPolicy,
) -> PerceptionHealthSnapshot {
    let visible_state = if reasons.contains(&DriftReason::StaleAcceptedObservation) {
        PerceptionHealthState::Stale
    } else if metrics.samples < policy.min_samples {
        PerceptionHealthState::WarmingUp
    } else {
        tracker.state
    };
    PerceptionHealthSnapshot {
        schema_version: PERCEPTION_HEALTH_SCHEMA_VERSION,
        stream,
        evaluated_at_ms: now_ms,
        state: visible_state,
        metrics,
        drift_reasons: reasons,
        consecutive_bad_windows: tracker.bad_windows,
        consecutive_good_windows: tracker.good_windows,
        baseline,
        note: "operational health only; not recognition accuracy or ground truth".into(),
    }
}

fn metrics(tracker: &Tracker, now_ms: u64) -> PerceptionHealthMetrics {
    let samples = tracker.points.len();
    let mut accepted = 0usize;
    let mut unknown = 0usize;
    let mut conflicts = 0usize;
    let mut errors = 0usize;
    let mut confidence = Vec::<f32>::new();

    for point in &tracker.points {
        match point.outcome {
            PerceptionOutcome::Accepted { confidence: value } => {
                accepted += 1;
                confidence.push(value.value());
            }
            PerceptionOutcome::Unknown => unknown += 1,
            PerceptionOutcome::Conflict => conflicts += 1,
            PerceptionOutcome::Error => errors += 1,
        }
    }
    confidence.sort_by(f32::total_cmp);

    PerceptionHealthMetrics {
        samples,
        accepted,
        unknown,
        conflicts,
        errors,
        coverage_rate: rate(accepted, samples),
        unknown_rate: rate(unknown, samples),
        conflict_rate: rate(conflicts, samples),
        error_rate: rate(errors, samples),
        confidence_count: confidence.len(),
        confidence_p50: percentile(&confidence, 0.50),
        confidence_p95: percentile(&confidence, 0.95),
        last_sample_ms: tracker.last_sample_ms,
        last_accepted_ms: tracker.last_accepted_ms,
        staleness_ms: tracker
            .last_accepted_ms
            .map(|at| now_ms.saturating_sub(at)),
    }
}

fn reasons(
    policy: &PerceptionHealthPolicy,
    baseline: Option<&PerceptionBaseline>,
    metrics: &PerceptionHealthMetrics,
) -> Vec<DriftReason> {
    let mut result = Vec::new();

    if let Some(age) = metrics.staleness_ms {
        if age > policy.max_staleness_ms {
            result.push(DriftReason::StaleAcceptedObservation);
        }
    }

    if metrics.samples < policy.min_samples {
        return result;
    }

    if metrics.unknown_rate.unwrap_or(0.0) > policy.max_unknown_rate {
        result.push(DriftReason::UnknownRate);
    }
    if metrics.conflict_rate.unwrap_or(0.0) > policy.max_conflict_rate {
        result.push(DriftReason::ConflictRate);
    }
    if metrics.error_rate.unwrap_or(0.0) > policy.max_error_rate {
        result.push(DriftReason::ErrorRate);
    }
    if let Some(value) = metrics.confidence_p50 {
        if value < policy.min_confidence_p50 {
            result.push(DriftReason::ConfidenceP50);
        }
    }

    if let Some(base) = baseline.filter(|base| base.samples >= policy.baseline_min_samples) {
        if metrics.unknown_rate.unwrap_or(0.0) - base.unknown_rate
            > policy.max_unknown_rate_delta_from_baseline
        {
            result.push(DriftReason::BaselineUnknownRateDelta);
        }
        if metrics.conflict_rate.unwrap_or(0.0) - base.conflict_rate
            > policy.max_conflict_rate_delta_from_baseline
        {
            result.push(DriftReason::BaselineConflictRateDelta);
        }
        if metrics.error_rate.unwrap_or(0.0) - base.error_rate
            > policy.max_error_rate_delta_from_baseline
        {
            result.push(DriftReason::BaselineErrorRateDelta);
        }
        if let (Some(current), Some(expected)) = (metrics.confidence_p50, base.confidence_p50) {
            if expected - current > policy.max_confidence_p50_drop_from_baseline {
                result.push(DriftReason::BaselineConfidenceP50Drop);
            }
        }
    }

    result.sort();
    result.dedup();
    result
}

fn rate(numerator: usize, denominator: usize) -> Option<f32> {
    if denominator == 0 {
        None
    } else {
        Some(numerator as f32 / denominator as f32)
    }
}

fn percentile(sorted: &[f32], q: f32) -> Option<f32> {
    if sorted.is_empty() {
        return None;
    }
    let p = (sorted.len() - 1) as f32 * q;
    let lo = p.floor() as usize;
    let hi = p.ceil() as usize;
    Some(sorted[lo] + (sorted[hi] - sorted[lo]) * (p - lo as f32))
}

fn finite_rate(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stream(profile: &str) -> PerceptionStreamId {
        PerceptionStreamId::new("hud", "gold", profile).unwrap()
    }

    fn policy() -> PerceptionHealthPolicy {
        PerceptionHealthPolicy {
            window_capacity: 8,
            min_samples: 4,
            baseline_min_samples: 4,
            max_unknown_rate: 0.25,
            max_conflict_rate: 0.20,
            max_error_rate: 0.20,
            min_confidence_p50: 0.70,
            max_staleness_ms: 100,
            max_unknown_rate_delta_from_baseline: 0.20,
            max_conflict_rate_delta_from_baseline: 0.20,
            max_error_rate_delta_from_baseline: 0.20,
            max_confidence_p50_drop_from_baseline: 0.10,
            degrade_after_bad_windows: 2,
            recover_after_good_windows: 2,
        }
    }

    fn accepted(at: u64, profile: &str, confidence: f32) -> PerceptionSample {
        PerceptionSample {
            stream: stream(profile),
            observed_at_ms: at,
            outcome: PerceptionOutcome::Accepted {
                confidence: Confidence::new(confidence).unwrap(),
            },
        }
    }

    fn outcome(at: u64, profile: &str, value: PerceptionOutcome) -> PerceptionSample {
        PerceptionSample {
            stream: stream(profile),
            observed_at_ms: at,
            outcome: value,
        }
    }

    #[test]
    fn stream_identity_is_validated() {
        assert!(PerceptionStreamId::new("hud", "", "v1").is_err());
        assert!(PerceptionStreamId::new("hud", "gold", "v1").is_ok());
    }

    #[test]
    fn policy_rejects_invalid_windows_and_rates() {
        let mut p = policy();
        p.min_samples = 9;
        assert!(p.validate().is_err());
        p = policy();
        p.max_unknown_rate = f32::NAN;
        assert!(p.validate().is_err());
    }

    #[test]
    fn healthy_after_enough_good_samples() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        let mut last = None;
        for at in [0, 10, 20, 30] {
            last = Some(monitor.observe(accepted(at, "v1", 0.95)).unwrap());
        }
        let last = last.unwrap();
        assert_eq!(last.state, PerceptionHealthState::Healthy);
        assert_eq!(last.metrics.coverage_rate, Some(1.0));
        assert_eq!(last.metrics.confidence_p50, Some(0.95));
    }

    #[test]
    fn single_unknown_does_not_trigger_drift() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        for at in [0, 10, 20, 30] {
            monitor.observe(accepted(at, "v1", 0.95)).unwrap();
        }
        let one = monitor
            .observe(outcome(40, "v1", PerceptionOutcome::Unknown))
            .unwrap();
        assert_eq!(one.state, PerceptionHealthState::Healthy);
        assert!(one.drift_reasons.is_empty());
    }

    #[test]
    fn persistent_unknowns_degrade_after_hysteresis() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        for at in [0, 10, 20, 30] {
            monitor.observe(accepted(at, "v1", 0.95)).unwrap();
        }
        monitor
            .observe(outcome(40, "v1", PerceptionOutcome::Unknown))
            .unwrap();
        let pending = monitor
            .observe(outcome(50, "v1", PerceptionOutcome::Unknown))
            .unwrap();
        assert_eq!(pending.state, PerceptionHealthState::Healthy);
        let degraded = monitor
            .observe(outcome(60, "v1", PerceptionOutcome::Unknown))
            .unwrap();
        assert_eq!(degraded.state, PerceptionHealthState::Degraded);
        assert!(degraded.drift_reasons.contains(&DriftReason::UnknownRate));
    }

    #[test]
    fn conflicts_and_errors_are_not_hidden_as_unknowns() {
        let mut p = policy();
        p.degrade_after_bad_windows = 1;
        let mut monitor = PerceptionHealthMonitor::new(p).unwrap();
        for (at, value) in [
            (0, PerceptionOutcome::Accepted { confidence: Confidence::new(0.95).unwrap() }),
            (10, PerceptionOutcome::Accepted { confidence: Confidence::new(0.95).unwrap() }),
            (20, PerceptionOutcome::Conflict),
            (30, PerceptionOutcome::Error),
        ] {
            monitor.observe(outcome(at, "v1", value)).unwrap();
        }
        let s = monitor.snapshot(&stream("v1"), 30).unwrap();
        assert_eq!(s.metrics.conflicts, 1);
        assert_eq!(s.metrics.errors, 1);
        assert!(s.drift_reasons.contains(&DriftReason::ConflictRate));
        assert!(s.drift_reasons.contains(&DriftReason::ErrorRate));
    }

    #[test]
    fn low_confidence_distribution_can_trigger_drift() {
        let mut p = policy();
        p.degrade_after_bad_windows = 1;
        let mut monitor = PerceptionHealthMonitor::new(p).unwrap();
        let mut last = None;
        for at in [0, 10, 20, 30] {
            last = Some(monitor.observe(accepted(at, "v1", 0.60)).unwrap());
        }
        let last = last.unwrap();
        assert_eq!(last.state, PerceptionHealthState::Degraded);
        assert!(last.drift_reasons.contains(&DriftReason::ConfidenceP50));
    }

    #[test]
    fn staleness_is_visible_without_inventing_a_new_sample() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        for at in [0, 10, 20, 30] {
            monitor.observe(accepted(at, "v1", 0.95)).unwrap();
        }
        let stale = monitor.snapshot(&stream("v1"), 200).unwrap();
        assert_eq!(stale.state, PerceptionHealthState::Stale);
        assert!(stale
            .drift_reasons
            .contains(&DriftReason::StaleAcceptedObservation));
    }

    #[test]
    fn baseline_delta_is_operational_not_accuracy() {
        let mut p = policy();
        p.max_unknown_rate = 1.0;
        p.degrade_after_bad_windows = 1;
        let mut monitor = PerceptionHealthMonitor::new(p).unwrap();
        monitor
            .set_baseline(
                stream("v1"),
                PerceptionBaseline {
                    samples: 100,
                    unknown_rate: 0.0,
                    conflict_rate: 0.0,
                    error_rate: 0.0,
                    confidence_p50: Some(0.95),
                },
            )
            .unwrap();
        monitor.observe(accepted(0, "v1", 0.95)).unwrap();
        monitor.observe(accepted(10, "v1", 0.95)).unwrap();
        monitor
            .observe(outcome(20, "v1", PerceptionOutcome::Unknown))
            .unwrap();
        let s = monitor
            .observe(outcome(30, "v1", PerceptionOutcome::Unknown))
            .unwrap();
        assert!(s
            .drift_reasons
            .contains(&DriftReason::BaselineUnknownRateDelta));
        assert!(s.note.contains("not recognition accuracy"));
    }

    #[test]
    fn profiles_are_isolated_streams() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        for at in [0, 10, 20, 30] {
            monitor.observe(accepted(at, "active", 0.95)).unwrap();
            monitor
                .observe(outcome(at, "candidate", PerceptionOutcome::Unknown))
                .unwrap();
        }
        let active = monitor.snapshot(&stream("active"), 30).unwrap();
        let candidate = monitor.snapshot(&stream("candidate"), 30).unwrap();
        assert_eq!(active.metrics.accepted, 4);
        assert_eq!(candidate.metrics.accepted, 0);
        assert_eq!(candidate.metrics.unknown, 4);
    }

    #[test]
    fn out_of_order_sample_is_rejected() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        monitor.observe(accepted(100, "v1", 0.95)).unwrap();
        assert!(matches!(
            monitor.observe(accepted(99, "v1", 0.95)),
            Err(PerceptionHealthError::OutOfOrderSample { .. })
        ));
    }

    #[test]
    fn snapshot_round_trips_json() {
        let mut monitor = PerceptionHealthMonitor::new(policy()).unwrap();
        for at in [0, 10, 20, 30] {
            monitor.observe(accepted(at, "v1", 0.95)).unwrap();
        }
        let s = monitor.snapshot(&stream("v1"), 30).unwrap();
        let encoded = serde_json::to_string(&s).unwrap();
        let decoded: PerceptionHealthSnapshot = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded, s);
    }
}
