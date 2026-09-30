use agente_tft_contracts::{
    Confidence, GameEventKind, ObservationSource, Observed,
};
use agente_tft_perception_core::ConsensusConfig;
use agente_tft_state_fusion::{
    AugmentObservationBatch, StateFusion,
};

fn option(id: &str, confidence: f32, at: u64) -> Observed<String> {
    Observed {
        value: id.into(),
        confidence: Confidence::new(confidence).unwrap(),
        source: ObservationSource::Vision,
        observed_at_ms: at,
    }
}

fn fusion() -> StateFusion {
    StateFusion::new(
        0,
        ConsensusConfig {
            min_confidence: 0.80,
            confirmations: 2,
            max_gap_ms: 500,
        },
    )
}

fn batch(
    at: u64,
    ids: &[&str],
    complete: bool,
) -> AugmentObservationBatch {
    AugmentObservationBatch {
        observed_at_ms: at,
        options: ids
            .iter()
            .map(|id| option(id, 0.95, at))
            .collect(),
        complete,
    }
}

#[test]
fn one_frame_does_not_promote_augment_options() {
    let mut fusion = fusion();

    let events = fusion.apply_augment_options(
        batch(100, &["A", "B", "C"], true),
    );

    assert!(events.is_empty());
    assert!(fusion.state().player.augment_options.is_empty());
}

#[test]
fn repeated_complete_snapshot_is_promoted() {
    let mut fusion = fusion();

    fusion.apply_augment_options(
        batch(100, &["A", "B", "C"], true),
    );
    let events = fusion.apply_augment_options(
        batch(150, &["A", "B", "C"], true),
    );

    assert_eq!(fusion.state().player.augment_options.len(), 3);
    assert_eq!(fusion.state().revision, 1);
    assert!(events.iter().any(|event| matches!(
        event,
        GameEventKind::AugmentOptionsChanged
    )));
}

#[test]
fn incomplete_snapshot_never_promotes() {
    let mut fusion = fusion();

    for at in [100, 150, 200] {
        fusion.apply_augment_options(
            batch(at, &["A", "B"], false),
        );
    }

    assert!(fusion.state().player.augment_options.is_empty());
}

#[test]
fn conflicting_snapshot_restarts_consensus() {
    let mut fusion = fusion();

    fusion.apply_augment_options(
        batch(100, &["A", "B", "C"], true),
    );
    fusion.apply_augment_options(
        batch(150, &["A", "B", "D"], true),
    );

    assert!(fusion.state().player.augment_options.is_empty());

    fusion.apply_augment_options(
        batch(200, &["A", "B", "D"], true),
    );

    let values: Vec<_> = fusion
        .state()
        .player
        .augment_options
        .iter()
        .map(|value| value.value.as_str())
        .collect();

    assert_eq!(values, vec!["A", "B", "D"]);
}

#[test]
fn duplicate_option_ids_are_rejected() {
    let mut fusion = fusion();

    for at in [100, 150] {
        fusion.apply_augment_options(
            batch(at, &["A", "A", "C"], true),
        );
    }

    assert!(fusion.state().player.augment_options.is_empty());
}
