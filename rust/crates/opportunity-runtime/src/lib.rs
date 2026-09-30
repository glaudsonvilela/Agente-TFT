use agente_tft_board_strength::BoardStrengthEngine;
use agente_tft_contracts::{DecisionPacket, GameState};
use agente_tft_decision_core::DecisionConfig;
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_meta_context::MetaSnapshot;
use agente_tft_opportunity_fact_builder::{
    FactBuildError, FactBuilderConfig, OpportunityFactBuild,
    OpportunityFactBuilder,
};
use agente_tft_opportunity_engine::{
    OpportunityConfig, OpportunityDelta, OpportunityEngine, OpportunityError,
    OpportunityFacts, OpportunityInput, OpportunityReport, OpportunityTier,
    OpportunityTracker,
};
use agente_tft_remote_training_protocol::OpportunitySummary;
use agente_tft_tft_rules::TftRuleSet;
use agente_tft_trait_core::TraitCatalog;
use serde::{Deserialize, Serialize};
use thiserror::Error;

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

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
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

    pub fn evaluate_with_board_strength(
        &mut self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
        meta: Option<&MetaSnapshot>,
        now_ms: u64,
        extra_facts: Option<&OpportunityFacts>,
    ) -> Result<AutomaticOpportunityCycle, AutomaticOpportunityError> {
        let mut fact_build = self
            .fact_builder
            .build_with_board_strength(
                state,
                rules,
                catalog,
                traits,
                board_strength,
                now_ms,
            )?;

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        let cycle = self.runtime.evaluate(
            state,
            &fact_build.facts,
            meta,
            now_ms,
        )?;

        Ok(AutomaticOpportunityCycle {
            fact_build,
            cycle,
        })
    }

    pub fn reset(&mut self) {
        self.tracker.reset();
    }
}


#[derive(Debug, Error)]
pub enum AutomaticOpportunityError {
    #[error("fact builder error: {0}")]
    Facts(#[from] FactBuildError),
    #[error("opportunity engine error: {0}")]
    Opportunity(#[from] OpportunityError),
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AutomaticOpportunityCycle {
    pub fact_build: OpportunityFactBuild,
    pub cycle: OpportunityCycle,
}

pub struct AutomaticOpportunityRuntime {
    fact_builder: OpportunityFactBuilder,
    runtime: OpportunityRuntime,
}

impl AutomaticOpportunityRuntime {
    pub fn new(
        runtime_config: OpportunityRuntimeConfig,
        fact_builder_config: FactBuilderConfig,
    ) -> Result<Self, AutomaticOpportunityError> {
        Ok(Self {
            fact_builder: OpportunityFactBuilder::new(
                fact_builder_config,
            )?,
            runtime: OpportunityRuntime::new(runtime_config)?,
        })
    }

    pub fn evaluate(
        &mut self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        meta: Option<&MetaSnapshot>,
        now_ms: u64,
        extra_facts: Option<&OpportunityFacts>,
    ) -> Result<AutomaticOpportunityCycle, AutomaticOpportunityError> {
        let mut fact_build = self
            .fact_builder
            .build(state, rules, catalog, now_ms)?;

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        let cycle = self.runtime.evaluate(
            state,
            &fact_build.facts,
            meta,
            now_ms,
        )?;

        Ok(AutomaticOpportunityCycle {
            fact_build,
            cycle,
        })
    }

    pub fn reset(&mut self) {
        self.runtime.reset();
    }
}

fn extend_facts(
    destination: &mut OpportunityFacts,
    extra: &OpportunityFacts,
) {
    destination.rolls.extend(extra.rolls.iter().cloned());
    destination.buys.extend(extra.buys.iter().cloned());
    destination.levels.extend(extra.levels.iter().cloned());
    destination.items.extend(extra.items.iter().cloned());
    destination.positions.extend(extra.positions.iter().cloned());
    destination.pivots.extend(extra.pivots.iter().cloned());
    destination.scouts.extend(extra.scouts.iter().cloned());
    destination.augments.extend(extra.augments.iter().cloned());
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

    fn catalog() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "set": {
                    "key": "TFTSet18",
                    "number": 18,
                    "name": "Set 18"
                },
                "champions": [
                    {"api_name": "A", "name": "Alpha", "cost": 4, "traits": []},
                    {"api_name": "B", "name": "Beta", "cost": 4, "traits": []},
                    {"api_name": "C", "name": "Gamma", "cost": 4, "traits": []},
                    {"api_name": "D", "name": "Delta", "cost": 4, "traits": []}
                ]
            })
            .to_string(),
        )
        .unwrap()
    }

    fn trait_catalog() -> TraitCatalog {
        TraitCatalog::from_json_str(
            &serde_json::json!({
                "traits": [
                    {
                        "api_name": "T_DUMMY",
                        "name": "Dummy",
                        "effects": [
                            {"min_units": 2}
                        ]
                    }
                ]
            })
            .to_string(),
        )
        .unwrap()
    }

    fn rules() -> TftRuleSet {
        use std::collections::BTreeMap;
        use agente_tft_tft_math::EconomyRules;
        use agente_tft_tft_rules::{
            ShopOdds, RULESET_SCHEMA_VERSION,
        };

        TftRuleSet {
            schema_version: RULESET_SCHEMA_VERSION,
            patch: "18.3b".into(),
            set: "TFTSet18".into(),
            shop_slots: 5,
            roll_cost_gold: 2,
            economy: EconomyRules::default(),
            shop_odds_by_level: BTreeMap::from([(
                7,
                ShopOdds {
                    by_cost: [0.19, 0.30, 0.40, 0.10, 0.01],
                },
            )]),
            unit_pool_copies_by_cost: BTreeMap::from([
                (1, 30),
                (2, 25),
                (3, 18),
                (4, 10),
                (5, 9),
            ]),
            xp_purchase_cost_gold: 4,
            xp_per_purchase: 4,
            xp_required_to_next_level: BTreeMap::from([
                (7, 36),
                (8, 68),
            ]),
            source: Some("fixture".into()),
            source_hash: None,
        }
    }

    fn automatic_state() -> GameState {
        use agente_tft_contracts::{
            ShopSlot, UnitInstance,
        };

        let mut state = state();
        state.patch = Some("18.3b".into());
        state.set = Some("TFTSet18".into());
        state.player.xp = Some(observed(20u16));
        state.player.board = vec![
            UnitInstance {
                instance_id: "A-2".into(),
                unit_id: "A".into(),
                stars: 2,
                position: None,
                items: vec![],
            },
            UnitInstance {
                instance_id: "B-1".into(),
                unit_id: "B".into(),
                stars: 1,
                position: None,
                items: vec![],
            },
        ];
        state.player.bench = vec![
            UnitInstance {
                instance_id: "B-1b".into(),
                unit_id: "B".into(),
                stars: 1,
                position: None,
                items: vec![],
            },
        ];
        state.player.shop = vec![
            Observed {
                value: ShopSlot {
                    slot: 0,
                    unit_id: Some("B".into()),
                },
                confidence: Confidence::new(0.95).unwrap(),
                source: ObservationSource::Simulator,
                observed_at_ms: 100,
            },
        ];
        state
    }

    #[test]
    fn automatic_runtime_builds_buy_roll_level_and_scout() {
        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig {
                roll_budgets_gold: vec![10, 20],
                include_max_affordable_budget: false,
                ..FactBuilderConfig::default()
            },
        )
        .unwrap();

        let result = runtime
            .evaluate(
                &automatic_state(),
                &rules(),
                &catalog(),
                None,
                10_000,
                None,
            )
            .unwrap();

        assert!(!result.fact_build.facts.buys.is_empty());
        assert!(!result.fact_build.facts.rolls.is_empty());
        assert!(result
            .fact_build
            .facts
            .levels
            .iter()
            .any(|fact| fact.target_level == 8));
        assert!(!result.cycle.report.all.is_empty());
    }

    #[test]
    fn automatic_runtime_merges_specialized_facts() {
        use agente_tft_opportunity_engine::ItemOpportunityFact;

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let extra = OpportunityFacts {
            items: vec![ItemOpportunityFact {
                item_id: "ITEM_1".into(),
                unit_instance_id: "A-2".into(),
                strength_gain: 0.7,
                flexibility_cost: 0.1,
                confidence: Confidence::new(0.90).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let result = runtime
            .evaluate(
                &automatic_state(),
                &rules(),
                &catalog(),
                None,
                10_000,
                Some(&extra),
            )
            .unwrap();

        assert!(result
            .fact_build
            .facts
            .items
            .iter()
            .any(|fact| fact.item_id == "ITEM_1"));
    }

    #[test]
    fn full_automatic_runtime_enriches_level_with_board_strength() {
        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig {
                roll_budgets_gold: vec![10, 20],
                include_max_affordable_budget: false,
                ..FactBuilderConfig::default()
            },
        )
        .unwrap();

        let strength = BoardStrengthEngine::new(
            agente_tft_board_strength::BoardStrengthConfig::default(),
        )
        .unwrap();

        let result = runtime
            .evaluate_with_board_strength(
                &automatic_state(),
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                None,
                10_000,
                None,
            )
            .unwrap();

        let level8 = result
            .fact_build
            .facts
            .levels
            .iter()
            .find(|fact| fact.target_level == 8)
            .unwrap();

        assert!(level8.expected_board_gain.is_some());
        assert!(level8.confidence.value() <= 0.55);
        assert!(result
            .fact_build
            .diagnostics
            .level_board_plans
            .iter()
            .any(|plan| plan.target_level == 8));
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
