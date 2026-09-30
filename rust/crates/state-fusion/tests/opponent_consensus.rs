use agente_tft_contracts::{
    Confidence, GameEventKind, HexPosition, ObservationSource, Observed, UnitInstance,
};
use agente_tft_perception_core::ConsensusConfig;
use agente_tft_state_fusion::{OpponentObservationBatch, StateFusion};

fn obs<T>(value: T, confidence: f32, at: u64) -> Observed<T> {
    Observed {
        value,
        confidence: Confidence::new(confidence).unwrap(),
        source: ObservationSource::Vision,
        observed_at_ms: at,
    }
}

fn unit(id: &str, stars: u8, row: u8, col: u8, confidence: f32, at: u64) -> Observed<UnitInstance> {
    obs(
        UnitInstance {
            instance_id: format!("{id}-{row}-{col}"),
            unit_id: id.into(),
            stars,
            position: Some(HexPosition { row, col }),
            items: vec![],
        },
        confidence,
        at,
    )
}

fn config() -> ConsensusConfig {
    ConsensusConfig {
        min_confidence: 0.80,
        confirmations: 2,
        max_gap_ms: 500,
    }
}

fn batch(
    player: &str,
    at: u64,
    units: Vec<Observed<UnitInstance>>,
) -> OpponentObservationBatch {
    OpponentObservationBatch {
        player_id: player.into(),
        display_name: Some(player.into()),
        hp: Some(obs(50u16, 0.95, at)),
        level: Some(obs(7u8, 0.95, at)),
        board: units,
        complete_board: true,
        observed_at_ms: at,
    }
}

#[test]
fn one_scout_frame_does_not_enter_lobby() {
    let mut fusion = StateFusion::new(0, config());
    let events = fusion.apply_opponent(
        batch("p2", 100, vec![unit("X", 2, 0, 0, 0.95, 100)]),
        config(),
    );

    assert!(events.is_empty());
    assert!(fusion.state().lobby.is_empty());
}

#[test]
fn repeated_scout_snapshot_is_promoted_and_counts_contestation() {
    let mut fusion = StateFusion::new(0, config());

    fusion.apply_opponent(
        batch("p2", 100, vec![unit("X", 2, 0, 0, 0.95, 100)]),
        config(),
    );

    let events = fusion.apply_opponent(
        batch("p2", 150, vec![unit("X", 2, 0, 0, 0.96, 150)]),
        config(),
    );

    assert_eq!(fusion.state().lobby.len(), 1);
    assert_eq!(fusion.state().lobby[0].player_id, "p2");

    assert!(events.iter().any(|event| matches!(
        event,
        GameEventKind::OpponentObserved { player_id } if player_id == "p2"
    )));

    assert!(events.iter().any(|event| matches!(
        event,
        GameEventKind::ContestationChanged {
            unit_id,
            observed_copies_before: 0,
            observed_copies_after: 3,
        } if unit_id == "X"
    )));
}

#[test]
fn same_stable_snapshot_is_not_emitted_repeatedly() {
    let mut fusion = StateFusion::new(0, config());

    for at in [100, 150] {
        fusion.apply_opponent(
            batch("p2", at, vec![unit("X", 2, 0, 0, 0.95, at)]),
            config(),
        );
    }
    let revision = fusion.state().revision;

    let events = fusion.apply_opponent(
        batch("p2", 200, vec![unit("X", 2, 0, 0, 0.95, 200)]),
        config(),
    );

    assert!(events.is_empty());
    assert_eq!(fusion.state().revision, revision);
}

#[test]
fn changed_board_requires_new_consensus() {
    let mut fusion = StateFusion::new(0, config());

    for at in [100, 150] {
        fusion.apply_opponent(
            batch("p2", at, vec![unit("X", 2, 0, 0, 0.95, at)]),
            config(),
        );
    }
    let revision = fusion.state().revision;

    fusion.apply_opponent(
        batch("p2", 200, vec![unit("Y", 1, 0, 0, 0.95, 200)]),
        config(),
    );

    assert_eq!(fusion.state().revision, revision);

    let events = fusion.apply_opponent(
        batch("p2", 250, vec![unit("Y", 1, 0, 0, 0.95, 250)]),
        config(),
    );

    assert!(fusion.state().revision > revision);
    assert!(events.iter().any(|event| matches!(
        event,
        GameEventKind::ContestationChanged { unit_id, .. } if unit_id == "X" || unit_id == "Y"
    )));
}

#[test]
fn incomplete_board_never_enters_lobby() {
    let mut fusion = StateFusion::new(0, config());

    let mut incomplete = batch(
        "p2",
        100,
        vec![unit("X", 2, 0, 0, 0.95, 100)],
    );
    incomplete.complete_board = false;

    for _ in 0..3 {
        fusion.apply_opponent(incomplete.clone(), config());
    }

    assert!(fusion.state().lobby.is_empty());
}
