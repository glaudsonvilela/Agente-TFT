mod common;
mod event;
mod game_state;
mod recommendation;

pub use common::*;
pub use event::*;
pub use game_state::*;
pub use recommendation::*;

pub const CONTRACT_SCHEMA_VERSION: &str = "0.1.0";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confidence_rejects_out_of_range_values() {
        assert!(Confidence::new(-0.01).is_err());
        assert!(Confidence::new(1.01).is_err());
        assert!(Confidence::new(f32::NAN).is_err());
        assert_eq!(Confidence::new(0.84).unwrap().value(), 0.84);
    }

    #[test]
    fn empty_state_has_current_schema_version() {
        let state = GameState::empty(1234);
        assert_eq!(state.schema_version, CONTRACT_SCHEMA_VERSION);
        assert_eq!(state.phase, MatchPhase::Idle);
    }

    #[test]
    fn recommendation_enforces_short_output_contract() {
        let rec = Recommendation {
            schema_version: CONTRACT_SCHEMA_VERSION.to_string(),
            recommendation_id: "rec-1".into(),
            state_revision: 9,
            generated_at_ms: 1234,
            action: Action::Roll {
                budget_gold: 20,
                stop_condition: Some("X reaches 2 stars".into()),
            },
            reason_short: "Player 2 started contesting X; waiting reduces availability.".into(),
            next_step: Some("Stop when X reaches 2 stars.".into()),
            confidence: Confidence::new(0.84).unwrap(),
            alternatives: vec![],
            evidence: vec![],
        };
        assert!(rec.validate().is_ok());
    }

    #[test]
    fn event_is_tagged_and_serializable() {
        let event = GameEvent::new(
            "evt-1",
            Some("match-1".into()),
            10,
            999,
            GameEventKind::GoldChanged { from: 50, to: 48 },
        );
        let value = serde_json::to_value(event).unwrap();
        assert_eq!(value["kind"]["type"], "gold_changed");
    }
}
