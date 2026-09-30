use agente_tft_contracts::{DecisionPacket, GameState};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const REMOTE_TRAINING_PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Error, PartialEq)]
pub enum ProtocolError {
    #[error("protocol version mismatch")]
    VersionMismatch,
    #[error("session_id cannot be empty")]
    EmptySessionId,
    #[error("job_id cannot be empty")]
    EmptyJobId,
    #[error("episode_id cannot be empty")]
    EmptyEpisodeId,
    #[error("state revision does not match decision state revision")]
    RevisionMismatch,
    #[error("rollout_count must be in [1, 4096]")]
    InvalidRolloutCount,
    #[error("horizon_steps must be in [1, 10000]")]
    InvalidHorizon,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TrainingMode {
    Replay,
    Simulator,
    SelfPlay,
    BotPool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OpponentPoolConfig {
    pub scripted_bots: Vec<String>,
    pub historical_policy_versions: Vec<String>,
    pub include_current_policy: bool,
}

impl Default for OpponentPoolConfig {
    fn default() -> Self {
        Self {
            scripted_bots: Vec::new(),
            historical_policy_versions: Vec::new(),
            include_current_policy: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TrainingJobRequest {
    pub protocol_version: u32,
    pub session_id: String,
    pub job_id: String,
    pub episode_id: String,
    pub created_at_ms: u64,
    pub mode: TrainingMode,
    pub state: GameState,
    pub decision: DecisionPacket,
    pub rollout_count: u32,
    pub horizon_steps: u32,
    pub opponent_pool: OpponentPoolConfig,
    #[serde(default)]
    pub metadata: serde_json::Value,
}

impl TrainingJobRequest {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        if self.protocol_version != REMOTE_TRAINING_PROTOCOL_VERSION {
            return Err(ProtocolError::VersionMismatch);
        }
        if self.session_id.trim().is_empty() {
            return Err(ProtocolError::EmptySessionId);
        }
        if self.job_id.trim().is_empty() {
            return Err(ProtocolError::EmptyJobId);
        }
        if self.episode_id.trim().is_empty() {
            return Err(ProtocolError::EmptyEpisodeId);
        }
        if self.state.revision != self.decision.state_revision {
            return Err(ProtocolError::RevisionMismatch);
        }
        if !(1..=4096).contains(&self.rollout_count) {
            return Err(ProtocolError::InvalidRolloutCount);
        }
        if !(1..=10_000).contains(&self.horizon_steps) {
            return Err(ProtocolError::InvalidHorizon);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TrainingJobStatus {
    Accepted,
    Running,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActionOutcome {
    pub action_index: u32,
    pub placement_mean: Option<f32>,
    pub placement_p25: Option<f32>,
    pub placement_p75: Option<f32>,
    pub top4_rate: Option<f32>,
    pub first_rate: Option<f32>,
    pub hp_mean_after_horizon: Option<f32>,
    pub gold_mean_after_horizon: Option<f32>,
    pub reward_mean: f32,
    pub reward_stddev: f32,
    pub samples: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TrainingJobResult {
    pub protocol_version: u32,
    pub session_id: String,
    pub job_id: String,
    pub episode_id: String,
    pub status: TrainingJobStatus,
    pub completed_at_ms: u64,
    pub simulator_version: String,
    pub policy_version: String,
    pub outcomes: Vec<ActionOutcome>,
    #[serde(default)]
    pub metrics: serde_json::Value,
    #[serde(default)]
    pub error: Option<String>,
}

impl TrainingJobResult {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        if self.protocol_version != REMOTE_TRAINING_PROTOCOL_VERSION {
            return Err(ProtocolError::VersionMismatch);
        }
        if self.session_id.trim().is_empty() {
            return Err(ProtocolError::EmptySessionId);
        }
        if self.job_id.trim().is_empty() {
            return Err(ProtocolError::EmptyJobId);
        }
        if self.episode_id.trim().is_empty() {
            return Err(ProtocolError::EmptyEpisodeId);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TrainingHeartbeat {
    pub protocol_version: u32,
    pub session_id: String,
    pub job_id: String,
    pub observed_at_ms: u64,
    pub status: TrainingJobStatus,
    pub completed_rollouts: u32,
    pub total_rollouts: u32,
    pub worker_id: String,
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{
        Action, Confidence, DecisionPacket, MatchPhase, PlayerState,
    };

    use super::*;

    fn state() -> GameState {
        let mut state = GameState::empty(100);
        state.revision = 7;
        state.phase = MatchPhase::Planning;
        state.player = PlayerState::default();
        state
    }

    fn decision() -> DecisionPacket {
        DecisionPacket::new(
            7,
            Action::HoldEcon,
            Confidence::new(0.80).unwrap(),
            vec![],
            vec![],
        )
    }

    #[test]
    fn valid_job_passes_validation() {
        let job = TrainingJobRequest {
            protocol_version: REMOTE_TRAINING_PROTOCOL_VERSION,
            session_id: "session-1".into(),
            job_id: "job-1".into(),
            episode_id: "episode-1".into(),
            created_at_ms: 1000,
            mode: TrainingMode::SelfPlay,
            state: state(),
            decision: decision(),
            rollout_count: 128,
            horizon_steps: 200,
            opponent_pool: OpponentPoolConfig::default(),
            metadata: serde_json::json!({}),
        };

        job.validate().unwrap();
    }

    #[test]
    fn revision_mismatch_is_rejected() {
        let mut job = TrainingJobRequest {
            protocol_version: REMOTE_TRAINING_PROTOCOL_VERSION,
            session_id: "session-1".into(),
            job_id: "job-1".into(),
            episode_id: "episode-1".into(),
            created_at_ms: 1000,
            mode: TrainingMode::Simulator,
            state: state(),
            decision: decision(),
            rollout_count: 64,
            horizon_steps: 100,
            opponent_pool: OpponentPoolConfig::default(),
            metadata: serde_json::json!({}),
        };
        job.state.revision = 8;

        assert_eq!(job.validate().unwrap_err(), ProtocolError::RevisionMismatch);
    }

    #[test]
    fn excessive_rollout_count_is_rejected() {
        let mut job = TrainingJobRequest {
            protocol_version: REMOTE_TRAINING_PROTOCOL_VERSION,
            session_id: "session-1".into(),
            job_id: "job-1".into(),
            episode_id: "episode-1".into(),
            created_at_ms: 1000,
            mode: TrainingMode::BotPool,
            state: state(),
            decision: decision(),
            rollout_count: 64,
            horizon_steps: 100,
            opponent_pool: OpponentPoolConfig::default(),
            metadata: serde_json::json!({}),
        };
        job.rollout_count = 5000;

        assert_eq!(
            job.validate().unwrap_err(),
            ProtocolError::InvalidRolloutCount
        );
    }
}
