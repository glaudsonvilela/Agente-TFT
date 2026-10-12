//! One bounded situation assembled from independent observations. Missing
//! evidence stays missing; visual candidates never become verified ownership.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

pub struct Situation {
    pub stage: Option<String>,
    pub gold: Option<i64>,
    pub hp: Option<i64>,
    pub level: Option<i64>,
    pub xp: Option<i64>,
    pub xp_threshold: Option<i64>,
    pub streak_kind_candidate: Option<String>,
    pub streak_count_verified: Option<i64>,
    pub shop: Vec<Value>,
    pub augment_options: Vec<Value>,
    pub augment_selection_visible: bool,
    pub augment_catalog: Option<Value>,
    pub augment_source_ms: Option<i64>,
    pub augment_selection_confirmed: bool,
    pub augment_ground_truth: bool,
    pub trait_counts: BTreeMap<String, i64>,
    pub board_candidates: usize,
    pub fielded_unit_candidates: Vec<String>,
    pub item_candidates: usize,
    pub opponent_candidates: usize,
    pub enemy_visible_item_icons: usize,
    pub enemy_equipped_unit_tracks: usize,
    pub opponent_linked: bool,
    pub board_identity_verified: bool,
    pub last_combat_loss: Option<Value>,
    pub ages_ms: BTreeMap<&'static str, i64>,
}

impl Situation {
    fn augment_evidence(&self) -> Value {
        let mut uniquely_bound = 0;
        let mut ambiguous_id = 0;
        let mut disabled_reference_conflict_slots = Vec::new();
        let mut stage_restriction_conflict_slots = Vec::new();
        for option in &self.augment_options {
            if option["status"] == "catalog_name_bound" { uniquely_bound += 1; }
            if option["status"] == "catalog_name_ambiguous_id" { ambiguous_id += 1; }
            let Some(refs) = option["candidate_references"].as_array()
                .filter(|refs| !refs.is_empty()) else { continue };
            if refs.iter().all(|row| row["patch_rule"]["availability"] ==
                    "temporarily_disabled_18_4b") {
                disabled_reference_conflict_slots.push(option["slot"].clone());
            }
            if let Some(stage) = self.stage.as_deref() {
                if refs.iter().all(|row| row["patch_rule"]["not_offered_on"]
                    .as_array().is_some_and(|stages| stages.iter().any(|s| s == stage))) {
                    stage_restriction_conflict_slots.push(option["slot"].clone());
                }
            }
        }
        json!({"offer_count":self.augment_options.len(),
            "uniquely_bound":uniquely_bound,"ambiguous_id":ambiguous_id,
            "disabled_reference_conflict_slots":disabled_reference_conflict_slots,
            "stage_restriction_conflict_slots":stage_restriction_conflict_slots,
            "rules_patch":self.augment_catalog.as_ref().map(|v| &v["rules_patch"]),
            "rules_patch_confirmed_from_replay_client":self.augment_catalog.as_ref()
                .is_some_and(|v| v["rules_patch_confirmed_from_replay_client"] == true),
            "selection_confirmed":self.augment_selection_confirmed,
            "ground_truth":self.augment_ground_truth})
    }

    pub fn diagnostics(&self) -> Value {
        json!({"stage":self.stage,"gold":self.gold,"hp":self.hp,"level":self.level,
            "xp":self.xp,"xp_threshold":self.xp_threshold,
            "streak_kind_candidate":self.streak_kind_candidate,
            "streak_count_verified":self.streak_count_verified,
            "fresh_shop_offers":self.shop.len(),"trait_counts":self.trait_counts,
            "augment_selection_visible":self.augment_selection_visible,
            "augment_options":self.augment_options,
            "augment_catalog":self.augment_catalog,
            "augment_source_ms":self.augment_source_ms,
            "augment_selection_confirmed":self.augment_selection_confirmed,
            "augment_ground_truth":self.augment_ground_truth,
            "augment_evidence":self.augment_evidence(),
            "board_candidates":self.board_candidates,
            "fielded_unit_candidates":self.fielded_unit_candidates,
            "item_candidates":self.item_candidates,"opponent_candidates":self.opponent_candidates,
            "opponent_linked":self.opponent_linked,
            "enemy_visible_item_icons":self.enemy_visible_item_icons,
            "enemy_equipped_unit_tracks":self.enemy_equipped_unit_tracks,
            "ages_ms":self.ages_ms,
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
    let xp = read_field("xp", 2_500, now, epoch, current, recent, &mut ages_ms,
        |v| valid_number(v, 0, 100)).and_then(|v| v.as_i64());
    let xp_threshold = read_field("xp_threshold", 2_500, now, epoch, current, recent,
        &mut ages_ms, |v| valid_number(v, 1, 100))
        .and_then(|v| v.as_i64()).filter(|threshold|
            xp.is_some_and(|value| value < *threshold) &&
            ages_ms.get("xp") == ages_ms.get("xp_threshold"));
    let streak = read_field("streak", 3_500, now, epoch, current, recent, &mut ages_ms,
        |v| v["status"] == "icon_color_candidate" && v["verified"] == false &&
            matches!(v["kind"].as_str(), Some("win" | "loss")) &&
            v["source_ms"].as_f64().is_some_and(|at| {
                let age = now as f64 - at;
                age.is_finite() && (0.0..=3_500.0).contains(&age)
            }));
    let streak_kind_candidate = streak.as_ref()
        .and_then(|v| v["kind"].as_str()).map(str::to_owned);
    let streak_count_verified = None;
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
    // A closed choice overlay clears options immediately. A visible offer is
    // retained only briefly across asynchronous OCR and never means chosen.
    let augment_hidden = current["augment_selection_visible"] == false;
    let augment_read = if augment_hidden { None } else {
        std::iter::once((now, epoch, current)).chain(recent.iter().rev()
            .map(|(ms, segment, row)| (*ms, *segment, row)))
            .find(|(at, segment, row)| *segment == epoch && *at <= now &&
                now - *at <= 3_500 && row["augment_selection_visible"] == true &&
                row["augment_options"].as_array().is_some_and(|options| {
                    options.len() == 3 && options.iter().enumerate().all(|(slot, option)|
                        option["slot"].as_u64() == Some(slot as u64))
                }))
    };
    let (augment_options, augment_catalog, augment_source_ms,
         augment_selection_confirmed, augment_ground_truth) = match augment_read {
        Some((at, _, row)) => {
            ages_ms.insert("augment_options", now - at);
            (row["augment_options"].as_array().cloned().unwrap_or_default(),
             row["augment_catalog"].as_object().map(|_| row["augment_catalog"].clone()),
             row["augment_source_ms"].as_f64().map(|ms| ms.round() as i64),
             row["augment_selection_confirmed"] == true,
             row["augment_ground_truth"] == true)
        },
        None => (Vec::new(), None, None, false, false),
    };
    let augment_selection_visible = !augment_options.is_empty();
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
    let enemy_equipment = read_field("enemy_equipment", 1_000, now, epoch, current, recent,
        &mut ages_ms, |v| v["status"] == "observed_minimum")
        .unwrap_or(Value::Null);
    let board_candidates = board.as_array().map_or(0, Vec::len);
    let item_candidates = inventory.as_array().map_or(0, Vec::len) +
        equipped.as_array().map_or(0, Vec::len);
    let opponent_candidates = opponents["players"].as_array().map_or(0, Vec::len);
    let enemy_visible_item_icons = enemy_equipment["visible_item_icons"].as_u64()
        .map_or(0, |value| value.min(30) as usize);
    let enemy_equipped_unit_tracks = enemy_equipment["equipped_unit_tracks"].as_u64()
        .map_or(0, |value| value.min(10) as usize);
    let opponent_linked = opponents["opponent_board_assigned"] == true &&
        opponents["current_opponent_status"] == "linked";
    let board_identity_verified = current["board_identity_verified"] == true;
    Situation { stage, gold, hp, level, xp, xp_threshold, streak_kind_candidate,
        streak_count_verified, shop, augment_options, augment_selection_visible,
        augment_catalog, augment_source_ms, augment_selection_confirmed,
        augment_ground_truth,
        trait_counts, board_candidates,
        fielded_unit_candidates:fielded.into_iter().collect(), item_candidates,
        opponent_candidates, enemy_visible_item_icons, enemy_equipped_unit_tracks,
        opponent_linked, board_identity_verified,
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
    fn gold_xp_and_streak_candidate_keep_distinct_confidence() {
        let empty = VecDeque::new();
        let current = json!({"gold":42,"xp":8,"xp_threshold":60,
            "streak":{"status":"icon_color_candidate","kind":"loss",
                "count":null,"verified":false,"source_ms":1000.5}});
        let state = integrate(&current, &empty, 0, 1200, None);
        assert_eq!((state.gold, state.xp, state.xp_threshold),
            (Some(42), Some(8), Some(60)));
        assert_eq!(state.streak_kind_candidate.as_deref(), Some("loss"));
        assert_eq!(state.streak_count_verified, None);
        assert_eq!(integrate(&current, &empty, 0, 5000, None).streak_kind_candidate, None);
    }
    #[test]
    fn augment_options_are_recent_and_clear_when_overlay_closes() {
        let options = json!([
            {"slot":0,"candidate_id":"DA_PatientStudy","status":"catalog_name_bound",
                "candidate_references":[{"id":"DA_PatientStudy",
                    "patch_rule":{"availability":"unverified"}}],
                "training_label":false,"selection_confirmed":false},
            {"slot":1,"candidate_id":"DA_Hustler","status":"catalog_name_bound"},
            {"slot":2,"candidate_id":"DA_18_CovenTraitAugment","status":"catalog_name_bound"}]);
        let recent = VecDeque::from([(1000, 0, json!({
            "augment_selection_visible":true,"augment_options":options,
            "augment_catalog":{"lookup_entry_count":762,"rules_patch":"18.4B",
                "rules_patch_confirmed_from_replay_client":false},
            "augment_source_ms":1000,"augment_selection_confirmed":false,
            "augment_ground_truth":false}))]);
        let visible = integrate(&json!({}), &recent, 0, 1200, None);
        assert!(visible.augment_selection_visible);
        assert_eq!(visible.augment_options.len(), 3);
        assert_eq!(visible.augment_options[0]["candidate_references"][0]
                   ["patch_rule"]["availability"], "unverified");
        assert_eq!(visible.augment_catalog.as_ref().unwrap()["lookup_entry_count"], 762);
        assert_eq!(visible.augment_source_ms, Some(1000));
        assert!(!visible.augment_selection_confirmed);
        assert!(!visible.augment_ground_truth);
        let closed = integrate(&json!({"augment_selection_visible":false,
            "augment_options":[]}), &recent, 0, 1200, None);
        assert!(!closed.augment_selection_visible);
        assert!(closed.augment_options.is_empty());
        assert!(closed.augment_catalog.is_none());
        let stale = integrate(&json!({}), &recent, 0, 5000, None);
        assert!(!stale.augment_selection_visible);
        assert!(stale.augment_options.is_empty());
    }
    #[test]
    fn patch_stage_rule_is_a_reference_conflict_not_a_training_label() {
        let current = json!({"stage":"2-1","augment_selection_visible":true,
            "augment_selection_confirmed":false,"augment_ground_truth":false,
            "augment_catalog":{"rules_patch":"18.4B",
                "rules_patch_confirmed_from_replay_client":false},
            "augment_options":[
                {"slot":0,"status":"catalog_name_ambiguous_id",
                    "candidate_references":[{"patch_rule":{
                        "availability":"stage_restricted","not_offered_on":["2-1"]}}]},
                {"slot":1,"status":"unresolved"},
                {"slot":2,"status":"catalog_name_bound"}]});
        let state = integrate(&current, &VecDeque::new(), 0, 1000, None);
        let evidence = &state.diagnostics()["augment_evidence"];
        assert_eq!(evidence["stage_restriction_conflict_slots"], json!([0]));
        assert_eq!(evidence["ambiguous_id"], 1);
        assert_eq!(evidence["rules_patch_confirmed_from_replay_client"], false);
        assert_eq!(evidence["ground_truth"], false);
    }
    #[test]
    fn enemy_equipment_is_a_bounded_recent_observation() {
        let recent = VecDeque::from([(1000, 0, json!({"enemy_equipment":{
            "status":"observed_minimum","visible_item_icons":2,
            "equipped_unit_tracks":1,"sampled_red_bars":4}}))]);
        let current = json!({});
        let fresh = integrate(&current, &recent, 0, 1750, None);
        assert_eq!(fresh.enemy_visible_item_icons, 2);
        assert_eq!(fresh.enemy_equipped_unit_tracks, 1);
        assert_eq!(integrate(&current, &recent, 0, 2101, None).enemy_visible_item_icons, 0);
        assert_eq!(integrate(&current, &recent, 1, 1750, None).enemy_visible_item_icons, 0);
    }
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
