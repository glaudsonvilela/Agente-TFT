//! Compute only combat facts supported by observations. A life drop does not
//! identify the unit, position, item, or opponent that caused the loss.
use serde_json::{json, Value};

pub fn analyze(request: &Value) -> Result<Value, String> {
    let id = request["id"].as_u64().ok_or("id missing")?;
    let before = request["hp_before"].as_i64().ok_or("hp_before missing")?;
    let after = request["hp_after"].as_i64().ok_or("hp_after missing")?;
    if !(0..=100).contains(&after) || !(1..=100).contains(&before) || after >= before {
        return Err("invalid HP drop".into());
    }
    // This operation deliberately has no inferred cause input. Future combat
    // explanations require independently verified, time-aligned unit events.
    Ok(json!({"id":id,"origin":"rust_combat_facts_v1",
        "hp_before":before,"hp_after":after,"damage":before-after,
        "outcome":"hp_drop_observed","cause_status":"unresolved",
        "causal_explanation":null,
        "missing_evidence":["own_units_verified","opponent_units_verified",
            "damage_and_survival_timeline","unit_positions_and_items"],
        "basis":["player.hp.temporal_drop"]}))
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn computes_damage_without_inventing_a_cause() {
        let result = analyze(&json!({"id":4,"hp_before":86,"hp_after":79})).unwrap();
        assert_eq!(result["damage"], 7);
        assert_eq!(result["cause_status"], "unresolved");
        assert!(result["causal_explanation"].is_null());
    }
    #[test] fn rejects_invalid_drop() {
        for (before, after) in [(50, 50), (20, 30), (101, 90), (50, -1)] {
            assert!(analyze(&json!({"id":4,"hp_before":before,"hp_after":after})).is_err());
        }
    }
}
