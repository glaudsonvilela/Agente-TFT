use agente_tft_contracts::{
    Confidence, GameEventKind, ObservationSource, Observed, ShopSlot,
};
use agente_tft_perception_core::ConsensusConfig;
use agente_tft_state_fusion::{ShopObservationBatch, StateFusion};

fn slot(index: u8, unit: &str, confidence: f32, at: u64) -> Observed<ShopSlot> {
    Observed {
        value: ShopSlot {
            slot: index,
            unit_id: Some(unit.into()),
        },
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

#[test]
fn one_shop_frame_does_not_change_state() {
    let mut fusion = fusion();
    let events = fusion.apply_shop(ShopObservationBatch {
        observed_at_ms: 100,
        slots: vec![slot(0, "A", 0.95, 100), slot(1, "B", 0.93, 100)],
    });

    assert!(events.is_empty());
    assert!(fusion.state().player.shop.is_empty());
    assert_eq!(fusion.state().revision, 0);
}

#[test]
fn repeated_shop_snapshot_is_promoted() {
    let mut fusion = fusion();

    fusion.apply_shop(ShopObservationBatch {
        observed_at_ms: 100,
        slots: vec![slot(0, "A", 0.90, 100), slot(1, "B", 0.91, 100)],
    });

    let events = fusion.apply_shop(ShopObservationBatch {
        observed_at_ms: 150,
        slots: vec![slot(0, "A", 0.95, 150), slot(1, "B", 0.94, 150)],
    });

    assert_eq!(fusion.state().player.shop.len(), 2);
    assert_eq!(fusion.state().revision, 1);
    assert!(events
        .iter()
        .any(|event| matches!(event, GameEventKind::ShopChanged)));
}

#[test]
fn conflicting_snapshot_restarts_consensus() {
    let mut fusion = fusion();

    fusion.apply_shop(ShopObservationBatch {
        observed_at_ms: 100,
        slots: vec![slot(0, "A", 0.95, 100)],
    });

    fusion.apply_shop(ShopObservationBatch {
        observed_at_ms: 150,
        slots: vec![slot(0, "B", 0.95, 150)],
    });

    assert!(fusion.state().player.shop.is_empty());

    fusion.apply_shop(ShopObservationBatch {
        observed_at_ms: 200,
        slots: vec![slot(0, "B", 0.95, 200)],
    });

    assert_eq!(
        fusion.state().player.shop[0].value.unit_id.as_deref(),
        Some("B")
    );
}

#[test]
fn one_low_confidence_slot_blocks_whole_snapshot() {
    let mut fusion = fusion();

    for at in [100, 150, 200] {
        fusion.apply_shop(ShopObservationBatch {
            observed_at_ms: at,
            slots: vec![
                slot(0, "A", 0.95, at),
                slot(1, "B", 0.60, at),
            ],
        });
    }

    assert!(fusion.state().player.shop.is_empty());
}

#[test]
fn duplicate_slot_indices_are_rejected_as_unstable_input() {
    let mut fusion = fusion();

    for at in [100, 150] {
        fusion.apply_shop(ShopObservationBatch {
            observed_at_ms: at,
            slots: vec![
                slot(0, "A", 0.95, at),
                slot(0, "B", 0.95, at),
            ],
        });
    }

    assert!(fusion.state().player.shop.is_empty());
}
