use std::collections::{BTreeMap, BTreeSet};

use agente_tft_contracts::{
    GameEventKind, GameState, MatchPhase, Observed, ShopSlot, UnitInstance,
};

pub fn diff_event_kinds(previous: &GameState, current: &GameState) -> Vec<GameEventKind> {
    let mut events = Vec::new();

    if previous.match_id.is_none() && current.match_id.is_some() {
        events.push(GameEventKind::MatchStarted);
    }

    if previous.phase != current.phase {
        match current.phase {
            MatchPhase::Combat => events.push(GameEventKind::CombatStarted),
            MatchPhase::PostCombat | MatchPhase::Planning
                if previous.phase == MatchPhase::Combat =>
            {
                events.push(GameEventKind::CombatEnded)
            }
            MatchPhase::AugmentSelection => events.push(GameEventKind::AugmentScreen),
            MatchPhase::MatchEnded => events.push(GameEventKind::MatchEnded),
            _ => {}
        }
    }

    if observed_value(&previous.player.stage) != observed_value(&current.player.stage) {
        if let Some(to) = observed_value(&current.player.stage).cloned() {
            events.push(GameEventKind::RoundChanged {
                from: observed_value(&previous.player.stage).cloned(),
                to,
            });
        }
    }

    push_numeric_change_u16(
        &mut events,
        &previous.player.gold,
        &current.player.gold,
        |from, to| GameEventKind::GoldChanged { from, to },
    );
    push_numeric_change_u16(
        &mut events,
        &previous.player.hp,
        &current.player.hp,
        |from, to| GameEventKind::HpChanged { from, to },
    );
    push_numeric_change_u8(
        &mut events,
        &previous.player.level,
        &current.player.level,
        |from, to| GameEventKind::LevelChanged { from, to },
    );

    if semantic_shop(&previous.player.shop) != semantic_shop(&current.player.shop) {
        events.push(GameEventKind::ShopChanged);
    }

    if previous.player.board != current.player.board {
        events.push(GameEventKind::BoardChanged);
    }

    if previous.player.bench != current.player.bench {
        events.push(GameEventKind::BenchChanged);
    }

    push_added_items(&mut events, &previous.player.items, &current.player.items);
    push_opponent_observations(&mut events, previous, current);
    push_contestation_changes(&mut events, previous, current);

    events
}

fn observed_value<T>(value: &Option<Observed<T>>) -> Option<&T> {
    value.as_ref().map(|v| &v.value)
}

fn push_numeric_change_u16<F>(
    events: &mut Vec<GameEventKind>,
    previous: &Option<Observed<u16>>,
    current: &Option<Observed<u16>>,
    make: F,
) where
    F: FnOnce(u16, u16) -> GameEventKind,
{
    if let (Some(from), Some(to)) = (observed_value(previous), observed_value(current)) {
        if from != to {
            events.push(make(*from, *to));
        }
    }
}

fn push_numeric_change_u8<F>(
    events: &mut Vec<GameEventKind>,
    previous: &Option<Observed<u8>>,
    current: &Option<Observed<u8>>,
    make: F,
) where
    F: FnOnce(u8, u8) -> GameEventKind,
{
    if let (Some(from), Some(to)) = (observed_value(previous), observed_value(current)) {
        if from != to {
            events.push(make(*from, *to));
        }
    }
}

fn semantic_shop(shop: &[Observed<ShopSlot>]) -> Vec<(u8, Option<String>)> {
    let mut result: Vec<_> = shop
        .iter()
        .map(|slot| (slot.value.slot, slot.value.unit_id.clone()))
        .collect();
    result.sort_by_key(|(slot, _)| *slot);
    result
}

fn item_counts(items: &[String]) -> BTreeMap<&str, usize> {
    let mut counts = BTreeMap::new();
    for item in items {
        *counts.entry(item.as_str()).or_insert(0) += 1;
    }
    counts
}

fn push_added_items(
    events: &mut Vec<GameEventKind>,
    previous: &[String],
    current: &[String],
) {
    let before = item_counts(previous);
    let after = item_counts(current);

    for (item, after_count) in after {
        let before_count = before.get(item).copied().unwrap_or(0);
        for _ in before_count..after_count {
            events.push(GameEventKind::ItemAdded {
                item_id: item.to_string(),
            });
        }
    }
}

fn push_opponent_observations(
    events: &mut Vec<GameEventKind>,
    previous: &GameState,
    current: &GameState,
) {
    let previous_by_id: BTreeMap<_, _> = previous
        .lobby
        .iter()
        .map(|opponent| (opponent.player_id.as_str(), opponent))
        .collect();

    for opponent in &current.lobby {
        let changed = previous_by_id
            .get(opponent.player_id.as_str())
            .map(|old| {
                opponent.last_seen_ms > old.last_seen_ms
                    || opponent.board != old.board
                    || opponent.level != old.level
                    || opponent.hp != old.hp
            })
            .unwrap_or(true);

        if changed {
            events.push(GameEventKind::OpponentObserved {
                player_id: opponent.player_id.clone(),
            });
        }
    }
}

fn push_contestation_changes(
    events: &mut Vec<GameEventKind>,
    previous: &GameState,
    current: &GameState,
) {
    let before = lobby_unit_copy_counts(previous);
    let after = lobby_unit_copy_counts(current);

    let unit_ids: BTreeSet<_> = before
        .keys()
        .chain(after.keys())
        .cloned()
        .collect();

    for unit_id in unit_ids {
        let old = before.get(&unit_id).copied().unwrap_or(0);
        let new = after.get(&unit_id).copied().unwrap_or(0);

        if old != new {
            events.push(GameEventKind::ContestationChanged {
                unit_id,
                observed_copies_before: old,
                observed_copies_after: new,
            });
        }
    }
}

pub fn lobby_unit_copy_counts(state: &GameState) -> BTreeMap<String, u16> {
    let mut counts = BTreeMap::new();

    for opponent in &state.lobby {
        for unit in &opponent.board {
            let copies = copies_for_stars(unit.stars);
            let entry = counts.entry(unit.unit_id.clone()).or_insert(0u16);
            *entry = entry.saturating_add(copies);
        }
    }

    counts
}

fn copies_for_stars(stars: u8) -> u16 {
    match stars {
        0 | 1 => 1,
        2 => 3,
        3 => 9,
        _ => 27,
    }
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{
        Confidence, GameState, MatchPhase, ObservationSource, Observed, OpponentState, PlayerState,
        ShopSlot, UnitInstance,
    };

    use super::*;

    fn observed<T>(value: T) -> Observed<T> {
        Observed {
            value,
            confidence: Confidence::new(1.0).unwrap(),
            source: ObservationSource::Simulator,
            observed_at_ms: 100,
        }
    }

    fn state() -> GameState {
        let mut state = GameState::empty(100);
        state.match_id = Some("m1".into());
        state.phase = MatchPhase::Planning;
        state.player = PlayerState {
            hp: Some(observed(80)),
            gold: Some(observed(50)),
            level: Some(observed(7)),
            xp: Some(observed(0)),
            stage: Some(observed("4-1".to_string())),
            board: vec![],
            bench: vec![],
            shop: vec![observed(ShopSlot {
                slot: 0,
                unit_id: Some("A".into()),
            })],
            items: vec![],
            augments: vec![],
        };
        state
    }

    fn unit(id: &str, stars: u8) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-{stars}"),
            unit_id: id.into(),
            stars,
            position: None,
            items: vec![],
        }
    }

    #[test]
    fn detects_basic_player_changes() {
        let previous = state();
        let mut current = previous.clone();
        current.revision = 1;
        current.player.gold = Some(observed(48));
        current.player.hp = Some(observed(73));
        current.player.level = Some(observed(8));
        current.player.stage = Some(observed("4-2".to_string()));
        current.player.shop = vec![observed(ShopSlot {
            slot: 0,
            unit_id: Some("B".into()),
        })];

        let events = diff_event_kinds(&previous, &current);

        assert!(events.iter().any(|e| matches!(
            e,
            GameEventKind::GoldChanged { from: 50, to: 48 }
        )));
        assert!(events.iter().any(|e| matches!(
            e,
            GameEventKind::HpChanged { from: 80, to: 73 }
        )));
        assert!(events.iter().any(|e| matches!(
            e,
            GameEventKind::LevelChanged { from: 7, to: 8 }
        )));
        assert!(events.iter().any(|e| matches!(e, GameEventKind::ShopChanged)));
        assert!(events.iter().any(|e| matches!(
            e,
            GameEventKind::RoundChanged { from: Some(from), to }
            if from == "4-1" && to == "4-2"
        )));
    }

    #[test]
    fn entering_combat_emits_combat_started() {
        let previous = state();
        let mut current = previous.clone();
        current.phase = MatchPhase::Combat;

        assert!(diff_event_kinds(&previous, &current)
            .iter()
            .any(|e| matches!(e, GameEventKind::CombatStarted)));
    }

    #[test]
    fn opponent_two_star_counts_as_three_observed_copies() {
        let mut current = state();
        current.lobby.push(OpponentState {
            player_id: "p2".into(),
            display_name: None,
            hp: None,
            level: None,
            board: vec![unit("X", 2)],
            last_seen_ms: 200,
            confidence: Confidence::new(1.0).unwrap(),
        });

        assert_eq!(lobby_unit_copy_counts(&current).get("X"), Some(&3));
    }

    #[test]
    fn contestation_change_is_emitted() {
        let previous = state();
        let mut current = previous.clone();
        current.lobby.push(OpponentState {
            player_id: "p2".into(),
            display_name: None,
            hp: None,
            level: None,
            board: vec![unit("X", 2)],
            last_seen_ms: 200,
            confidence: Confidence::new(1.0).unwrap(),
        });

        let events = diff_event_kinds(&previous, &current);
        assert!(events.iter().any(|e| matches!(
            e,
            GameEventKind::ContestationChanged {
                unit_id,
                observed_copies_before: 0,
                observed_copies_after: 3
            } if unit_id == "X"
        )));
    }

    #[test]
    fn timestamp_only_shop_updates_do_not_emit_shop_changed() {
        let previous = state();
        let mut current = previous.clone();
        current.player.shop[0].observed_at_ms = 999;

        assert!(!diff_event_kinds(&previous, &current)
            .iter()
            .any(|e| matches!(e, GameEventKind::ShopChanged)));
    }
}
