use std::collections::BTreeSet;

use agente_tft_contracts::GameState;
use agente_tft_lobby_analysis::analyze_unit_contestation;
use agente_tft_meta_context::{MetaEntityKind, MetaSnapshot};
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UnitMetaHints {
    pub unit_id: String,
    pub recommended_item_ids: Vec<String>,
    pub top_item_ids: Vec<String>,
    pub positioning: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CompTransitionCandidate {
    pub comp_id: String,
    pub name: String,
    pub unit_ids: Vec<String>,
    pub own_units_present: Vec<String>,
    pub missing_unit_ids: Vec<String>,
    pub overlap_ratio: f32,
    pub observed_contested_copies: u16,
    /// Descriptive performance prior in [-1,1], not action utility.
    pub meta_strength_prior: f32,
    pub frequency: Option<f32>,
    pub sample_size: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CompCandidateConfig {
    pub min_comp_units: usize,
    pub min_overlap_ratio: f32,
    pub max_candidates: usize,
    pub max_age_ms: u64,
    pub allow_unknown_patch_set: bool,
}

impl Default for CompCandidateConfig {
    fn default() -> Self {
        Self {
            min_comp_units: 4,
            min_overlap_ratio: 0.25,
            max_candidates: 12,
            max_age_ms: 6 * 60 * 60 * 1000,
            allow_unknown_patch_set: false,
        }
    }
}

pub fn unit_meta_hints(
    snapshot: &MetaSnapshot,
    unit_id: &str,
) -> Option<UnitMetaHints> {
    let entity = snapshot.entity(MetaEntityKind::Unit, unit_id)?;

    Some(UnitMetaHints {
        unit_id: unit_id.to_string(),
        recommended_item_ids: string_array_attribute(
            entity.attributes.get("recommended_item_ids"),
        ),
        top_item_ids: string_array_attribute(
            entity.attributes.get("top_item_ids"),
        ),
        positioning: entity
            .attributes
            .get("positioning")
            .and_then(|value| value.as_str())
            .map(str::to_string),
    })
}

pub fn generate_comp_transition_candidates(
    state: &GameState,
    snapshot: &MetaSnapshot,
    now_ms: u64,
    config: CompCandidateConfig,
) -> Vec<CompTransitionCandidate> {
    if !snapshot.is_fresh(now_ms, config.max_age_ms) {
        return Vec::new();
    }

    let patch_set_match = snapshot.matches_patch_set(
        state.patch.as_deref(),
        state.set.as_deref(),
    );
    if !patch_set_match && !config.allow_unknown_patch_set {
        return Vec::new();
    }

    if config.max_candidates == 0 {
        return Vec::new();
    }

    let owned: BTreeSet<String> = state
        .player
        .board
        .iter()
        .chain(state.player.bench.iter())
        .map(|unit| unit.unit_id.clone())
        .collect();

    let mut candidates = Vec::new();

    for entity in &snapshot.entities {
        if entity.kind != MetaEntityKind::Comp {
            continue;
        }

        let comp_units: BTreeSet<String> = entity
            .unit_ids
            .iter()
            .filter(|value| !value.trim().is_empty())
            .cloned()
            .collect();

        if comp_units.len() < config.min_comp_units {
            continue;
        }

        let own_units_present: Vec<String> = comp_units
            .iter()
            .filter(|unit_id| owned.contains(*unit_id))
            .cloned()
            .collect();

        let overlap_ratio = own_units_present.len() as f32 / comp_units.len() as f32;
        if overlap_ratio < config.min_overlap_ratio {
            continue;
        }

        let missing_unit_ids: Vec<String> = comp_units
            .iter()
            .filter(|unit_id| !owned.contains(*unit_id))
            .cloned()
            .collect();

        let observed_contested_copies = comp_units
            .iter()
            .fold(0u16, |total, unit_id| {
                total.saturating_add(
                    analyze_unit_contestation(state, unit_id)
                        .observed_opponent_copies,
                )
            });

        let meta_strength_prior = entity
            .performance
            .descriptive_strength_prior()
            .unwrap_or(0.0);

        candidates.push(CompTransitionCandidate {
            comp_id: entity.id.clone(),
            name: entity.name.clone(),
            unit_ids: comp_units.into_iter().collect(),
            own_units_present,
            missing_unit_ids,
            overlap_ratio,
            observed_contested_copies,
            meta_strength_prior,
            frequency: entity.performance.frequency,
            sample_size: entity.performance.sample_size,
        });
    }

    candidates.sort_by(|a, b| {
        b.overlap_ratio
            .total_cmp(&a.overlap_ratio)
            .then_with(|| b.meta_strength_prior.total_cmp(&a.meta_strength_prior))
            .then_with(|| {
                a.observed_contested_copies
                    .cmp(&b.observed_contested_copies)
            })
            .then_with(|| a.comp_id.cmp(&b.comp_id))
    });

    candidates.truncate(config.max_candidates);
    candidates
}

fn string_array_attribute(
    value: Option<&serde_json::Value>,
) -> Vec<String> {
    value
        .and_then(|value| value.as_array())
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use agente_tft_contracts::{
        Confidence, OpponentState, UnitInstance,
    };
    use agente_tft_meta_context::{
        MetaEntity, MetaPerformance,
    };

    use super::*;

    fn unit(id: &str, stars: u8) -> UnitInstance {
        UnitInstance {
            instance_id: format!("{id}-{stars}"),
            unit_id: id.into(),
            stars,
            position: None,
            items: vec![],
        }
    }

    fn state() -> GameState {
        let mut state = GameState::empty(1_000);
        state.patch = Some("18.3b".into());
        state.set = Some("TFTSet18".into());
        state.player.board = vec![
            unit("A", 2),
            unit("B", 1),
            unit("X", 1),
        ];
        state.player.bench = vec![unit("C", 1)];
        state.lobby = vec![OpponentState {
            player_id: "p2".into(),
            display_name: Some("P2".into()),
            hp: None,
            level: None,
            board: vec![unit("D", 2), unit("A", 1)],
            last_seen_ms: 900,
            confidence: Confidence::new(0.95).unwrap(),
        }];
        state
    }

    fn snapshot() -> MetaSnapshot {
        let mut unit_attrs = BTreeMap::new();
        unit_attrs.insert(
            "recommended_item_ids".into(),
            serde_json::json!(["ITEM_1", "ITEM_2", "ITEM_3"]),
        );
        unit_attrs.insert(
            "top_item_ids".into(),
            serde_json::json!(["ITEM_2", "ITEM_4"]),
        );
        unit_attrs.insert(
            "positioning".into(),
            serde_json::json!("in the front row"),
        );

        MetaSnapshot {
            schema_version: 1,
            source: "metatft_public".into(),
            source_url: "https://www.metatft.com/comps".into(),
            captured_at_ms: 900,
            patch: Some("18.3b".into()),
            set: Some("TFTSet18".into()),
            queue: Some("ranked".into()),
            rank_filter: Some("platinum_plus".into()),
            window: Some("last_3_days".into()),
            entities: vec![
                MetaEntity {
                    kind: MetaEntityKind::Unit,
                    id: "A".into(),
                    name: "A".into(),
                    unit_ids: vec![],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(4.0),
                        top4_rate: Some(0.55),
                        win_rate: Some(0.15),
                        frequency: Some(0.10),
                        sample_size: Some(10_000),
                    },
                    tags: vec![],
                    attributes: unit_attrs,
                },
                MetaEntity {
                    kind: MetaEntityKind::Comp,
                    id: "comp-abcd".into(),
                    name: "ABCD".into(),
                    unit_ids: vec![
                        "A".into(),
                        "B".into(),
                        "C".into(),
                        "D".into(),
                    ],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(3.8),
                        top4_rate: Some(0.60),
                        win_rate: Some(0.17),
                        frequency: Some(0.08),
                        sample_size: Some(20_000),
                    },
                    tags: vec!["tier:S".into()],
                    attributes: BTreeMap::new(),
                },
                MetaEntity {
                    kind: MetaEntityKind::Comp,
                    id: "comp-wxyz".into(),
                    name: "WXYZ".into(),
                    unit_ids: vec![
                        "W".into(),
                        "X".into(),
                        "Y".into(),
                        "Z".into(),
                    ],
                    trait_ids: vec![],
                    performance: MetaPerformance {
                        avg_place: Some(3.4),
                        top4_rate: Some(0.65),
                        win_rate: Some(0.20),
                        frequency: Some(0.05),
                        sample_size: Some(10_000),
                    },
                    tags: vec![],
                    attributes: BTreeMap::new(),
                },
            ],
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn extracts_rich_unit_hints() {
        let hints = unit_meta_hints(&snapshot(), "A").unwrap();
        assert_eq!(
            hints.recommended_item_ids,
            vec!["ITEM_1", "ITEM_2", "ITEM_3"]
        );
        assert_eq!(hints.positioning.as_deref(), Some("in the front row"));
    }

    #[test]
    fn comp_candidates_require_real_board_overlap() {
        let candidates = generate_comp_transition_candidates(
            &state(),
            &snapshot(),
            1_000,
            CompCandidateConfig::default(),
        );

        assert_eq!(candidates.len(), 1);
        assert_eq!(candidates[0].comp_id, "comp-abcd");
        assert_eq!(candidates[0].own_units_present.len(), 3);
        assert_eq!(candidates[0].missing_unit_ids, vec!["D"]);
    }

    #[test]
    fn contestation_is_measured_from_real_lobby() {
        let candidates = generate_comp_transition_candidates(
            &state(),
            &snapshot(),
            1_000,
            CompCandidateConfig::default(),
        );

        // Opponent holds A 1★ (1 copy) + D 2★ (3 copies).
        assert_eq!(candidates[0].observed_contested_copies, 4);
    }

    #[test]
    fn stale_snapshot_generates_no_candidates() {
        let candidates = generate_comp_transition_candidates(
            &state(),
            &snapshot(),
            100_000,
            CompCandidateConfig {
                max_age_ms: 100,
                ..CompCandidateConfig::default()
            },
        );
        assert!(candidates.is_empty());
    }

    #[test]
    fn patch_mismatch_generates_no_candidates() {
        let mut state = state();
        state.patch = Some("18.4".into());

        let candidates = generate_comp_transition_candidates(
            &state,
            &snapshot(),
            1_000,
            CompCandidateConfig::default(),
        );

        assert!(candidates.is_empty());
    }
}
