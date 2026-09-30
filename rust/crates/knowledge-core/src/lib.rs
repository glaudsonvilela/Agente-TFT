use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum KnowledgeError {
    #[error("invalid unit catalog JSON: {0}")]
    InvalidJson(String),
    #[error("unit api_name cannot be empty")]
    EmptyUnitId,
    #[error("unit name cannot be empty")]
    EmptyUnitName,
    #[error("unit cost must be in [1,5]")]
    InvalidUnitCost,
    #[error("duplicate unit api_name: {0}")]
    DuplicateUnit(String),
    #[error("catalog contains no units")]
    EmptyCatalog,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnitDefinition {
    pub api_name: String,
    #[serde(default)]
    pub character_name: String,
    pub name: String,
    pub cost: u8,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub traits: Vec<String>,
}

impl UnitDefinition {
    pub fn validate(&self) -> Result<(), KnowledgeError> {
        if self.api_name.trim().is_empty() {
            return Err(KnowledgeError::EmptyUnitId);
        }
        if self.name.trim().is_empty() {
            return Err(KnowledgeError::EmptyUnitName);
        }
        if !(1..=5).contains(&self.cost) {
            return Err(KnowledgeError::InvalidUnitCost);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CatalogSetInfo {
    pub key: String,
    #[serde(default)]
    pub number: Option<i64>,
    pub name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct UnitCatalogDocument {
    #[serde(default)]
    schema_version: Option<u32>,
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    set: Option<CatalogSetInfo>,
    #[serde(alias = "units")]
    champions: Vec<UnitDefinition>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnitCatalog {
    set: Option<CatalogSetInfo>,
    units: BTreeMap<String, UnitDefinition>,
    by_cost: BTreeMap<u8, Vec<String>>,
}

impl UnitCatalog {
    pub fn from_json_str(value: &str) -> Result<Self, KnowledgeError> {
        let document: UnitCatalogDocument =
            serde_json::from_str(value)
                .map_err(|error| KnowledgeError::InvalidJson(error.to_string()))?;

        if document.champions.is_empty() {
            return Err(KnowledgeError::EmptyCatalog);
        }

        let mut units = BTreeMap::new();
        let mut by_cost: BTreeMap<u8, Vec<String>> = BTreeMap::new();

        for unit in document.champions {
            unit.validate()?;
            let id = unit.api_name.clone();

            if units.contains_key(&id) {
                return Err(KnowledgeError::DuplicateUnit(id));
            }

            by_cost
                .entry(unit.cost)
                .or_default()
                .push(id.clone());
            units.insert(id, unit);
        }

        for ids in by_cost.values_mut() {
            ids.sort();
        }

        Ok(Self {
            set: document.set,
            units,
            by_cost,
        })
    }

    pub fn set(&self) -> Option<&CatalogSetInfo> {
        self.set.as_ref()
    }

    pub fn len(&self) -> usize {
        self.units.len()
    }

    pub fn is_empty(&self) -> bool {
        self.units.is_empty()
    }

    pub fn unit(&self, unit_id: &str) -> Option<&UnitDefinition> {
        self.units.get(unit_id)
    }

    pub fn cost(&self, unit_id: &str) -> Option<u8> {
        self.unit(unit_id).map(|unit| unit.cost)
    }

    pub fn name(&self, unit_id: &str) -> Option<&str> {
        self.unit(unit_id).map(|unit| unit.name.as_str())
    }

    pub fn units_at_cost(&self, cost: u8) -> &[String] {
        self.by_cost
            .get(&cost)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &UnitDefinition)> {
        self.units
            .iter()
            .map(|(id, unit)| (id.as_str(), unit))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> String {
        serde_json::json!({
            "schema_version": 1,
            "source": "communitydragon_tft",
            "set": {
                "key": "TFTSet18",
                "number": 18,
                "name": "Set 18"
            },
            "champions": [
                {
                    "api_name": "TFT18_A",
                    "character_name": "TFT18_A",
                    "name": "Alpha",
                    "cost": 1,
                    "role": "Carry",
                    "traits": ["TFT18_Trait_X"]
                },
                {
                    "api_name": "TFT18_B",
                    "character_name": "TFT18_B",
                    "name": "Beta",
                    "cost": 4,
                    "role": "Tank",
                    "traits": ["TFT18_Trait_Y"]
                },
                {
                    "api_name": "TFT18_C",
                    "character_name": "TFT18_C",
                    "name": "Gamma",
                    "cost": 4,
                    "role": null,
                    "traits": []
                }
            ]
        })
        .to_string()
    }

    #[test]
    fn parses_and_indexes_units_by_cost() {
        let catalog = UnitCatalog::from_json_str(&fixture()).unwrap();

        assert_eq!(catalog.len(), 3);
        assert_eq!(catalog.cost("TFT18_A"), Some(1));
        assert_eq!(catalog.name("TFT18_B"), Some("Beta"));
        assert_eq!(
            catalog.units_at_cost(4),
            &["TFT18_B".to_string(), "TFT18_C".to_string()]
        );
    }

    #[test]
    fn duplicate_unit_ids_are_rejected() {
        let value = serde_json::json!({
            "champions": [
                {
                    "api_name": "A",
                    "name": "A",
                    "cost": 1,
                    "traits": []
                },
                {
                    "api_name": "A",
                    "name": "A2",
                    "cost": 2,
                    "traits": []
                }
            ]
        })
        .to_string();

        assert_eq!(
            UnitCatalog::from_json_str(&value).unwrap_err(),
            KnowledgeError::DuplicateUnit("A".into())
        );
    }

    #[test]
    fn invalid_cost_is_rejected() {
        let value = serde_json::json!({
            "champions": [
                {
                    "api_name": "A",
                    "name": "A",
                    "cost": 0,
                    "traits": []
                }
            ]
        })
        .to_string();

        assert_eq!(
            UnitCatalog::from_json_str(&value).unwrap_err(),
            KnowledgeError::InvalidUnitCost
        );
    }
}
