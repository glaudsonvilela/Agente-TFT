use agente_tft_board_strength::BoardStrengthEngine;
use agente_tft_contracts::{DecisionPacket, GameState};
use agente_tft_decision_core::DecisionConfig;
use agente_tft_item_strength::{
    evaluate_item_facts,
    ItemStrengthConfig,
    ItemStrengthEvaluator,
};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_meta_context::MetaSnapshot;
use agente_tft_matchup_positioning::{
    MatchupPositioningConfig,
    MatchupPositioningDiagnostic,
    MatchupPositioningError,
    MatchupPositioningEvaluator,
    OpponentPerspective,
};
use agente_tft_meta_hints::{
    generate_augment_meta_facts,
    generate_comp_transition_candidates,
    generate_item_opportunity_facts,
    generate_pivot_opportunity_facts,
    generate_position_opportunity_facts,
    CompCandidateConfig,
    MetaAugmentOpportunityPolicy,
    MetaItemOpportunityPolicy,
    MetaPivotOpportunityPolicy,
    MetaPositionOpportunityPolicy,
};
use agente_tft_opportunity_fact_builder::{
    FactBuildError, FactBuilderConfig, OpportunityFactBuild,
    OpportunityFactBuilder,
};
use agente_tft_opportunity_engine::{
    OpportunityConfig, OpportunityDelta, OpportunityEngine, OpportunityError,
    OpportunityFacts, OpportunityInput, OpportunityReport, OpportunityTier,
    OpportunityTracker,
};
use agente_tft_positioning_core::{
    BoardCoordinateConvention,
    PositioningError,
};
use agente_tft_pivot_core::{
    evaluate_comp_candidates,
    PivotConfig,
    PivotEvaluator,
};
use agente_tft_remote_training_protocol::OpportunitySummary;
use agente_tft_sell_core::{
    SellDiagnostic,
    SellEvaluator,
};
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
    #[error("positioning error: {0}")]
    Positioning(#[from] PositioningError),
    #[error("matchup positioning error: {0}")]
    MatchupPositioning(#[from] MatchupPositioningError),
}



#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ObservedMatchupRequest<'a> {
    pub opponent_id: &'a str,
    pub perspective: OpponentPerspective,
    pub config: MatchupPositioningConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct MatchupAutomaticOpportunityCycle {
    pub fact_build: OpportunityFactBuild,
    pub cycle: OpportunityCycle,
    pub matchup_opponent_id: String,
    pub matchup_opponent_found: bool,
    pub matchup_positioning: Option<MatchupPositioningDiagnostic>,
}



#[derive(Clone, Copy)]
pub struct CompleteOpportunityRequest<'a> {
    pub positioning: Option<&'a BoardCoordinateConvention>,
    pub matchup: Option<ObservedMatchupRequest<'a>>,
    pub sell_evaluator: Option<&'a SellEvaluator>,
}

impl<'a> Default for CompleteOpportunityRequest<'a> {
    fn default() -> Self {
        Self {
            positioning: None,
            matchup: None,
            sell_evaluator: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CompleteOpportunityCycle {
    pub fact_build: OpportunityFactBuild,
    pub cycle: OpportunityCycle,
    pub sell_diagnostic: Option<SellDiagnostic>,
    pub matchup_opponent_id: Option<String>,
    pub matchup_opponent_found: bool,
    pub matchup_positioning: Option<MatchupPositioningDiagnostic>,
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

        inject_meta_facts(
            state,
            meta,
            now_ms,
            &mut fact_build.facts,
        );

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        dedupe_specialized_facts(&mut fact_build.facts);

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

        inject_meta_facts(
            state,
            meta,
            now_ms,
            &mut fact_build.facts,
        );

        inject_structural_pivot_facts(
            state,
            meta,
            now_ms,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        inject_structural_item_facts(
            state,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        dedupe_specialized_facts(&mut fact_build.facts);

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

    pub fn evaluate_full(
        &mut self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
        positioning: Option<&BoardCoordinateConvention>,
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

        inject_meta_facts(
            state,
            meta,
            now_ms,
            &mut fact_build.facts,
        );

        inject_structural_pivot_facts(
            state,
            meta,
            now_ms,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        if let (Some(snapshot), Some(convention)) = (meta, positioning) {
            fact_build.facts.positions.extend(
                generate_position_opportunity_facts(
                    state,
                    snapshot,
                    convention,
                    MetaPositionOpportunityPolicy::default(),
                )?,
            );
        }

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        inject_structural_item_facts(
            state,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        dedupe_specialized_facts(&mut fact_build.facts);

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

    pub fn evaluate_full_with_matchup(
        &mut self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
        positioning: Option<&BoardCoordinateConvention>,
        matchup: ObservedMatchupRequest<'_>,
        meta: Option<&MetaSnapshot>,
        now_ms: u64,
        extra_facts: Option<&OpportunityFacts>,
    ) -> Result<MatchupAutomaticOpportunityCycle, AutomaticOpportunityError> {
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

        inject_meta_facts(
            state,
            meta,
            now_ms,
            &mut fact_build.facts,
        );

        inject_structural_pivot_facts(
            state,
            meta,
            now_ms,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        if let (Some(snapshot), Some(convention)) = (meta, positioning) {
            fact_build.facts.positions.extend(
                generate_position_opportunity_facts(
                    state,
                    snapshot,
                    convention,
                    MetaPositionOpportunityPolicy::default(),
                )?,
            );
        }

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        inject_structural_item_facts(
            state,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        let opponent = state
            .lobby
            .iter()
            .find(|value| value.player_id == matchup.opponent_id);

        let mut matchup_positioning = None;
        let opponent_found = opponent.is_some();

        if let Some(opponent) = opponent {
            if !fact_build.facts.positions.is_empty() {
                let evaluator = MatchupPositioningEvaluator::new(
                    matchup.config,
                    matchup.perspective,
                )?;

                let refined = evaluator.evaluate_position_facts(
                    &state.player.board,
                    &opponent.board,
                    &fact_build.facts.positions,
                    opponent.confidence,
                );

                fact_build.facts.positions.extend(refined.facts);
                matchup_positioning = Some(refined.diagnostic);
            }
        }

        dedupe_specialized_facts(&mut fact_build.facts);

        let cycle = self.runtime.evaluate(
            state,
            &fact_build.facts,
            meta,
            now_ms,
        )?;

        Ok(MatchupAutomaticOpportunityCycle {
            fact_build,
            cycle,
            matchup_opponent_id: matchup.opponent_id.to_string(),
            matchup_opponent_found: opponent_found,
            matchup_positioning,
        })
    }

    pub fn evaluate_complete(
        &mut self,
        state: &GameState,
        rules: &TftRuleSet,
        catalog: &UnitCatalog,
        traits: &TraitCatalog,
        board_strength: &BoardStrengthEngine,
        request: CompleteOpportunityRequest<'_>,
        meta: Option<&MetaSnapshot>,
        now_ms: u64,
        extra_facts: Option<&OpportunityFacts>,
    ) -> Result<CompleteOpportunityCycle, AutomaticOpportunityError> {
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

        inject_meta_facts(
            state,
            meta,
            now_ms,
            &mut fact_build.facts,
        );

        inject_structural_pivot_facts(
            state,
            meta,
            now_ms,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        if let (Some(snapshot), Some(convention)) =
            (meta, request.positioning)
        {
            fact_build.facts.positions.extend(
                generate_position_opportunity_facts(
                    state,
                    snapshot,
                    convention,
                    MetaPositionOpportunityPolicy::default(),
                )?,
            );
        }

        if let Some(extra) = extra_facts {
            extend_facts(&mut fact_build.facts, extra);
        }

        inject_structural_item_facts(
            state,
            catalog,
            traits,
            board_strength,
            &mut fact_build.facts,
        );

        let sell_diagnostic =
            request.sell_evaluator.map(|evaluator| {
                let evaluation =
                    evaluator.evaluate(state, catalog);
                fact_build
                    .facts
                    .sells
                    .extend(evaluation.facts);
                evaluation.diagnostic
            });

        let mut matchup_opponent_id = None;
        let mut matchup_opponent_found = false;
        let mut matchup_positioning = None;

        if let Some(matchup) = request.matchup {
            matchup_opponent_id =
                Some(matchup.opponent_id.to_string());

            if let Some(opponent) = state
                .lobby
                .iter()
                .find(|value| {
                    value.player_id == matchup.opponent_id
                })
            {
                matchup_opponent_found = true;

                if !fact_build.facts.positions.is_empty() {
                    let evaluator =
                        MatchupPositioningEvaluator::new(
                            matchup.config,
                            matchup.perspective,
                        )?;

                    let refined =
                        evaluator.evaluate_position_facts(
                            &state.player.board,
                            &opponent.board,
                            &fact_build.facts.positions,
                            opponent.confidence,
                        );

                    fact_build
                        .facts
                        .positions
                        .extend(refined.facts);
                    matchup_positioning =
                        Some(refined.diagnostic);
                }
            }
        }

        dedupe_specialized_facts(
            &mut fact_build.facts,
        );

        let cycle = self.runtime.evaluate(
            state,
            &fact_build.facts,
            meta,
            now_ms,
        )?;

        Ok(CompleteOpportunityCycle {
            fact_build,
            cycle,
            sell_diagnostic,
            matchup_opponent_id,
            matchup_opponent_found,
            matchup_positioning,
        })
    }

    pub fn reset(&mut self) {
        self.runtime.reset();
    }
}

fn inject_meta_facts(
    state: &GameState,
    meta: Option<&MetaSnapshot>,
    now_ms: u64,
    facts: &mut OpportunityFacts,
) {
    let Some(snapshot) = meta else {
        return;
    };

    facts.items.extend(
        generate_item_opportunity_facts(
            state,
            snapshot,
            MetaItemOpportunityPolicy::default(),
        ),
    );

    facts.augments.extend(
        generate_augment_meta_facts(
            state,
            snapshot,
            now_ms,
            MetaAugmentOpportunityPolicy::default(),
        ),
    );

    facts.pivots.extend(
        generate_pivot_opportunity_facts(
            state,
            snapshot,
            now_ms,
            CompCandidateConfig::default(),
            MetaPivotOpportunityPolicy::default(),
        ),
    );
}

fn inject_structural_item_facts(
    state: &GameState,
    catalog: &UnitCatalog,
    traits: &TraitCatalog,
    board_strength: &BoardStrengthEngine,
    facts: &mut OpportunityFacts,
) {
    if facts.items.is_empty() {
        return;
    }

    let Ok(evaluator) =
        ItemStrengthEvaluator::new(ItemStrengthConfig::default())
    else {
        return;
    };

    let refined = evaluate_item_facts(
        state,
        &facts.items,
        catalog,
        traits,
        board_strength,
        &evaluator,
    );

    facts.items.extend(
        refined
            .into_iter()
            .filter(|evaluation| evaluation.structural_gain > 0.0)
            .map(|evaluation| evaluation.fact),
    );
}

fn inject_structural_pivot_facts(
    state: &GameState,
    meta: Option<&MetaSnapshot>,
    now_ms: u64,
    catalog: &UnitCatalog,
    traits: &TraitCatalog,
    board_strength: &BoardStrengthEngine,
    facts: &mut OpportunityFacts,
) {
    let Some(snapshot) = meta else {
        return;
    };

    let candidates = generate_comp_transition_candidates(
        state,
        snapshot,
        now_ms,
        CompCandidateConfig::default(),
    );

    if candidates.is_empty() {
        return;
    }

    let Ok(evaluator) = PivotEvaluator::new(PivotConfig::default()) else {
        return;
    };

    facts.pivots.extend(
        evaluate_comp_candidates(
            state,
            &candidates,
            catalog,
            traits,
            board_strength,
            &evaluator,
        )
        .into_iter()
        .map(|evaluation| evaluation.fact),
    );
}

fn dedupe_specialized_facts(facts: &mut OpportunityFacts) {
    dedupe_sell_facts(&mut facts.sells);
    dedupe_item_facts(&mut facts.items);
    dedupe_pivot_facts(&mut facts.pivots);
    dedupe_position_facts(&mut facts.positions);
    dedupe_augment_facts(&mut facts.augments);
}

fn dedupe_sell_facts(
    values: &mut Vec<agente_tft_opportunity_engine::SellOpportunityFact>,
) {
    use std::collections::BTreeMap;

    let mut by_key: BTreeMap<
        String,
        agente_tft_opportunity_engine::SellOpportunityFact,
    > = BTreeMap::new();

    for fact in values.drain(..) {
        let key = fact.unit_instance_id.clone();

        match by_key.remove(&key) {
            None => {
                by_key.insert(key, fact);
            }
            Some(existing) => {
                let chosen =
                    if fact.confidence.value() > existing.confidence.value()
                        || (
                            (fact.confidence.value()
                                - existing.confidence.value())
                                .abs()
                                <= f32::EPSILON
                            && (
                                fact.board_strength_loss
                                    < existing.board_strength_loss
                                || (
                                    (fact.board_strength_loss
                                        - existing.board_strength_loss)
                                        .abs()
                                        <= f32::EPSILON
                                    && fact.economy_value
                                        > existing.economy_value
                                )
                            )
                        )
                    {
                        fact
                    } else {
                        existing
                    };

                by_key.insert(key, chosen);
            }
        }
    }

    *values = by_key.into_values().collect();
}

fn dedupe_item_facts(
    values: &mut Vec<agente_tft_opportunity_engine::ItemOpportunityFact>,
) {
    use std::collections::BTreeMap;

    let mut by_key: BTreeMap<
        (String, String),
        agente_tft_opportunity_engine::ItemOpportunityFact,
    > = BTreeMap::new();

    for fact in values.drain(..) {
        let key = (
            fact.unit_instance_id.clone(),
            fact.item_id.clone(),
        );

        match by_key.remove(&key) {
            None => {
                by_key.insert(key, fact);
            }
            Some(existing) => {
                let preserved_prior =
                    if fact.external_meta_prior.abs()
                        >= existing.external_meta_prior.abs()
                    {
                        fact.external_meta_prior
                    } else {
                        existing.external_meta_prior
                    };

                let mut chosen =
                    if fact.confidence.value() > existing.confidence.value()
                        || fact.strength_gain > existing.strength_gain
                    {
                        fact
                    } else {
                        existing
                    };

                chosen.external_meta_prior = preserved_prior;
                by_key.insert(key, chosen);
            }
        }
    }

    *values = by_key.into_values().collect();
}

fn dedupe_pivot_facts(
    values: &mut Vec<agente_tft_opportunity_engine::PivotOpportunityFact>,
) {
    use std::collections::BTreeMap;

    let mut by_key: BTreeMap<
        String,
        agente_tft_opportunity_engine::PivotOpportunityFact,
    > = BTreeMap::new();

    for fact in values.drain(..) {
        let key = fact
            .meta_comp_id
            .clone()
            .unwrap_or_else(|| fact.target.clone());

        match by_key.remove(&key) {
            None => {
                by_key.insert(key, fact);
            }
            Some(existing) => {
                let chosen =
                    if fact.confidence.value() > existing.confidence.value()
                        || fact.immediate_gain > existing.immediate_gain
                    {
                        fact
                    } else {
                        existing
                    };
                by_key.insert(key, chosen);
            }
        }
    }

    *values = by_key.into_values().collect();
}

fn dedupe_augment_facts(
    values: &mut Vec<agente_tft_opportunity_engine::AugmentOpportunityFact>,
) {
    use std::collections::BTreeMap;

    let mut by_key: BTreeMap<
        String,
        agente_tft_opportunity_engine::AugmentOpportunityFact,
    > = BTreeMap::new();

    for fact in values.drain(..) {
        let key = fact.augment_id.clone();

        match by_key.remove(&key) {
            None => {
                by_key.insert(key, fact);
            }
            Some(existing) => {
                let preserved_prior =
                    if fact.external_meta_prior.abs()
                        >= existing.external_meta_prior.abs()
                    {
                        fact.external_meta_prior
                    } else {
                        existing.external_meta_prior
                    };

                let mut chosen =
                    if fact.confidence.value() > existing.confidence.value()
                        || fact.board_gain > existing.board_gain
                        || fact.flexibility > existing.flexibility
                    {
                        fact
                    } else {
                        existing
                    };

                chosen.external_meta_prior = preserved_prior;
                by_key.insert(key, chosen);
            }
        }
    }

    *values = by_key.into_values().collect();
}

fn dedupe_position_facts(
    values: &mut Vec<agente_tft_opportunity_engine::PositionOpportunityFact>,
) {
    use std::collections::BTreeMap;

    let mut by_key: BTreeMap<
        String,
        agente_tft_opportunity_engine::PositionOpportunityFact,
    > = BTreeMap::new();

    for fact in values.drain(..) {
        let key = serde_json::to_string(&fact.moves)
            .unwrap_or_else(|_| format!("{:?}", fact.moves));

        match by_key.remove(&key) {
            None => {
                by_key.insert(key, fact);
            }
            Some(existing) => {
                let chosen =
                    if fact.confidence.value() > existing.confidence.value()
                        || fact.matchup_gain > existing.matchup_gain
                    {
                        fact
                    } else {
                        existing
                    };
                by_key.insert(key, chosen);
            }
        }
    }

    *values = by_key.into_values().collect();
}

fn extend_facts(
    destination: &mut OpportunityFacts,
    extra: &OpportunityFacts,
) {
    destination.sells.extend(extra.sells.iter().cloned());
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

    fn meta_snapshot() -> MetaSnapshot {
        use std::collections::BTreeMap;
        use agente_tft_meta_context::{
            MetaEntity, MetaEntityKind, MetaPerformance,
        };

        let mut attributes = BTreeMap::new();
        attributes.insert(
            "recommended_item_ids".into(),
            serde_json::json!(["ITEM_META"]),
        );
        attributes.insert(
            "positioning".into(),
            serde_json::json!("in the front row"),
        );

        MetaSnapshot {
            schema_version: 1,
            source: "metatft_public".into(),
            source_url: "https://www.metatft.com/comps".into(),
            captured_at_ms: 9_000,
            patch: Some("18.3b".into()),
            set: Some("TFTSet18".into()),
            queue: Some("ranked".into()),
            rank_filter: Some("platinum_plus".into()),
            window: Some("last_3_days".into()),
            entities: vec![
                MetaEntity {
                    kind: MetaEntityKind::Unit,
                    id: "A".into(),
                    name: "Alpha".into(),
                    unit_ids: vec![],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(4.0),
                        top4_rate: Some(0.55),
                        win_rate: Some(0.14),
                        frequency: Some(0.10),
                        sample_size: Some(10_000),
                    },
                    tags: vec![],
                    attributes,
                },
                MetaEntity {
                    kind: MetaEntityKind::Comp,
                    id: "comp-abcd".into(),
                    name: "ABCD".into(),
                    unit_ids: vec![
                        "A".into(),
                        "B".into(),
                        "C".into(),
                        "D".into(),
                    ],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(3.9),
                        top4_rate: Some(0.58),
                        win_rate: Some(0.16),
                        frequency: Some(0.08),
                        sample_size: Some(20_000),
                    },
                    tags: vec![],
                    attributes: BTreeMap::new(),
                },
            ],
            metadata: BTreeMap::new(),
        }
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
                external_meta_prior: 0.0,
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
    fn runtime_auto_injects_meta_item_and_pivot_candidates() {
        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let mut state = automatic_state();
        state.player.items = vec!["ITEM_META".into()];

        let result = runtime
            .evaluate(
                &state,
                &rules(),
                &catalog(),
                Some(&meta_snapshot()),
                10_000,
                None,
            )
            .unwrap();

        assert!(result
            .fact_build
            .facts
            .items
            .iter()
            .any(|fact| fact.item_id == "ITEM_META"));

        assert!(result
            .fact_build
            .facts
            .pivots
            .iter()
            .any(|fact| fact.meta_comp_id.as_deref() == Some("comp-abcd")));
    }

    #[test]
    fn local_item_fact_overrides_meta_only_duplicate_but_keeps_prior() {
        use agente_tft_opportunity_engine::ItemOpportunityFact;

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let mut state = automatic_state();
        state.player.items = vec!["ITEM_META".into()];

        let extra = OpportunityFacts {
            items: vec![ItemOpportunityFact {
                item_id: "ITEM_META".into(),
                unit_instance_id: "A-2".into(),
                strength_gain: 0.70,
                flexibility_cost: 0.10,
                external_meta_prior: 0.0,
                confidence: Confidence::new(0.90).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let result = runtime
            .evaluate(
                &state,
                &rules(),
                &catalog(),
                Some(&meta_snapshot()),
                10_000,
                Some(&extra),
            )
            .unwrap();

        let fact = result
            .fact_build
            .facts
            .items
            .iter()
            .find(|fact| {
                fact.item_id == "ITEM_META"
                    && fact.unit_instance_id == "A-2"
            })
            .unwrap();

        assert_eq!(fact.strength_gain, 0.70);
        assert_eq!(fact.confidence.value(), 0.90);
        assert!(fact.external_meta_prior > 0.0);
    }

    #[test]
    fn full_runtime_prefers_structural_pivot_over_meta_only() {
        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
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
                Some(&meta_snapshot()),
                10_000,
                None,
            )
            .unwrap();

        let pivot = result
            .fact_build
            .facts
            .pivots
            .iter()
            .find(|fact| {
                fact.meta_comp_id.as_deref() == Some("comp-abcd")
            })
            .unwrap();

        // Meta-only candidate is capped at 0.45. Structural evaluation is
        // preferred by dedupe when its board model has better confidence.
        assert!(pivot.confidence.value() >= 0.45);
    }

    #[test]
    fn full_runtime_turns_meta_position_hint_into_valid_move() {
        use agente_tft_contracts::HexPosition;

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let strength = BoardStrengthEngine::new(
            agente_tft_board_strength::BoardStrengthConfig::default(),
        )
        .unwrap();

        let convention = BoardCoordinateConvention {
            rows: 4,
            cols: 7,
            front_rows: vec![0],
            back_rows: vec![3],
            left_cols: vec![0, 1],
            right_cols: vec![5, 6],
            center_cols: vec![3],
        };

        let mut state = automatic_state();
        state.player.board[0].position =
            Some(HexPosition { row: 3, col: 3 });

        let result = runtime
            .evaluate_full(
                &state,
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                Some(&convention),
                Some(&meta_snapshot()),
                10_000,
                None,
            )
            .unwrap();

        let position = result
            .fact_build
            .facts
            .positions
            .first()
            .unwrap();

        assert_eq!(position.moves[0].to.row, 0);
        assert_eq!(position.moves[0].to.col, 3);
        assert_eq!(position.matchup_gain, 0.0);
        assert!(position.confidence.value() <= 0.45);
    }

    #[test]
    fn full_matchup_runtime_refines_meta_positioning() {
        use agente_tft_contracts::{
            HexPosition, OpponentState,
        };
        use agente_tft_board_strength::{
            BoardStrengthConfig,
        };

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let convention = BoardCoordinateConvention {
            rows: 4,
            cols: 7,
            front_rows: vec![0],
            back_rows: vec![3],
            left_cols: vec![0, 1],
            right_cols: vec![5, 6],
            center_cols: vec![3],
        };

        let mut state = automatic_state();
        state.player.board[0].position =
            Some(HexPosition { row: 3, col: 0 });

        state.lobby = vec![OpponentState {
            player_id: "p2".into(),
            display_name: Some("P2".into()),
            hp: None,
            level: None,
            board: vec![
                agente_tft_contracts::UnitInstance {
                    instance_id: "enemy-a".into(),
                    unit_id: "C".into(),
                    stars: 2,
                    position: Some(HexPosition { row: 3, col: 0 }),
                    items: vec!["I1".into(), "I2".into()],
                },
                agente_tft_contracts::UnitInstance {
                    instance_id: "enemy-b".into(),
                    unit_id: "D".into(),
                    stars: 2,
                    position: Some(HexPosition { row: 2, col: 1 }),
                    items: vec!["I1".into()],
                },
            ],
            last_seen_ms: 9_900,
            confidence: Confidence::new(0.90).unwrap(),
        }];

        // Provide an explicit position proposal to the far side so this test
        // doesn't depend on external meta text orientation.
        let extra = OpportunityFacts {
            positions: vec![
                agente_tft_opportunity_engine::PositionOpportunityFact {
                    moves: vec![
                        agente_tft_contracts::PositionMove {
                            unit_instance_id:
                                state.player.board[0].instance_id.clone(),
                            to: HexPosition { row: 3, col: 6 },
                        },
                    ],
                    matchup_gain: 0.0,
                    confidence: Confidence::new(0.40).unwrap(),
                },
            ],
            ..OpportunityFacts::default()
        };

        let result = runtime
            .evaluate_full_with_matchup(
                &state,
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                Some(&convention),
                ObservedMatchupRequest {
                    opponent_id: "p2",
                    perspective: OpponentPerspective {
                        rows: 4,
                        cols: 7,
                        mirror_rows: false,
                        mirror_cols: false,
                    },
                    config: MatchupPositioningConfig {
                        min_gain: 0.01,
                        min_observed_opponent_units: 2,
                        ..MatchupPositioningConfig::default()
                    },
                },
                None,
                10_000,
                Some(&extra),
            )
            .unwrap();

        assert!(result.matchup_opponent_found);
        assert!(result.matchup_positioning.is_some());
        assert!(result
            .fact_build
            .facts
            .positions
            .iter()
            .any(|fact| fact.matchup_gain > 0.0));
    }

    #[test]
    fn unknown_matchup_opponent_does_not_invent_position_gain() {
        use agente_tft_board_strength::BoardStrengthConfig;

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let result = runtime
            .evaluate_full_with_matchup(
                &automatic_state(),
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                None,
                ObservedMatchupRequest {
                    opponent_id: "missing",
                    perspective: OpponentPerspective {
                        rows: 4,
                        cols: 7,
                        mirror_rows: false,
                        mirror_cols: false,
                    },
                    config: MatchupPositioningConfig::default(),
                },
                None,
                10_000,
                None,
            )
            .unwrap();

        assert!(!result.matchup_opponent_found);
        assert!(result.matchup_positioning.is_none());
    }

    #[test]
    fn board_strength_runtime_refines_item_gain() {
        use agente_tft_board_strength::BoardStrengthConfig;
        use agente_tft_opportunity_engine::ItemOpportunityFact;

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let mut state = automatic_state();
        state.player.items = vec!["ITEM_1".into()];
        state.player.board[0].items.clear();

        let extra = OpportunityFacts {
            items: vec![ItemOpportunityFact {
                item_id: "ITEM_1".into(),
                unit_instance_id: state.player.board[0].instance_id.clone(),
                strength_gain: 0.0,
                flexibility_cost: 0.0,
                external_meta_prior: 0.08,
                confidence: Confidence::new(0.45).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let result = runtime
            .evaluate_with_board_strength(
                &state,
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                None,
                10_000,
                Some(&extra),
            )
            .unwrap();

        let item = result
            .fact_build
            .facts
            .items
            .iter()
            .find(|fact| fact.item_id == "ITEM_1")
            .unwrap();

        assert!(item.strength_gain > 0.0);
        assert_eq!(item.external_meta_prior, 0.08);
        assert!(item.confidence.value() <= 0.35);
    }

    #[test]
    fn augment_meta_prior_merges_with_base_offer() {
        use agente_tft_meta_context::{
            MetaEntity, MetaEntityKind, MetaPerformance,
        };
        use std::collections::BTreeMap;

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig::default(),
        )
        .unwrap();

        let mut state = automatic_state();
        state.phase = MatchPhase::AugmentSelection;
        state.patch = Some("18.3b".into());
        state.set = Some("TFTSet18".into());
        state.player.augment_options = vec![
            Observed {
                value: "AUG_A".into(),
                confidence: Confidence::new(0.95).unwrap(),
                source: ObservationSource::Simulator,
                observed_at_ms: 100,
            },
        ];

        let mut snapshot = meta_snapshot();
        snapshot.patch = Some("18.3b".into());
        snapshot.set = Some("TFTSet18".into());
        snapshot.captured_at_ms = 9_900;
        snapshot.entities.push(MetaEntity {
            kind: MetaEntityKind::Augment,
            id: "AUG_A".into(),
            name: "Aug A".into(),
            unit_ids: vec![],
            trait_ids: vec![],
            performance: MetaPerformance {
                avg_place: Some(3.7),
                top4_rate: Some(0.61),
                win_rate: Some(0.17),
                frequency: Some(0.08),
                sample_size: Some(10_000),
            },
            tags: vec![],
            attributes: BTreeMap::new(),
        });

        let result = runtime
            .evaluate(
                &state,
                &rules(),
                &catalog(),
                Some(&snapshot),
                10_000,
                None,
            )
            .unwrap();

        assert_eq!(result.fact_build.facts.augments.len(), 1);
        let augment = &result.fact_build.facts.augments[0];
        assert_eq!(augment.augment_id, "AUG_A");
        assert!(augment.external_meta_prior > 0.0);
        assert_eq!(augment.board_gain, 0.0);
        assert!(augment.confidence.value() <= 0.45);
    }

    #[test]
    fn complete_runtime_includes_conservative_sell_facts() {
        use agente_tft_board_strength::BoardStrengthConfig;
        use agente_tft_sell_core::{
            SellConfig,
            SellEvaluator,
            SellValueRule,
        };

        let mut runtime = AutomaticOpportunityRuntime::new(
            OpportunityRuntimeConfig::default(),
            FactBuilderConfig {
                roll_budgets_gold: vec![10, 20],
                include_max_affordable_budget: false,
                ..FactBuilderConfig::default()
            },
        )
        .unwrap();

        let strength =
            BoardStrengthEngine::new(BoardStrengthConfig::default()).unwrap();

        let sell = SellEvaluator::new(SellConfig {
            bench_capacity: 1,
            economy_scale_gold: 10,
            min_bench_occupancy_ratio: 1.0,
            confidence_cap: 0.70,
            preserve_upgrade_material: false,
            skip_itemized_bench_units: true,
            sell_values: vec![SellValueRule {
                cost: 4,
                stars: 1,
                gold: 4,
            }],
        })
        .unwrap();

        let result = runtime
            .evaluate_complete(
                &automatic_state(),
                &rules(),
                &catalog(),
                &trait_catalog(),
                &strength,
                CompleteOpportunityRequest {
                    positioning: None,
                    matchup: None,
                    sell_evaluator: Some(&sell),
                },
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
        assert_eq!(result.fact_build.facts.sells.len(), 1);
        assert!(result.sell_diagnostic.is_some());

        assert!(result.cycle.report.all.iter().any(|candidate| {
            matches!(candidate.action, Action::Sell { .. })
        }));
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
