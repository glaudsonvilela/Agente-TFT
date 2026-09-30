use agente_tft_contracts::{Confidence, GameEventKind, ObservationSource};
use agente_tft_perception_core::ConsensusConfig;
use agente_tft_perception_hud::{parse_candidate, HudField, OcrCandidate};
use agente_tft_state_fusion::StateFusion;

fn candidate(text: &str, at: u64) -> OcrCandidate {
    OcrCandidate {
        field: HudField::Gold,
        text: text.into(),
        confidence: Confidence::new(0.95).unwrap(),
        observed_at_ms: at,
    }
}

#[test]
fn hud_candidate_reaches_game_state_and_emits_semantic_event() {
    let mut fusion = StateFusion::new(
        0,
        ConsensusConfig {
            min_confidence: 0.80,
            confirmations: 2,
            max_gap_ms: 500,
        },
    );

    // Establish stable gold = 50.
    for (text, at) in [("50", 100), ("50", 150)] {
        let batch = parse_candidate(candidate(text, at)).unwrap();
        fusion.apply_hud(batch);
    }

    let gold = fusion.state().player.gold.as_ref().unwrap();
    assert_eq!(gold.value, 50);
    assert_eq!(gold.source, ObservationSource::Vision);

    // One 48 read is not enough to change canonical state.
    let batch = parse_candidate(candidate("48", 200)).unwrap();
    assert!(fusion.apply_hud(batch).is_empty());
    assert_eq!(fusion.state().player.gold.as_ref().unwrap().value, 50);

    // Second matching read promotes 48 and emits GoldChanged.
    let batch = parse_candidate(candidate("48", 250)).unwrap();
    let events = fusion.apply_hud(batch);

    assert_eq!(fusion.state().player.gold.as_ref().unwrap().value, 48);
    assert!(events.iter().any(|event| matches!(
        event,
        GameEventKind::GoldChanged { from: 50, to: 48 }
    )));
}

#[test]
fn malformed_ocr_never_reaches_state_fusion() {
    let result = parse_candidate(candidate("5O", 100));
    assert!(result.is_err());
}
