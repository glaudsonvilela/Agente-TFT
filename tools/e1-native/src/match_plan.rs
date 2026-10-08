//! A spoken recommendation becomes a revisable hypothesis, never a training label.
use serde_json::{json, Value};
use crate::match_brain::Situation;

pub fn goal(action: &Value) -> Option<String> {
    match action["type"].as_str()? {
        "trait_shop_review" => Some(format!("trait:{}:{}",
            action["trait"].as_str()?, action["next_breakpoint"].as_i64()?)),
        "buy_xp" | "prepare_level" | "rebuild_after_level" =>
            Some(format!("level:{}",action["target_level"].as_i64()?)),
        "buy_pair" => Some(format!("pair:{}",action["unit_id"].as_str()?)),
        _ => None,
    }
}

/// Reward a newly viable step toward a spoken plan, without bypassing normal
/// evidence and resource checks or preventing a more urgent change of course.
pub fn alignment_bonus(plan: Option<&Value>, candidate: &Value) -> f32 {
    let Some(plan) = plan.filter(|plan| plan["status"] == "observing") else { return 0.0 };
    if goal(&plan["action"]).is_some_and(|held| Some(held) == goal(&candidate["action"])) {
        0.10
    } else { 0.0 }
}

pub fn expectation(candidate: &Value) -> Value {
    let action = &candidate["action"];
    match action["type"].as_str() {
        Some("trait_shop_review") => match (action["trait"].as_str(),
            action["next_breakpoint"].as_i64()) {
            (Some(name), Some(target)) if (1..=12).contains(&target) => json!({
                "kind":"trait_reaches", "trait":name, "target":target,
                "condition":"player_acquires_and_fields_unit",
                "causal_claim":false}),
            _ => json!({"kind":"not_observable","causal_claim":false}),
        },
        Some("buy_xp" | "prepare_level" | "rebuild_after_level") =>
            match action["target_level"].as_i64() {
                Some(target) if (2..=10).contains(&target) => json!({
                    "kind":"level_reaches", "target":target,
                    "condition":"player_buys_xp_or_levels_naturally",
                    "causal_claim":false}),
                _ => json!({"kind":"not_observable","causal_claim":false}),
            },
        // Seeing a shop change does not prove that a pair was bought or a roll
        // was taken. Do not call an unverifiable action a success or failure.
        _ => json!({"kind":"not_observable","causal_claim":false}),
    }
}

pub fn review(plan: &Value, situation: &Situation, now_ms: i64) -> Value {
    let started = plan["source_ms"].as_i64().unwrap_or(now_ms);
    let age = now_ms.saturating_sub(started);
    let target = &plan["expectation"];
    let observed = match target["kind"].as_str() {
        Some("trait_reaches") => target["trait"].as_str()
            .and_then(|name| situation.trait_counts.get(name))
            .zip(target["target"].as_i64())
            .is_some_and(|(count, threshold)| *count >= threshold),
        Some("level_reaches") => situation.level.zip(target["target"].as_i64())
            .is_some_and(|(level, threshold)| level >= threshold),
        _ => false,
    };
    let (status, reason) = if observed {
        ("target_observed", "observed_state_reached_target_not_proof_of_advice_effect")
    } else if age > 120_000 {
        ("expired_unverified", "observation_window_ended_without_verifiable_outcome")
    } else {
        ("observing", "awaiting_new_evidence")
    };
    json!({"status":status,"reason":reason,"age_ms":age,
        "causal_claim":false,"training_label":false})
}

#[cfg(test)] mod tests {
    use super::*;
    use crate::match_brain::integrate;
    use std::collections::VecDeque;

    #[test]
    fn trait_target_is_observed_without_claiming_the_tip_caused_it() {
        let candidate=json!({"action":{"type":"trait_shop_review",
            "trait":"Defendente","next_breakpoint":4}});
        let plan=json!({"source_ms":1000,"expectation":expectation(&candidate)});
        let empty=VecDeque::new();
        let state=integrate(&json!({"trait_counts":{"Defendente":4}}),&empty,0,2000,None);
        let result=review(&plan,&state,2000);
        assert_eq!(result["status"],"target_observed");
        assert_eq!(result["causal_claim"],false);
        assert_eq!(result["training_label"],false);
    }

    #[test]
    fn unknown_action_expires_unverified_not_failed() {
        let candidate=json!({"action":{"type":"buy_pair","unit_id":"A"}});
        let plan=json!({"source_ms":1000,"expectation":expectation(&candidate)});
        let state=integrate(&json!({}),&VecDeque::new(),0,122_000,None);
        assert_eq!(review(&plan,&state,122_000)["status"],"expired_unverified");
    }

    #[test]
    fn a_leveling_plan_supports_a_verified_next_step_but_not_an_unrelated_tip() {
        let plan=json!({"status":"observing","action":{"type":"prepare_level",
            "target_level":8}});
        assert_eq!(alignment_bonus(Some(&plan),&json!({"action":{"type":"buy_xp",
            "target_level":8}})),0.10);
        assert_eq!(alignment_bonus(Some(&plan),&json!({"action":{"type":"buy_xp",
            "target_level":9}})),0.0);
        assert_eq!(alignment_bonus(Some(&plan),&json!({"action":{"type":"hold_econ"}})),0.0);
    }
}
