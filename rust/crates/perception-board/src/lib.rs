use std::collections::{BTreeMap, BTreeSet};

use agente_tft_contracts::{Confidence, HexPosition};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const BOARD_GEOMETRY_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error, PartialEq)]
pub enum BoardPerceptionError {
    #[error("invalid board geometry: {0}")]
    InvalidGeometry(String),
    #[error("detection confidence must be finite and in [0,1]")]
    InvalidConfidence,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct NormalizedPoint {
    pub x: f32,
    pub y: f32,
}

impl NormalizedPoint {
    pub fn validate(self) -> Result<(), BoardPerceptionError> {
        if !self.x.is_finite()
            || !self.y.is_finite()
            || !(0.0..=1.0).contains(&self.x)
            || !(0.0..=1.0).contains(&self.y)
        {
            return Err(BoardPerceptionError::InvalidGeometry(
                "point must be finite and inside [0,1]".into(),
            ));
        }
        Ok(())
    }

    fn squared_distance(self, other: Self) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        dx * dx + dy * dy
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct NormalizedBox {
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
}

impl NormalizedBox {
    pub fn validate(self) -> Result<(), BoardPerceptionError> {
        let values = [self.x, self.y, self.width, self.height];
        if values.iter().any(|value| !value.is_finite())
            || self.x < 0.0
            || self.y < 0.0
            || self.width <= 0.0
            || self.height <= 0.0
            || self.x + self.width > 1.0
            || self.y + self.height > 1.0
        {
            return Err(BoardPerceptionError::InvalidGeometry(
                "box must be finite and fully inside [0,1]".into(),
            ));
        }
        Ok(())
    }

    pub fn center(self) -> NormalizedPoint {
        NormalizedPoint {
            x: self.x + self.width * 0.5,
            y: self.y + self.height * 0.5,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardCell {
    pub position: HexPosition,
    pub center: NormalizedPoint,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardGeometry {
    pub schema_version: u32,
    pub name: String,
    pub reference_width: u32,
    pub reference_height: u32,
    /// Maximum normalized Euclidean distance from a detection center to a cell center.
    pub max_assignment_distance: f32,
    pub cells: Vec<BoardCell>,
}

impl BoardGeometry {
    pub fn validate(&self) -> Result<(), BoardPerceptionError> {
        if self.schema_version != BOARD_GEOMETRY_SCHEMA_VERSION {
            return Err(BoardPerceptionError::InvalidGeometry(format!(
                "unsupported schema_version {}",
                self.schema_version
            )));
        }
        if self.name.trim().is_empty() {
            return Err(BoardPerceptionError::InvalidGeometry(
                "name cannot be empty".into(),
            ));
        }
        if self.reference_width == 0 || self.reference_height == 0 {
            return Err(BoardPerceptionError::InvalidGeometry(
                "reference dimensions must be > 0".into(),
            ));
        }
        if !self.max_assignment_distance.is_finite()
            || self.max_assignment_distance <= 0.0
            || self.max_assignment_distance > 1.0
        {
            return Err(BoardPerceptionError::InvalidGeometry(
                "max_assignment_distance must be in (0,1]".into(),
            ));
        }
        if self.cells.is_empty() {
            return Err(BoardPerceptionError::InvalidGeometry(
                "at least one board cell is required".into(),
            ));
        }

        let mut positions = BTreeSet::new();
        for cell in &self.cells {
            cell.center.validate()?;
            let key = (cell.position.row, cell.position.col);
            if !positions.insert(key) {
                return Err(BoardPerceptionError::InvalidGeometry(format!(
                    "duplicate board position {},{}",
                    cell.position.row, cell.position.col
                )));
            }
        }
        Ok(())
    }

    pub fn nearest_cell(&self, point: NormalizedPoint) -> Option<(HexPosition, f32)> {
        if point.validate().is_err() {
            return None;
        }

        let mut best: Option<(&BoardCell, f32)> = None;
        for cell in &self.cells {
            let distance_sq = point.squared_distance(cell.center);
            match best {
                None => best = Some((cell, distance_sq)),
                Some((_, current)) if distance_sq < current => {
                    best = Some((cell, distance_sq))
                }
                _ => {}
            }
        }

        let (cell, distance_sq) = best?;
        let distance = distance_sq.sqrt();
        if distance > self.max_assignment_distance {
            None
        } else {
            Some((cell.position, distance))
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UnitDetection {
    pub unit_id: String,
    pub bbox: NormalizedBox,
    pub confidence: Confidence,
    #[serde(default)]
    pub stars: Option<u8>,
}

impl UnitDetection {
    pub fn validate(&self) -> Result<(), BoardPerceptionError> {
        if self.unit_id.trim().is_empty() {
            return Err(BoardPerceptionError::InvalidGeometry(
                "unit_id cannot be empty".into(),
            ));
        }
        self.bbox.validate()?;
        if let Some(stars) = self.stars {
            if stars == 0 || stars > 4 {
                return Err(BoardPerceptionError::InvalidGeometry(
                    "stars must be in [1,4] when present".into(),
                ));
            }
        }
        Ok(())
    }
}

pub trait BoardDetector {
    fn detect(
        &mut self,
        image_width: u32,
        image_height: u32,
        rgba: &[u8],
    ) -> Result<Vec<UnitDetection>, String>;
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AssignedUnit {
    pub unit_id: String,
    pub position: HexPosition,
    pub confidence: Confidence,
    pub stars: Option<u8>,
    pub assignment_distance: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AssignmentDiagnostics {
    pub assigned: Vec<AssignedUnit>,
    pub unassigned: Vec<UnitDetection>,
    pub conflicts_dropped: Vec<UnitDetection>,
}

pub fn assign_detections(
    geometry: &BoardGeometry,
    detections: impl IntoIterator<Item = UnitDetection>,
    min_confidence: f32,
) -> Result<AssignmentDiagnostics, BoardPerceptionError> {
    geometry.validate()?;

    if !min_confidence.is_finite() || !(0.0..=1.0).contains(&min_confidence) {
        return Err(BoardPerceptionError::InvalidConfidence);
    }

    let mut by_cell: BTreeMap<(u8, u8), (AssignedUnit, UnitDetection)> = BTreeMap::new();
    let mut unassigned = Vec::new();
    let mut conflicts_dropped = Vec::new();

    for detection in detections {
        detection.validate()?;

        if detection.confidence.value() < min_confidence {
            unassigned.push(detection);
            continue;
        }

        let Some((position, distance)) = geometry.nearest_cell(detection.bbox.center()) else {
            unassigned.push(detection);
            continue;
        };

        let assigned = AssignedUnit {
            unit_id: detection.unit_id.clone(),
            position,
            confidence: detection.confidence,
            stars: detection.stars,
            assignment_distance: distance,
        };

        let key = (position.row, position.col);
        match by_cell.remove(&key) {
            None => {
                by_cell.insert(key, (assigned, detection));
            }
            Some((current_assigned, current_detection)) => {
                let new_is_better = detection.confidence.value()
                    > current_assigned.confidence.value()
                    || (detection.confidence.value() == current_assigned.confidence.value()
                        && distance < current_assigned.assignment_distance);

                if new_is_better {
                    conflicts_dropped.push(current_detection);
                    by_cell.insert(key, (assigned, detection));
                } else {
                    conflicts_dropped.push(detection);
                    by_cell.insert(key, (current_assigned, current_detection));
                }
            }
        }
    }

    let assigned = by_cell
        .into_values()
        .map(|(assigned, _)| assigned)
        .collect();

    Ok(AssignmentDiagnostics {
        assigned,
        unassigned,
        conflicts_dropped,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn confidence(value: f32) -> Confidence {
        Confidence::new(value).unwrap()
    }

    fn geometry() -> BoardGeometry {
        BoardGeometry {
            schema_version: BOARD_GEOMETRY_SCHEMA_VERSION,
            name: "fixture".into(),
            reference_width: 100,
            reference_height: 100,
            max_assignment_distance: 0.20,
            cells: vec![
                BoardCell {
                    position: HexPosition { row: 0, col: 0 },
                    center: NormalizedPoint { x: 0.25, y: 0.5 },
                },
                BoardCell {
                    position: HexPosition { row: 0, col: 1 },
                    center: NormalizedPoint { x: 0.75, y: 0.5 },
                },
            ],
        }
    }

    fn detection(unit_id: &str, x: f32, confidence_value: f32) -> UnitDetection {
        UnitDetection {
            unit_id: unit_id.into(),
            bbox: NormalizedBox {
                x,
                y: 0.4,
                width: 0.1,
                height: 0.2,
            },
            confidence: confidence(confidence_value),
            stars: Some(2),
        }
    }

    #[test]
    fn assigns_detection_to_nearest_cell() {
        let result = assign_detections(
            &geometry(),
            [detection("A", 0.20, 0.95)],
            0.80,
        )
        .unwrap();

        assert_eq!(result.assigned.len(), 1);
        assert_eq!(
            result.assigned[0].position,
            HexPosition { row: 0, col: 0 }
        );
    }

    #[test]
    fn far_detection_is_left_unassigned() {
        let mut g = geometry();
        g.max_assignment_distance = 0.05;

        let result = assign_detections(
            &g,
            [detection("A", 0.40, 0.95)],
            0.80,
        )
        .unwrap();

        assert!(result.assigned.is_empty());
        assert_eq!(result.unassigned.len(), 1);
    }

    #[test]
    fn conflict_keeps_higher_confidence_detection() {
        let result = assign_detections(
            &geometry(),
            [
                detection("A", 0.20, 0.85),
                detection("B", 0.21, 0.95),
            ],
            0.80,
        )
        .unwrap();

        assert_eq!(result.assigned.len(), 1);
        assert_eq!(result.assigned[0].unit_id, "B");
        assert_eq!(result.conflicts_dropped.len(), 1);
        assert_eq!(result.conflicts_dropped[0].unit_id, "A");
    }

    #[test]
    fn low_confidence_detection_never_enters_board() {
        let result = assign_detections(
            &geometry(),
            [detection("A", 0.20, 0.50)],
            0.80,
        )
        .unwrap();

        assert!(result.assigned.is_empty());
        assert_eq!(result.unassigned.len(), 1);
    }

    #[test]
    fn duplicate_geometry_cells_are_rejected() {
        let mut invalid = geometry();
        invalid.cells.push(invalid.cells[0].clone());
        assert!(invalid.validate().is_err());
    }
}
