use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum TraitError {
    #[error("invalid trait catalog JSON: {0}")]
    InvalidJson(String),
    #[error("trait api_name cannot be empty")]
    EmptyTraitId,
    #[error("trait name cannot be empty")]
    EmptyTraitName,
    #[error("trait breakpoint min_units must be > 0")]
    InvalidBreakpoint,
    #[error("duplicate trait api_name: {0}")]
    DuplicateTrait(String),
    #[error("catalog contains no traits")]
    EmptyCatalog,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TraitEffect {
    #[serde(default)]
    pub min_units: Option<u8>,
    #[serde(default)]
    pub max_units: Option<u16>,
    #[serde(default)]
    pub style: Option<i64>,
    #[serde(default)]
    pub variables: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TraitDefinition {
    pub api_name: String,
    pub name: String,
    #[serde(default)]
    pub desc: String,
    #[serde(default)]
    pub effects: Vec<TraitEffect>,
}

impl TraitDefinition {
    pub fn validate(&self) -> Result<(), TraitError> {
        if self.api_name.trim().is_empty() {
            return Err(TraitError::EmptyTraitId);
        }
        if self.name.trim().is_empty() {
            return Err(TraitError::EmptyTraitName);
        }
        if self
            .effects
            .iter()
            .filter_map(|effect| effect.min_units)
            .any(|value| value == 0)
        {
            return Err(TraitError::InvalidBreakpoint);
        }
        Ok(())
    }

    pub fn breakpoints(&self) -> Vec<u8> {
        let mut result: Vec<u8> = self
            .effects
            .iter()
            .filter_map(|effect| effect.min_units)
            .filter(|value| *value > 0)
            .collect();
        result.sort_unstable();
        result.dedup();
        result
    }
}

#[derive(Debug, Clone, Deserialize)]
struct TraitCatalogDocument {
    #[serde(default)]
    set: Option<serde_json::Value>,
    traits: Vec<TraitDefinition>,
}

#[derive(Debug, Clone)]
pub struct TraitCatalog {
    traits: BTreeMap<String, TraitDefinition>,
    aliases: BTreeMap<String, String>,
}

impl TraitCatalog {
    pub fn from_json_str(value: &str) -> Result<Self, TraitError> {
        let document: TraitCatalogDocument = serde_json::from_str(value)
            .map_err(|error| TraitError::InvalidJson(error.to_string()))?;

        if document.traits.is_empty() {
            return Err(TraitError::EmptyCatalog);
        }

        let _ = document.set;

        let mut traits = BTreeMap::new();
        let mut aliases = BTreeMap::new();

        for definition in document.traits {
            definition.validate()?;
            let id = definition.api_name.clone();
            if traits.contains_key(&id) {
                return Err(TraitError::DuplicateTrait(id));
            }

            aliases.insert(normalized_key(&definition.api_name), id.clone());
            aliases.insert(normalized_key(&definition.name), id.clone());
            traits.insert(id, definition);
        }

        Ok(Self { traits, aliases })
    }

    pub fn trait_by_id(&self, trait_id: &str) -> Option<&TraitDefinition> {
        self.traits.get(trait_id)
    }

    pub fn resolve_id(&self, reference: &str) -> Option<&str> {
        if self.traits.contains_key(reference) {
            return Some(reference);
        }

        self.aliases
            .get(&normalized_key(reference))
            .map(String::as_str)
    }

    pub fn breakpoints(&self, reference: &str) -> Option<Vec<u8>> {
        let id = self.resolve_id(reference)?;
        Some(self.traits.get(id)?.breakpoints())
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &TraitDefinition)> {
        self.traits
            .iter()
            .map(|(id, definition)| (id.as_str(), definition))
    }
}

fn normalized_key(value: &str) -> String {
    value
        .chars()
        .flat_map(char::to_lowercase)
        .filter(|ch| ch.is_alphanumeric())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> String {
        serde_json::json!({
            "set": {
                "key": "TFTSet18",
                "number": 18,
                "name": "Set 18"
            },
            "traits": [
                {
                    "api_name": "TFT18_Void",
                    "name": "Void",
                    "desc": "fixture",
                    "effects": [
                        {"min_units": 2, "max_units": 3, "style": 1, "variables": {}},
                        {"min_units": 4, "max_units": 5, "style": 2, "variables": {}},
                        {"min_units": 6, "max_units": null, "style": 3, "variables": {}}
                    ]
                },
                {
                    "api_name": "TFT18_Warden",
                    "name": "Warden",
                    "effects": [
                        {"min_units": 2, "max_units": null, "variables": {}}
                    ]
                }
            ]
        })
        .to_string()
    }

    #[test]
    fn parses_breakpoints_and_aliases() {
        let catalog = TraitCatalog::from_json_str(&fixture()).unwrap();

        assert_eq!(catalog.resolve_id("Void"), Some("TFT18_Void"));
        assert_eq!(catalog.resolve_id("TFT18_Void"), Some("TFT18_Void"));
        assert_eq!(catalog.breakpoints("Void"), Some(vec![2, 4, 6]));
    }

    #[test]
    fn empty_or_zero_breakpoint_is_rejected() {
        let value = serde_json::json!({
            "traits": [
                {
                    "api_name": "A",
                    "name": "A",
                    "effects": [
                        {"min_units": 0}
                    ]
                }
            ]
        })
        .to_string();

        assert_eq!(
            TraitCatalog::from_json_str(&value).unwrap_err(),
            TraitError::InvalidBreakpoint
        );
    }
}
