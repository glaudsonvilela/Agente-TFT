use std::collections::BTreeSet;

use agente_tft_contracts::{HexPosition, PositionMove, UnitInstance};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum PositioningError {
    #[error("board rows and cols must be > 0")]
    InvalidDimensions,
    #[error("configured row or column is outside board bounds")]
    OutOfBounds,
    #[error("front/back or left/right regions overlap")]
    OverlappingRegions,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BoardCoordinateConvention {
    pub rows: u8,
    pub cols: u8,
    #[serde(default)]
    pub front_rows: Vec<u8>,
    #[serde(default)]
    pub back_rows: Vec<u8>,
    #[serde(default)]
    pub left_cols: Vec<u8>,
    #[serde(default)]
    pub right_cols: Vec<u8>,
    #[serde(default)]
    pub center_cols: Vec<u8>,
}

impl BoardCoordinateConvention {
    pub fn validate(&self) -> Result<(), PositioningError> {
        if self.rows == 0 || self.cols == 0 {
            return Err(PositioningError::InvalidDimensions);
        }

        if self
            .front_rows
            .iter()
            .chain(self.back_rows.iter())
            .any(|row| *row >= self.rows)
            || self
                .left_cols
                .iter()
                .chain(self.right_cols.iter())
                .chain(self.center_cols.iter())
                .any(|col| *col >= self.cols)
        {
            return Err(PositioningError::OutOfBounds);
        }

        if overlaps(&self.front_rows, &self.back_rows)
            || overlaps(&self.left_cols, &self.right_cols)
        {
            return Err(PositioningError::OverlappingRegions);
        }

        Ok(())
    }
}

fn overlaps(a: &[u8], b: &[u8]) -> bool {
    let set: BTreeSet<_> = a.iter().copied().collect();
    b.iter().any(|value| set.contains(value))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PositioningDirective {
    Front,
    Back,
    Left,
    Right,
    Center,
    FrontLeft,
    FrontRight,
    BackLeft,
    BackRight,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PositionProposal {
    pub unit_instance_id: String,
    pub directive: PositioningDirective,
    pub source_text: String,
    pub movement: PositionMove,
}

pub fn parse_directive(text: &str) -> Option<PositioningDirective> {
    let normalized = text.to_lowercase();

    let front = contains_any(
        &normalized,
        &["front row", "frontline", "front line", "na frente", "linha da frente"],
    );
    let back = contains_any(
        &normalized,
        &["back row", "backline", "back line", "atrás", "linha de trás"],
    );
    let left = contains_any(
        &normalized,
        &["left side", "left corner", "esquerda", "canto esquerdo"],
    );
    let right = contains_any(
        &normalized,
        &["right side", "right corner", "direita", "canto direito"],
    );
    let center = contains_any(
        &normalized,
        &["center", "middle", "centro", "meio"],
    );

    match (front, back, left, right, center) {
        (true, false, true, false, _) => Some(PositioningDirective::FrontLeft),
        (true, false, false, true, _) => Some(PositioningDirective::FrontRight),
        (false, true, true, false, _) => Some(PositioningDirective::BackLeft),
        (false, true, false, true, _) => Some(PositioningDirective::BackRight),
        (true, false, false, false, _) => Some(PositioningDirective::Front),
        (false, true, false, false, _) => Some(PositioningDirective::Back),
        (false, false, true, false, _) => Some(PositioningDirective::Left),
        (false, false, false, true, _) => Some(PositioningDirective::Right),
        (false, false, false, false, true) => Some(PositioningDirective::Center),
        _ => None,
    }
}

fn contains_any(text: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| text.contains(needle))
}

pub fn propose_move(
    board: &[UnitInstance],
    unit_instance_id: &str,
    hint: &str,
    convention: &BoardCoordinateConvention,
) -> Result<Option<PositionProposal>, PositioningError> {
    convention.validate()?;

    let directive = match parse_directive(hint) {
        Some(value) => value,
        None => return Ok(None),
    };

    let Some(unit) = board
        .iter()
        .find(|unit| unit.instance_id == unit_instance_id)
    else {
        return Ok(None);
    };

    let Some(current) = unit.position else {
        return Ok(None);
    };

    let occupied: BTreeSet<(u8, u8)> = board
        .iter()
        .filter(|other| other.instance_id != unit_instance_id)
        .filter_map(|other| other.position.map(|p| (p.row, p.col)))
        .collect();

    let row_choices = desired_rows(directive, current.row, convention);
    let col_choices = desired_cols(directive, current.col, convention);

    if row_choices.is_empty() || col_choices.is_empty() {
        return Ok(None);
    }

    let mut candidates = Vec::<HexPosition>::new();
    for row in row_choices {
        for col in &col_choices {
            if occupied.contains(&(row, *col)) {
                continue;
            }
            candidates.push(HexPosition { row, col: *col });
        }
    }

    candidates.sort_by(|a, b| {
        manhattan(current, *a)
            .cmp(&manhattan(current, *b))
            .then_with(|| a.row.cmp(&b.row))
            .then_with(|| a.col.cmp(&b.col))
    });

    let Some(target) = candidates.into_iter().next() else {
        return Ok(None);
    };

    if target == current {
        return Ok(None);
    }

    Ok(Some(PositionProposal {
        unit_instance_id: unit_instance_id.to_string(),
        directive,
        source_text: hint.to_string(),
        movement: PositionMove {
            unit_instance_id: unit_instance_id.to_string(),
            to: target,
        },
    }))
}

fn desired_rows(
    directive: PositioningDirective,
    current: u8,
    convention: &BoardCoordinateConvention,
) -> Vec<u8> {
    match directive {
        PositioningDirective::Front
        | PositioningDirective::FrontLeft
        | PositioningDirective::FrontRight => convention.front_rows.clone(),
        PositioningDirective::Back
        | PositioningDirective::BackLeft
        | PositioningDirective::BackRight => convention.back_rows.clone(),
        PositioningDirective::Left
        | PositioningDirective::Right
        | PositioningDirective::Center => vec![current],
    }
}

fn desired_cols(
    directive: PositioningDirective,
    current: u8,
    convention: &BoardCoordinateConvention,
) -> Vec<u8> {
    match directive {
        PositioningDirective::Left
        | PositioningDirective::FrontLeft
        | PositioningDirective::BackLeft => convention.left_cols.clone(),
        PositioningDirective::Right
        | PositioningDirective::FrontRight
        | PositioningDirective::BackRight => convention.right_cols.clone(),
        PositioningDirective::Center => convention.center_cols.clone(),
        PositioningDirective::Front | PositioningDirective::Back => vec![current],
    }
}

fn manhattan(a: HexPosition, b: HexPosition) -> u16 {
    a.row.abs_diff(b.row) as u16 + a.col.abs_diff(b.col) as u16
}

pub fn propose_moves_from_hints(
    board: &[UnitInstance],
    hints: impl IntoIterator<Item = (String, String)>,
    convention: &BoardCoordinateConvention,
) -> Result<Vec<PositionProposal>, PositioningError> {
    let mut values = Vec::new();

    for (unit_instance_id, text) in hints {
        if let Some(proposal) = propose_move(
            board,
            &unit_instance_id,
            &text,
            convention,
        )? {
            values.push(proposal);
        }
    }

    values.sort_by(|a, b| {
        a.unit_instance_id
            .cmp(&b.unit_instance_id)
            .then_with(|| {
                a.movement
                    .to
                    .row
                    .cmp(&b.movement.to.row)
            })
            .then_with(|| {
                a.movement
                    .to
                    .col
                    .cmp(&b.movement.to.col)
            })
    });

    Ok(values)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn convention() -> BoardCoordinateConvention {
        BoardCoordinateConvention {
            rows: 4,
            cols: 7,
            front_rows: vec![0],
            back_rows: vec![3],
            left_cols: vec![0, 1],
            right_cols: vec![5, 6],
            center_cols: vec![3],
        }
    }

    fn unit(id: &str, row: u8, col: u8) -> UnitInstance {
        UnitInstance {
            instance_id: id.into(),
            unit_id: id.into(),
            stars: 1,
            position: Some(HexPosition { row, col }),
            items: vec![],
        }
    }

    #[test]
    fn parses_common_positioning_phrases() {
        assert_eq!(
            parse_directive("should be positioned in the front row"),
            Some(PositioningDirective::Front)
        );
        assert_eq!(
            parse_directive("play on the back right corner"),
            Some(PositioningDirective::BackRight)
        );
        assert_eq!(
            parse_directive("mova para a esquerda"),
            Some(PositioningDirective::Left)
        );
    }

    #[test]
    fn proposes_nearest_free_front_cell_without_hardcoded_orientation() {
        let board = vec![
            unit("carry", 3, 3),
            unit("blocker", 0, 3),
        ];

        let proposal = propose_move(
            &board,
            "carry",
            "front row",
            &convention(),
        )
        .unwrap()
        .unwrap();

        assert_eq!(proposal.movement.to.row, 0);
        assert_eq!(proposal.movement.to.col, 3);
    }

    #[test]
    fn occupied_target_is_not_recommended() {
        let board = vec![
            unit("carry", 3, 6),
            unit("blocker", 0, 6),
        ];

        let result = propose_move(
            &board,
            "carry",
            "front right",
            &convention(),
        )
        .unwrap();

        // 0,6 is occupied; 0,5 is the next nearest allowed right-side cell.
        assert_eq!(result.unwrap().movement.to, HexPosition { row: 0, col: 5 });
    }

    #[test]
    fn already_satisfied_hint_generates_no_move() {
        let board = vec![unit("carry", 3, 2)];

        let result = propose_move(
            &board,
            "carry",
            "back row",
            &convention(),
        )
        .unwrap();

        assert!(result.is_none());
    }

    #[test]
    fn invalid_geometry_is_rejected() {
        let mut config = convention();
        config.front_rows = vec![4];

        assert_eq!(
            config.validate().unwrap_err(),
            PositioningError::OutOfBounds
        );
    }
}
