use agente_tft_contracts::{
    Action, Confidence, DecisionPacket, Evidence, GameState, MatchPhase, PositionMove,
};
use agente_tft_decision_core::{select_decision, CandidateDecision, DecisionConfig};
use agente_tft_meta_context::{
    entity_meta_prior, unit_meta_prior, MetaEntityKind, MetaPriorPolicy, MetaSnapshot,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum OpportunityError {
    #[error("opportunity metric must be finite")]
    NonFiniteMetric,
    #[error("opportunity metric must be in [-1,1]")]
    MetricOutOfRange,
    #[error("confidence must be valid")]
    InvalidConfidence,
    #[error("shortlist size must be greater than zero")]
    InvalidShortlist,
    #[error("meta context error: {0}")]
    Meta(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OpportunityTier {
    Micro,
    Tactical,
    Strategic,
    Information,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, Default)]
pub struct OpportunityVector {
    pub immediate_board_gain: f32,
    pub upgrade_value: f32,
    pub hp_preservation: f32,
    pub economy_value: f32,
    pub contest_urgency: f32,
    pub flexibility: f32,
    pub information_value: f32,
    /// Already bounded by MetaPriorPolicy. It is deliberately small.
    pub external_meta_prior: f32,
    /// Positive value means more uncertainty/risk and is subtracted from utility.
    pub uncertainty: f32,
}

impl OpportunityVector {
    pub fn validate(&self) -> Result<(), OpportunityError> {
        for value in [
            self.immediate_board_gain,
            self.upgrade_value,
            self.hp_preservation,
            self.economy_value,
            self.contest_urgency,
            self.flexibility,
            self.information_value,
            self.external_meta_prior,
            self.uncertainty,
        ] {
            if !value.is_finite() {
                return Err(OpportunityError::NonFiniteMetric);
            }
            if !(-1.0..=1.0).contains(&value) {
                return Err(OpportunityError::MetricOutOfRange);
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct OpportunityWeights {
    pub immediate_board_gain: f32,
    pub upgrade_value: f32,
    pub hp_preservation: f32,
    pub economy_value: f32,
    pub contest_urgency: f32,
    pub flexibility: f32,
    pub information_value: f32,
    pub external_meta_prior: f32,
    pub uncertainty_penalty: f32,
}

impl Default for OpportunityWeights {
    fn default() -> Self {
        // Heuristic baseline only. These weights are intentionally explicit
        // and versioned in configuration; they are not claimed to be learned.
        Self {
            immediate_board_gain: 1.20,
            upgrade_value: 1.00,
            hp_preservation: 0.90,
            economy_value: 0.80,
            contest_urgency: 0.70,
            flexibility: 0.50,
            information_value: 0.40,
            external_meta_prior: 1.00,
            uncertainty_penalty: 0.80,
        }
    }
}

impl OpportunityWeights {
    pub fn score(&self, vector: OpportunityVector) -> Result<f32, OpportunityError> {
        vector.validate()?;
        let values = [
            self.immediate_board_gain,
            self.upgrade_value,
            self.hp_preservation,
            self.economy_value,
            self.contest_urgency,
            self.flexibility,
            self.information_value,
            self.external_meta_prior,
            self.uncertainty_penalty,
        ];
        if values.iter().any(|value| !value.is_finite()) {
            return Err(OpportunityError::NonFiniteMetric);
        }

        Ok(
            vector.immediate_board_gain * self.immediate_board_gain
                + vector.upgrade_value * self.upgrade_value
                + vector.hp_preservation * self.hp_preservation
                + vector.economy_value * self.economy_value
                + vector.contest_urgency * self.contest_urgency
                + vector.flexibility * self.flexibility
                + vector.information_value * self.information_value
                + vector.external_meta_prior * self.external_meta_prior
                - vector.uncertainty * self.uncertainty_penalty,
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RollOpportunityFact {
    pub budget_gold: u16,
    pub stop_condition: Option<String>,
    pub target_unit_id: Option<String>,
    pub probability_at_least_one: Option<f32>,
    pub expected_target_copies: Option<f32>,
    pub interest_lost: Option<u16>,
    pub contested_copies: Option<u16>,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BuyOpportunityFact {
    pub shop_slot: u8,
    pub unit_id: String,
    pub gold_cost: u16,
    pub closes_upgrade: bool,
    pub contested_copies: Option<u16>,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LevelOpportunityFact {
    pub target_level: u8,
    pub gold_cost: u16,
    /// Deterministic/learned estimate from another module, already normalized [0,1].
    pub expected_board_gain: Option<f32>,
    pub slots_gained: u8,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemOpportunityFact {
    pub item_id: String,
    pub unit_instance_id: String,
    pub strength_gain: f32,
    pub flexibility_cost: f32,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PositionOpportunityFact {
    pub moves: Vec<PositionMove>,
    pub matchup_gain: f32,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PivotOpportunityFact {
    pub target: String,
    pub immediate_gain: f32,
    pub transition_cost: f32,
    pub flexibility_after: f32,
    pub meta_comp_id: Option<String>,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScoutOpportunityFact {
    pub player_id: String,
    pub uncertainty_reduction: f32,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AugmentOpportunityFact {
    pub augment_id: String,
    pub board_gain: f32,
    pub flexibility: f32,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct OpportunityFacts {
    pub rolls: Vec<RollOpportunityFact>,
    pub buys: Vec<BuyOpportunityFact>,
    pub levels: Vec<LevelOpportunityFact>,
    pub items: Vec<ItemOpportunityFact>,
    pub positions: Vec<PositionOpportunityFact>,
    pub pivots: Vec<PivotOpportunityFact>,
    pub scouts: Vec<ScoutOpportunityFact>,
    pub augments: Vec<AugmentOpportunityFact>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OpportunityCandidate {
    pub action: Action,
    pub tier: OpportunityTier,
    /// Utility is a ranking score, not a probability.
    pub utility: f32,
    pub confidence: Confidence,
    pub vector: OpportunityVector,
    pub evidence: Vec<Evidence>,
}

impl OpportunityCandidate {
    pub fn to_decision_candidate(&self) -> CandidateDecision {
        CandidateDecision {
            action: self.action.clone(),
            utility: self.utility,
            confidence: self.confidence,
            evidence: self.evidence.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OpportunityReport {
    pub state_revision: u64,
    pub evaluated_at_ms: u64,
    /// Every currently valid opportunity evaluated from supplied facts.
    pub all: Vec<OpportunityCandidate>,
    /// Ranked subset for deeper policy/Shadow/Swarm evaluation.
    pub shortlist: Vec<OpportunityCandidate>,
}


impl OpportunityReport {
    pub fn shortlist_decision_candidates(&self) -> Vec<CandidateDecision> {
        self.shortlist
            .iter()
            .map(OpportunityCandidate::to_decision_candidate)
            .collect()
    }

    pub fn all_decision_candidates(&self) -> Vec<CandidateDecision> {
        self.all
            .iter()
            .map(OpportunityCandidate::to_decision_candidate)
            .collect()
    }

    /// Produce the immediate local decision from the shortlist.
    ///
    /// Shadow/Swarm may refine the decision later, but the local response never
    /// waits for the network.
    pub fn local_decision(&self, config: DecisionConfig) -> DecisionPacket {
        select_decision(
            self.state_revision,
            self.shortlist_decision_candidates(),
            config,
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct OpportunityConfig {
    pub weights: OpportunityWeights,
    pub shortlist_size: usize,
    pub meta_policy: MetaPriorPolicy,
}

impl Default for OpportunityConfig {
    fn default() -> Self {
        Self {
            weights: OpportunityWeights::default(),
            shortlist_size: 5,
            meta_policy: MetaPriorPolicy::default(),
        }
    }
}

pub struct OpportunityInput<'a> {
    pub state: &'a GameState,
    pub facts: &'a OpportunityFacts,
    pub meta: Option<&'a MetaSnapshot>,
    pub now_ms: u64,
}

pub struct OpportunityEngine {
    config: OpportunityConfig,
}

impl OpportunityEngine {
    pub fn new(config: OpportunityConfig) -> Result<Self, OpportunityError> {
        if config.shortlist_size == 0 {
            return Err(OpportunityError::InvalidShortlist);
        }
        Ok(Self { config })
    }

    pub fn evaluate(
        &self,
        input: OpportunityInput<'_>,
    ) -> Result<OpportunityReport, OpportunityError> {
        let mut candidates = Vec::new();

        if allows_economic_actions(&input.state.phase) {
            candidates.push(self.hold_candidate(input.state)?);
            for fact in &input.facts.rolls {
                candidates.push(self.roll_candidate(&input, fact)?);
            }
            for fact in &input.facts.buys {
                candidates.push(self.buy_candidate(&input, fact)?);
            }
            for fact in &input.facts.levels {
                candidates.push(self.level_candidate(input.state, fact)?);
            }
            for fact in &input.facts.items {
                candidates.push(self.item_candidate(input.state, fact)?);
            }
            for fact in &input.facts.positions {
                candidates.push(self.position_candidate(input.state, fact)?);
            }
            for fact in &input.facts.pivots {
                candidates.push(self.pivot_candidate(&input, fact)?);
            }
        }

        if matches!(
            input.state.phase,
            MatchPhase::Planning | MatchPhase::Combat | MatchPhase::PostCombat
        ) {
            for fact in &input.facts.scouts {
                candidates.push(self.scout_candidate(input.state, fact)?);
            }
        }

        if input.state.phase == MatchPhase::AugmentSelection {
            for fact in &input.facts.augments {
                candidates.push(self.augment_candidate(input.state, fact)?);
            }
        }

        if candidates.is_empty() {
            candidates.push(self.wait_candidate(input.state)?);
        }

        candidates.sort_by(|a, b| {
            b.utility
                .total_cmp(&a.utility)
                .then_with(|| b.confidence.value().total_cmp(&a.confidence.value()))
        });

        let shortlist = candidates
            .iter()
            .take(self.config.shortlist_size)
            .cloned()
            .collect();

        Ok(OpportunityReport {
            state_revision: input.state.revision,
            evaluated_at_ms: input.now_ms,
            all: candidates,
            shortlist,
        })
    }

    fn hold_candidate(
        &self,
        state: &GameState,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let gold = state.player.gold.as_ref().map(|value| value.value).unwrap_or(0);
        let hp = state.player.hp.as_ref().map(|value| value.value);
        let economy_value = (gold as f32 / 50.0).clamp(0.0, 1.0);
        let pressure = hp_pressure(hp);

        self.build(
            state,
            Action::HoldEcon,
            OpportunityTier::Tactical,
            OpportunityVector {
                economy_value,
                hp_preservation: -pressure,
                flexibility: 0.35,
                ..OpportunityVector::default()
            },
            state_confidence(state),
            vec![
                Evidence {
                    code: "HOLD_ECON".into(),
                    detail: format!("Current gold: {gold}."),
                },
                Evidence {
                    code: "HP_PRESSURE".into(),
                    detail: format!("HP pressure score: {pressure:.2}."),
                },
            ],
        )
    }

    fn roll_candidate(
        &self,
        input: &OpportunityInput<'_>,
        fact: &RollOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let current_gold = input
            .state
            .player
            .gold
            .as_ref()
            .map(|value| value.value)
            .unwrap_or(0)
            .max(1);

        let probability = bounded01(fact.probability_at_least_one.unwrap_or(0.0))?;
        let expected = nonnegative01(
            fact.expected_target_copies
                .map(|value| (value / 2.0).min(1.0))
                .unwrap_or(0.0),
        )?;
        let contest = bounded01(
            fact.contested_copies
                .map(|copies| copies as f32 / 9.0)
                .unwrap_or(0.0),
        )?;
        let spend_ratio = bounded01(fact.budget_gold as f32 / current_gold as f32)?;
        let interest_penalty = bounded01(
            fact.interest_lost
                .map(|value| value as f32 / 5.0)
                .unwrap_or(0.0),
        )?;
        let hp_pressure = hp_pressure(
            input.state.player.hp.as_ref().map(|value| value.value),
        );

        let meta_prior = match (&input.meta, &fact.target_unit_id) {
            (Some(meta), Some(unit_id)) => unit_meta_prior(
                meta,
                self.config.meta_policy,
                input.now_ms,
                input.state.patch.as_deref(),
                input.state.set.as_deref(),
                unit_id,
            )
            .map_err(|error| OpportunityError::Meta(error.to_string()))?
            .unwrap_or(0.0),
            _ => 0.0,
        };

        let mut evidence = vec![
            Evidence {
                code: "ROLL_BUDGET".into(),
                detail: format!("Roll budget: {}g.", fact.budget_gold),
            },
            Evidence {
                code: "ROLL_HIT_PROBABILITY".into(),
                detail: format!("P(at least one target): {probability:.3}."),
            },
        ];

        if let Some(copies) = fact.contested_copies {
            evidence.push(Evidence {
                code: "CONTESTED_COPIES".into(),
                detail: format!("{copies} target copies observed on opponents."),
            });
        }

        self.build(
            input.state,
            Action::Roll {
                budget_gold: fact.budget_gold,
                stop_condition: fact.stop_condition.clone(),
            },
            OpportunityTier::Tactical,
            OpportunityVector {
                immediate_board_gain: (probability * 0.6 + expected * 0.4).clamp(0.0, 1.0),
                upgrade_value: probability,
                hp_preservation: hp_pressure * probability,
                economy_value: -(spend_ratio * 0.65 + interest_penalty * 0.35),
                contest_urgency: contest,
                flexibility: -(spend_ratio * 0.5),
                external_meta_prior: meta_prior,
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(input.state, fact.confidence)?,
            evidence,
        )
    }

    fn buy_candidate(
        &self,
        input: &OpportunityInput<'_>,
        fact: &BuyOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let current_gold = input
            .state
            .player
            .gold
            .as_ref()
            .map(|value| value.value)
            .unwrap_or(0)
            .max(1);
        let contest = bounded01(
            fact.contested_copies
                .map(|copies| copies as f32 / 9.0)
                .unwrap_or(0.0),
        )?;
        let cost_ratio = bounded01(fact.gold_cost as f32 / current_gold as f32)?;
        let meta_prior = match input.meta {
            Some(meta) => unit_meta_prior(
                meta,
                self.config.meta_policy,
                input.now_ms,
                input.state.patch.as_deref(),
                input.state.set.as_deref(),
                &fact.unit_id,
            )
            .map_err(|error| OpportunityError::Meta(error.to_string()))?
            .unwrap_or(0.0),
            None => 0.0,
        };

        self.build(
            input.state,
            Action::Buy {
                shop_slot: fact.shop_slot,
                unit_id: fact.unit_id.clone(),
            },
            OpportunityTier::Micro,
            OpportunityVector {
                immediate_board_gain: if fact.closes_upgrade { 1.0 } else { 0.25 },
                upgrade_value: if fact.closes_upgrade { 1.0 } else { 0.35 },
                economy_value: -cost_ratio,
                contest_urgency: contest,
                flexibility: if fact.closes_upgrade { 0.15 } else { -0.05 },
                external_meta_prior: meta_prior,
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(input.state, fact.confidence)?,
            vec![
                Evidence {
                    code: "SHOP_BUY".into(),
                    detail: format!(
                        "Slot {} offers {} for {}g.",
                        fact.shop_slot, fact.unit_id, fact.gold_cost
                    ),
                },
                Evidence {
                    code: "CLOSES_UPGRADE".into(),
                    detail: fact.closes_upgrade.to_string(),
                },
            ],
        )
    }

    fn level_candidate(
        &self,
        state: &GameState,
        fact: &LevelOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let current_gold = state
            .player
            .gold
            .as_ref()
            .map(|value| value.value)
            .unwrap_or(0)
            .max(1);
        let cost_ratio = bounded01(fact.gold_cost as f32 / current_gold as f32)?;
        let board_gain = bounded01(
            fact.expected_board_gain.unwrap_or(0.0),
        )?;

        self.build(
            state,
            Action::Level {
                target_level: fact.target_level,
            },
            OpportunityTier::Tactical,
            OpportunityVector {
                immediate_board_gain: board_gain,
                hp_preservation: hp_pressure(
                    state.player.hp.as_ref().map(|value| value.value),
                ) * board_gain,
                economy_value: -cost_ratio,
                flexibility: (0.25 + fact.slots_gained as f32 * 0.25).min(1.0),
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(state, fact.confidence)?,
            vec![Evidence {
                code: "LEVEL_OPTION".into(),
                detail: format!(
                    "Level {} costs {}g and adds {} board slot(s).",
                    fact.target_level, fact.gold_cost, fact.slots_gained
                ),
            }],
        )
    }

    fn item_candidate(
        &self,
        state: &GameState,
        fact: &ItemOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let strength = bounded01(fact.strength_gain)?;
        let flexibility_cost = bounded01(fact.flexibility_cost)?;
        let external_meta_prior = signed01(fact.external_meta_prior)?;

        self.build(
            state,
            Action::EquipItem {
                item_id: fact.item_id.clone(),
                unit_instance_id: fact.unit_instance_id.clone(),
            },
            OpportunityTier::Micro,
            OpportunityVector {
                immediate_board_gain: strength,
                hp_preservation: hp_pressure(
                    state.player.hp.as_ref().map(|value| value.value),
                ) * strength,
                flexibility: -flexibility_cost,
                external_meta_prior,
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(state, fact.confidence)?,
            {
                let mut evidence = vec![Evidence {
                    code: "ITEM_SLAM".into(),
                    detail: format!(
                        "{} on {} has normalized local strength gain {:.2}.",
                        fact.item_id, fact.unit_instance_id, strength
                    ),
                }];
                if external_meta_prior != 0.0 {
                    evidence.push(Evidence {
                        code: "ITEM_EXTERNAL_META_PRIOR".into(),
                        detail: format!(
                            "External item prior: {external_meta_prior:.3}."
                        ),
                    });
                }
                evidence
            },
        )
    }

    fn position_candidate(
        &self,
        state: &GameState,
        fact: &PositionOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let gain = signed01(fact.matchup_gain)?;

        self.build(
            state,
            Action::Position {
                moves: fact.moves.clone(),
            },
            OpportunityTier::Micro,
            OpportunityVector {
                immediate_board_gain: gain,
                hp_preservation: hp_pressure(
                    state.player.hp.as_ref().map(|value| value.value),
                ) * gain.max(0.0),
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(state, fact.confidence)?,
            vec![Evidence {
                code: "POSITION_MATCHUP_GAIN".into(),
                detail: format!("Normalized matchup gain: {gain:.2}."),
            }],
        )
    }

    fn pivot_candidate(
        &self,
        input: &OpportunityInput<'_>,
        fact: &PivotOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let immediate_gain = signed01(fact.immediate_gain)?;
        let transition_cost = bounded01(fact.transition_cost)?;
        let flexibility = signed01(fact.flexibility_after)?;

        let meta_prior = match (&input.meta, &fact.meta_comp_id) {
            (Some(meta), Some(comp_id)) => entity_meta_prior(
                meta,
                self.config.meta_policy,
                input.now_ms,
                input.state.patch.as_deref(),
                input.state.set.as_deref(),
                MetaEntityKind::Comp,
                comp_id,
            )
            .map_err(|error| OpportunityError::Meta(error.to_string()))?
            .unwrap_or(0.0),
            _ => 0.0,
        };

        self.build(
            input.state,
            Action::Pivot {
                target: fact.target.clone(),
            },
            OpportunityTier::Strategic,
            OpportunityVector {
                immediate_board_gain: immediate_gain,
                economy_value: -transition_cost,
                flexibility,
                external_meta_prior: meta_prior,
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(input.state, fact.confidence)?,
            vec![
                Evidence {
                    code: "PIVOT_TARGET".into(),
                    detail: fact.target.clone(),
                },
                Evidence {
                    code: "TRANSITION_COST".into(),
                    detail: format!("{transition_cost:.2}"),
                },
            ],
        )
    }

    fn scout_candidate(
        &self,
        state: &GameState,
        fact: &ScoutOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let info = bounded01(fact.uncertainty_reduction)?;

        self.build(
            state,
            Action::Scout {
                player_id: fact.player_id.clone(),
            },
            OpportunityTier::Information,
            OpportunityVector {
                information_value: info,
                flexibility: info * 0.25,
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(state, fact.confidence)?,
            vec![Evidence {
                code: "SCOUT_INFORMATION_GAIN".into(),
                detail: format!(
                    "Scouting {} reduces normalized uncertainty by {:.2}.",
                    fact.player_id, info
                ),
            }],
        )
    }

    fn augment_candidate(
        &self,
        state: &GameState,
        fact: &AugmentOpportunityFact,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let board_gain = signed01(fact.board_gain)?;
        let flexibility = signed01(fact.flexibility)?;

        self.build(
            state,
            Action::ChooseAugment {
                augment_id: fact.augment_id.clone(),
            },
            OpportunityTier::Strategic,
            OpportunityVector {
                immediate_board_gain: board_gain,
                flexibility,
                uncertainty: 1.0 - fact.confidence.value(),
                ..OpportunityVector::default()
            },
            conservative_confidence(state, fact.confidence)?,
            vec![Evidence {
                code: "AUGMENT_OPTION".into(),
                detail: fact.augment_id.clone(),
            }],
        )
    }

    fn wait_candidate(
        &self,
        state: &GameState,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        self.build(
            state,
            Action::Wait,
            OpportunityTier::Tactical,
            OpportunityVector {
                uncertainty: 0.75,
                ..OpportunityVector::default()
            },
            state_confidence(state),
            vec![Evidence {
                code: "NO_ACTION_WINDOW".into(),
                detail: format!("No supplied opportunity is valid in phase {:?}.", state.phase),
            }],
        )
    }

    fn build(
        &self,
        _state: &GameState,
        action: Action,
        tier: OpportunityTier,
        vector: OpportunityVector,
        confidence: Confidence,
        evidence: Vec<Evidence>,
    ) -> Result<OpportunityCandidate, OpportunityError> {
        let utility = self.config.weights.score(vector)?;
        Ok(OpportunityCandidate {
            action,
            tier,
            utility,
            confidence,
            vector,
            evidence,
        })
    }
}


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UtilityShift {
    pub action: Action,
    pub previous: f32,
    pub current: f32,
    pub absolute_delta: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OpportunityDelta {
    pub previous_revision: Option<u64>,
    pub current_revision: u64,
    pub added: Vec<Action>,
    pub removed: Vec<Action>,
    pub top_changed: bool,
    pub previous_top: Option<Action>,
    pub current_top: Option<Action>,
    pub material_utility_shifts: Vec<UtilityShift>,
}

impl OpportunityDelta {
    pub fn is_material(&self) -> bool {
        self.top_changed
            || !self.added.is_empty()
            || !self.removed.is_empty()
            || !self.material_utility_shifts.is_empty()
    }
}

pub struct OpportunityTracker {
    previous: Option<OpportunityReport>,
    utility_shift_threshold: f32,
}

impl OpportunityTracker {
    pub fn new(utility_shift_threshold: f32) -> Result<Self, OpportunityError> {
        if !utility_shift_threshold.is_finite() || utility_shift_threshold < 0.0 {
            return Err(OpportunityError::NonFiniteMetric);
        }
        Ok(Self {
            previous: None,
            utility_shift_threshold,
        })
    }

    pub fn observe(
        &mut self,
        current: OpportunityReport,
    ) -> Result<OpportunityDelta, OpportunityError> {
        let previous = self.previous.as_ref();

        let previous_by_key = previous
            .map(index_candidates)
            .unwrap_or_default();
        let current_by_key = index_candidates(&current);

        let mut added = Vec::new();
        let mut removed = Vec::new();
        let mut shifts = Vec::new();

        for (key, candidate) in &current_by_key {
            match previous_by_key.get(key) {
                None => added.push(candidate.action.clone()),
                Some(old) => {
                    let delta = (candidate.utility - old.utility).abs();
                    if delta >= self.utility_shift_threshold {
                        shifts.push(UtilityShift {
                            action: candidate.action.clone(),
                            previous: old.utility,
                            current: candidate.utility,
                            absolute_delta: delta,
                        });
                    }
                }
            }
        }

        for (key, candidate) in &previous_by_key {
            if !current_by_key.contains_key(key) {
                removed.push(candidate.action.clone());
            }
        }

        let previous_top = previous
            .and_then(|report| report.all.first())
            .map(|candidate| candidate.action.clone());
        let current_top = current
            .all
            .first()
            .map(|candidate| candidate.action.clone());

        let top_changed = match (&previous_top, &current_top) {
            (None, None) => false,
            (Some(a), Some(b)) => action_key(a)? != action_key(b)?,
            _ => true,
        };

        let delta = OpportunityDelta {
            previous_revision: previous.map(|report| report.state_revision),
            current_revision: current.state_revision,
            added,
            removed,
            top_changed,
            previous_top,
            current_top,
            material_utility_shifts: shifts,
        };

        self.previous = Some(current);
        Ok(delta)
    }

    pub fn reset(&mut self) {
        self.previous = None;
    }
}

fn action_key(action: &Action) -> Result<String, OpportunityError> {
    serde_json::to_string(action)
        .map_err(|_| OpportunityError::NonFiniteMetric)
}

fn index_candidates(
    report: &OpportunityReport,
) -> std::collections::BTreeMap<String, OpportunityCandidate> {
    report
        .all
        .iter()
        .filter_map(|candidate| {
            action_key(&candidate.action)
                .ok()
                .map(|key| (key, candidate.clone()))
        })
        .collect()
}

fn allows_economic_actions(phase: &MatchPhase) -> bool {
    matches!(phase, MatchPhase::Planning | MatchPhase::PostCombat)
}

fn state_confidence(state: &GameState) -> Confidence {
    state.overall_confidence
}

fn conservative_confidence(
    state: &GameState,
    fact: Confidence,
) -> Result<Confidence, OpportunityError> {
    Confidence::new(state.overall_confidence.value().min(fact.value()))
        .map_err(|_| OpportunityError::InvalidConfidence)
}

fn hp_pressure(hp: Option<u16>) -> f32 {
    match hp {
        None => 0.35,
        Some(0..=15) => 1.0,
        Some(16..=30) => 0.80,
        Some(31..=45) => 0.60,
        Some(46..=65) => 0.35,
        Some(66..=80) => 0.15,
        Some(_) => 0.05,
    }
}

fn bounded01(value: f32) -> Result<f32, OpportunityError> {
    if !value.is_finite() {
        return Err(OpportunityError::NonFiniteMetric);
    }
    if !(0.0..=1.0).contains(&value) {
        return Err(OpportunityError::MetricOutOfRange);
    }
    Ok(value)
}

fn nonnegative01(value: f32) -> Result<f32, OpportunityError> {
    bounded01(value)
}

fn signed01(value: f32) -> Result<f32, OpportunityError> {
    if !value.is_finite() {
        return Err(OpportunityError::NonFiniteMetric);
    }
    if !(-1.0..=1.0).contains(&value) {
        return Err(OpportunityError::MetricOutOfRange);
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use agente_tft_contracts::{
        Confidence, MatchPhase, ObservationSource, Observed, PlayerState,
    };
    use agente_tft_meta_context::{
        MetaEntity, MetaPerformance,
    };

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
        state.patch = Some("18.3b".into());
        state.set = Some("TFTSet18".into());
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

    fn meta() -> MetaSnapshot {
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
            entities: vec![MetaEntity {
                kind: MetaEntityKind::Unit,
                id: "X".into(),
                name: "X".into(),
                unit_ids: vec![],
                trait_ids: vec![],
                performance: MetaPerformance {
                    avg_place: Some(3.8),
                    top4_rate: Some(0.60),
                    win_rate: Some(0.16),
                    frequency: Some(0.08),
                    sample_size: Some(10_000),
                },
                tags: vec![],
                attributes: BTreeMap::new(),
            }],
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn evaluates_all_supplied_opportunities_before_shortlisting() {
        let facts = OpportunityFacts {
            rolls: vec![
                RollOpportunityFact {
                    budget_gold: 10,
                    stop_condition: Some("upgrade".into()),
                    target_unit_id: Some("X".into()),
                    probability_at_least_one: Some(0.35),
                    expected_target_copies: Some(0.45),
                    interest_lost: Some(1),
                    contested_copies: Some(3),
                    confidence: Confidence::new(0.90).unwrap(),
                },
                RollOpportunityFact {
                    budget_gold: 20,
                    stop_condition: Some("upgrade".into()),
                    target_unit_id: Some("X".into()),
                    probability_at_least_one: Some(0.62),
                    expected_target_copies: Some(0.90),
                    interest_lost: Some(2),
                    contested_copies: Some(3),
                    confidence: Confidence::new(0.90).unwrap(),
                },
            ],
            levels: vec![LevelOpportunityFact {
                target_level: 8,
                gold_cost: 32,
                expected_board_gain: Some(0.45),
                slots_gained: 1,
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let engine = OpportunityEngine::new(OpportunityConfig {
            shortlist_size: 2,
            ..OpportunityConfig::default()
        })
        .unwrap();

        let report = engine
            .evaluate(OpportunityInput {
                state: &state(),
                facts: &facts,
                meta: Some(&meta()),
                now_ms: 1_001,
            })
            .unwrap();

        // hold + 2 roll options + level
        assert_eq!(report.all.len(), 4);
        assert_eq!(report.shortlist.len(), 2);
    }

    #[test]
    fn strong_contested_roll_can_outrank_hold_under_pressure() {
        let facts = OpportunityFacts {
            rolls: vec![RollOpportunityFact {
                budget_gold: 20,
                stop_condition: Some("X 2-star".into()),
                target_unit_id: Some("X".into()),
                probability_at_least_one: Some(0.75),
                expected_target_copies: Some(1.2),
                interest_lost: Some(2),
                contested_copies: Some(6),
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let engine = OpportunityEngine::new(OpportunityConfig::default()).unwrap();
        let report = engine
            .evaluate(OpportunityInput {
                state: &state(),
                facts: &facts,
                meta: None,
                now_ms: 1_001,
            })
            .unwrap();

        assert!(matches!(
            report.all[0].action,
            Action::Roll { budget_gold: 20, .. }
        ));
    }

    #[test]
    fn meta_prior_is_small_and_cannot_dominate_local_vector() {
        let facts = OpportunityFacts {
            buys: vec![BuyOpportunityFact {
                shop_slot: 0,
                unit_id: "X".into(),
                gold_cost: 4,
                closes_upgrade: false,
                contested_copies: Some(0),
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let engine = OpportunityEngine::new(OpportunityConfig::default()).unwrap();
        let report = engine
            .evaluate(OpportunityInput {
                state: &state(),
                facts: &facts,
                meta: Some(&meta()),
                now_ms: 1_001,
            })
            .unwrap();

        let buy = report
            .all
            .iter()
            .find(|candidate| matches!(candidate.action, Action::Buy { .. }))
            .unwrap();

        assert!(buy.vector.external_meta_prior.abs() <= 0.10);
    }

    #[test]
    fn local_decision_comes_from_shortlist() {
        let facts = OpportunityFacts {
            rolls: vec![RollOpportunityFact {
                budget_gold: 20,
                stop_condition: Some("X 2-star".into()),
                target_unit_id: Some("X".into()),
                probability_at_least_one: Some(0.80),
                expected_target_copies: Some(1.2),
                interest_lost: Some(2),
                contested_copies: Some(6),
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let report = OpportunityEngine::new(OpportunityConfig::default())
            .unwrap()
            .evaluate(OpportunityInput {
                state: &state(),
                facts: &facts,
                meta: None,
                now_ms: 1_001,
            })
            .unwrap();

        let decision = report.local_decision(DecisionConfig::default());

        assert_eq!(decision.state_revision, report.state_revision);
        assert!(matches!(
            decision.action,
            Action::Roll { budget_gold: 20, .. }
        ));
    }

    #[test]
    fn tracker_detects_new_and_changed_top_opportunity() {
        let engine = OpportunityEngine::new(OpportunityConfig::default()).unwrap();
        let first_facts = OpportunityFacts::default();
        let first = engine
            .evaluate(OpportunityInput {
                state: &state(),
                facts: &first_facts,
                meta: None,
                now_ms: 1_001,
            })
            .unwrap();

        let second_facts = OpportunityFacts {
            rolls: vec![RollOpportunityFact {
                budget_gold: 20,
                stop_condition: Some("X 2-star".into()),
                target_unit_id: Some("X".into()),
                probability_at_least_one: Some(0.90),
                expected_target_copies: Some(1.5),
                interest_lost: Some(1),
                contested_copies: Some(6),
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        };
        let second = engine
            .evaluate(OpportunityInput {
                state: &state(),
                facts: &second_facts,
                meta: None,
                now_ms: 1_002,
            })
            .unwrap();

        let mut tracker = OpportunityTracker::new(0.20).unwrap();
        let initial = tracker.observe(first).unwrap();
        assert!(initial.is_material());

        let delta = tracker.observe(second).unwrap();
        assert!(delta.is_material());
        assert!(delta.top_changed);
        assert!(delta.added.iter().any(|action| matches!(
            action,
            Action::Roll { budget_gold: 20, .. }
        )));
    }

    #[test]
    fn augment_phase_only_evaluates_augment_facts() {
        let mut state = state();
        state.phase = MatchPhase::AugmentSelection;

        let facts = OpportunityFacts {
            rolls: vec![RollOpportunityFact {
                budget_gold: 20,
                stop_condition: None,
                target_unit_id: None,
                probability_at_least_one: Some(0.9),
                expected_target_copies: Some(1.0),
                interest_lost: Some(2),
                contested_copies: None,
                confidence: Confidence::new(0.95).unwrap(),
            }],
            augments: vec![AugmentOpportunityFact {
                augment_id: "AUG_A".into(),
                board_gain: 0.6,
                flexibility: 0.2,
                confidence: Confidence::new(0.95).unwrap(),
            }],
            ..OpportunityFacts::default()
        };

        let report = OpportunityEngine::new(OpportunityConfig::default())
            .unwrap()
            .evaluate(OpportunityInput {
                state: &state,
                facts: &facts,
                meta: None,
                now_ms: 1_001,
            })
            .unwrap();

        assert_eq!(report.all.len(), 1);
        assert!(matches!(
            report.all[0].action,
            Action::ChooseAugment { .. }
        ));
    }
}
