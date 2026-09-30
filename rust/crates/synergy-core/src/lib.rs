use std::collections::{BTreeMap, BTreeSet};

use agente_tft_contracts::UnitInstance;
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_trait_core::TraitCatalog;
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TraitActivation {
    pub trait_id: String,
    pub trait_name: String,
    pub unit_count: u8,
    pub active_breakpoint: Option<u8>,
    pub next_breakpoint: Option<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ClosedTraitBreakpoint {
    pub trait_id: String,
    pub trait_name: String,
    pub from_count: u8,
    pub to_count: u8,
    pub breakpoint: u8,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SynergyDelta {
    pub unit_id: String,
    pub closed_breakpoints: Vec<ClosedTraitBreakpoint>,
    pub affected_traits: Vec<TraitActivation>,
}

pub fn board_trait_state(
    board: &[UnitInstance],
    units: &UnitCatalog,
    traits: &TraitCatalog,
) -> Vec<TraitActivation> {
    let unique_units: BTreeSet<&str> =
        board.iter().map(|unit| unit.unit_id.as_str()).collect();

    let mut counts: BTreeMap<String, u8> = BTreeMap::new();

    for unit_id in unique_units {
        let Some(unit) = units.unit(unit_id) else {
            continue;
        };

        let mut per_unit_seen = BTreeSet::new();
        for trait_ref in &unit.traits {
            let Some(trait_id) = traits.resolve_id(trait_ref) else {
                continue;
            };
            if !per_unit_seen.insert(trait_id.to_string()) {
                continue;
            }
            *counts.entry(trait_id.to_string()).or_insert(0) += 1;
        }
    }

    let mut result = Vec::new();

    for (trait_id, count) in counts {
        let Some(definition) = traits.trait_by_id(&trait_id) else {
            continue;
        };
        let breakpoints = definition.breakpoints();

        let active_breakpoint = breakpoints
            .iter()
            .copied()
            .filter(|threshold| *threshold <= count)
            .max();

        let next_breakpoint = breakpoints
            .iter()
            .copied()
            .find(|threshold| *threshold > count);

        result.push(TraitActivation {
            trait_id,
            trait_name: definition.name.clone(),
            unit_count: count,
            active_breakpoint,
            next_breakpoint,
        });
    }

    result.sort_by(|a, b| a.trait_id.cmp(&b.trait_id));
    result
}

pub fn marginal_add_unit(
    board: &[UnitInstance],
    candidate: &UnitInstance,
    units: &UnitCatalog,
    traits: &TraitCatalog,
) -> SynergyDelta {
    let before = board_trait_state(board, units, traits);

    let already_fielded = board
        .iter()
        .any(|unit| unit.unit_id == candidate.unit_id);

    let mut after_board = board.to_vec();
    after_board.push(candidate.clone());

    let after = board_trait_state(&after_board, units, traits);

    let before_by_id: BTreeMap<_, _> = before
        .iter()
        .map(|value| (value.trait_id.as_str(), value))
        .collect();

    let mut closed = Vec::new();

    if !already_fielded {
        for after_trait in &after {
            let before_count = before_by_id
                .get(after_trait.trait_id.as_str())
                .map(|value| value.unit_count)
                .unwrap_or(0);

            let Some(definition) =
                traits.trait_by_id(&after_trait.trait_id)
            else {
                continue;
            };

            for breakpoint in definition.breakpoints() {
                if before_count < breakpoint
                    && after_trait.unit_count >= breakpoint
                {
                    closed.push(ClosedTraitBreakpoint {
                        trait_id: after_trait.trait_id.clone(),
                        trait_name: after_trait.trait_name.clone(),
                        from_count: before_count,
                        to_count: after_trait.unit_count,
                        breakpoint,
                    });
                }
            }
        }
    }

    closed.sort_by(|a, b| {
        a.trait_id
            .cmp(&b.trait_id)
            .then_with(|| a.breakpoint.cmp(&b.breakpoint))
    });

    SynergyDelta {
        unit_id: candidate.unit_id.clone(),
        closed_breakpoints: closed,
        affected_traits: after,
    }
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::UnitInstance;
    use agente_tft_knowledge_core::UnitCatalog;
    use agente_tft_trait_core::TraitCatalog;

    use super::*;

    fn unit(id: &str) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-1"),
            unit_id: id.into(),
            stars: 1,
            position: None,
            items: vec![],
        }
    }

    fn unit_catalog() -> UnitCatalog {
        UnitCatalog::from_json_str(
            &serde_json::json!({
                "champions": [
                    {"api_name": "A", "name": "A", "cost": 1, "traits": ["Void"]},
                    {"api_name": "B", "name": "B", "cost": 1, "traits": ["Void"]},
                    {"api_name": "C", "name": "C", "cost": 1, "traits": ["Void", "Warden"]},
                    {"api_name": "D", "name": "D", "cost": 1, "traits": ["Warden"]}
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
                        "api_name": "T_VOID",
                        "name": "Void",
                        "effects": [
                            {"min_units": 2},
                            {"min_units": 4}
                        ]
                    },
                    {
                        "api_name": "T_WARDEN",
                        "name": "Warden",
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

    #[test]
    fn duplicate_champion_does_not_count_twice_for_traits() {
        let board = vec![unit("A"), unit("A")];
        let state = board_trait_state(
            &board,
            &unit_catalog(),
            &trait_catalog(),
        );

        let void = state
            .iter()
            .find(|value| value.trait_name == "Void")
            .unwrap();

        assert_eq!(void.unit_count, 1);
        assert_eq!(void.active_breakpoint, None);
        assert_eq!(void.next_breakpoint, Some(2));
    }

    #[test]
    fn adding_unit_detects_new_trait_breakpoints() {
        let board = vec![unit("A"), unit("C")];
        let delta = marginal_add_unit(
            &board,
            &unit("D"),
            &unit_catalog(),
            &trait_catalog(),
        );

        let warden = delta
            .closed_breakpoints
            .iter()
            .find(|value| value.trait_name == "Warden")
            .unwrap();

        assert_eq!(warden.from_count, 1);
        assert_eq!(warden.to_count, 2);
        assert_eq!(warden.breakpoint, 2);
    }

    #[test]
    fn adding_duplicate_unit_closes_no_trait_breakpoint() {
        let board = vec![unit("A")];
        let delta = marginal_add_unit(
            &board,
            &unit("A"),
            &unit_catalog(),
            &trait_catalog(),
        );

        assert!(delta.closed_breakpoints.is_empty());
    }
}
