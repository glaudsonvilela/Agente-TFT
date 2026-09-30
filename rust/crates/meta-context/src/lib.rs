use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum MetaContextError {
    #[error("source name cannot be empty")]
    EmptySource,
    #[error("source_url cannot be empty")]
    EmptySourceUrl,
    #[error("captured_at_ms must be > 0")]
    InvalidCapturedAt,
    #[error("metric must be finite")]
    NonFiniteMetric,
    #[error("rate must be in [0,1]")]
    InvalidRate,
    #[error("avg_place must be in [1,8]")]
    InvalidAveragePlace,
    #[error("frequency must be >= 0")]
    InvalidFrequency,
    #[error("sample_size must be > 0 when supplied")]
    InvalidSampleSize,
    #[error("invalid meta snapshot JSON: {0}")]
    InvalidJson(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MetaEntityKind {
    Comp,
    Unit,
    Item,
    Trait,
    Augment,
    Player,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MetaPerformance {
    pub avg_place: Option<f32>,
    pub top4_rate: Option<f32>,
    pub win_rate: Option<f32>,
    pub frequency: Option<f32>,
    pub sample_size: Option<u64>,
}

impl MetaPerformance {
    pub fn validate(&self) -> Result<(), MetaContextError> {
        if let Some(value) = self.avg_place {
            if !value.is_finite() {
                return Err(MetaContextError::NonFiniteMetric);
            }
            if !(1.0..=8.0).contains(&value) {
                return Err(MetaContextError::InvalidAveragePlace);
            }
        }

        for value in [self.top4_rate, self.win_rate] {
            if let Some(value) = value {
                if !value.is_finite() {
                    return Err(MetaContextError::NonFiniteMetric);
                }
                if !(0.0..=1.0).contains(&value) {
                    return Err(MetaContextError::InvalidRate);
                }
            }
        }

        if let Some(value) = self.frequency {
            if !value.is_finite() {
                return Err(MetaContextError::NonFiniteMetric);
            }
            if value < 0.0 {
                return Err(MetaContextError::InvalidFrequency);
            }
        }

        if self.sample_size == Some(0) {
            return Err(MetaContextError::InvalidSampleSize);
        }

        Ok(())
    }

    /// Convert available placement/rate metrics into a bounded prior in [-1, 1].
    ///
    /// This is intentionally a descriptive prior, not a calibrated action utility.
    /// Missing metrics contribute nothing.
    pub fn descriptive_strength_prior(&self) -> Result<f32, MetaContextError> {
        self.validate()?;

        let mut weighted_sum = 0.0_f32;
        let mut weight = 0.0_f32;

        if let Some(avg_place) = self.avg_place {
            // 1st maps near +1, 4.5 maps 0, 8th maps near -1.
            let normalized = ((4.5 - avg_place) / 3.5).clamp(-1.0, 1.0);
            weighted_sum += normalized * 0.55;
            weight += 0.55;
        }

        if let Some(top4_rate) = self.top4_rate {
            let normalized = ((top4_rate - 0.5) * 2.0).clamp(-1.0, 1.0);
            weighted_sum += normalized * 0.30;
            weight += 0.30;
        }

        if let Some(win_rate) = self.win_rate {
            // In an eight-player lobby, 12.5% is a neutral first-place baseline.
            let normalized = ((win_rate - 0.125) / 0.125).clamp(-1.0, 1.0);
            weighted_sum += normalized * 0.15;
            weight += 0.15;
        }

        if weight == 0.0 {
            Ok(0.0)
        } else {
            Ok((weighted_sum / weight).clamp(-1.0, 1.0))
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MetaEntity {
    pub kind: MetaEntityKind,
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub unit_ids: Vec<String>,
    #[serde(default)]
    pub trait_ids: Vec<String>,
    pub performance: MetaPerformance,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub attributes: BTreeMap<String, serde_json::Value>,
}

impl MetaEntity {
    pub fn validate(&self) -> Result<(), MetaContextError> {
        self.performance.validate()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MetaSnapshot {
    pub schema_version: u32,
    pub source: String,
    pub source_url: String,
    pub captured_at_ms: u64,
    pub patch: Option<String>,
    pub set: Option<String>,
    pub queue: Option<String>,
    pub rank_filter: Option<String>,
    pub window: Option<String>,
    #[serde(default)]
    pub entities: Vec<MetaEntity>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

impl MetaSnapshot {
    pub fn from_json_str(value: &str) -> Result<Self, MetaContextError> {
        let snapshot: Self = serde_json::from_str(value)
            .map_err(|error| MetaContextError::InvalidJson(error.to_string()))?;
        snapshot.validate()?;
        Ok(snapshot)
    }

    pub fn to_json_string(&self) -> Result<String, MetaContextError> {
        self.validate()?;
        serde_json::to_string_pretty(self)
            .map_err(|error| MetaContextError::InvalidJson(error.to_string()))
    }

    pub fn validate(&self) -> Result<(), MetaContextError> {
        if self.source.trim().is_empty() {
            return Err(MetaContextError::EmptySource);
        }
        if self.source_url.trim().is_empty() {
            return Err(MetaContextError::EmptySourceUrl);
        }
        if self.captured_at_ms == 0 {
            return Err(MetaContextError::InvalidCapturedAt);
        }
        for entity in &self.entities {
            entity.validate()?;
        }
        Ok(())
    }

    pub fn age_ms(&self, now_ms: u64) -> u64 {
        now_ms.saturating_sub(self.captured_at_ms)
    }

    pub fn is_fresh(&self, now_ms: u64, max_age_ms: u64) -> bool {
        self.age_ms(now_ms) <= max_age_ms
    }

    pub fn matches_patch_set(
        &self,
        patch: Option<&str>,
        set: Option<&str>,
    ) -> bool {
        let patch_ok = match (&self.patch, patch) {
            (Some(snapshot), Some(current)) => snapshot == current,
            (None, _) => true,
            (_, None) => false,
        };

        let set_ok = match (&self.set, set) {
            (Some(snapshot), Some(current)) => snapshot == current,
            (None, _) => true,
            (_, None) => false,
        };

        patch_ok && set_ok
    }

    pub fn entity(&self, kind: MetaEntityKind, id: &str) -> Option<&MetaEntity> {
        self.entities
            .iter()
            .find(|entity| entity.kind == kind && entity.id == id)
    }

    pub fn comps_containing_unit(&self, unit_id: &str) -> Vec<&MetaEntity> {
        self.entities
            .iter()
            .filter(|entity| {
                entity.kind == MetaEntityKind::Comp
                    && entity.unit_ids.iter().any(|id| id == unit_id)
            })
            .collect()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MetaPriorPolicy {
    /// Maximum influence of any external meta prior on a local opportunity score.
    pub max_abs_adjustment: f32,
    /// Data older than this is ignored.
    pub max_age_ms: u64,
    /// If false, mismatched/unknown patch-set snapshots are ignored.
    pub allow_unknown_patch_set: bool,
}

impl Default for MetaPriorPolicy {
    fn default() -> Self {
        Self {
            max_abs_adjustment: 0.10,
            max_age_ms: 6 * 60 * 60 * 1000,
            allow_unknown_patch_set: false,
        }
    }
}



#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MetaCacheReject {
    InvalidSnapshot(String),
    Stale,
    PatchSetMismatch,
}

#[derive(Debug, Clone, PartialEq)]
pub enum MetaCacheUpdate {
    Accepted {
        source: String,
        captured_at_ms: u64,
        entities: usize,
    },
    Rejected(MetaCacheReject),
}

#[derive(Debug, Default, Clone)]
pub struct MetaSnapshotCache {
    current: Option<MetaSnapshot>,
}

impl MetaSnapshotCache {
    pub fn current(&self) -> Option<&MetaSnapshot> {
        self.current.as_ref()
    }

    pub fn clear(&mut self) {
        self.current = None;
    }

    pub fn try_update_json(
        &mut self,
        value: &str,
        now_ms: u64,
        patch: Option<&str>,
        set: Option<&str>,
        policy: MetaPriorPolicy,
    ) -> MetaCacheUpdate {
        let snapshot = match MetaSnapshot::from_json_str(value) {
            Ok(snapshot) => snapshot,
            Err(error) => {
                return MetaCacheUpdate::Rejected(
                    MetaCacheReject::InvalidSnapshot(error.to_string()),
                )
            }
        };

        if !snapshot.is_fresh(now_ms, policy.max_age_ms) {
            return MetaCacheUpdate::Rejected(MetaCacheReject::Stale);
        }

        if !snapshot.matches_patch_set(patch, set)
            && !policy.allow_unknown_patch_set
        {
            return MetaCacheUpdate::Rejected(
                MetaCacheReject::PatchSetMismatch,
            );
        }

        let result = MetaCacheUpdate::Accepted {
            source: snapshot.source.clone(),
            captured_at_ms: snapshot.captured_at_ms,
            entities: snapshot.entities.len(),
        };
        self.current = Some(snapshot);
        result
    }
}

pub fn entity_meta_prior(
    snapshot: &MetaSnapshot,
    policy: MetaPriorPolicy,
    now_ms: u64,
    patch: Option<&str>,
    set: Option<&str>,
    kind: MetaEntityKind,
    id: &str,
) -> Result<Option<f32>, MetaContextError> {
    snapshot.validate()?;

    if !snapshot.is_fresh(now_ms, policy.max_age_ms) {
        return Ok(None);
    }

    let matches = snapshot.matches_patch_set(patch, set);
    if !matches && !policy.allow_unknown_patch_set {
        return Ok(None);
    }

    let Some(entity) = snapshot.entity(kind, id) else {
        return Ok(None);
    };

    let prior = entity.performance.descriptive_strength_prior()?;
    let max = policy.max_abs_adjustment.abs().min(1.0);
    Ok(Some(prior.clamp(-1.0, 1.0) * max))
}

pub fn unit_meta_prior(
    snapshot: &MetaSnapshot,
    policy: MetaPriorPolicy,
    now_ms: u64,
    patch: Option<&str>,
    set: Option<&str>,
    unit_id: &str,
) -> Result<Option<f32>, MetaContextError> {
    snapshot.validate()?;

    if !snapshot.is_fresh(now_ms, policy.max_age_ms) {
        return Ok(None);
    }

    let matches = snapshot.matches_patch_set(patch, set);
    if !matches && !policy.allow_unknown_patch_set {
        return Ok(None);
    }

    let mut priors = Vec::new();

    if let Some(unit) = snapshot.entity(MetaEntityKind::Unit, unit_id) {
        priors.push(unit.performance.descriptive_strength_prior()?);
    }

    for comp in snapshot.comps_containing_unit(unit_id) {
        priors.push(comp.performance.descriptive_strength_prior()?);
    }

    if priors.is_empty() {
        return Ok(None);
    }

    let mean = priors.iter().sum::<f32>() / priors.len() as f32;
    let max = policy.max_abs_adjustment.abs().min(1.0);
    Ok(Some(mean.clamp(-1.0, 1.0) * max))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot() -> MetaSnapshot {
        MetaSnapshot {
            schema_version: 1,
            source: "metatft_public".into(),
            source_url: "https://www.metatft.com/comps".into(),
            captured_at_ms: 1_000,
            patch: Some("18.3b".into()),
            set: Some("TFTSet18".into()),
            queue: Some("ranked".into()),
            rank_filter: Some("platinum_plus".into()),
            window: Some("last_3_days".into()),
            entities: vec![
                MetaEntity {
                    kind: MetaEntityKind::Unit,
                    id: "TFT18_X".into(),
                    name: "X".into(),
                    unit_ids: vec![],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(4.0),
                        top4_rate: Some(0.56),
                        win_rate: Some(0.15),
                        frequency: Some(0.10),
                        sample_size: Some(10_000),
                    },
                    tags: vec![],
                    attributes: BTreeMap::new(),
                },
                MetaEntity {
                    kind: MetaEntityKind::Comp,
                    id: "comp-x".into(),
                    name: "X Comp".into(),
                    unit_ids: vec!["TFT18_X".into()],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(3.8),
                        top4_rate: Some(0.60),
                        win_rate: Some(0.17),
                        frequency: Some(0.08),
                        sample_size: Some(5_000),
                    },
                    tags: vec![],
                    attributes: BTreeMap::new(),
                },
            ],
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn stale_snapshot_is_ignored() {
        let result = unit_meta_prior(
            &snapshot(),
            MetaPriorPolicy {
                max_abs_adjustment: 0.1,
                max_age_ms: 100,
                allow_unknown_patch_set: false,
            },
            2_000,
            Some("18.3b"),
            Some("TFTSet18"),
            "TFT18_X",
        )
        .unwrap();

        assert_eq!(result, None);
    }

    #[test]
    fn patch_mismatch_is_ignored_by_default() {
        let result = unit_meta_prior(
            &snapshot(),
            MetaPriorPolicy::default(),
            1_001,
            Some("18.4"),
            Some("TFTSet18"),
            "TFT18_X",
        )
        .unwrap();

        assert_eq!(result, None);
    }

    #[test]
    fn matching_snapshot_produces_bounded_small_prior() {
        let result = unit_meta_prior(
            &snapshot(),
            MetaPriorPolicy::default(),
            1_001,
            Some("18.3b"),
            Some("TFTSet18"),
            "TFT18_X",
        )
        .unwrap()
        .unwrap();

        assert!(result > 0.0);
        assert!(result <= 0.10);
    }

    #[test]
    fn snapshot_round_trips_json() {
        let snapshot = snapshot();
        let encoded = snapshot.to_json_string().unwrap();
        let decoded = MetaSnapshot::from_json_str(&encoded).unwrap();
        assert_eq!(decoded, snapshot);
    }

    #[test]
    fn cache_keeps_last_good_snapshot() {
        let good = snapshot().to_json_string().unwrap();
        let mut cache = MetaSnapshotCache::default();

        let accepted = cache.try_update_json(
            &good,
            1_001,
            Some("18.3b"),
            Some("TFTSet18"),
            MetaPriorPolicy::default(),
        );
        assert!(matches!(accepted, MetaCacheUpdate::Accepted { .. }));
        assert_eq!(cache.current().unwrap().patch.as_deref(), Some("18.3b"));

        let rejected = cache.try_update_json(
            "{not json}",
            1_002,
            Some("18.3b"),
            Some("TFTSet18"),
            MetaPriorPolicy::default(),
        );
        assert!(matches!(
            rejected,
            MetaCacheUpdate::Rejected(MetaCacheReject::InvalidSnapshot(_))
        ));
        assert_eq!(cache.current().unwrap().patch.as_deref(), Some("18.3b"));
    }

    #[test]
    fn cache_rejects_stale_and_patch_mismatch_without_replacing() {
        let good = snapshot().to_json_string().unwrap();
        let mut cache = MetaSnapshotCache::default();

        cache.try_update_json(
            &good,
            1_001,
            Some("18.3b"),
            Some("TFTSet18"),
            MetaPriorPolicy::default(),
        );

        let stale = cache.try_update_json(
            &good,
            100_000_000,
            Some("18.3b"),
            Some("TFTSet18"),
            MetaPriorPolicy {
                max_age_ms: 100,
                ..MetaPriorPolicy::default()
            },
        );
        assert_eq!(
            stale,
            MetaCacheUpdate::Rejected(MetaCacheReject::Stale)
        );

        let mismatch = cache.try_update_json(
            &good,
            1_002,
            Some("18.4"),
            Some("TFTSet18"),
            MetaPriorPolicy::default(),
        );
        assert_eq!(
            mismatch,
            MetaCacheUpdate::Rejected(MetaCacheReject::PatchSetMismatch)
        );

        assert_eq!(cache.current().unwrap().patch.as_deref(), Some("18.3b"));
    }

    #[test]
    fn invalid_rates_are_rejected() {
        let invalid = MetaPerformance {
            avg_place: None,
            top4_rate: Some(1.2),
            win_rate: None,
            frequency: None,
            sample_size: None,
        };
        assert_eq!(
            invalid.validate().unwrap_err(),
            MetaContextError::InvalidRate
        );
    }
}
