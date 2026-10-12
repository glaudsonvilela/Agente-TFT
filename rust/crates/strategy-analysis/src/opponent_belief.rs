//! Conditional belief for exactly one unidentified enemy board unit.
//! This is a likelihood model, not a claim that a synergy identifies a unit.

use std::collections::{BTreeMap, BTreeSet};

use agente_tft_contracts::{GameState, UnitInstance};
use agente_tft_knowledge_core::UnitCatalog;
use agente_tft_synergy_core::board_trait_state;
use agente_tft_trait_core::TraitCatalog;
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TraitSignal {
    pub trait_id: String,
    pub count: u8,
    pub confidence: f32,
    pub observed_at_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ConfirmedBenchUnit {
    pub slot: u8,
    pub unit_id: String,
    pub stars: u8,
    pub observed_at_ms: u64,
    pub confidence: f32,
    pub identity_verified: bool,
    pub stars_verified: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct OpponentStrategyEvidence {
    pub player_id: String,
    /// Same snapshot timestamp as the opponent board in `GameState`.
    pub observed_at_ms: u64,
    pub bench: Vec<ConfirmedBenchUnit>,
    pub trait_signals: Vec<TraitSignal>,
    pub trait_panel_complete: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ObservedPoolCount {
    pub self_copies: u16,
    pub opponent_board_copies: u16,
    pub confirmed_opponent_bench_copies: u16,
    pub observed_total: u16,
}

/// Strategy-only adapter. It reads the tracker state and separately supplied
/// bench evidence; it never writes back identities or beliefs to perception.
pub fn observed_pool_count(
    state: &GameState,
    evidence: &[OpponentStrategyEvidence],
    unit_id: &str,
    now_ms: u64,
    max_age_ms: u64,
    min_confidence: f32,
) -> ObservedPoolCount {
    let self_copies = agente_tft_lobby_analysis::self_owned_copies(state, unit_id);
    let opponent_board_copies = state
        .lobby
        .iter()
        .filter(|rival| {
            rival.last_seen_ms <= now_ms
                && now_ms - rival.last_seen_ms <= max_age_ms
                && rival.confidence.value().is_finite()
                && rival.confidence.value() >= min_confidence
        })
        .flat_map(|rival| rival.board.iter())
        .filter(|unit| unit.unit_id == unit_id)
        .fold(0u16, |total, unit| {
            total.saturating_add(agente_tft_lobby_analysis::copies_represented_by_stars(
                unit.stars,
            ))
        });
    let mut latest_by_slot = BTreeMap::new();
    for rival in evidence.iter().filter(|rival| {
        state.lobby.iter().any(|board| {
            board.player_id == rival.player_id
                && board.last_seen_ms == rival.observed_at_ms
                && board.last_seen_ms <= now_ms
                && now_ms - board.last_seen_ms <= max_age_ms
        })
    }) {
        for unit in &rival.bench {
            if unit.slot >= 9
                || !unit.identity_verified
                || !unit.stars_verified
                || !(1..=3).contains(&unit.stars)
                || !unit.confidence.is_finite()
                || unit.confidence < min_confidence
                || unit.observed_at_ms > now_ms
                || now_ms - unit.observed_at_ms > max_age_ms
            {
                continue;
            }
            let key = (rival.player_id.as_str(), unit.slot);
            let replace = latest_by_slot
                .get(&key)
                .map(|previous: &&ConfirmedBenchUnit| unit.observed_at_ms > previous.observed_at_ms)
                .unwrap_or(true);
            if replace {
                latest_by_slot.insert(key, unit);
            }
        }
    }
    let confirmed_opponent_bench_copies = latest_by_slot
        .values()
        .filter(|unit| unit.unit_id == unit_id)
        .fold(0u16, |total, unit| {
            total.saturating_add(agente_tft_lobby_analysis::copies_represented_by_stars(
                unit.stars,
            ))
        });
    ObservedPoolCount {
        self_copies,
        opponent_board_copies,
        confirmed_opponent_bench_copies,
        observed_total: self_copies
            .saturating_add(opponent_board_copies)
            .saturating_add(confirmed_opponent_bench_copies),
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CandidateBelief {
    pub unit_id: String,
    pub prior: f64,
    pub likelihood: f64,
    pub posterior: f64,
}

/// Assumes one unidentified board slot, a complete trait read, and no
/// unmodelled emblem/trait modifiers. `count_error_scale` is an externally
/// calibrated Laplace error scale in trait-count units. Returns `None` if
/// evidence or model parameters are insufficient.
pub fn one_unknown_board_unit_posterior(
    confirmed_board: &[UnitInstance],
    observed_traits: &[TraitSignal],
    trait_panel_complete: bool,
    trait_modifiers_accounted_for: bool,
    total_board_units: usize,
    now_ms: u64,
    max_age_ms: u64,
    candidate_priors: &[(String, f64)],
    units: &UnitCatalog,
    traits: &TraitCatalog,
    count_error_scale: f64,
) -> Option<Vec<CandidateBelief>> {
    if !trait_panel_complete
        || !trait_modifiers_accounted_for
        || total_board_units != confirmed_board.len() + 1
        || observed_traits.is_empty()
        || observed_traits.iter().any(|entry| {
            !entry.confidence.is_finite()
                || !(0.0..=1.0).contains(&entry.confidence)
                || entry.observed_at_ms > now_ms
                || now_ms - entry.observed_at_ms > max_age_ms
        })
        || candidate_priors.is_empty()
        || !count_error_scale.is_finite()
        || count_error_scale <= 0.0
        || candidate_priors.iter().any(|(id, prior)| {
            id.is_empty() || units.unit(id).is_none() || !prior.is_finite() || *prior < 0.0
        })
    {
        return None;
    }

    let mut seen_candidates = BTreeSet::new();
    if candidate_priors
        .iter()
        .any(|(id, _)| !seen_candidates.insert(id.as_str()))
    {
        return None;
    }
    let mut seen_traits = BTreeSet::new();
    if observed_traits.iter().any(|row| match traits.resolve_id(&row.trait_id) {
        Some(id) => !seen_traits.insert(id.to_string()),
        None => true,
    }) {
        return None;
    }

    let prior_sum: f64 = candidate_priors.iter().map(|(_, prior)| prior).sum();
    if !prior_sum.is_finite() || prior_sum <= 0.0 {
        return None;
    }

    let mut scores = Vec::with_capacity(candidate_priors.len());
    for (unit_id, prior) in candidate_priors {
        let mut board = confirmed_board.to_vec();
        board.push(UnitInstance {
            instance_id: "hypothetical-unknown-slot".into(),
            unit_id: unit_id.clone(),
            stars: 1,
            position: None,
            items: vec![],
        });
        let predicted: BTreeMap<_, _> = board_trait_state(&board, units, traits)
            .into_iter()
            .map(|entry| (entry.trait_id, entry.unit_count))
            .collect();
        let mut log_likelihood = 0.0;
        for observation in observed_traits {
            let trait_id = traits.resolve_id(&observation.trait_id)?;
            let predicted_count = predicted.get(trait_id).copied().unwrap_or(0);
            let difference = predicted_count.abs_diff(observation.count) as f64;
            log_likelihood -= difference * observation.confidence as f64 / count_error_scale;
        }
        let likelihood = log_likelihood.exp();
        scores.push(CandidateBelief {
            unit_id: unit_id.clone(),
            prior: prior / prior_sum,
            likelihood,
            posterior: (prior / prior_sum) * likelihood,
        });
    }

    let evidence: f64 = scores.iter().map(|score| score.posterior).sum();
    if !evidence.is_finite() || evidence <= 0.0 {
        return None;
    }
    for score in &mut scores {
        score.posterior /= evidence;
    }
    scores.sort_by(|a, b| {
        b.posterior
            .total_cmp(&a.posterior)
            .then_with(|| a.unit_id.cmp(&b.unit_id))
    });
    Some(scores)
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{Confidence, OpponentState};

    use super::*;

    fn catalog() -> (UnitCatalog, TraitCatalog) {
        let units = UnitCatalog::from_json_str(
            r#"{"champions":[
                {"api_name":"A","name":"A","cost":1,"traits":["Void"]},
                {"api_name":"B","name":"B","cost":1,"traits":["Warden"]},
                {"api_name":"C","name":"C","cost":1,"traits":["Void"]}
            ]}"#,
        )
        .unwrap();
        let traits = TraitCatalog::from_json_str(
            r#"{"traits":[
                {"api_name":"T_VOID","name":"Void","effects":[{"min_units":2}]},
                {"api_name":"T_WARDEN","name":"Warden","effects":[{"min_units":2}]}
            ]}"#,
        )
        .unwrap();
        (units, traits)
    }

    fn unit(id: &str) -> UnitInstance {
        UnitInstance {
            instance_id: id.into(),
            unit_id: id.into(),
            stars: 1,
            position: None,
            items: vec![],
        }
    }

    #[test]
    fn observed_synergy_updates_prior_without_becoming_confirmed_copy() {
        let (units, traits) = catalog();
        let observation = TraitSignal {
            trait_id: "T_VOID".into(),
            count: 2,
            confidence: 1.0,
            observed_at_ms: 100,
        };
        let beliefs = one_unknown_board_unit_posterior(
            &[unit("C")],
            &[observation],
            true,
            true,
            2,
            100,
            500,
            &[("A".into(), 0.5), ("B".into(), 0.5)],
            &units,
            &traits,
            0.25,
        )
        .unwrap();
        assert_eq!(beliefs[0].unit_id, "A");
        assert!(beliefs[0].posterior > 0.98);
        assert!((beliefs.iter().map(|x| x.posterior).sum::<f64>() - 1.0).abs() < 1e-12);
    }

    #[test]
    fn refuses_to_infer_without_trait_evidence() {
        let (units, traits) = catalog();
        assert!(one_unknown_board_unit_posterior(
            &[unit("C")],
            &[],
            true,
            true,
            2,
            100,
            500,
            &[("A".into(), 1.0)],
            &units,
            &traits,
            0.25,
        )
        .is_none());
    }

    #[test]
    fn incomplete_panel_cannot_generate_posterior() {
        let (units, traits) = catalog();
        let observation = TraitSignal {
            trait_id: "T_VOID".into(),
            count: 2,
            confidence: 1.0,
            observed_at_ms: 100,
        };
        assert!(one_unknown_board_unit_posterior(
            &[unit("C")],
            &[observation],
            false,
            true,
            2,
            100,
            500,
            &[("A".into(), 0.5), ("B".into(), 0.5)],
            &units,
            &traits,
            0.25,
        )
        .is_none());
    }

    #[test]
    fn confirmed_bench_is_counted_once_and_tentative_units_are_ignored() {
        let mut state = GameState::empty(100);
        state.lobby.push(OpponentState {
            player_id: "p2".into(),
            display_name: None,
            hp: None,
            level: None,
            board: vec![unit("A")],
            last_seen_ms: 100,
            confidence: Confidence::new(1.0).unwrap(),
        });
        let confirmed = ConfirmedBenchUnit {
            slot: 0,
            unit_id: "A".into(),
            stars: 2,
            observed_at_ms: 100,
            confidence: 0.95,
            identity_verified: true,
            stars_verified: true,
        };
        let tentative = ConfirmedBenchUnit {
            slot: 1,
            identity_verified: false,
            ..confirmed.clone()
        };
        let evidence = vec![OpponentStrategyEvidence {
            player_id: "p2".into(),
            observed_at_ms: 100,
            bench: vec![confirmed.clone(), confirmed, tentative],
            trait_signals: vec![],
            trait_panel_complete: false,
        }];
        let count = observed_pool_count(&state, &evidence, "A", 100, 500, 0.9);
        assert_eq!(count.opponent_board_copies, 1);
        assert_eq!(count.confirmed_opponent_bench_copies, 3);
        assert_eq!(count.observed_total, 4);
        let mut asynchronous = evidence;
        asynchronous[0].observed_at_ms = 99;
        let unmatched = observed_pool_count(&state, &asynchronous, "A", 100, 500, 0.9);
        assert_eq!(unmatched.confirmed_opponent_bench_copies, 0);
    }
}
