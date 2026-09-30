use serde::{Deserialize, Serialize};

use crate::CONTRACT_SCHEMA_VERSION;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum GameEventKind {
    MatchStarted,
    MatchEnded,
    RoundChanged { from: Option<String>, to: String },
    ShopChanged,
    BoardChanged,
    BenchChanged,
    GoldChanged { from: u16, to: u16 },
    HpChanged { from: u16, to: u16 },
    LevelChanged { from: u8, to: u8 },
    ItemAdded { item_id: String },
    ItemEquipped { item_id: String, unit_instance_id: String },
    AugmentScreen,
    AugmentOptionsChanged,
    CombatStarted,
    CombatEnded,
    OpponentObserved { player_id: String },
    ContestationChanged {
        unit_id: String,
        observed_copies_before: u16,
        observed_copies_after: u16,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GameEvent {
    pub schema_version: String,
    pub event_id: String,
    pub match_id: Option<String>,
    pub state_revision: u64,
    pub occurred_at_ms: u64,
    pub kind: GameEventKind,
}

impl GameEvent {
    pub fn new(
        event_id: impl Into<String>,
        match_id: Option<String>,
        state_revision: u64,
        occurred_at_ms: u64,
        kind: GameEventKind,
    ) -> Self {
        Self {
            schema_version: CONTRACT_SCHEMA_VERSION.to_string(),
            event_id: event_id.into(),
            match_id,
            state_revision,
            occurred_at_ms,
            kind,
        }
    }
}
