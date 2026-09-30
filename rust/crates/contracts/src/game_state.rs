use serde::{Deserialize, Serialize};

use crate::{Confidence, HexPosition, Observed, CONTRACT_SCHEMA_VERSION};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchPhase {
    Idle,
    MatchDetected,
    Planning,
    Combat,
    AugmentSelection,
    CarouselOrSpecial,
    PostCombat,
    MatchEnded,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnitInstance {
    pub instance_id: String,
    pub unit_id: String,
    pub stars: u8,
    pub position: Option<HexPosition>,
    pub items: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ShopSlot {
    pub slot: u8,
    pub unit_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct PlayerState {
    pub hp: Option<Observed<u16>>,
    pub gold: Option<Observed<u16>>,
    pub level: Option<Observed<u8>>,
    pub xp: Option<Observed<u16>>,
    pub stage: Option<Observed<String>>,
    pub board: Vec<UnitInstance>,
    pub bench: Vec<UnitInstance>,
    pub shop: Vec<Observed<ShopSlot>>,
    pub items: Vec<String>,
    pub augments: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OpponentState {
    pub player_id: String,
    pub display_name: Option<String>,
    pub hp: Option<Observed<u16>>,
    pub level: Option<Observed<u8>>,
    pub board: Vec<UnitInstance>,
    pub last_seen_ms: u64,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GameState {
    pub schema_version: String,
    pub revision: u64,
    pub match_id: Option<String>,
    pub patch: Option<String>,
    pub set: Option<String>,
    pub phase: MatchPhase,
    pub observed_at_ms: u64,
    pub player: PlayerState,
    pub lobby: Vec<OpponentState>,
    pub overall_confidence: Confidence,
}

impl GameState {
    pub fn empty(now_ms: u64) -> Self {
        Self {
            schema_version: CONTRACT_SCHEMA_VERSION.to_string(),
            revision: 0,
            match_id: None,
            patch: None,
            set: None,
            phase: MatchPhase::Idle,
            observed_at_ms: now_ms,
            player: PlayerState::default(),
            lobby: Vec::new(),
            overall_confidence: Confidence::default(),
        }
    }
}
