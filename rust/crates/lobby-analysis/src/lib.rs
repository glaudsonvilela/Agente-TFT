use std::collections::BTreeMap;

use agente_tft_contracts::{GameState, OpponentState, UnitInstance};
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ContestingPlayer {
    pub player_id: String,
    pub display_name: Option<String>,
    pub observed_copies: u16,
    pub unit_instances: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UnitContestation {
    pub unit_id: String,
    pub observed_opponent_copies: u16,
    pub contesting_players: Vec<ContestingPlayer>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ContestedUnitSummary {
    pub unit_id: String,
    pub observed_opponent_copies: u16,
    pub contesting_players: usize,
}

pub fn copies_represented_by_stars(stars: u8) -> u16 {
    match stars {
        0 | 1 => 1,
        2 => 3,
        3 => 9,
        _ => 27,
    }
}

pub fn analyze_unit_contestation(
    state: &GameState,
    unit_id: &str,
) -> UnitContestation {
    let mut players = Vec::new();
    let mut total = 0u16;

    for opponent in &state.lobby {
        let (copies, instances) = player_unit_copies(opponent, unit_id);
        if copies == 0 {
            continue;
        }

        total = total.saturating_add(copies);
        players.push(ContestingPlayer {
            player_id: opponent.player_id.clone(),
            display_name: opponent.display_name.clone(),
            observed_copies: copies,
            unit_instances: instances,
        });
    }

    players.sort_by(|a, b| {
        b.observed_copies
            .cmp(&a.observed_copies)
            .then_with(|| a.player_id.cmp(&b.player_id))
    });

    UnitContestation {
        unit_id: unit_id.to_string(),
        observed_opponent_copies: total,
        contesting_players: players,
    }
}

pub fn summarize_contested_units(state: &GameState) -> Vec<ContestedUnitSummary> {
    let mut by_unit: BTreeMap<String, (u16, std::collections::BTreeSet<String>)> =
        BTreeMap::new();

    for opponent in &state.lobby {
        let mut per_player: BTreeMap<String, u16> = BTreeMap::new();

        for unit in &opponent.board {
            let copies = copies_represented_by_stars(unit.stars);
            let entry = per_player.entry(unit.unit_id.clone()).or_insert(0);
            *entry = entry.saturating_add(copies);
        }

        for (unit_id, copies) in per_player {
            let entry = by_unit
                .entry(unit_id)
                .or_insert_with(|| (0, std::collections::BTreeSet::new()));
            entry.0 = entry.0.saturating_add(copies);
            entry.1.insert(opponent.player_id.clone());
        }
    }

    let mut result: Vec<_> = by_unit
        .into_iter()
        .map(|(unit_id, (copies, players))| ContestedUnitSummary {
            unit_id,
            observed_opponent_copies: copies,
            contesting_players: players.len(),
        })
        .collect();

    result.sort_by(|a, b| {
        b.observed_opponent_copies
            .cmp(&a.observed_opponent_copies)
            .then_with(|| b.contesting_players.cmp(&a.contesting_players))
            .then_with(|| a.unit_id.cmp(&b.unit_id))
    });

    result
}

fn player_unit_copies(opponent: &OpponentState, unit_id: &str) -> (u16, usize) {
    let mut copies = 0u16;
    let mut instances = 0usize;

    for unit in &opponent.board {
        if unit.unit_id == unit_id {
            copies = copies.saturating_add(copies_represented_by_stars(unit.stars));
            instances += 1;
        }
    }

    (copies, instances)
}

pub fn self_owned_copies(state: &GameState, unit_id: &str) -> u16 {
    state
        .player
        .board
        .iter()
        .chain(state.player.bench.iter())
        .filter(|unit| unit.unit_id == unit_id)
        .fold(0u16, |total, unit| {
            total.saturating_add(copies_represented_by_stars(unit.stars))
        })
}

pub fn observed_total_copies(state: &GameState, unit_id: &str) -> u16 {
    self_owned_copies(state, unit_id)
        .saturating_add(analyze_unit_contestation(state, unit_id).observed_opponent_copies)
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{
        Confidence, HexPosition, OpponentState, PlayerState,
    };

    use super::*;

    fn unit(id: &str, stars: u8, row: u8, col: u8) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-{row}-{col}"),
            unit_id: id.into(),
            stars,
            position: Some(HexPosition { row, col }),
            items: vec![],
        }
    }

    fn opponent(id: &str, units: Vec<UnitInstance>) -> OpponentState {
        OpponentState {
            player_id: id.into(),
            display_name: Some(id.into()),
            hp: None,
            level: None,
            board: units,
            last_seen_ms: 100,
            confidence: Confidence::new(0.95).unwrap(),
        }
    }

    fn state() -> GameState {
        let mut state = GameState::empty(0);
        state.player = PlayerState {
            board: vec![unit("X", 1, 0, 0)],
            bench: vec![unit("X", 2, 0, 1)],
            ..PlayerState::default()
        };
        state.lobby = vec![
            opponent("p2", vec![unit("X", 2, 0, 0), unit("Y", 1, 0, 1)]),
            opponent("p3", vec![unit("X", 1, 0, 0), unit("Y", 2, 0, 1)]),
        ];
        state
    }

    #[test]
    fn star_levels_map_to_copy_counts() {
        assert_eq!(copies_represented_by_stars(1), 1);
        assert_eq!(copies_represented_by_stars(2), 3);
        assert_eq!(copies_represented_by_stars(3), 9);
    }

    #[test]
    fn analyzes_players_contesting_target_unit() {
        let analysis = analyze_unit_contestation(&state(), "X");
        assert_eq!(analysis.observed_opponent_copies, 4);
        assert_eq!(analysis.contesting_players.len(), 2);
        assert_eq!(analysis.contesting_players[0].player_id, "p2");
        assert_eq!(analysis.contesting_players[0].observed_copies, 3);
    }

    #[test]
    fn self_owned_counts_board_and_bench() {
        assert_eq!(self_owned_copies(&state(), "X"), 4);
    }

    #[test]
    fn observed_total_combines_self_and_opponents() {
        assert_eq!(observed_total_copies(&state(), "X"), 8);
    }

    #[test]
    fn contested_summary_sorts_by_observed_copies() {
        let summary = summarize_contested_units(&state());
        assert_eq!(summary[0].unit_id, "X");
        assert_eq!(summary[0].observed_opponent_copies, 4);
        assert_eq!(summary[1].unit_id, "Y");
        assert_eq!(summary[1].observed_opponent_copies, 4);
    }
}
