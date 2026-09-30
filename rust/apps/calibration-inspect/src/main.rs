use std::{
    env,
    fs,
    path::PathBuf,
    process::ExitCode,
};

use agente_tft_pattern_engine::EvaluatorFeedbackEngine;

#[derive(Debug, Clone, PartialEq)]
struct Config {
    input: PathBuf,
    min_samples: u64,
    min_abs_correlation: f32,
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
    let args: Vec<String> = env::args().skip(1).collect();
    let config = parse_args(&args)?;

    let content = fs::read_to_string(&config.input)
        .map_err(|error| {
            format!(
                "failed reading {}: {error}",
                config.input.display()
            )
        })?;

    let engine = load_feedback(&content).map_err(|error| {
        format!(
            "could not load evaluator feedback from {}: {error}",
            config.input.display()
        )
    })?;

    let report = engine.calibration_report(
        config.min_samples,
        config.min_abs_correlation,
    );

    println!(
        "{}",
        serde_json::to_string_pretty(&report)
            .map_err(|error| {
                format!("failed serializing calibration report: {error}")
            })?
    );

    Ok(())
}

fn load_feedback(
    content: &str,
) -> Result<EvaluatorFeedbackEngine, String> {
    if let Ok(engine) =
        serde_json::from_str::<EvaluatorFeedbackEngine>(content)
    {
        return Ok(engine);
    }

    let mut last_snapshot: Option<EvaluatorFeedbackEngine> = None;

    for (index, line) in content.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let Ok(value) = serde_json::from_str::<serde_json::Value>(line)
        else {
            continue;
        };

        let Some(payload) = value.get("payload") else {
            continue;
        };

        if payload
            .get("type")
            .and_then(|value| value.as_str())
            != Some("evaluator_feedback_snapshot")
        {
            continue;
        }

        let Some(feedback) = payload.get("feedback") else {
            continue;
        };

        let parsed = serde_json::from_value::<EvaluatorFeedbackEngine>(
            feedback.clone(),
        )
        .map_err(|error| {
            format!(
                "invalid evaluator feedback snapshot at JSONL line {}: {}",
                index + 1,
                error
            )
        })?;

        last_snapshot = Some(parsed);
    }

    last_snapshot.ok_or_else(|| {
        "input is neither raw EvaluatorFeedbackEngine JSON nor telemetry JSONL containing evaluator_feedback_snapshot".into()
    })
}

fn parse_args(args: &[String]) -> Result<Config, String> {
    if args.is_empty()
        || args.iter().any(|value| value == "-h" || value == "--help")
    {
        return Err(usage());
    }

    let mut input: Option<PathBuf> = None;
    let mut min_samples = 20_u64;
    let mut min_abs_correlation = 0.20_f32;

    let mut index = 0usize;
    while index < args.len() {
        match args[index].as_str() {
            "--min-samples" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err("--min-samples requires a value".into());
                };
                min_samples = value
                    .parse::<u64>()
                    .map_err(|_| "--min-samples must be an integer".to_string())?;
            }
            "--min-abs-correlation" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(
                        "--min-abs-correlation requires a value".into()
                    );
                };
                min_abs_correlation = value
                    .parse::<f32>()
                    .map_err(|_| {
                        "--min-abs-correlation must be a number".to_string()
                    })?;
                if !min_abs_correlation.is_finite()
                    || !(0.0..=1.0).contains(&min_abs_correlation)
                {
                    return Err(
                        "--min-abs-correlation must be in [0,1]".into()
                    );
                }
            }
            value if value.starts_with('-') => {
                return Err(format!("unknown option: {value}"));
            }
            value => {
                if input.is_some() {
                    return Err("only one input file is supported".into());
                }
                input = Some(PathBuf::from(value));
            }
        }
        index += 1;
    }

    let Some(input) = input else {
        return Err(usage());
    };

    Ok(Config {
        input,
        min_samples: min_samples.max(2),
        min_abs_correlation,
    })
}

fn usage() -> String {
    [
        "Usage:",
        "  agente-tft-calibration-inspect <feedback.json> [options]",
        "",
        "Options:",
        "  --min-samples N",
        "      Minimum samples per feature (default: 20; minimum: 2).",
        "",
        "  --min-abs-correlation X",
        "      Minimum absolute correlation in [0,1] (default: 0.20).",
        "",
        "Input can be either:",
        "  - serialized EvaluatorFeedbackEngine JSON; or",
        "  - telemetry JSONL containing evaluator_feedback_snapshot.",
        "",
        "For telemetry JSONL, the latest valid feedback snapshot is used.",
        "The output is a CalibrationReport JSON.",
    ]
    .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_uses_safe_defaults() {
        let config = parse_args(&["feedback.json".into()]).unwrap();

        assert_eq!(config.input, PathBuf::from("feedback.json"));
        assert_eq!(config.min_samples, 20);
        assert!((config.min_abs_correlation - 0.20).abs() < 1e-6);
    }

    #[test]
    fn parser_accepts_thresholds() {
        let config = parse_args(&[
            "feedback.json".into(),
            "--min-samples".into(),
            "50".into(),
            "--min-abs-correlation".into(),
            "0.35".into(),
        ])
        .unwrap();

        assert_eq!(config.min_samples, 50);
        assert!((config.min_abs_correlation - 0.35).abs() < 1e-6);
    }

    #[test]
    fn loader_reads_raw_feedback_json() {
        let engine = EvaluatorFeedbackEngine::default();
        let encoded = serde_json::to_string(&engine).unwrap();

        let loaded = load_feedback(&encoded).unwrap();
        assert_eq!(loaded, engine);
    }

    #[test]
    fn loader_reads_latest_telemetry_feedback_snapshot() {
        let first = EvaluatorFeedbackEngine::default();

        let mut second = EvaluatorFeedbackEngine::default();
        // Keep snapshots structurally distinct without requiring reward data.
        // Serialized default equality is enough for first; second is produced
        // through a harmless empty calibration read and remains valid.
        let _ = second.calibration_report(2, 0.2);

        let line1 = serde_json::json!({
            "schema_version": 1,
            "session_id": "fixture",
            "sequence": 0,
            "recorded_at_ms": 100,
            "payload": {
                "type": "evaluator_feedback_snapshot",
                "feedback": first
            }
        });
        let line2 = serde_json::json!({
            "schema_version": 1,
            "session_id": "fixture",
            "sequence": 1,
            "recorded_at_ms": 200,
            "payload": {
                "type": "evaluator_feedback_snapshot",
                "feedback": second
            }
        });

        let content = format!("{}\n{}\n", line1, line2);
        let loaded = load_feedback(&content).unwrap();

        assert_eq!(
            serde_json::to_value(loaded).unwrap(),
            line2["payload"]["feedback"]
        );
    }

    #[test]
    fn parser_rejects_invalid_correlation() {
        assert!(parse_args(&[
            "feedback.json".into(),
            "--min-abs-correlation".into(),
            "1.5".into(),
        ])
        .is_err());
    }
}
