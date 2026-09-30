use serde::{Deserialize, Serialize};

use crate::{Confidence, ContractError, HexPosition};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PositionMove {
    pub unit_instance_id: String,
    pub to: HexPosition,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Action {
    Buy { shop_slot: u8, unit_id: String },
    SkipBuy { shop_slot: u8 },
    Sell { unit_instance_id: String },
    Roll {
        budget_gold: u16,
        stop_condition: Option<String>,
    },
    Level { target_level: u8 },
    HoldEcon,
    EquipItem { item_id: String, unit_instance_id: String },
    ChooseAugment { augment_id: String },
    Pivot { target: String },
    PartialPivot { target: String },
    Position { moves: Vec<PositionMove> },
    Scout { player_id: String },
    Wait,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AlternativeAction {
    pub action: Action,
    pub score: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub code: String,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Recommendation {
    pub schema_version: String,
    pub recommendation_id: String,
    pub state_revision: u64,
    pub generated_at_ms: u64,
    pub action: Action,
    pub reason_short: String,
    pub next_step: Option<String>,
    pub confidence: Confidence,
    pub alternatives: Vec<AlternativeAction>,
    pub evidence: Vec<Evidence>,
}

impl Recommendation {
    pub fn validate(&self) -> Result<(), ContractError> {
        let reason_len = self.reason_short.chars().count();
        if self.reason_short.trim().is_empty() || reason_len > 160 {
            return Err(ContractError::InvalidReason);
        }
        if self
            .next_step
            .as_ref()
            .is_some_and(|value| value.chars().count() > 160)
        {
            return Err(ContractError::InvalidNextStep);
        }
        Confidence::new(self.confidence.value())?;
        Ok(())
    }
}
