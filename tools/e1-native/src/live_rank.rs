//! Rank observed, provisional coaching hypotheses in the resident Rust worker.
//! The visual interpreter supplies candidates; this module chooses relevance.
use agente_tft_opportunity_engine::{OpportunityVector, OpportunityWeights};
use serde_json::{json, Value};
use std::time::Instant;
use crate::match_memory::{History, MatchMemory, summary_json};
use crate::match_brain::{integrate, pooled_snapshots, Situation};
use std::collections::VecDeque;

fn integer(value: &Value, key: &str) -> Option<i64> { value.get(key)?.as_i64() }

fn same_decision_goal(candidate: &Value) -> Option<String> {
    let action = &candidate["action"];
    match action["type"].as_str()? {
        "trait_shop_review" => Some(format!("goal:trait:{}:{}:{}",
            action["unit_id"].as_str()?, action["trait"].as_str()?,
            action["next_breakpoint"].as_i64()?)),
        "buy_pair" => Some(format!("goal:pair:{}", action["unit_id"].as_str()?)),
        _ => None,
    }
}

struct MacroState {
    phase: &'static str,
    pressure: &'static str,
    hp_loss_90s: i64,
    gold_change_90s: Option<i64>,
}

impl MacroState {
    fn from(situation: &Situation, history: &History) -> Self {
        let stage = situation.stage.as_deref().and_then(|s| s.as_bytes().first().copied());
        let phase = match stage { Some(b'1'..=b'2') => "opening",
            Some(b'3'..=b'4') => "middle", Some(b'5'..=b'9') => "late", _ => "unknown" };
        let pressure = match situation.hp {
            Some(0..=20) => "survival",
            Some(21..=35) if history.hp_loss_90s >= 10 => "recovering",
            Some(21..=35) => "fragile",
            Some(_) => "normal",
            None => "unknown",
        };
        Self { phase, pressure, hp_loss_90s: history.hp_loss_90s,
            gold_change_90s: history.gold_change_90s }
    }

    fn diagnostics(&self) -> Value {
        json!({"phase":self.phase,"pressure":self.pressure,
            "observed_hp_loss_90s":self.hp_loss_90s,
            "observed_gold_change_90s":self.gold_change_90s})
    }
}

fn utility(candidate: &Value, situation: &Situation, macro_state: &MacroState) -> Result<f32, String> {
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
            let slot = integer(action, "shop_slot").ok_or("shop slot missing")?;
            let unit = action["unit_id"].as_str().ok_or("shop unit missing")?;
            if situation.fielded_unit_candidates.iter().any(|existing| existing == unit) {
                return Err("offered unit is already a persistent field candidate".into());
            }
            if !situation.shop.iter().any(|offer| offer["slot"] == slot &&
                offer["unit_id"] == unit && offer["catalog_status"] == "unique_name_bound" &&
                offer["status"] == "offer_text_readable") {
                return Err("trait advice does not match a fresh shop offer".into());
            }
            if breakpoint == count + 1 {
                v.immediate_board_gain = 0.72;
                v.flexibility = 0.18;
                v.uncertainty = 0.38; // The offered unit may already be fielded.
            } else {
                return Err("visible trait does not reach its next breakpoint".into());
            }
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
            let gold = situation.gold.ok_or("gold missing")?;
            let hp = situation.hp.ok_or("hp missing")?;
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
            let gold = situation.gold.ok_or("gold missing")?;
            let cost = integer(action, "gold_cost").ok_or("XP cost missing")?;
            if cost <= 0 || cost > gold { return Err("XP resources inconsistent".into()); }
            let quote = &candidate["resource_quote"];
            let verified_quote = quote["engine"] == "resource_budget_v1" &&
                quote["gold_cost"].as_i64() == Some(cost) &&
                quote["gold_after"].as_i64() == Some(gold-cost) &&
                action["gold_after"].as_i64() == Some(gold-cost) &&
                quote["target_level"] == action["target_level"] &&
                quote["reserve_met"] == true;
            v.immediate_board_gain = 0.48;
            v.economy_value = -0.12;
            v.flexibility = 0.25;
            v.uncertainty = if verified_quote { 0.05 } else { 0.16 };
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
    weights.hp_preservation += (macro_state.hp_loss_90s as f32 / 30.0).clamp(0.0, 0.6);
    // The same situation also changes the value of long-horizon economy
    // advice. Losing a great deal of HP makes waiting less useful.
    if matches!(macro_state.pressure, "survival" | "recovering") {
        weights.economy_value *= 0.55;
    }
    if macro_state.phase == "late" { weights.economy_value *= 0.8; }
    weights.score(v).map_err(|e| e.to_string())
}

pub fn rank(request: &Value, memory: &mut MatchMemory) -> Result<Value, String> {
    let start = Instant::now();
    let id = request["id"].as_u64().ok_or("id missing")?;
    let source_ms = request["source_ms"].as_u64().ok_or("source_ms missing")?;
    let supplied = request["candidates"].as_array().ok_or("candidates missing")?;
    if supplied.len() > 24 { return Err("candidate budget exceeded".into()); }
    let match_id = request["match_id"].as_str();
    let epoch = request["epoch"].as_i64().unwrap_or(0);
    let mut memory_error = None;
    let mut history = if let Some(match_id) = match_id {
        match memory.history(match_id, epoch, source_ms as i64) {
            Ok(value) => value,
            Err(error) => { memory_error = Some(error); History::default() }
        }
    } else { History::default() };
    let mut current = request["observation"].clone();
    if !current.is_object() { current = json!({}); }
    for field in ["gold", "hp"] {
        if current[field].is_null() && !request["context"][field].is_null() {
            current[field] = request["context"][field].clone();
        }
    }
    let last_event = match match_id {
        Some(id) => match memory.latest_event(id, epoch, source_ms as i64) {
            Ok(value) => value,
            Err(error) => { memory_error = Some(error); None }
        },
        None => None,
    };
    let match_pool = match match_id {
        Some(id) => match memory.pool(id, epoch, source_ms as i64) {
            Ok(value) => value,
            Err(error) => { memory_error = Some(error); json!({}) }
        },
        None => json!({}),
    };
    let empty = VecDeque::new();
    let recent = match match_id {
        Some(id) => match memory.recent_snapshots(id) {
            Ok(rows) => rows,
            Err(error) => { memory_error = Some(error); &empty }
        },
        None => &empty,
    };
    let mut combined = recent.clone();
    combined.extend(pooled_snapshots(&match_pool, epoch));
    combined.make_contiguous().sort_by_key(|(at, _, _)| *at);
    let situation = integrate(&current, &combined, epoch, source_ms as i64, last_event.as_ref());
    if let Some(hp) = current["hp"].as_i64() {
        if let Some(previous) = history.latest_hp {
            history.hp_loss_90s += (previous-hp).max(0);
        }
    }
    if let (Some(gold), Some(oldest)) = (current["gold"].as_i64(), history.oldest_gold_90s) {
        history.gold_change_90s = Some(gold-oldest);
    }
    let macro_state = MacroState::from(&situation, &history);
    let mut candidates = supplied.clone();
    for derived in situation.derive_candidates() {
        let action = &derived["action"];
        if !candidates.iter().any(|row| row["action"]["type"] == action["type"] &&
            row["action"]["unit_id"] == action["unit_id"]) {
            candidates.push(derived);
        }
    }
    for candidate in &mut candidates {
        if let Some(goal) = same_decision_goal(candidate) {
            candidate["decision_key"] = Value::String(goal);
        }
    }
    let mut ranked = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        if candidate["policy"] != "partial_state_live_v1" &&
           candidate["policy"] != "resource_budget_v1" &&
           candidate["policy"] != "replay_standard_tempo_v1" &&
           candidate["policy"] != "integrated_match_v1" {
            continue;
        }
        if let Ok(base) = utility(candidate, &situation, &macro_state) {
            let key = candidate["decision_key"].as_str()
                .map(str::to_owned).unwrap_or_else(|| candidate["action"].to_string());
            let repeats = match match_id {
                Some(id) if memory_error.is_none() => memory.recent_repeats(id, epoch, source_ms as i64, &key)
                    .unwrap_or(0),
                _ => 0,
            };
            let sightings = match match_id {
                Some(id) if memory_error.is_none() =>
                    match memory.recent_candidate_sightings(id, epoch, source_ms as i64, &key) {
                        Ok(value) => value,
                        Err(error) => { memory_error = Some(error); 0 }
                    },
                _ => 0,
            };
            // Repeated advice has lower information value even when the same
            // shop pixels keep arriving. This is uniform across action types.
            let novelty_penalty = (repeats.min(4) as f32) * 0.22;
            // A candidate that remained visible across earlier frames is
            // more stable evidence, even if it was never spoken aloud.
            let persistence_bonus = (sightings.min(3) as f32) * 0.03;
            // Novelty reorders supported alternatives; it must not erase the
            // sole valid opportunity merely because playback was delayed.
            let score = if base > 0.08 {
                (base + persistence_bonus - novelty_penalty).max(0.081)
            } else { base };
            if base > 0.08 {
                ranked.push(json!({"index":index,"utility":score,"base_utility":base,
                    "recent_repeats":repeats,"novelty_penalty":novelty_penalty,
                    "observed_times_90s":sightings,"persistence_bonus":persistence_bonus,
                    "action_type":candidate["action"]["type"],"decision_key":key}));
            }
        }
    }
    ranked.sort_by(|a,b| b["utility"].as_f64().unwrap().total_cmp(&a["utility"].as_f64().unwrap()));
    let mut selected_row = None;
    for row in &ranked {
        let Some(key) = row["decision_key"].as_str() else { continue };
        let repeated = match match_id {
            Some(id) if memory_error.is_none() =>
                match memory.already_emitted(id, epoch, source_ms as i64,
                    situation.stage.as_deref(), key,
                    matches!(row["action_type"].as_str(),
                        Some("prepare_level" | "rebuild_after_level" | "hold_econ"))) {
                    Ok(value) => value,
                    Err(error) => { memory_error = Some(error); false }
                },
            _ => false,
        };
        if !repeated { selected_row = Some(row); break; }
    }
    let selected_index = selected_row.and_then(|row| row["index"].as_u64()).map(|n| n as usize);
    if match_id.is_some() {
        let selected = selected_row.and_then(|row| Some((row["decision_key"].as_str()?,
            row["action_type"].as_str()?, row["utility"].as_f64()? as f32)));
        if let Err(error) = memory.record(request, selected) { memory_error = Some(error); }
        if let Some(match_key) = match_id {
            if let Err(error) = memory.record_assessment(match_key, id as i64,
                &candidates, &ranked) { memory_error = Some(error); }
        }
    }
    let updated_pool = match match_id {
        Some(id) => match memory.pool(id, epoch, source_ms as i64) {
            Ok(value) => value,
            Err(error) => { memory_error = Some(error); match_pool }
        },
        None => match_pool,
    };
    Ok(json!({"id":id,"source_ms":source_ms,"origin":"rust_live_opportunity_v1",
        "selected_index":selected_index,"selected_candidate":selected_index.and_then(|i|candidates.get(i)),
        "held_duplicate":selected_index.is_none() && !ranked.is_empty(),
        "ranked":ranked,"whole_state":situation.diagnostics(),
        "macro_state":macro_state.diagnostics(),
        "match_pool":updated_pool,
        "memory":summary_json(&history, memory.location()),"memory_error":memory_error,
        "native_ms":start.elapsed().as_secs_f64()*1000.0}))
}

pub fn acknowledge(request: &Value, memory: &mut MatchMemory) -> Result<Value, String> {
    let frame_id = request["id"].as_u64().ok_or("id missing")?;
    let match_id = request["match_id"].as_str().ok_or("match identity missing")?;
    let source_ms = request["source_ms"].as_i64().ok_or("source time missing")?;
    let epoch = request["epoch"].as_i64().ok_or("epoch missing")?;
    let key = request["decision_key"].as_str().ok_or("decision key missing")?;
    if key.len() > 256 || key.is_empty() { return Err("invalid decision key".into()); }
    let stage = request["stage"].as_str();
    if stage.is_some_and(|value| value.len() > 8) { return Err("invalid stage".into()); }
    if !memory.was_selected(match_id, frame_id as i64, epoch, source_ms, key)? {
        return Err("advice was not selected for this observation".into());
    }
    memory.mark_emitted(match_id, epoch, source_ms, stage, key)?;
    Ok(json!({"id":frame_id,"origin":"rust_match_brain_ack_v1","acknowledged":true}))
}

pub fn observe_event(request: &Value, memory: &mut MatchMemory) -> Result<Value, String> {
    let frame_id = request["id"].as_i64().ok_or("id missing")?;
    let match_id = request["match_id"].as_str().ok_or("match identity missing")?;
    let source_ms = request["source_ms"].as_i64().ok_or("source time missing")?;
    let epoch = request["epoch"].as_i64().ok_or("epoch missing")?;
    let event = request.get("event").ok_or("match event missing")?;
    memory.record_event(match_id, frame_id, epoch, source_ms, event)?;
    Ok(json!({"id":frame_id,"origin":"rust_match_event_v1","stored":true}))
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn immediate_trait_completion_beats_economy_reminder() {
        let result=rank(&json!({"id":7,"source_ms":100,"context":{"gold":30},
            "observation":{"shop_fresh":true,"shop":[{"slot":2,"unit_id":"A",
                "catalog_status":"unique_name_bound","status":"offer_text_readable"}]},"candidates":[
            {"policy":"partial_state_live_v1","action":{"type":"prepare_level"}},
            {"policy":"partial_state_live_v1","action":{"type":"trait_shop_review",
                "shop_slot":2,"unit_id":"A","visible_trait_count":3,
                "next_breakpoint":4,"completes_breakpoint_if_fielded":true}}
        ]}), &mut MatchMemory::new(None)).unwrap();
        assert_eq!(result["selected_index"],1);
    }
    #[test] fn incomplete_trait_is_stored_but_not_spoken() {
        let candidate=json!({"policy":"partial_state_live_v1","action":{
            "type":"trait_shop_review","shop_slot":2,"unit_id":"A",
            "visible_trait_count":3,"next_breakpoint":5,
            "completes_breakpoint_if_fielded":false}});
        let request=|fresh| json!({"id":7,"source_ms":100,"context":{"gold":40},
            "observation":{"shop_fresh":fresh,"shop":[{"slot":2,"unit_id":"A",
                "catalog_status":"unique_name_bound","status":"offer_text_readable"}]},
            "candidates":[candidate]});
        assert!(rank(&request(true), &mut MatchMemory::new(None)).unwrap()["selected_index"].is_null());
        assert!(rank(&request(false), &mut MatchMemory::new(None)).unwrap()["selected_index"].is_null());
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
        assert!(acknowledge(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "decision_key":"pair-b"}), &mut memory).is_err());
        acknowledge(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "decision_key":"pair-a"}), &mut memory).unwrap();
        let next=rank(&json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "observation":{"gold":30},"context":{"gold":30},"candidates":choices}), &mut memory).unwrap();
        assert_eq!(next["selected_index"],1);
        assert_eq!(next["ranked"].as_array().unwrap().iter()
            .find(|row| row["decision_key"] == "pair-b").unwrap()["observed_times_90s"], 1);
        assert_eq!(next["memory"]["observed_rows_90s"],1);
    }
    #[test]
    fn whole_state_tries_an_alternative_and_keeps_context_when_every_tip_was_emitted() {
        let mut memory = MatchMemory::new(None);
        let id = "0123456789abcdef0123456789abcdef";
        let options = json!([
            {"policy":"partial_state_live_v1","decision_key":"trait-a",
                "action":{"type":"trait_shop_review","shop_slot":0,"unit_id":"A",
                    "visible_trait_count":3,
                    "next_breakpoint":4,"completes_breakpoint_if_fielded":true}},
            {"policy":"partial_state_live_v1","decision_key":"level-a",
                "action":{"type":"prepare_level"}}
        ]);
        let make = |frame, ms, stage| json!({"id":frame,"source_ms":ms,"epoch":0,
            "match_id":id,"context":{"gold":30},
            "observation":{"stage":stage,"gold":30,"hp":75,
                "shop_fresh":true,"shop":[{"slot":0,"unit_id":"A",
                    "catalog_status":"unique_name_bound","status":"offer_text_readable"}],
                "inventory":[{"current_candidate_id":"item-a","identity_verified":false}],
                "opponents":{"players":[{"name":"player-a","status":"persistent_candidate"}]}},
            "candidates":options});
        let first = rank(&make(1, 1000, "3-2"), &mut memory).unwrap();
        assert_eq!(first["selected_index"], 0);
        acknowledge(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "stage":"3-2","decision_key":"trait-a"}), &mut memory).unwrap();
        let second = rank(&make(2, 2000, "3-2"), &mut memory).unwrap();
        assert_eq!(second["selected_index"], 1);
        acknowledge(&json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "stage":"3-2","decision_key":"level-a"}), &mut memory).unwrap();
        assert_eq!(second["whole_state"]["item_candidates"], 1);
        assert_eq!(second["whole_state"]["opponent_candidates"], 1);
        let quiet = rank(&make(3, 3000, "3-2"), &mut memory).unwrap();
        assert_eq!(quiet["held_duplicate"], true);
        assert_eq!(quiet["selected_index"], Value::Null);
        let next_stage = rank(&make(4, 4000, "3-3"), &mut memory).unwrap();
        assert_eq!(next_stage["selected_index"], 0);
        assert_eq!(next_stage["memory"]["observed_rows_match"], 3);
    }
    #[test]
    fn same_trait_goal_from_two_readers_is_spoken_once() {
        let mut memory = MatchMemory::new(None);
        let id = "0123456789abcdef0123456789abcdef";
        let offer = json!({"slot":0,"unit_id":"DA_18_Ornn","status":"offer_text_readable",
            "catalog_status":"unique_name_bound","observed_cost":1,
            "catalog_traits":["Defendente"],
            "trait_breakpoints":{"Defendente":[2,4,6]}});
        let original = json!({"policy":"partial_state_live_v1","decision_key":"python-hash",
            "action":{"type":"trait_shop_review","shop_slot":0,
                "unit_id":"DA_18_Ornn","trait":"Defendente",
                "visible_trait_count":3,"next_breakpoint":4,
                "completes_breakpoint_if_fielded":true}});
        let first = rank(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "observation":{"gold":34,"shop_fresh":true,"shop":[offer],
                "trait_counts":{"Defendente":3}},"candidates":[original]}),
            &mut memory).unwrap();
        assert_eq!(first["selected_candidate"]["decision_key"],
            "goal:trait:DA_18_Ornn:Defendente:4");
        acknowledge(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "decision_key":"goal:trait:DA_18_Ornn:Defendente:4"}), &mut memory).unwrap();
        let next = rank(&json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "observation":{"gold":34,"trait_counts":{"Defendente":3}},
            "candidates":[]}), &mut memory).unwrap();
        assert_eq!(next["held_duplicate"], true);
        assert!(next["selected_index"].is_null());
    }
    #[test]
    fn observed_combat_loss_is_available_to_next_decision_without_claiming_a_cause() {
        let mut memory = MatchMemory::new(None);
        let id = "0123456789abcdef0123456789abcdef";
        let event = json!({"event":"combat_loss_observed","damage":8,
            "hp_before":60,"hp_after":52,"cause_status":"unresolved"});
        observe_event(&json!({"id":3,"source_ms":2000,"epoch":0,
            "match_id":id,"event":event}), &mut memory).unwrap();
        let result = rank(&json!({"id":4,"source_ms":2500,"epoch":0,
            "match_id":id,"observation":{"stage":"3-2","hp":52},"candidates":[]}),
            &mut memory).unwrap();
        assert_eq!(result["whole_state"]["last_combat_loss"]["damage"], 8);
        assert_eq!(result["whole_state"]["last_combat_loss"]["cause_status"], "unresolved");
        assert!(observe_event(&json!({"id":5,"source_ms":3000,"epoch":0,
            "match_id":id,"event":{"event":"combat_loss_observed","damage":8,
            "cause_status":"item_mistake"}}), &mut memory).is_err());
    }
    #[test]
    fn macro_pressure_and_verified_xp_quote_change_the_common_ranking() {
        let id = "0123456789abcdef0123456789abcdef";
        let mut memory = MatchMemory::new(None);
        memory.record(&json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "observation":{"stage":"5-1","gold":30,"hp":43}}), None).unwrap();
        let result = rank(&json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "observation":{"stage":"5-2","gold":24,"hp":30},"candidates":[
                {"policy":"partial_state_live_v1","decision_key":"provisional-xp",
                    "action":{"type":"buy_xp","target_level":8,"gold_cost":4,"gold_after":20}},
                {"policy":"replay_standard_tempo_v1","decision_key":"verified-xp",
                    "action":{"type":"buy_xp","target_level":8,"gold_cost":4,"gold_after":20},
                    "resource_quote":{"engine":"resource_budget_v1","target_level":8,
                        "gold_cost":4,"gold_after":20,"reserve_met":true}}
            ]}), &mut memory).unwrap();
        assert_eq!(result["selected_candidate"]["decision_key"], "verified-xp");
        assert_eq!(result["macro_state"]["phase"], "late");
        assert_eq!(result["macro_state"]["pressure"], "recovering");
        assert_eq!(result["macro_state"]["observed_hp_loss_90s"], 13);
        assert_eq!(result["macro_state"]["observed_gold_change_90s"], -6);
        assert_eq!(result["ranked"].as_array().unwrap().len(), 2);
    }
}
