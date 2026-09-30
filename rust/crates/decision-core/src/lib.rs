use agente_tft_contracts::{
    Action, AlternativeAction, Confidence, DecisionPacket, Evidence,
};

#[derive(Debug, Clone, PartialEq)]
pub struct CandidateDecision {
    /// Higher utility is better. The producer owns the meaning/calibration.
    pub action: Action,
    pub utility: f32,
    pub confidence: Confidence,
    pub evidence: Vec<Evidence>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DecisionConfig {
    pub min_confidence: f32,
    pub max_alternatives: usize,
    /// If the utility margin is below this value, record ambiguity evidence.
    /// This does not change the selected action or fabricate confidence.
    pub ambiguity_margin: f32,
}

impl Default for DecisionConfig {
    fn default() -> Self {
        Self {
            min_confidence: 0.60,
            max_alternatives: 3,
            ambiguity_margin: 0.05,
        }
    }
}

pub fn select_decision(
    state_revision: u64,
    candidates: impl IntoIterator<Item = CandidateDecision>,
    config: DecisionConfig,
) -> DecisionPacket {
    let min_confidence = config.min_confidence.clamp(0.0, 1.0);
    let ambiguity_margin = if config.ambiguity_margin.is_finite() {
        config.ambiguity_margin.max(0.0)
    } else {
        0.0
    };

    let mut valid: Vec<(usize, CandidateDecision)> = candidates
        .into_iter()
        .enumerate()
        .filter(|(_, candidate)| {
            candidate.utility.is_finite()
                && candidate.confidence.value() >= min_confidence
        })
        .collect();

    valid.sort_by(|(index_a, a), (index_b, b)| {
        b.utility
            .total_cmp(&a.utility)
            .then_with(|| {
                b.confidence
                    .value()
                    .total_cmp(&a.confidence.value())
            })
            .then_with(|| index_a.cmp(index_b))
    });

    let Some((_, winner)) = valid.first().cloned() else {
        return DecisionPacket::new(
            state_revision,
            Action::Wait,
            Confidence::default(),
            Vec::new(),
            vec![Evidence {
                code: "NO_CONFIDENT_CANDIDATE".into(),
                detail: format!(
                    "No candidate met minimum confidence {:.2}.",
                    min_confidence
                ),
            }],
        );
    };

    let mut evidence = winner.evidence.clone();

    if let Some((_, runner_up)) = valid.get(1) {
        let margin = winner.utility - runner_up.utility;
        if margin < ambiguity_margin {
            evidence.push(Evidence {
                code: "CLOSE_ALTERNATIVE".into(),
                detail: format!(
                    "Top utility margin {:.4} is below configured ambiguity margin {:.4}.",
                    margin, ambiguity_margin
                ),
            });
        }
    }

    let alternatives = valid
        .iter()
        .skip(1)
        .take(config.max_alternatives)
        .map(|(_, candidate)| AlternativeAction {
            action: candidate.action.clone(),
            score: candidate.utility,
        })
        .collect();

    DecisionPacket::new(
        state_revision,
        winner.action,
        winner.confidence,
        alternatives,
        evidence,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn confidence(value: f32) -> Confidence {
        Confidence::new(value).unwrap()
    }

    fn candidate(action: Action, utility: f32, confidence_value: f32) -> CandidateDecision {
        CandidateDecision {
            action,
            utility,
            confidence: confidence(confidence_value),
            evidence: vec![],
        }
    }

    #[test]
    fn selects_highest_utility_candidate() {
        let packet = select_decision(
            7,
            [
                candidate(Action::HoldEcon, 0.40, 0.90),
                candidate(
                    Action::Roll {
                        budget_gold: 20,
                        stop_condition: Some("X reaches 2 stars".into()),
                    },
                    0.82,
                    0.84,
                ),
                candidate(Action::Level { target_level: 8 }, 0.61, 0.92),
            ],
            DecisionConfig::default(),
        );

        assert!(matches!(
            packet.action,
            Action::Roll {
                budget_gold: 20,
                ..
            }
        ));
        assert_eq!(packet.confidence.value(), 0.84);
        assert_eq!(packet.alternatives.len(), 2);
        assert!(matches!(
            packet.alternatives[0].action,
            Action::Level { target_level: 8 }
        ));
    }

    #[test]
    fn low_confidence_candidates_are_excluded() {
        let packet = select_decision(
            3,
            [
                candidate(Action::HoldEcon, 0.40, 0.95),
                candidate(Action::Level { target_level: 8 }, 0.99, 0.30),
            ],
            DecisionConfig {
                min_confidence: 0.60,
                ..DecisionConfig::default()
            },
        );

        assert!(matches!(packet.action, Action::HoldEcon));
    }

    #[test]
    fn returns_wait_when_nothing_is_confident_enough() {
        let packet = select_decision(
            10,
            [candidate(Action::HoldEcon, 0.90, 0.20)],
            DecisionConfig::default(),
        );

        assert!(matches!(packet.action, Action::Wait));
        assert_eq!(packet.confidence.value(), 0.0);
        assert_eq!(packet.evidence[0].code, "NO_CONFIDENT_CANDIDATE");
    }

    #[test]
    fn close_top_candidates_add_ambiguity_evidence() {
        let packet = select_decision(
            5,
            [
                candidate(Action::HoldEcon, 0.80, 0.90),
                candidate(Action::Level { target_level: 8 }, 0.79, 0.91),
            ],
            DecisionConfig {
                ambiguity_margin: 0.05,
                ..DecisionConfig::default()
            },
        );

        assert!(packet
            .evidence
            .iter()
            .any(|evidence| evidence.code == "CLOSE_ALTERNATIVE"));
    }

    #[test]
    fn deterministic_tie_break_prefers_higher_confidence_then_input_order() {
        let packet = select_decision(
            1,
            [
                candidate(Action::HoldEcon, 0.5, 0.80),
                candidate(Action::Level { target_level: 8 }, 0.5, 0.90),
            ],
            DecisionConfig::default(),
        );
        assert!(matches!(
            packet.action,
            Action::Level { target_level: 8 }
        ));

        let packet = select_decision(
            1,
            [
                candidate(Action::HoldEcon, 0.5, 0.90),
                candidate(Action::Level { target_level: 8 }, 0.5, 0.90),
            ],
            DecisionConfig::default(),
        );
        assert!(matches!(packet.action, Action::HoldEcon));
    }
}
