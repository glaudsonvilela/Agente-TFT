use agente_tft_contracts::{Confidence, Observed};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ConsensusConfig {
    pub min_confidence: f32,
    pub confirmations: u8,
    pub max_gap_ms: u64,
}

impl Default for ConsensusConfig {
    fn default() -> Self {
        Self {
            min_confidence: 0.80,
            confirmations: 2,
            max_gap_ms: 750,
        }
    }
}

#[derive(Debug, Clone)]
struct Pending<T> {
    value: T,
    confirmations: u8,
    last_seen_ms: u64,
    best: Observed<T>,
}

#[derive(Debug)]
pub struct TemporalConsensus<T> {
    config: ConsensusConfig,
    pending: Option<Pending<T>>,
}

impl<T> TemporalConsensus<T>
where
    T: Clone + PartialEq,
{
    pub fn new(config: ConsensusConfig) -> Self {
        Self {
            config: ConsensusConfig {
                min_confidence: config.min_confidence.clamp(0.0, 1.0),
                confirmations: config.confirmations.max(1),
                max_gap_ms: config.max_gap_ms,
            },
            pending: None,
        }
    }

    pub fn observe(&mut self, observation: Observed<T>) -> Option<Observed<T>> {
        if observation.confidence.value() < self.config.min_confidence {
            return None;
        }

        let should_reset = self
            .pending
            .as_ref()
            .map(|pending| {
                pending.value != observation.value
                    || observation
                        .observed_at_ms
                        .saturating_sub(pending.last_seen_ms)
                        > self.config.max_gap_ms
            })
            .unwrap_or(true);

        if should_reset {
            self.pending = Some(Pending {
                value: observation.value.clone(),
                confirmations: 1,
                last_seen_ms: observation.observed_at_ms,
                best: observation,
            });
        } else if let Some(pending) = &mut self.pending {
            pending.confirmations = pending.confirmations.saturating_add(1);
            pending.last_seen_ms = observation.observed_at_ms;

            if observation.confidence.value() >= pending.best.confidence.value() {
                pending.best = observation;
            }
        }

        let pending = self.pending.as_ref()?;
        if pending.confirmations >= self.config.confirmations {
            Some(pending.best.clone())
        } else {
            None
        }
    }

    pub fn reset(&mut self) {
        self.pending = None;
    }
}

#[derive(Debug)]
pub struct StableValue<T> {
    value: Option<Observed<T>>,
}

impl<T> Default for StableValue<T> {
    fn default() -> Self {
        Self { value: None }
    }
}

impl<T> StableValue<T>
where
    T: Clone + PartialEq,
{
    pub fn update_if_changed(&mut self, candidate: Observed<T>) -> bool {
        let changed = self
            .value
            .as_ref()
            .map(|current| current.value != candidate.value)
            .unwrap_or(true);

        if changed {
            self.value = Some(candidate);
        } else if let Some(current) = &mut self.value {
            if candidate.confidence.value() >= current.confidence.value()
                || candidate.observed_at_ms > current.observed_at_ms
            {
                *current = candidate;
            }
        }

        changed
    }

    pub fn get(&self) -> Option<&Observed<T>> {
        self.value.as_ref()
    }
}

pub fn combine_confidence(values: &[Confidence]) -> Confidence {
    if values.is_empty() {
        return Confidence::default();
    }

    // Conservative fusion: a decision cannot be more trustworthy than
    // the weakest critical observation it depends on.
    let min = values
        .iter()
        .map(|v| v.value())
        .fold(1.0_f32, f32::min);

    Confidence::new(min).expect("minimum of valid confidence values is valid")
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{ObservationSource, Observed};

    use super::*;

    fn obs(value: u16, confidence: f32, at: u64) -> Observed<u16> {
        Observed {
            value,
            confidence: Confidence::new(confidence).unwrap(),
            source: ObservationSource::Vision,
            observed_at_ms: at,
        }
    }

    #[test]
    fn low_confidence_observation_is_ignored() {
        let mut gate = TemporalConsensus::new(ConsensusConfig::default());
        assert!(gate.observe(obs(50, 0.50, 100)).is_none());
    }

    #[test]
    fn two_matching_observations_promote_value() {
        let mut gate = TemporalConsensus::new(ConsensusConfig {
            confirmations: 2,
            ..ConsensusConfig::default()
        });

        assert!(gate.observe(obs(50, 0.90, 100)).is_none());
        let stable = gate.observe(obs(50, 0.95, 150)).unwrap();

        assert_eq!(stable.value, 50);
        assert_eq!(stable.confidence.value(), 0.95);
    }

    #[test]
    fn conflicting_value_resets_confirmation_count() {
        let mut gate = TemporalConsensus::new(ConsensusConfig {
            confirmations: 2,
            ..ConsensusConfig::default()
        });

        assert!(gate.observe(obs(50, 0.90, 100)).is_none());
        assert!(gate.observe(obs(43, 0.95, 150)).is_none());
        assert_eq!(gate.observe(obs(43, 0.92, 200)).unwrap().value, 43);
    }

    #[test]
    fn stale_confirmation_does_not_promote() {
        let mut gate = TemporalConsensus::new(ConsensusConfig {
            confirmations: 2,
            max_gap_ms: 100,
            ..ConsensusConfig::default()
        });

        assert!(gate.observe(obs(50, 0.90, 100)).is_none());
        assert!(gate.observe(obs(50, 0.95, 500)).is_none());
    }

    #[test]
    fn combined_confidence_uses_weakest_dependency() {
        let values = [
            Confidence::new(0.96).unwrap(),
            Confidence::new(0.82).unwrap(),
            Confidence::new(0.91).unwrap(),
        ];
        assert_eq!(combine_confidence(&values).value(), 0.82);
    }

    #[test]
    fn stable_value_only_reports_semantic_change() {
        let mut stable = StableValue::default();

        assert!(stable.update_if_changed(obs(50, 0.90, 100)));
        assert!(!stable.update_if_changed(obs(50, 0.95, 200)));
        assert!(stable.update_if_changed(obs(48, 0.91, 300)));
    }
}
