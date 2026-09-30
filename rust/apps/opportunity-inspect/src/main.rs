use std::{
    env,
    fs,
    path::PathBuf,
    process::ExitCode,
};

use agente_tft_contracts::GameState;
use agente_tft_decision_core::DecisionConfig;
use agente_tft_meta_context::MetaSnapshot;
use agente_tft_opportunity_engine::{
    OpportunityConfig, OpportunityEngine, OpportunityFacts, OpportunityInput,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct InputFile {
    state: GameState,
    facts: OpportunityFacts,
    now_ms: u64,
    #[serde(default)]
    config: Option<OpportunityConfig>,
    #[serde(default)]
    meta: Option<MetaSnapshot>,
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
    let Some(path) = args.next() else {
        return Err(usage());
    };

    if path == "-h" || path == "--help" {
        println!("{}", usage());
        return Ok(());
    }

    let path = PathBuf::from(path);
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("failed reading {}: {e}", path.display()))?;

    let input: InputFile = serde_json::from_str(&content)
        .map_err(|e| format!("invalid input JSON {}: {e}", path.display()))?;

    if let Some(meta) = &input.meta {
        meta.validate()
            .map_err(|e| format!("invalid meta snapshot: {e}"))?;
    }

    let engine = OpportunityEngine::new(
        input.config.unwrap_or_default(),
    )
    .map_err(|e| format!("invalid Opportunity Engine config: {e}"))?;

    let report = engine
        .evaluate(OpportunityInput {
            state: &input.state,
            facts: &input.facts,
            meta: input.meta.as_ref(),
            now_ms: input.now_ms,
        })
        .map_err(|e| format!("Opportunity Engine failed: {e}"))?;

    let decision = report.local_decision(DecisionConfig::default());

    let output = serde_json::json!({
        "report": report,
        "decision": decision,
    });

    println!(
        "{}",
        serde_json::to_string_pretty(&output)
            .map_err(|e| format!("failed serializing output: {e}"))?
    );

    Ok(())
}

fn usage() -> String {
    [
        "Usage:",
        "  agente-tft-opportunity-inspect <input.json>",
        "",
        "Input JSON:",
        "  state   = canonical GameState",
        "  facts   = OpportunityFacts",
        "  now_ms  = evaluation timestamp",
        "  config  = optional OpportunityConfig",
        "  meta    = optional MetaSnapshot (e.g. normalized MetaTFT snapshot)",
        "",
        "Example:",
        "  cargo run --manifest-path rust/Cargo.toml \\",
        "    -p agente-tft-opportunity-inspect -- opportunity.json",
    ]
    .join("\n")
}
