//! One bounded situation assembled from independent observations. Missing
//! evidence stays missing; visual candidates never become verified ownership.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

pub struct Situation {
    pub stage: Option<String>,
    pub gold: Option<i64>,
    pub hp: Option<i64>,
    pub level: Option<i64>,
    pub shop: Vec<Value>,
    pub trait_counts: BTreeMap<String, i64>,
    pub board_candidates: usize,
    pub fielded_unit_candidates: Vec<String>,
    pub item_candidates: usize,
    pub opponent_candidates: usize,
    pub opponent_linked: bool,
    pub board_identity_verified: bool,
    pub last_combat_loss: Option<Value>,
    pub ages_ms: BTreeMap<&'static str, i64>,
}

impl Situation {
    pub fn diagnostics(&self) -> Value {
        json!({"stage":self.stage,"gold":self.gold,"hp":self.hp,"level":self.level,
            "fresh_shop_offers":self.shop.len(),"trait_counts":self.trait_counts,
            "board_candidates":self.board_candidates,
            "fielded_unit_candidates":self.fielded_unit_candidates,
            "item_candidates":self.item_candidates,"opponent_candidates":self.opponent_candidates,
            "opponent_linked":self.opponent_linked,"ages_ms":self.ages_ms,
            "board_identity_verified":self.board_identity_verified,
            "last_combat_loss":self.last_combat_loss})
    }

    pub fn derive_candidates(&self) -> Vec<Value> {
        let Some(gold) = self.gold else { return Vec::new() };
        let mut by_unit: BTreeMap<&str, Vec<(i64, i64)>> = BTreeMap::new();
        for offer in &self.shop {
            if offer["catalog_status"] != "unique_name_bound" ||
               offer["status"] != "offer_text_readable" { continue; }
            let (Some(unit), Some(slot), Some(cost)) = (offer["unit_id"].as_str(),
                offer["slot"].as_i64(), offer["observed_cost"].as_i64()) else { continue };
            if !(0..5).contains(&slot) || !(1..=5).contains(&cost) { continue; }
            by_unit.entry(unit).or_default().push((slot, cost));
        }
        let mut result = Vec::new();
        for (unit, offers) in by_unit {
            if offers.len() < 2 || offers[0].1 != offers[1].1 ||
               gold < offers[0].1 * 2 { continue; }
            result.push(json!({"schema_version":"0.1.0","policy":"integrated_match_v1",
                "action":{"type":"buy_pair","unit_id":unit,
                    "shop_slots":[offers[0].0,offers[1].0],"catalog_cost_each":offers[0].1},
                "decision_key":format!("provisional:whole:pair:{unit}:{}-{}",offers[0].0,offers[1].0),
                "basis":["shop.two_fresh_exact_names","hud.gold"],
                "evidence_level":"provisional","family":"buy",
                "training_label":false,"learned_neural_weights":false}));
        }
        for offer in &self.shop {
            if offer["catalog_status"] != "unique_name_bound" ||
               offer["status"] != "offer_text_readable" { continue; }
            let (Some(unit),Some(slot),Some(cost))=(offer["unit_id"].as_str(),
                offer["slot"].as_i64(),offer["observed_cost"].as_i64()) else { continue };
            if !(0..5).contains(&slot) || !(1..=5).contains(&cost) || gold < cost { continue; }
            if self.fielded_unit_candidates.iter().any(|existing| existing == unit) { continue; }
            let Some(traits)=offer["catalog_traits"].as_array() else { continue };
            for trait_value in traits {
                let Some(trait_name)=trait_value.as_str() else { continue };
                let Some(&count)=self.trait_counts.get(trait_name) else { continue };
                if !(1..=9).contains(&count) { continue; }
                let Some(tiers)=offer["trait_breakpoints"][trait_name].as_array() else { continue };
                let next=tiers.iter().filter_map(Value::as_i64)
                    .filter(|tier| *tier > count && *tier <= 12).min();
                if next != Some(count+1) { continue; }
                result.push(json!({"schema_version":"0.1.0","policy":"integrated_match_v1",
                    "action":{"type":"trait_shop_review","unit_id":unit,"shop_slot":slot,
                        "trait":trait_name,"visible_trait_count":count,
                        "next_breakpoint":count+1,"completes_breakpoint_if_fielded":true},
                    "decision_key":format!("provisional:whole:trait:{unit}:{trait_name}:{count}:{}:{slot}",count+1),
                    "basis":["shop.fresh_exact_name","hub.recent_confirmed_trait_count",
                        "patch.trait_breakpoint","hud.gold"],
                    "evidence_level":"provisional","family":"synergy",
                    "training_label":false,"learned_neural_weights":false}));
            }
        }
        result
    }
}

fn valid_number(value: &Value, low: i64, high: i64) -> bool {
    value.as_i64().is_some_and(|n| (low..=high).contains(&n))
}

fn select<'a>(field: &'static str, ttl: i64, now: i64, epoch: i64,
              current: &'a Value, recent: &'a VecDeque<(i64, i64, Value)>,
              accept: impl Fn(&Value) -> bool) -> Option<(Value, i64)> {
    let candidates = std::iter::once((now, epoch, current)).chain(recent.iter().rev()
        .map(|(ms, segment, row)| (*ms, *segment, row)));
    for (at, segment, row) in candidates {
        if segment != epoch || at > now || now - at > ttl { continue; }
        let value = &row[field];
        if accept(value) { return Some((value.clone(), now - at)); }
    }
    None
}

fn read_field(field: &'static str, ttl: i64, now: i64, epoch: i64,
              current: &Value, recent: &VecDeque<(i64, i64, Value)>,
              ages: &mut BTreeMap<&'static str, i64>,
              accept: impl Fn(&Value) -> bool) -> Option<Value> {
    let result = select(field, ttl, now, epoch, current, recent, accept);
    if let Some((_, age)) = &result { ages.insert(field, *age); }
    result.map(|(value, _)| value)
}

pub fn integrate(current: &Value, recent: &VecDeque<(i64, i64, Value)>,
                 epoch: i64, now: i64, last_combat_loss: Option<&Value>) -> Situation {
    let mut ages_ms = BTreeMap::new();
    let stage = read_field("stage", 10_000, now, epoch, current, recent, &mut ages_ms,
        |v| v.as_str().is_some_and(|s| {
        let bytes = s.as_bytes();
        bytes.len() == 3 && (b'1'..=b'9').contains(&bytes[0]) && bytes[1] == b'-' &&
            (b'1'..=b'7').contains(&bytes[2])
    })).and_then(|v| v.as_str().map(str::to_owned));
    let gold = read_field("gold", 2_500, now, epoch, current, recent, &mut ages_ms,
        |v| valid_number(v, 0, 300)).and_then(|v| v.as_i64());
    let hp = read_field("hp", 5_000, now, epoch, current, recent, &mut ages_ms,
        |v| valid_number(v, 0, 100)).and_then(|v| v.as_i64());
    let level = read_field("level", 5_000, now, epoch, current, recent, &mut ages_ms,
        |v| valid_number(v, 1, 10)).and_then(|v| v.as_i64());
    // An explicitly hidden shop clears the active offer set. Otherwise, the
    // last fresh read survives the reader's normal two-second cadence.
    let hidden = current["shop"].as_array().is_some_and(|rows| !rows.is_empty() &&
        rows.iter().all(|r| r["status"] == "unavailable"));
    let shop = if hidden { Vec::new() } else {
        let frames = std::iter::once((now, epoch, current)).chain(recent.iter().rev()
            .map(|(ms, segment, row)| (*ms, *segment, row)));
        frames.filter(|(at, segment, row)| *segment == epoch && *at <= now &&
            now - *at <= 2_500 && row["shop_fresh"] == true)
            .find_map(|(at, _, row)| row["shop"].as_array().map(|offers| {
                ages_ms.insert("shop", now - at); offers.clone()
            })).unwrap_or_default()
    };
    let mut trait_counts = BTreeMap::new();
    for (at, segment, row) in std::iter::once((now, epoch, current)).chain(recent.iter().rev()
        .map(|(ms, segment, row)| (*ms, *segment, row))) {
        if segment != epoch || at > now || now-at > 3_500 { continue; }
        if let Some(traits) = row["trait_counts"].as_object() {
            for (name, count) in traits {
                if let Some(value) = count.as_i64().filter(|n| (0..=10).contains(n)) {
                    trait_counts.entry(name.clone()).or_insert(value);
                    ages_ms.entry("trait_counts").or_insert(now-at);
                }
            }
        }
    }
    let board = read_field("board", 3_500, now, epoch, current, recent, &mut ages_ms,
        Value::is_array).unwrap_or(Value::Null);
    let mut fielded = BTreeSet::new();
    for (at, segment, row) in std::iter::once((now, epoch, current)).chain(recent.iter().rev()
        .map(|(ms, segment, row)| (*ms, *segment, row))) {
        if segment != epoch || at > now || now-at > 3_500 { continue; }
        if let Some(units) = row["board"].as_array() {
            for unit in units {
                if unit["status"] == "persistent_candidate" &&
                    unit["support_frames"].as_i64().is_some_and(|n| n >= 2) &&
                    unit["position"][0] == "board" {
                    if let Some(id) = unit["candidate_id"].as_str() {
                        fielded.insert(id.to_owned());
                    }
                }
            }
        }
    }
    let inventory = read_field("inventory", 3_500, now, epoch, current, recent, &mut ages_ms,
        Value::is_array).unwrap_or(Value::Null);
    let equipped = read_field("equipped", 3_500, now, epoch, current, recent, &mut ages_ms,
        Value::is_array).unwrap_or(Value::Null);
    let opponents = read_field("opponents", 5_000, now, epoch, current, recent, &mut ages_ms,
        Value::is_object).unwrap_or(Value::Null);
    let board_candidates = board.as_array().map_or(0, Vec::len);
    let item_candidates = inventory.as_array().map_or(0, Vec::len) +
        equipped.as_array().map_or(0, Vec::len);
    let opponent_candidates = opponents["players"].as_array().map_or(0, Vec::len);
    let opponent_linked = opponents["opponent_board_assigned"] == true &&
        opponents["current_opponent_status"] == "linked";
    let board_identity_verified = current["board_identity_verified"] == true;
    Situation { stage, gold, hp, level, shop, trait_counts, board_candidates,
        fielded_unit_candidates:fielded.into_iter().collect(), item_candidates,
        opponent_candidates, opponent_linked, board_identity_verified,
        last_combat_loss:last_combat_loss.cloned(), ages_ms }
}

/// Rehydrate recent facts from the durable pool, preserving each fact's own
/// observation time. The normal per-field TTL in integrate still applies.
pub fn pooled_snapshots(pool: &Value, epoch: i64) -> VecDeque<(i64, i64, Value)> {
    let mut rows = Vec::new();
    let Some(facts) = pool.as_object() else { return VecDeque::new() };
    for (field, fact) in facts {
        if field == "traits" {
            if let Some(traits) = fact.as_object() {
                for (name, entry) in traits {
                    if let Some(at) = entry["source_ms"].as_i64() {
                        rows.push((at, epoch, json!({"trait_counts":{name:entry["value"]}})));
                    }
                }
            }
        } else if field == "units" {
            if let Some(units) = fact.as_object() {
                for entry in units.values() {
                    if let Some(at) = entry["source_ms"].as_i64() {
                        rows.push((at, epoch, json!({"board":[entry["value"]]})));
                    }
                }
            }
        } else if let Some(at) = fact["source_ms"].as_i64() {
            let mut observation = serde_json::Map::new();
            observation.insert(field.clone(), fact["value"].clone());
            if field == "shop" { observation.insert("shop_fresh".into(), Value::Bool(true)); }
            rows.push((at, epoch, Value::Object(observation)));
        }
    }
    rows.sort_by_key(|(at, _, _)| *at);
    rows.into()
}

#[cfg(test)] mod tests {
    use super::*;
    #[test]
    fn merges_only_fresh_same_epoch_evidence_and_keeps_candidates_unverified() {
        let recent = VecDeque::from([(1000, 0, json!({"stage":"3-2","gold":34,"hp":71,
            "board":[{"candidate_id":"Ornn","identity_verified":false}],
            "shop":[{"slot":0,"unit_id":"A","status":"offer_text_readable",
                "catalog_status":"unique_name_bound","observed_cost":2}]}))]);
        let state = integrate(&json!({"stage":null,"gold":null,"hp":null}), &recent, 0, 2000, None);
        assert_eq!(state.gold, Some(34));
        assert_eq!(state.board_candidates, 1);
        assert_eq!(state.diagnostics()["board_identity_verified"], false);
        assert_eq!(integrate(&json!({}), &recent, 1, 2000, None).gold, None);
        assert_eq!(integrate(&json!({}), &recent, 0, 5000, None).gold, None);
    }
    #[test]
    fn derives_pair_only_from_two_fresh_affordable_matching_offers() {
        let shop = json!([{"slot":0,"unit_id":"A","status":"offer_text_readable",
            "catalog_status":"unique_name_bound","observed_cost":2},
            {"slot":3,"unit_id":"A","status":"offer_text_readable",
            "catalog_status":"unique_name_bound","observed_cost":2}]);
        let empty = VecDeque::new();
        let state = integrate(&json!({"gold":4,"shop":shop,"shop_fresh":true}), &empty, 0, 1000, None);
        assert_eq!(state.derive_candidates().len(), 1);
        let hidden = integrate(&json!({"gold":4,"shop":shop,"shop_fresh":false}), &empty, 0, 1000, None);
        assert!(hidden.derive_candidates().is_empty());
    }
    #[test]
    fn joins_shop_and_trait_read_on_different_frames() {
        let shop = json!([{"slot":2,"unit_id":"TFT_Sejuani",
            "observed_name":"Sejuani","status":"offer_text_readable",
            "catalog_status":"unique_name_bound","observed_cost":2,
            "catalog_traits":["Defendente"],
            "trait_breakpoints":{"Defendente":[2,4,6]}}]);
        let recent = VecDeque::from([(1_000, 0, json!({"gold":39,
            "shop_fresh":true,"shop":shop}))]);
        let state = integrate(&json!({"trait_counts":{"Defendente":3}}),
            &recent, 0, 2_000, None);
        assert_eq!(state.derive_candidates()[0]["action"]["unit_id"], "TFT_Sejuani");
        assert_eq!(state.derive_candidates()[0]["action"]["next_breakpoint"], 4);
        assert!(integrate(&json!({"trait_counts":{"Defendente":3}}),
            &recent, 0, 4_000, None).derive_candidates().is_empty());
    }
    #[test]
    fn pooled_facts_keep_independent_trait_times_without_reviving_old_shop() {
        let pool = json!({"gold":{"source_ms":1_000,"value":30},
            "shop":{"source_ms":1_000,"value":[{"slot":0,"unit_id":"A"}]},
            "traits":{"Defendente":{"source_ms":2_000,"value":3},
                "Inferno":{"source_ms":2_500,"value":2}}});
        let recent = pooled_snapshots(&pool, 0);
        let state = integrate(&json!({}), &recent, 0, 4_000, None);
        assert_eq!(state.trait_counts["Defendente"], 3);
        assert_eq!(state.trait_counts["Inferno"], 2);
        assert!(state.shop.is_empty());
    }
    #[test]
    fn recent_field_candidate_prevents_recommending_the_same_trait_unit_again() {
        let pool = json!({"units":{"board:0:4:0":{"source_ms":1_500,
            "value":{"candidate_id":"DA_18_Ornn","status":"persistent_candidate",
                "support_frames":3,"position":["board",0,4]}}}});
        let recent = pooled_snapshots(&pool, 0);
        let current = json!({"gold":34,"trait_counts":{"Defendente":3},
            "shop_fresh":true,"shop":[{"slot":0,"unit_id":"DA_18_Ornn",
                "catalog_status":"unique_name_bound","status":"offer_text_readable",
                "observed_cost":1,"catalog_traits":["Defendente"],
                "trait_breakpoints":{"Defendente":[2,4,6]}}]});
        let state = integrate(&current, &recent, 0, 2_000, None);
        assert_eq!(state.fielded_unit_candidates, vec!["DA_18_Ornn"]);
        assert!(state.derive_candidates().is_empty());
    }
}
