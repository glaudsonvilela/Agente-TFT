use serde::{Deserialize, Deserializer, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum ContractError {
    #[error("confidence must be finite and between 0.0 and 1.0")]
    InvalidConfidence,
    #[error("reason_short must be non-empty and <= 160 characters")]
    InvalidReason,
    #[error("next_step must be <= 160 characters")]
    InvalidNextStep,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
#[serde(transparent)]
pub struct Confidence(f32);

impl Confidence {
    pub fn new(value: f32) -> Result<Self, ContractError> {
        if value.is_finite() && (0.0..=1.0).contains(&value) {
            Ok(Self(value))
        } else {
            Err(ContractError::InvalidConfidence)
        }
    }

    pub const fn value(self) -> f32 {
        self.0
    }
}

impl<'de> Deserialize<'de> for Confidence {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = f32::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

impl Default for Confidence {
    fn default() -> Self {
        Self(0.0)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationSource {
    Vision,
    RiotApi,
    KnowledgePack,
    Derived,
    UserObservation,
    Simulator,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Observed<T> {
    pub value: T,
    pub confidence: Confidence,
    pub source: ObservationSource,
    pub observed_at_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct HexPosition {
    pub row: u8,
    pub col: u8,
}
