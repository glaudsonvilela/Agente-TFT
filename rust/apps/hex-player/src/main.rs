//! Selects a simulated action from paired complete-match placements.
//! The synthetic simulator supplies outcomes; Rust owns the decision math.
use serde_json::{json, Value};
use std::io::{self, Read};

fn decide(input: &Value) -> Result<Value, String> {
    if input["scope"] != "experimental_hex_lab" {
        return Err("only experimental_hex_lab outcomes are supported".into());
    }
    let candidates = input["candidates"].as_array().ok_or("candidates missing")?;
    if candidates.is_empty() || candidates.len() > 512 {
        return Err("candidate count outside budget".into());
    }
    let mut expected_samples = None;
    let mut summary = Vec::with_capacity(candidates.len());
    let mut chosen = None;
    for (index, candidate) in candidates.iter().enumerate() {
        let action = candidate.get("action").ok_or("action missing")?;
        if !action["kind"].is_string() || !action["args"].is_array() {
            return Err("invalid action".into());
        }
        let placements = candidate["placements"].as_array().ok_or("placements missing")?;
        if placements.is_empty() || placements.len() > 4096 {
            return Err("sample count outside budget".into());
        }
        if expected_samples.replace(placements.len()).is_some_and(|n| n != placements.len()) {
            return Err("candidate samples are not paired".into());
        }
        let mut sum = 0.0;
        let mut top4 = 0;
        let mut first = 0;
        for placement in placements {
            let p = placement.as_f64().ok_or("invalid placement")?;
            if !p.is_finite() || !(1.0..=8.0).contains(&p) {
                return Err("placement outside 1..8".into());
            }
            sum += p;
            if p <= 4.0 { top4 += 1; }
            if p == 1.0 { first += 1; }
        }
        let mean = sum / placements.len() as f64;
        summary.push(json!({"action":action,"samples":placements.len(),
            "mean_placement":mean,"top4_rate":top4 as f64/placements.len() as f64,
            "first_rate":first as f64/placements.len() as f64}));
        // Stable input order breaks exact ties; no hand-tuned gold or trait score.
        if chosen.is_none_or(|(_, best): (usize, f64)| mean < best) {
            chosen = Some((index, mean));
        }
    }
    let (index, _) = chosen.ok_or("no candidate")?;
    Ok(json!({"scope":"experimental_hex_lab","runtime_promoted":false,
        "policy":"empirical_placement_v1","action":candidates[index]["action"],
        "selected_index":index,"selected":summary[index],"candidates":summary,
        "neural_weights_trained":false,"real_tft_probability":null}))
}

fn main() {
    let mut body = String::new();
    let result = io::stdin().take(1024 * 1024).read_to_string(&mut body)
        .map_err(|e| e.to_string())
        .and_then(|_| serde_json::from_str::<Value>(&body).map_err(|e| e.to_string()))
        .and_then(|request| decide(&request));
    match result {
        Ok(output) => println!("{output}"),
        Err(error) => { eprintln!("{error}"); std::process::exit(2); }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chooses_better_full_match_outcomes_over_gold() {
        let result = decide(&json!({"scope":"experimental_hex_lab","candidates":[
            {"action":{"kind":"hold","args":[]},"placements":[5,6,5]},
            {"action":{"kind":"buy","args":[0]},"placements":[2,3,2]}
        ]})).unwrap();
        assert_eq!(result["action"]["kind"], "buy");
        assert_eq!(result["selected"]["mean_placement"], 7.0/3.0);
        assert_eq!(result["real_tft_probability"], Value::Null);
    }
    #[test]
    fn rejects_unpaired_or_unphysical_results() {
        for placements in [json!([0,2]),json!([1]),json!([1,null])] {
            let request=json!({"scope":"experimental_hex_lab","candidates":[
                {"action":{"kind":"hold","args":[]},"placements":[1,2]},
                {"action":{"kind":"buy","args":[0]},"placements":placements}
            ]});
            assert!(decide(&request).is_err());
        }
    }
}
