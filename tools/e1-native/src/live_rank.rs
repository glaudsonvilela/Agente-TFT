//! Rank observed, provisional coaching hypotheses in the resident Rust worker.
//! The visual interpreter supplies candidates; this module chooses relevance.
use agente_tft_opportunity_engine::{OpportunityVector, OpportunityWeights};
use serde_json::{json, Value};
use std::time::Instant;
use crate::match_memory::{History, MatchMemory, summary_json};

fn integer(value: &Value, key: &str) -> Option<i64> { value.get(key)?.as_i64() }

fn utility(candidate: &Value, context: &Value, history: &History) -> Result<f32, String> {
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
    let mut weights = OpportunityWeights::default();
    // A recent, observed HP decline increases the value of actions that
    // actually preserve HP. The same weights apply to every action family.
    weights.hp_preservation += (history.hp_loss_90s as f32 / 30.0).clamp(0.0, 0.6);
    weights.score(v).map_err(|e| e.to_string())
}

pub fn rank(request: &Value, memory: &mut MatchMemory) -> Result<Value, String> {
    let start = Instant::now();
    let id = request["id"].as_u64().ok_or("id missing")?;
    let source_ms = request["source_ms"].as_u64().ok_or("source_ms missing")?;
    let candidates = request["candidates"].as_array().ok_or("candidates missing")?;
    if candidates.len() > 24 { return Err("candidate budget exceeded".into()); }
    let context = &request["context"];
    let match_id = request["match_id"].as_str();
    let epoch = request["epoch"].as_i64().unwrap_or(0);
    let mut memory_error = None;
    let history = if let Some(match_id) = match_id {
        match memory.history(match_id, epoch, source_ms as i64) {
            Ok(value) => value,
            Err(error) => { memory_error = Some(error); History::default() }
        }
    } else { History::default() };
    let mut ranked = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        if candidate["policy"] != "partial_state_live_v1" &&
           candidate["policy"] != "resource_budget_v1" &&
           candidate["policy"] != "replay_standard_tempo_v1" {
            continue;
        }
        if let Ok(base) = utility(candidate, context, &history) {
            let key = candidate["decision_key"].as_str()
                .map(str::to_owned).unwrap_or_else(|| candidate["action"].to_string());
            let repeats = match match_id {
                Some(id) if memory_error.is_none() => memory.recent_repeats(id, epoch, source_ms as i64, &key)
                    .unwrap_or(0),
                _ => 0,
            };
            // Repeated advice has lower information value even when the same
            // shop pixels keep arriving. This is uniform across action types.
            let novelty_penalty = (repeats.min(4) as f32) * 0.22;
            // Novelty reorders supported alternatives; it must not erase the
            // sole valid opportunity merely because playback was delayed.
            let score = if base > 0.08 { (base - novelty_penalty).max(0.081) } else { base };
            if base > 0.08 {
                ranked.push(json!({"index":index,"utility":score,"base_utility":base,
                    "recent_repeats":repeats,"novelty_penalty":novelty_penalty,
                    "action_type":candidate["action"]["type"],"decision_key":key}));
            }
        }
    }
    ranked.sort_by(|a,b| b["utility"].as_f64().unwrap().total_cmp(&a["utility"].as_f64().unwrap()));
    if match_id.is_some() {
        let selected = ranked.first().and_then(|row| Some((row["decision_key"].as_str()?,
            row["action_type"].as_str()?, row["utility"].as_f64()? as f32)));
        if let Err(error) = memory.record(request, selected) { memory_error = Some(error); }
    }
    Ok(json!({"id":id,"source_ms":source_ms,"origin":"rust_live_opportunity_v1",
        "selected_index":ranked.first().map(|row|row["index"].clone()),"ranked":ranked,
        "memory":summary_json(&history, memory.location()),"memory_error":memory_error,
        "native_ms":start.elapsed().as_secs_f64()*1000.0}))
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn immediate_trait_completion_beats_economy_reminder() {
        let result=rank(&json!({"id":7,"source_ms":100,"context":{"gold":30},"candidates":[
            {"policy":"partial_state_live_v1","action":{"type":"prepare_level"}},
            {"policy":"partial_state_live_v1","action":{"type":"trait_shop_review",
                "visible_trait_count":3,"next_breakpoint":4,"completes_breakpoint_if_fielded":true}}
        ]}), &mut MatchMemory::new(None)).unwrap();
        assert_eq!(result["selected_index"],1);
    }
    #[test] fn inconsistent_and_unsupported_candidates_abstain() {
        let result=rank(&json!({"id":1,"source_ms":0,"context":{"gold":2},"candidates":[
            {"policy":"partial_state_live_v1","action":{"type":"buy_xp","gold_cost":8}},
            {"policy":"partial_state_live_v1","action":{"type":"equip"}}
        ]}), &mut MatchMemory::new(None)).unwrap();
        assert!(result["selected_index"].is_null());
    }
    #[test] fn repeated_choice_loses_to_an_equally_supported_new_choice() {
        let mut memory=MatchMemory::new(None);
        let id="0123456789abcdef0123456789abcdef";
        let choices=json!([
            {"policy":"partial_state_live_v1","decision_key":"pair-a",
                "action":{"type":"buy_pair","shop_slots":[0,1]}},
            {"policy":"partial_state_live_v1","decision_key":"pair-b",
                "action":{"type":"buy_pair","shop_slots":[2,3]}}
        ]);
        let first=rank(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "observation":{"gold":30},"context":{"gold":30},"candidates":choices}), &mut memory).unwrap();
        assert_eq!(first["selected_index"],0);
        let next=rank(&json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "observation":{"gold":30},"context":{"gold":30},"candidates":choices}), &mut memory).unwrap();
        assert_eq!(next["selected_index"],1);
        assert_eq!(next["memory"]["observed_rows_90s"],1);
    }
}
