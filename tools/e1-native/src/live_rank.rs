//! Rank observed, provisional coaching hypotheses in the resident Rust worker.
//! The visual interpreter supplies candidates; this module chooses relevance.
use agente_tft_opportunity_engine::{OpportunityVector, OpportunityWeights};
use serde_json::{json, Value};
use std::time::Instant;

fn integer(value: &Value, key: &str) -> Option<i64> { value.get(key)?.as_i64() }

fn utility(candidate: &Value, context: &Value) -> Result<f32, String> {
    let action = &candidate["action"];
    let kind = action["type"].as_str().ok_or("candidate action type missing")?;
    let mut v = OpportunityVector::default();
    match kind {
        "trait_shop_review" => {
            let count = integer(action, "visible_trait_count").ok_or("trait count missing")?;
            let breakpoint = integer(action, "next_breakpoint").ok_or("trait breakpoint missing")?;
            if count < 1 || breakpoint <= count || breakpoint > 12 {
                return Err("invalid trait breakpoint".into());
            }
            if action["completes_breakpoint_if_fielded"].as_bool() != Some(breakpoint == count + 1) {
                return Err("trait completion inconsistent".into());
            }
            v.immediate_board_gain = if breakpoint == count + 1 { 0.72 } else { 0.18 };
            v.flexibility = 0.18;
            v.uncertainty = 0.38; // The offered unit may already be fielded.
        }
        "buy_pair" => {
            let slots = action["shop_slots"].as_array().ok_or("pair slots missing")?;
            if slots.len() != 2 || slots[0] == slots[1] { return Err("invalid pair".into()); }
            v.upgrade_value = 0.55;
            v.flexibility = 0.18;
            v.uncertainty = 0.24; // A pair does not establish a third copy.
        }
        "buy_synergy" => {
            let board = action["board_unit_ids"].as_array().ok_or("synergy evidence missing")?;
            if board.len() < 2 { return Err("insufficient synergy evidence".into()); }
            v.immediate_board_gain = 0.42;
            v.flexibility = 0.12;
            v.uncertainty = 0.32; // Board identities are candidate observations.
        }
        "roll" => {
            let gold = integer(context, "gold").ok_or("gold missing")?;
            let hp = integer(context, "hp").ok_or("hp missing")?;
            let rolls = integer(action, "rolls_max").ok_or("roll count missing")?;
            let reserve = integer(action, "reserve_gold").ok_or("reserve missing")?;
            if !(1..=50).contains(&rolls) || !(0..=300).contains(&gold) ||
               !(1..=100).contains(&hp) || gold - 2 * rolls < reserve {
                return Err("roll resources inconsistent".into());
            }
            v.hp_preservation = if hp <= 20 { 0.92 } else if hp <= 35 { 0.68 } else { 0.25 };
            v.economy_value = -0.22;
            v.uncertainty = 0.33; // No target or odds verified.
        }
        "buy_xp" => {
            let gold = integer(context, "gold").ok_or("gold missing")?;
            let cost = integer(action, "gold_cost").ok_or("XP cost missing")?;
            if cost <= 0 || cost > gold { return Err("XP resources inconsistent".into()); }
            v.immediate_board_gain = 0.48;
            v.economy_value = -0.12;
            v.flexibility = 0.25;
            v.uncertainty = 0.16;
        }
        "prepare_level" | "rebuild_after_level" => {
            v.economy_value = 0.37;
            v.flexibility = 0.16;
            v.uncertainty = 0.30;
        }
        "hold_econ" => {
            v.economy_value = 0.24;
            v.uncertainty = 0.38;
        }
        _ => return Err(format!("unsupported live action: {kind}")),
    }
    OpportunityWeights::default().score(v).map_err(|e| e.to_string())
}

pub fn rank(request: &Value) -> Result<Value, String> {
    let start = Instant::now();
    let id = request["id"].as_u64().ok_or("id missing")?;
    let source_ms = request["source_ms"].as_u64().ok_or("source_ms missing")?;
    let candidates = request["candidates"].as_array().ok_or("candidates missing")?;
    if candidates.len() > 24 { return Err("candidate budget exceeded".into()); }
    let context = &request["context"];
    let mut ranked = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        if candidate["policy"] != "partial_state_live_v1" &&
           candidate["policy"] != "resource_budget_v1" &&
           candidate["policy"] != "replay_standard_tempo_v1" {
            continue;
        }
        if let Ok(score) = utility(candidate, context) {
            if score > 0.08 {
                ranked.push(json!({"index":index,"utility":score,"action_type":candidate["action"]["type"]}));
            }
        }
    }
    ranked.sort_by(|a,b| b["utility"].as_f64().unwrap().total_cmp(&a["utility"].as_f64().unwrap()));
    Ok(json!({"id":id,"source_ms":source_ms,"origin":"rust_live_opportunity_v1",
        "selected_index":ranked.first().map(|row|row["index"].clone()),"ranked":ranked,
        "native_ms":start.elapsed().as_secs_f64()*1000.0}))
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn immediate_trait_completion_beats_economy_reminder() {
        let result=rank(&json!({"id":7,"source_ms":100,"context":{"gold":30},"candidates":[
            {"policy":"partial_state_live_v1","action":{"type":"prepare_level"}},
            {"policy":"partial_state_live_v1","action":{"type":"trait_shop_review",
                "visible_trait_count":3,"next_breakpoint":4,"completes_breakpoint_if_fielded":true}}
        ]})).unwrap();
        assert_eq!(result["selected_index"],1);
    }
    #[test] fn inconsistent_and_unsupported_candidates_abstain() {
        let result=rank(&json!({"id":1,"source_ms":0,"context":{"gold":2},"candidates":[
            {"policy":"partial_state_live_v1","action":{"type":"buy_xp","gold_cost":8}},
            {"policy":"partial_state_live_v1","action":{"type":"equip"}}
        ]})).unwrap();
        assert!(result["selected_index"].is_null());
    }
}
