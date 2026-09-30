use agente_tft_contracts::{
    Confidence, HexPosition, PositionMove, UnitInstance,
};
use agente_tft_opportunity_engine::PositionOpportunityFact;
use agente_tft_positioning_core::PositionProposal;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum MatchupPositioningError {
    #[error("board dimensions must be > 0")]
    InvalidDimensions,
    #[error("config values must be finite")]
    NonFiniteConfig,
    #[error("confidence_cap and min_gain must be in [0,1]")]
    InvalidBoundedConfig,
    #[error("distance_decay must be > 0")]
    InvalidDistanceDecay,
    #[error("min_observed_opponent_units must be > 0")]
    InvalidObservedUnitMinimum,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct OpponentPerspective {
    pub rows: u8,
    pub cols: u8,
    /// Explicit calibration knobs. No orientation is assumed implicitly.
    pub mirror_rows: bool,
    pub mirror_cols: bool,
}

impl OpponentPerspective {
    pub fn validate(self) -> Result<(), MatchupPositioningError> {
        if self.rows == 0 || self.cols == 0 {
            return Err(MatchupPositioningError::InvalidDimensions);
        }
        Ok(())
    }

    pub fn map(self, position: HexPosition) -> Option<HexPosition> {
        self.validate().ok()?;
        if position.row >= self.rows || position.col >= self.cols {
            return None;
        }

        Some(HexPosition {
            row: if self.mirror_rows {
                self.rows - 1 - position.row
            } else {
                position.row
            },
            col: if self.mirror_cols {
                self.cols - 1 - position.col
            } else {
                position.col
            },
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MatchupPositioningConfig {
    /// Structural confidence cap until calibrated against combat outcomes.
    pub confidence_cap: f32,
    /// Minimum normalized exposure improvement required for an opportunity.
    pub min_gain: f32,
    /// Extra structural threat weight per equipped item.
    pub item_weight: f32,
    /// Extra structural threat weight per star above 1★.
    pub star_weight: f32,
    /// Controls how quickly threat contribution falls with Manhattan distance.
    pub distance_decay: f32,
    pub min_observed_opponent_units: usize,
}

impl Default for MatchupPositioningConfig {
    fn default() -> Self {
        Self {
            confidence_cap: 0.45,
            min_gain: 0.05,
            item_weight: 0.12,
            star_weight: 0.18,
            distance_decay: 1.0,
            min_observed_opponent_units: 2,
        }
    }
}

impl MatchupPositioningConfig {
    pub fn validate(self) -> Result<(), MatchupPositioningError> {
        let values = [
            self.confidence_cap,
            self.min_gain,
            self.item_weight,
            self.star_weight,
            self.distance_decay,
        ];
        if values.iter().any(|value| !value.is_finite()) {
            return Err(MatchupPositioningError::NonFiniteConfig);
        }

        if !(0.0..=1.0).contains(&self.confidence_cap)
            || !(0.0..=1.0).contains(&self.min_gain)
        {
            return Err(MatchupPositioningError::InvalidBoundedConfig);
        }

        if self.item_weight < 0.0 || self.star_weight < 0.0 {
            return Err(MatchupPositioningError::InvalidBoundedConfig);
        }

        if self.distance_decay <= 0.0 {
            return Err(MatchupPositioningError::InvalidDistanceDecay);
        }

        if self.min_observed_opponent_units == 0 {
            return Err(MatchupPositioningError::InvalidObservedUnitMinimum);
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ThreatCell {
    pub unit_instance_id: String,
    pub mapped_position: HexPosition,
    /// Structural threat weight, not damage/DPS.
    pub structural_weight: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExposureMeasurement {
    pub unit_instance_id: String,
    pub before: f32,
    pub after: f32,
    pub normalized_gain: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MatchupPositioningDiagnostic {
    pub observed_opponent_units: usize,
    pub usable_opponent_units: usize,
    pub threats: Vec<ThreatCell>,
    pub measurements: Vec<ExposureMeasurement>,
    pub skipped_proposals: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MatchupPositioningEvaluation {
    pub facts: Vec<PositionOpportunityFact>,
    pub diagnostic: MatchupPositioningDiagnostic,
}

pub struct MatchupPositioningEvaluator {
    config: MatchupPositioningConfig,
    perspective: OpponentPerspective,
}

impl MatchupPositioningEvaluator {
    pub fn new(
        config: MatchupPositioningConfig,
        perspective: OpponentPerspective,
    ) -> Result<Self, MatchupPositioningError> {
        config.validate()?;
        perspective.validate()?;
        Ok(Self {
            config,
            perspective,
        })
    }

    pub fn evaluate_proposals(
        &self,
        own_board: &[UnitInstance],
        opponent_board: &[UnitInstance],
        proposals: &[PositionProposal],
        source_confidence: Confidence,
    ) -> MatchupPositioningEvaluation {
        let move_sets = proposals
            .iter()
            .map(|proposal| vec![proposal.movement.clone()])
            .collect::<Vec<_>>();

        self.evaluate_move_sets(
            own_board,
            opponent_board,
            &move_sets,
            source_confidence,
        )
    }

    pub fn evaluate_position_facts(
        &self,
        own_board: &[UnitInstance],
        opponent_board: &[UnitInstance],
        facts: &[PositionOpportunityFact],
        opponent_confidence: Confidence,
    ) -> MatchupPositioningEvaluation {
        let move_sets = facts
            .iter()
            .map(|fact| fact.moves.clone())
            .collect::<Vec<_>>();

        let fact_confidence = facts
            .iter()
            .map(|fact| fact.confidence.value())
            .fold(1.0_f32, f32::min);

        let source_confidence = Confidence::new(
            opponent_confidence
                .value()
                .min(fact_confidence),
        )
        .expect("minimum of valid confidences remains valid");

        self.evaluate_move_sets(
            own_board,
            opponent_board,
            &move_sets,
            source_confidence,
        )
    }

    pub fn evaluate_move_sets(
        &self,
        own_board: &[UnitInstance],
        opponent_board: &[UnitInstance],
        move_sets: &[Vec<PositionMove>],
        source_confidence: Confidence,
    ) -> MatchupPositioningEvaluation {
        let threats = opponent_board
            .iter()
            .filter_map(|unit| {
                let position = unit.position?;
                let mapped = self.perspective.map(position)?;
                Some(ThreatCell {
                    unit_instance_id: unit.instance_id.clone(),
                    mapped_position: mapped,
                    structural_weight: self.structural_threat_weight(unit),
                })
            })
            .collect::<Vec<_>>();

        let observed_opponent_units = opponent_board.len();
        let usable_opponent_units = threats.len();

        if usable_opponent_units < self.config.min_observed_opponent_units {
            return MatchupPositioningEvaluation {
                facts: Vec::new(),
                diagnostic: MatchupPositioningDiagnostic {
                    observed_opponent_units,
                    usable_opponent_units,
                    threats,
                    measurements: Vec::new(),
                    skipped_proposals: move_sets.len(),
                },
            };
        }

        let position_coverage = if opponent_board.is_empty() {
            0.0
        } else {
            usable_opponent_units as f32 / opponent_board.len() as f32
        };

        let confidence = Confidence::new(
            source_confidence
                .value()
                .min(self.config.confidence_cap)
                * position_coverage.clamp(0.0, 1.0),
        )
        .expect("bounded matchup confidence is valid");

        let mut facts = Vec::new();
        let mut measurements = Vec::new();
        let mut skipped = 0usize;

        for moves in move_sets {
            if moves.is_empty() {
                skipped += 1;
                continue;
            }

            let mut before_total = 0.0_f32;
            let mut after_total = 0.0_f32;
            let mut valid_moves = 0usize;

            for movement in moves {
                let Some(unit) = own_board
                    .iter()
                    .find(|unit| unit.instance_id == movement.unit_instance_id)
                else {
                    continue;
                };

                let Some(before_position) = unit.position else {
                    continue;
                };

                let before = self.exposure(before_position, &threats);
                let after = self.exposure(movement.to, &threats);

                before_total += before;
                after_total += after;
                valid_moves += 1;

                let denominator = before.max(after).max(f32::EPSILON);
                let normalized_gain =
                    ((before - after) / denominator).clamp(-1.0, 1.0);

                measurements.push(ExposureMeasurement {
                    unit_instance_id: unit.instance_id.clone(),
                    before,
                    after,
                    normalized_gain,
                });
            }

            if valid_moves != moves.len() {
                skipped += 1;
                continue;
            }

            let denominator = before_total.max(after_total).max(f32::EPSILON);
            let normalized_gain =
                ((before_total - after_total) / denominator).clamp(-1.0, 1.0);

            if normalized_gain < self.config.min_gain {
                skipped += 1;
                continue;
            }

            facts.push(PositionOpportunityFact {
                moves: moves.clone(),
                matchup_gain: normalized_gain,
                confidence,
            });
        }

        facts.sort_by(|a, b| {
            b.matchup_gain
                .total_cmp(&a.matchup_gain)
                .then_with(|| {
                    a.moves
                        .first()
                        .map(|value| value.unit_instance_id.as_str())
                        .cmp(
                            &b.moves
                                .first()
                                .map(|value| value.unit_instance_id.as_str()),
                        )
                })
        });

        measurements.sort_by(|a, b| {
            b.normalized_gain
                .total_cmp(&a.normalized_gain)
                .then_with(|| a.unit_instance_id.cmp(&b.unit_instance_id))
        });

        MatchupPositioningEvaluation {
            facts,
            diagnostic: MatchupPositioningDiagnostic {
                observed_opponent_units,
                usable_opponent_units,
                threats,
                measurements,
                skipped_proposals: skipped,
            },
        }
    }

    fn structural_threat_weight(&self, unit: &UnitInstance) -> f32 {
        let extra_stars = unit.stars.saturating_sub(1) as f32;
        let item_count = unit.items.len().min(3) as f32;

        (1.0
            + extra_stars * self.config.star_weight
            + item_count * self.config.item_weight)
            .max(0.0)
    }

    fn exposure(
        &self,
        position: HexPosition,
        threats: &[ThreatCell],
    ) -> f32 {
        threats
            .iter()
            .map(|threat| {
                let distance = manhattan(position, threat.mapped_position) as f32;
                threat.structural_weight
                    / (1.0 + distance * self.config.distance_decay)
            })
            .sum()
    }
}

fn manhattan(a: HexPosition, b: HexPosition) -> u16 {
    a.row.abs_diff(b.row) as u16 + a.col.abs_diff(b.col) as u16
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{PositionMove};
    use agente_tft_positioning_core::PositioningDirective;

    use super::*;

    fn unit(
        id: &str,
        row: u8,
        col: u8,
        stars: u8,
        items: usize,
    ) -> UnitInstance {
        UnitInstance {
            instance_id: id.into(),
            unit_id: id.into(),
            stars,
            position: Some(HexPosition { row, col }),
            items: (0..items).map(|index| format!("I{index}")).collect(),
        }
    }

    fn proposal(
        id: &str,
        from_text: &str,
        row: u8,
        col: u8,
    ) -> PositionProposal {
        PositionProposal {
            unit_instance_id: id.into(),
            directive: PositioningDirective::Right,
            source_text: from_text.into(),
            movement: PositionMove {
                unit_instance_id: id.into(),
                to: HexPosition { row, col },
            },
        }
    }

    fn evaluator() -> MatchupPositioningEvaluator {
        MatchupPositioningEvaluator::new(
            MatchupPositioningConfig {
                min_gain: 0.01,
                min_observed_opponent_units: 2,
                ..MatchupPositioningConfig::default()
            },
            OpponentPerspective {
                rows: 4,
                cols: 7,
                mirror_rows: false,
                mirror_cols: false,
            },
        )
        .unwrap()
    }

    #[test]
    fn moving_away_from_observed_concentration_has_positive_structural_gain() {
        let own = vec![unit("carry", 3, 0, 2, 3)];
        let opponent = vec![
            unit("enemy-a", 3, 0, 2, 3),
            unit("enemy-b", 2, 1, 1, 2),
        ];

        let evaluation = evaluator().evaluate_proposals(
            &own,
            &opponent,
            &[proposal("carry", "move right", 3, 6)],
            Confidence::new(0.95).unwrap(),
        );

        assert_eq!(evaluation.facts.len(), 1);
        assert!(evaluation.facts[0].matchup_gain > 0.0);
        assert!(evaluation.facts[0].confidence.value() <= 0.45);
    }

    #[test]
    fn refines_existing_position_fact() {
        let own = vec![unit("carry", 3, 0, 2, 3)];
        let opponent = vec![
            unit("enemy-a", 3, 0, 2, 3),
            unit("enemy-b", 2, 1, 1, 2),
        ];
        let base = PositionOpportunityFact {
            moves: vec![PositionMove {
                unit_instance_id: "carry".into(),
                to: HexPosition { row: 3, col: 6 },
            }],
            matchup_gain: 0.0,
            confidence: Confidence::new(0.40).unwrap(),
        };

        let evaluation = evaluator().evaluate_position_facts(
            &own,
            &opponent,
            &[base],
            Confidence::new(0.90).unwrap(),
        );

        assert_eq!(evaluation.facts.len(), 1);
        assert!(evaluation.facts[0].matchup_gain > 0.0);
        assert!(evaluation.facts[0].confidence.value() <= 0.40);
    }

    #[test]
    fn moving_closer_is_not_promoted_as_opportunity() {
        let own = vec![unit("carry", 3, 6, 2, 3)];
        let opponent = vec![
            unit("enemy-a", 3, 0, 2, 3),
            unit("enemy-b", 2, 1, 1, 2),
        ];

        let evaluation = evaluator().evaluate_proposals(
            &own,
            &opponent,
            &[proposal("carry", "move left", 3, 0)],
            Confidence::new(0.95).unwrap(),
        );

        assert!(evaluation.facts.is_empty());
        assert_eq!(evaluation.diagnostic.skipped_proposals, 1);
        assert!(
            evaluation.diagnostic.measurements[0].normalized_gain < 0.0
        );
    }

    #[test]
    fn insufficient_observed_positions_generate_no_fact() {
        let own = vec![unit("carry", 3, 0, 2, 3)];
        let opponent = vec![unit("enemy-a", 3, 0, 2, 3)];

        let evaluation = evaluator().evaluate_proposals(
            &own,
            &opponent,
            &[proposal("carry", "move right", 3, 6)],
            Confidence::new(0.95).unwrap(),
        );

        assert!(evaluation.facts.is_empty());
        assert_eq!(evaluation.diagnostic.usable_opponent_units, 1);
    }

    #[test]
    fn explicit_perspective_mapping_is_applied() {
        let perspective = OpponentPerspective {
            rows: 4,
            cols: 7,
            mirror_rows: true,
            mirror_cols: true,
        };

        assert_eq!(
            perspective.map(HexPosition { row: 0, col: 0 }),
            Some(HexPosition { row: 3, col: 6 })
        );
    }

    #[test]
    fn invalid_config_is_rejected() {
        assert_eq!(
            MatchupPositioningEvaluator::new(
                MatchupPositioningConfig {
                    distance_decay: 0.0,
                    ..MatchupPositioningConfig::default()
                },
                OpponentPerspective {
                    rows: 4,
                    cols: 7,
                    mirror_rows: false,
                    mirror_cols: false,
                },
            )
            .err()
            .unwrap(),
            MatchupPositioningError::InvalidDistanceDecay
        );
    }
}
