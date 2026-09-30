use agente_tft_contracts::{DecisionPacket, GameState};
use agente_tft_decision_core::DecisionConfig;
use agente_tft_meta_context::MetaSnapshot;
use agente_tft_opportunity_engine::{
    OpportunityConfig, OpportunityDelta, OpportunityEngine, OpportunityError,
    OpportunityFacts, OpportunityInput, OpportunityReport, OpportunityTier,
    OpportunityTracker,
};
use agente_tft_remote_training_protocol::OpportunitySummary;
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OpportunityRuntimeConfig {
    pub engine: OpportunityConfig,
    pub decision: DecisionConfig,
    pub utility_shift_threshold: f32,
}

impl Default for OpportunityRuntimeConfig {
    fn default() -> Self {
        Self {
            engine: OpportunityConfig::default(),
            decision: DecisionConfig::default(),
            utility_shift_threshold: 0.20,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct OpportunityCycle {
    pub report: OpportunityReport,
    pub delta: OpportunityDelta,
    pub decision: DecisionPacket,
    pub remote_shortlist: Vec<OpportunitySummary>,
    pub should_refresh_ui: bool,
    pub should_remote_evaluate: bool,
}

pub struct OpportunityRuntime {
    engine: OpportunityEngine,
    tracker: OpportunityTracker,
    decision_config: DecisionConfig,
}

impl OpportunityRuntime {
    pub fn new(
        config: OpportunityRuntimeConfig,
    ) -> Result<Self, OpportunityError> {
        Ok(Self {
            engine: OpportunityEngine::new(config.engine)?,
            tracker: OpportunityTracker::new(
                config.utility_shift_threshold,
            )?,
            decision_config: config.decision,
        })
    }

    pub fn evaluate(
        &mut self,
        state: &GameState,
        facts: &OpportunityFacts,
        meta: Option<&MetaSnapshot>,
        now_ms: u64,
    ) -> Result<OpportunityCycle, OpportunityError> {
        let report = self.engine.evaluate(OpportunityInput {
            state,
            facts,
            meta,
            now_ms,
        })?;

        let decision = report.local_decision(self.decision_config);
        let remote_shortlist = report
            .shortlist
            .iter()
            .map(|candidate| OpportunitySummary {
                action: candidate.action.clone(),
                utility: candidate.utility,
                confidence: candidate.confidence,
                tier: tier_name(candidate.tier).to_string(),
                evidence: candidate.evidence.clone(),
            })
            .collect::<Vec<_>>();

        let delta = self.tracker.observe(report.clone())?;
        let material = delta.is_material();

        Ok(OpportunityCycle {
            report,
            delta,
            decision,
            remote_shortlist,
            should_refresh_ui: material,
            should_remote_evaluate: material,
        })
    }

    pub fn reset(&mut self) {
        self.tracker.reset();
    }
}

fn tier_name(tier: OpportunityTier) -> &'static str {
    match tier {
        OpportunityTier::Micro => "micro",
        OpportunityTier::Tactical => "tactical",
        OpportunityTier::Strategic => "strategic",
        OpportunityTier::Information => "information",
    }
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{
        Action, Confidence, MatchPhase, ObservationSource, Observed,
        PlayerState,
    };
    use agente_tft_opportunity_engine::RollOpportunityFact;

    use super::*;

    fn observed<T>(value: T) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(0.95).unwrap(),
            source: ObservationSource::Simulator,
            observed_at_ms: 100,
        }
    }

    fn state() -> GameState {
        let mut state = GameState::empty(100);
        state.revision = 7;
        state.phase = MatchPhase::Planning;
        state.player = PlayerState {
            hp: Some(observed(31)),
            gold: Some(observed(48)),
            level: Some(observed(7)),
            ..PlayerState::default()
        };
        state.overall_confidence = Confidence::new(0.92).unwrap();
        state
    }

    fn facts(probability: f32) -> OpportunityFacts {
        OpportunityFacts {
            rolls: vec![RollOpportunityFact {
                budget_gold: 20,
                stop_condition: Some("X 2-star".into()),
                target_unit_id: Some("X".into()),
                probability_at_least_one: Some(probability),
                expected_target_copies: Some(1.2),
                interest_lost: Some(2),
                contested_copies: Some(6),
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        }
    }

    #[test]
    fn cycle_uses_same_shortlist_for_local_and_remote_paths() {
        let mut runtime =
            OpportunityRuntime::new(OpportunityRuntimeConfig::default()).unwrap();

        let cycle = runtime
            .evaluate(&state(), &facts(0.80), None, 1_000)
            .unwrap();

        assert!(!cycle.remote_shortlist.is_empty());
        assert_eq!(
            cycle.remote_shortlist[0].action,
            cycle.report.shortlist[0].action
        );
        assert_eq!(
            cycle.remote_shortlist[0].utility,
            cycle.report.shortlist[0].utility
        );
        assert_eq!(
            cycle.remote_shortlist[0].confidence,
            cycle.report.shortlist[0].confidence
        );
    }

    #[test]
    fn local_decision_is_generated_from_current_report() {
        let mut runtime =
            OpportunityRuntime::new(OpportunityRuntimeConfig::default()).unwrap();

        let cycle = runtime
            .evaluate(&state(), &facts(0.90), None, 1_000)
            .unwrap();

        assert_eq!(cycle.decision.state_revision, 7);
        assert!(matches!(
            cycle.decision.action,
            Action::Roll {
                budget_gold: 20,
                ..
            }
        ));
    }

    #[test]
    fn unchanged_cycle_does_not_request_repeated_remote_work() {
        let mut runtime =
            OpportunityRuntime::new(OpportunityRuntimeConfig::default()).unwrap();

        let first = runtime
            .evaluate(&state(), &facts(0.80), None, 1_000)
            .unwrap();
        assert!(first.should_remote_evaluate);

        let second = runtime
            .evaluate(&state(), &facts(0.80), None, 1_001)
            .unwrap();
        assert!(!second.should_remote_evaluate);
        assert!(!second.should_refresh_ui);
    }

    #[test]
    fn material_utility_change_requests_new_remote_evaluation() {
        let mut runtime =
            OpportunityRuntime::new(OpportunityRuntimeConfig {
                utility_shift_threshold: 0.05,
                ..OpportunityRuntimeConfig::default()
            })
            .unwrap();

        runtime
            .evaluate(&state(), &facts(0.30), None, 1_000)
            .unwrap();

        let changed = runtime
            .evaluate(&state(), &facts(0.95), None, 1_001)
            .unwrap();

        assert!(changed.should_remote_evaluate);
        assert!(!changed.delta.material_utility_shifts.is_empty());
    }

    #[test]
    fn reset_makes_next_cycle_material_again() {
        let mut runtime =
            OpportunityRuntime::new(OpportunityRuntimeConfig::default()).unwrap();

        runtime
            .evaluate(&state(), &facts(0.80), None, 1_000)
            .unwrap();
        runtime.reset();

        let after_reset = runtime
            .evaluate(&state(), &facts(0.80), None, 1_001)
            .unwrap();

        assert!(after_reset.should_remote_evaluate);
    }
}
