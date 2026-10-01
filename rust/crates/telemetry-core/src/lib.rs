use std::{
    fs::{self, File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

use agente_tft_contracts::{DecisionPacket, GameEvent, GameState, Recommendation};
use agente_tft_opportunity_fact_builder::OpportunityFactBuild;
use agente_tft_perception_adaptation::{
    ActivationRecord, PromotionDecision, RoiSearchReport, RollbackDecision,
};
use agente_tft_perception_health::PerceptionHealthSnapshot;
use agente_tft_opportunity_runtime::{CompleteOpportunityCycle, OpportunityCycle};
use agente_tft_pattern_engine::EvaluatorFeedbackEngine;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

pub const TELEMETRY_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error)]
pub enum TelemetryError {
    #[error("telemetry session_id cannot be empty")]
    EmptySessionId,
    #[error("telemetry I/O error: {0}")]
    Io(String),
    #[error("telemetry serialization error: {0}")]
    Serialize(String),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum TelemetryPayload {
    SessionStarted {
        profile: String,
        patch: Option<String>,
        set: Option<String>,
    },
    StateSnapshot {
        state: GameState,
    },
    GameEvent {
        event: GameEvent,
    },
    Analysis {
        name: String,
        data: Value,
    },
    OpportunityFactBuild {
        build: OpportunityFactBuild,
    },
    OpportunityCycle {
        cycle: OpportunityCycle,
    },
    CompleteOpportunityCycle {
        cycle: CompleteOpportunityCycle,
    },
    EvaluatorFeedbackSnapshot {
        feedback: EvaluatorFeedbackEngine,
    },
    PerceptionHealthSnapshot {
        snapshot: PerceptionHealthSnapshot,
    },
    PerceptionRoiSearch {
        report: RoiSearchReport,
    },
    PerceptionPromotionDecision {
        decision: PromotionDecision,
    },
    PerceptionActivation {
        activation: ActivationRecord,
    },
    PerceptionRollbackDecision {
        decision: RollbackDecision,
    },
    Decision {
        decision: DecisionPacket,
    },
    Recommendation {
        recommendation: Recommendation,
    },
    PlayerAction {
        action: Value,
    },
    Outcome {
        data: Value,
    },
    Metric {
        name: String,
        value: f64,
        unit: Option<String>,
    },
    SessionEnded {
        reason: String,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TelemetryRecord {
    pub schema_version: u32,
    pub session_id: String,
    pub sequence: u64,
    pub recorded_at_ms: u64,
    pub payload: TelemetryPayload,
}

pub struct JsonlRecorder {
    session_id: String,
    path: PathBuf,
    writer: BufWriter<File>,
    next_sequence: u64,
}

impl JsonlRecorder {
    pub fn create(
        directory: impl AsRef<Path>,
        session_id: impl Into<String>,
    ) -> Result<Self, TelemetryError> {
        let session_id = sanitize_session_id(session_id.into())?;
        let directory = directory.as_ref();

        fs::create_dir_all(directory)
            .map_err(|e| TelemetryError::Io(e.to_string()))?;

        let path = directory.join(format!("{session_id}.jsonl"));
        let file = OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(&path)
            .map_err(|e| TelemetryError::Io(e.to_string()))?;

        Ok(Self {
            session_id,
            path,
            writer: BufWriter::new(file),
            next_sequence: 0,
        })
    }

    pub fn append(
        &mut self,
        recorded_at_ms: u64,
        payload: TelemetryPayload,
    ) -> Result<TelemetryRecord, TelemetryError> {
        let record = TelemetryRecord {
            schema_version: TELEMETRY_SCHEMA_VERSION,
            session_id: self.session_id.clone(),
            sequence: self.next_sequence,
            recorded_at_ms,
            payload,
        };

        serde_json::to_writer(&mut self.writer, &record)
            .map_err(|e| TelemetryError::Serialize(e.to_string()))?;
        self.writer
            .write_all(b"\n")
            .map_err(|e| TelemetryError::Io(e.to_string()))?;

        self.next_sequence = self.next_sequence.saturating_add(1);
        Ok(record)
    }

    pub fn flush(&mut self) -> Result<(), TelemetryError> {
        self.writer
            .flush()
            .map_err(|e| TelemetryError::Io(e.to_string()))
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn session_id(&self) -> &str {
        &self.session_id
    }
}

impl Drop for JsonlRecorder {
    fn drop(&mut self) {
        let _ = self.writer.flush();
    }
}

fn sanitize_session_id(value: String) -> Result<String, TelemetryError> {
    let value = value.trim();
    if value.is_empty() {
        return Err(TelemetryError::EmptySessionId);
    }

    let sanitized: String = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_') {
                ch
            } else {
                '_'
            }
        })
        .take(120)
        .collect();

    if sanitized.is_empty() {
        Err(TelemetryError::EmptySessionId)
    } else {
        Ok(sanitized)
    }
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::*;

    fn temp_dir() -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "agente-tft-telemetry-{}-{nonce}",
            std::process::id()
        ))
    }

    #[test]
    fn recorder_writes_ordered_json_lines() {
        let root = temp_dir();
        let mut recorder = JsonlRecorder::create(&root, "match/fixture").unwrap();

        let first = recorder
            .append(
                100,
                TelemetryPayload::SessionStarted {
                    profile: "replay".into(),
                    patch: Some("test".into()),
                    set: Some("set".into()),
                },
            )
            .unwrap();
        let second = recorder
            .append(
                150,
                TelemetryPayload::Metric {
                    name: "state_update_ms".into(),
                    value: 2.5,
                    unit: Some("ms".into()),
                },
            )
            .unwrap();
        recorder.flush().unwrap();

        assert_eq!(first.sequence, 0);
        assert_eq!(second.sequence, 1);
        assert_eq!(recorder.session_id(), "match_fixture");

        let content = fs::read_to_string(recorder.path()).unwrap();
        let lines: Vec<_> = content.lines().collect();
        assert_eq!(lines.len(), 2);

        let parsed: TelemetryRecord = serde_json::from_str(lines[1]).unwrap();
        assert_eq!(parsed.sequence, 1);
        assert!(matches!(parsed.payload, TelemetryPayload::Metric { .. }));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recorder_round_trips_opportunity_fact_build() {
        let root = temp_dir();
        let mut recorder =
            JsonlRecorder::create(&root, "fact-build-fixture").unwrap();

        let build = OpportunityFactBuild {
            facts: Default::default(),
            diagnostics: Default::default(),
        };

        recorder
            .append(
                100,
                TelemetryPayload::OpportunityFactBuild {
                    build: build.clone(),
                },
            )
            .unwrap();
        recorder.flush().unwrap();

        let content = fs::read_to_string(recorder.path()).unwrap();
        let parsed: TelemetryRecord =
            serde_json::from_str(content.lines().next().unwrap()).unwrap();

        match parsed.payload {
            TelemetryPayload::OpportunityFactBuild { build: saved } => {
                assert_eq!(saved, build);
            }
            other => panic!("unexpected payload: {other:?}"),
        }

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recorder_round_trips_opportunity_cycle() {
        use agente_tft_contracts::{
            Action, Confidence, DecisionPacket,
        };
        use agente_tft_opportunity_engine::{
            OpportunityDelta, OpportunityReport,
        };

        let root = temp_dir();
        let mut recorder =
            JsonlRecorder::create(&root, "opportunity-fixture").unwrap();

        let cycle = OpportunityCycle {
            report: OpportunityReport {
                state_revision: 7,
                evaluated_at_ms: 100,
                all: vec![],
                shortlist: vec![],
            },
            delta: OpportunityDelta {
                previous_revision: None,
                current_revision: 7,
                added: vec![Action::HoldEcon],
                removed: vec![],
                top_changed: true,
                previous_top: None,
                current_top: Some(Action::HoldEcon),
                material_utility_shifts: vec![],
            },
            decision: DecisionPacket::new(
                7,
                Action::HoldEcon,
                Confidence::new(0.90).unwrap(),
                vec![],
                vec![],
            ),
            remote_shortlist: vec![],
            should_refresh_ui: true,
            should_remote_evaluate: true,
        };

        recorder
            .append(
                100,
                TelemetryPayload::OpportunityCycle {
                    cycle: cycle.clone(),
                },
            )
            .unwrap();
        recorder.flush().unwrap();

        let content = fs::read_to_string(recorder.path()).unwrap();
        let parsed: TelemetryRecord =
            serde_json::from_str(content.lines().next().unwrap()).unwrap();

        match parsed.payload {
            TelemetryPayload::OpportunityCycle { cycle: saved } => {
                assert_eq!(saved, cycle);
                assert_eq!(saved.decision.state_revision, 7);
            }
            other => panic!("unexpected payload: {other:?}"),
        }

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recorder_round_trips_complete_opportunity_cycle() {
        use agente_tft_contracts::{
            Action, Confidence, DecisionPacket,
        };
        use agente_tft_opportunity_engine::{
            OpportunityDelta, OpportunityReport,
        };

        let root = temp_dir();
        let mut recorder =
            JsonlRecorder::create(&root, "complete-opportunity-fixture").unwrap();

        let opportunity_cycle = OpportunityCycle {
            report: OpportunityReport {
                state_revision: 11,
                evaluated_at_ms: 200,
                all: vec![],
                shortlist: vec![],
            },
            delta: OpportunityDelta {
                previous_revision: Some(10),
                current_revision: 11,
                added: vec![Action::HoldEcon],
                removed: vec![],
                top_changed: true,
                previous_top: None,
                current_top: Some(Action::HoldEcon),
                material_utility_shifts: vec![],
            },
            decision: DecisionPacket::new(
                11,
                Action::HoldEcon,
                Confidence::new(0.90).unwrap(),
                vec![],
                vec![],
            ),
            remote_shortlist: vec![],
            should_refresh_ui: true,
            should_remote_evaluate: true,
        };

        let cycle = CompleteOpportunityCycle {
            fact_build: OpportunityFactBuild {
                facts: Default::default(),
                diagnostics: Default::default(),
            },
            cycle: opportunity_cycle,
            item_evaluations: vec![],
            pivot_evaluations: vec![],
            sell_diagnostic: None,
            matchup_opponent_id: Some("p2".into()),
            matchup_opponent_found: false,
            matchup_positioning: None,
        };

        recorder
            .append(
                200,
                TelemetryPayload::CompleteOpportunityCycle {
                    cycle: cycle.clone(),
                },
            )
            .unwrap();
        recorder.flush().unwrap();

        let content = fs::read_to_string(recorder.path()).unwrap();
        let parsed: TelemetryRecord =
            serde_json::from_str(content.lines().next().unwrap()).unwrap();

        match parsed.payload {
            TelemetryPayload::CompleteOpportunityCycle { cycle: saved } => {
                assert_eq!(saved, cycle);
                assert_eq!(saved.cycle.decision.state_revision, 11);
            }
            other => panic!("unexpected payload: {other:?}"),
        }

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn recorder_round_trips_evaluator_feedback_snapshot() {
        let root = temp_dir();
        let mut recorder =
            JsonlRecorder::create(&root, "feedback-fixture").unwrap();

        let feedback = EvaluatorFeedbackEngine::default();

        recorder
            .append(
                300,
                TelemetryPayload::EvaluatorFeedbackSnapshot {
                    feedback: feedback.clone(),
                },
            )
            .unwrap();
        recorder.flush().unwrap();

        let content = fs::read_to_string(recorder.path()).unwrap();
        let parsed: TelemetryRecord =
            serde_json::from_str(content.lines().next().unwrap()).unwrap();

        match parsed.payload {
            TelemetryPayload::EvaluatorFeedbackSnapshot {
                feedback: saved,
            } => {
                assert_eq!(saved, feedback);
            }
            other => panic!("unexpected payload: {other:?}"),
        }

        let _ = fs::remove_dir_all(root);
    }


    #[test]
    fn recorder_round_trips_perception_health_snapshot() {
        use agente_tft_contracts::Confidence;
        use agente_tft_perception_health::{
            PerceptionHealthMonitor, PerceptionHealthPolicy, PerceptionOutcome,
            PerceptionSample, PerceptionStreamId,
        };

        let root = temp_dir();
        let mut recorder = JsonlRecorder::create(&root, "health-fixture").unwrap();
        let stream = PerceptionStreamId::new("hud", "gold", "fixture").unwrap();
        let mut monitor = PerceptionHealthMonitor::new(PerceptionHealthPolicy {
            min_samples: 1,
            ..PerceptionHealthPolicy::default()
        }).unwrap();
        let snapshot = monitor.observe(PerceptionSample {
            stream,
            observed_at_ms: 100,
            outcome: PerceptionOutcome::Accepted {
                confidence: Confidence::new(0.95).unwrap(),
            },
        }).unwrap();

        recorder.append(
            100,
            TelemetryPayload::PerceptionHealthSnapshot {
                snapshot: snapshot.clone(),
            },
        ).unwrap();
        recorder.flush().unwrap();

        let content = fs::read_to_string(recorder.path()).unwrap();
        let parsed: TelemetryRecord = serde_json::from_str(content.lines().next().unwrap()).unwrap();
        match parsed.payload {
            TelemetryPayload::PerceptionHealthSnapshot { snapshot: saved } => assert_eq!(saved, snapshot),
            other => panic!("unexpected payload: {other:?}"),
        }
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn empty_session_id_is_rejected() {
        let root = temp_dir();
        assert!(matches!(
            JsonlRecorder::create(&root, "   "),
            Err(TelemetryError::EmptySessionId)
        ));
        let _ = fs::remove_dir_all(root);
    }
}
