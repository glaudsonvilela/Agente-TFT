use std::{
    collections::BTreeMap,
    env,
    fs,
    path::PathBuf,
    process::ExitCode,
};

use agente_tft_contracts::Action;
use agente_tft_opportunity_engine::{
    OpportunityCandidate, OpportunityWeights,
};
use agente_tft_opportunity_runtime::CompleteOpportunityCycle;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct CandidateConfig {
    weights: OpportunityWeights,
    #[serde(default = "default_min_confidence")]
    min_confidence: f32,
}

fn default_min_confidence() -> f32 {
    0.60
}

#[derive(Debug, Clone, PartialEq, Serialize)]
struct WeightReplayDiff {
    schema_version: u32,
    cycles_seen: u64,
    cycles_with_candidates: u64,
    baseline_wait: u64,
    candidate_wait: u64,
    changed_decisions: u64,
    agreement_rate: Option<f32>,
    transition_counts: BTreeMap<String, u64>,
    candidate: CandidateConfig,
    notes: Vec<String>,
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let Some(telemetry_path) = args.next() else {
        return Err(usage());
    };
    let Some(config_path) = args.next() else {
        return Err(usage());
    };
    if args.next().is_some() {
        return Err(usage());
    }

    let telemetry_path = PathBuf::from(telemetry_path);
    let config_path = PathBuf::from(config_path);

    let config_text = fs::read_to_string(&config_path)
        .map_err(|error| {
            format!(
                "failed reading candidate config {}: {error}",
                config_path.display()
            )
        })?;
    let config: CandidateConfig =
        serde_json::from_str(&config_text).map_err(|error| {
            format!(
                "invalid candidate config {}: {error}",
                config_path.display()
            )
        })?;

    validate_config(&config)?;

    let telemetry = fs::read_to_string(&telemetry_path)
        .map_err(|error| {
            format!(
                "failed reading telemetry {}: {error}",
                telemetry_path.display()
            )
        })?;

    let cycles = load_complete_cycles(&telemetry)?;
    let report = compare_cycles(&cycles, config);

    println!(
        "{}",
        serde_json::to_string_pretty(&report)
            .map_err(|error| format!("failed serializing report: {error}"))?
    );

    Ok(())
}

fn validate_config(config: &CandidateConfig) -> Result<(), String> {
    if !config.min_confidence.is_finite()
        || !(0.0..=1.0).contains(&config.min_confidence)
    {
        return Err("min_confidence must be in [0,1]".into());
    }

    let values = [
        config.weights.immediate_board_gain,
        config.weights.upgrade_value,
        config.weights.hp_preservation,
        config.weights.economy_value,
        config.weights.contest_urgency,
        config.weights.flexibility,
        config.weights.information_value,
        config.weights.external_meta_prior,
        config.weights.uncertainty_penalty,
    ];

    if values.iter().any(|value| !value.is_finite()) {
        return Err("all OpportunityWeights must be finite".into());
    }

    Ok(())
}

fn load_complete_cycles(
    telemetry_jsonl: &str,
) -> Result<Vec<CompleteOpportunityCycle>, String> {
    let mut cycles = Vec::new();

    for (index, line) in telemetry_jsonl.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let value: serde_json::Value =
            serde_json::from_str(line).map_err(|error| {
                format!(
                    "invalid JSONL at line {}: {}",
                    index + 1,
                    error
                )
            })?;

        let Some(payload) = value.get("payload") else {
            continue;
        };

        if payload
            .get("type")
            .and_then(|value| value.as_str())
            != Some("complete_opportunity_cycle")
        {
            continue;
        }

        let Some(cycle) = payload.get("cycle") else {
            continue;
        };

        let parsed: CompleteOpportunityCycle =
            serde_json::from_value(cycle.clone()).map_err(|error| {
                format!(
                    "invalid complete_opportunity_cycle at line {}: {}",
                    index + 1,
                    error
                )
            })?;

        cycles.push(parsed);
    }

    Ok(cycles)
}

fn compare_cycles(
    cycles: &[CompleteOpportunityCycle],
    config: CandidateConfig,
) -> WeightReplayDiff {
    let mut baseline_wait = 0u64;
    let mut candidate_wait = 0u64;
    let mut changed = 0u64;
    let mut cycles_with_candidates = 0u64;
    let mut transitions = BTreeMap::<String, u64>::new();

    for complete in cycles {
        let baseline = &complete.cycle.decision.action;
        let candidate = choose_action(
            &complete.cycle.report.all,
            config.weights,
            config.min_confidence,
        );

        if matches!(baseline, Action::Wait) {
            baseline_wait = baseline_wait.saturating_add(1);
        }
        if matches!(candidate, Action::Wait) {
            candidate_wait = candidate_wait.saturating_add(1);
        }
        if !complete.cycle.report.all.is_empty() {
            cycles_with_candidates =
                cycles_with_candidates.saturating_add(1);
        }

        if *baseline != candidate {
            changed = changed.saturating_add(1);
        }

        let key = format!(
            "{}->{}",
            action_class(baseline),
            action_class(&candidate),
        );
        *transitions.entry(key).or_default() += 1;
    }

    let agreement_rate = if cycles.is_empty() {
        None
    } else {
        Some(
            (cycles.len() as u64 - changed) as f32
                / cycles.len() as f32,
        )
    };

    WeightReplayDiff {
        schema_version: 1,
        cycles_seen: cycles.len() as u64,
        cycles_with_candidates,
        baseline_wait,
        candidate_wait,
        changed_decisions: changed,
        agreement_rate,
        transition_counts: transitions,
        candidate: config,
        notes: vec![
            "This report measures behavior drift only.".into(),
            "A changed decision is not evidence of a better decision.".into(),
            "Promotion requires reward/ground-truth evaluation against a frozen baseline.".into(),
        ],
    }
}

fn choose_action(
    candidates: &[OpportunityCandidate],
    weights: OpportunityWeights,
    min_confidence: f32,
) -> Action {
    let threshold = min_confidence.clamp(0.0, 1.0);

    let mut scored: Vec<(usize, &OpportunityCandidate, f32)> = candidates
        .iter()
        .enumerate()
        .filter_map(|(index, candidate)| {
            if candidate.confidence.value() < threshold {
                return None;
            }
            let Ok(score) = weights.score(candidate.vector) else {
                return None;
            };
            if !score.is_finite() {
                return None;
            }
            Some((index, candidate, score))
        })
        .collect();

    scored.sort_by(|(index_a, candidate_a, score_a), (index_b, candidate_b, score_b)| {
        score_b
            .total_cmp(score_a)
            .then_with(|| {
                candidate_b
                    .confidence
                    .value()
                    .total_cmp(&candidate_a.confidence.value())
            })
            .then_with(|| index_a.cmp(index_b))
    });

    scored
        .first()
        .map(|(_, candidate, _)| candidate.action.clone())
        .unwrap_or(Action::Wait)
}

fn action_class(action: &Action) -> &'static str {
    match action {
        Action::Buy { .. } => "buy",
        Action::SkipBuy { .. } => "skip_buy",
        Action::Sell { .. } => "sell",
        Action::Roll { .. } => "roll",
        Action::Level { .. } => "level",
        Action::HoldEcon => "hold_econ",
        Action::EquipItem { .. } => "equip_item",
        Action::ChooseAugment { .. } => "choose_augment",
        Action::Pivot { .. } => "pivot",
        Action::PartialPivot { .. } => "partial_pivot",
        Action::Position { .. } => "position",
        Action::Scout { .. } => "scout",
        Action::Wait => "wait",
    }
}

fn usage() -> String {
    [
        "Usage:",
        "  agente-tft-weight-replay-diff <telemetry.jsonl> <candidate-weights.json>",
        "",
        "candidate-weights.json:",
        r#"  {"weights": {...OpportunityWeights...}, "min_confidence": 0.60}"#,
        "",
        "The report shows behavior drift only; it does not claim the candidate is better.",
    ]
    .join("\n")
}

#[cfg(test)]
mod tests {
    use agente_tft_contracts::{Confidence, Evidence};
    use agente_tft_opportunity_engine::{
        OpportunityTier, OpportunityVector,
    };

    use super::*;

    fn candidate(
        action: Action,
        vector: OpportunityVector,
        confidence: f32,
    ) -> OpportunityCandidate {
        OpportunityCandidate {
            action,
            tier: OpportunityTier::Tactical,
            utility: 0.0,
            confidence: Confidence::new(confidence).unwrap(),
            vector,
            evidence: vec![Evidence {
                code: "fixture".into(),
                detail: "fixture".into(),
            }],
        }
    }

    #[test]
    fn candidate_weights_can_change_selected_action() {
        let values = vec![
            candidate(
                Action::HoldEcon,
                OpportunityVector {
                    economy_value: 1.0,
                    ..OpportunityVector::default()
                },
                0.90,
            ),
            candidate(
                Action::Roll {
                    budget_gold: 20,
                    stop_condition: None,
                },
                OpportunityVector {
                    upgrade_value: 1.0,
                    ..OpportunityVector::default()
                },
                0.90,
            ),
        ];

        let mut weights = OpportunityWeights::default();
        weights.economy_value = 0.0;
        weights.upgrade_value = 2.0;

        let selected = choose_action(&values, weights, 0.60);

        assert!(matches!(
            selected,
            Action::Roll {
                budget_gold: 20,
                ..
            }
        ));
    }

    #[test]
    fn low_confidence_candidates_become_wait() {
        let values = vec![candidate(
            Action::HoldEcon,
            OpportunityVector {
                economy_value: 1.0,
                ..OpportunityVector::default()
            },
            0.40,
        )];

        let selected = choose_action(
            &values,
            OpportunityWeights::default(),
            0.60,
        );

        assert_eq!(selected, Action::Wait);
    }

    #[test]
    fn invalid_min_confidence_is_rejected() {
        let config = CandidateConfig {
            weights: OpportunityWeights::default(),
            min_confidence: 1.5,
        };

        assert!(validate_config(&config).is_err());
    }
}
