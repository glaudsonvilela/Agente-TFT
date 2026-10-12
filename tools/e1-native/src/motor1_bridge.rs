//! Complete Motor 1 observations in the Rust strategy lane. The full JSON is
//! available to strategy/AI code, while all candidate flags remain unchanged.
use base64::{engine::general_purpose::STANDARD, Engine as _};
use flate2::read::ZlibDecoder;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::Read;

const MAX_RAW: usize = 1_000_000;
const MAX_ENCODED: usize = 64_000;

fn decode(packed: &Value) -> Result<Value, String> {
    if packed["codec"] != "zlib_json_base64_v1" {
        return Err("unsupported Motor 1 codec".into());
    }
    let data = packed["data"].as_str().ok_or("Motor 1 data missing")?;
    if data.len() > MAX_ENCODED { return Err("Motor 1 encoded budget exceeded".into()); }
    let compressed = STANDARD.decode(data).map_err(|e| e.to_string())?;
    let mut reader = ZlibDecoder::new(compressed.as_slice()).take((MAX_RAW + 1) as u64);
    let mut raw = Vec::new();
    reader.read_to_end(&mut raw).map_err(|e| e.to_string())?;
    if raw.len() > MAX_RAW || packed["raw_bytes"].as_u64() != Some(raw.len() as u64) {
        return Err("Motor 1 raw size mismatch".into());
    }
    let digest = format!("{:x}", Sha256::digest(&raw));
    if packed["sha256"].as_str() != Some(digest.as_str()) {
        return Err("Motor 1 digest mismatch".into());
    }
    serde_json::from_slice(&raw).map_err(|e| e.to_string())
}

pub struct Motor1Evidence {
    pub reader: Value,
    pub hub: Option<Value>,
    pub aux: Value,
    pub hub_age_ms: Option<i64>,
}

impl Motor1Evidence {
    pub fn from_request(request: &Value) -> Result<Option<Self>, String> {
        let packed = &request["motor1"];
        if packed.is_null() { return Ok(None); }
        if packed["schema"] != "motor1_to_motor2_v1" ||
            packed["epoch"] != request["epoch"] ||
            packed["source_ms"] != request["source_ms"] {
            return Err("Motor 1 epoch/source mismatch".into());
        }
        let reader = decode(&packed["reader"])?;
        let aux = if packed["aux"].is_null() { json!({}) } else { decode(&packed["aux"])? };
        if reader["id"] != request["id"] || reader["source_ms"] != request["source_ms"] {
            return Err("Motor 1 reader frame mismatch".into());
        }
        let (hub, hub_age_ms) = if packed["hub"].is_null() {
            (None, None)
        } else {
            let source = packed["hub"]["source_ms"].as_f64().ok_or("hub time missing")?;
            let now = request["source_ms"].as_f64().ok_or("reader time missing")?;
            let age = now - source;
            if packed["hub"]["epoch"] != request["epoch"] ||
                !age.is_finite() || !(0.0..=3500.0).contains(&age) {
                return Err("Motor 1 HUB stale or wrong epoch".into());
            }
            (Some(decode(&packed["hub"])?), Some(age.round() as i64))
        };
        Ok(Some(Self { reader, hub, aux, hub_age_ms }))
    }

    pub fn diagnostics(&self) -> Value {
        let hub = self.hub.as_ref();
        json!({"schema":"motor1_to_motor2_v1", "reader_received":true,
            "hub_received":hub.is_some(), "hub_age_ms":self.hub_age_ms,
            "reader_fields":self.reader.as_object().map_or(0, |v| v.len()),
            "aux_sources":self.aux.as_object().map_or(0, |v| v.len()),
            "augment_options_visible":self.aux["augment_options"]["selection_visible"] == true,
            "augment_offer_count":self.aux["augment_options"]["options"]
                .as_array().map_or(0, Vec::len),
            "augment_catalog_lookup_count":self.aux["augment_options"]["catalog"]
                ["lookup_entry_count"].as_u64(),
            "augment_patch_confirmed_from_client":self.aux["augment_options"]
                ["catalog_patch_verified_from_client"] == true,
            "hub_fields":hub.and_then(Value::as_object).map_or(0, |v| v.len()),
            "own_cells":hub.and_then(|v|v["spatial_map"]["own_cells"].as_array()).map_or(0, Vec::len),
            "enemy_cells":hub.and_then(|v|v["spatial_map"]["enemy_cells"].as_array()).map_or(0, Vec::len),
            "own_bench":hub.and_then(|v|v["spatial_map"]["own_bench"].as_array()).map_or(0, Vec::len),
            "enemy_bench":hub.and_then(|v|v["spatial_map"]["enemy_bench"].as_array()).map_or(0, Vec::len),
            "item_evidence":hub.and_then(|v|v["item_evidence"]["inventory"].as_array()).map_or(0, Vec::len)
                + hub.and_then(|v|v["item_evidence"]["equipped"].as_array()).map_or(0, Vec::len),
            "opponent_rows":hub.and_then(|v|v["opponents"]["players"].as_array()).map_or(0,
                |rows| rows.iter().filter(|row| row["status"] == "persistent_candidate"
                    && row["name"].as_str().is_some_and(|name| !name.trim().is_empty())
                    && row["last_seen_age_ms"].as_f64().is_none_or(|age| age <= 15000.0))
                    .count()),
            "opponent_raw_rows":hub.and_then(|v|v["opponents"]["players"].as_array()).map_or(0, Vec::len),
            "candidate_identity_promoted_by_bridge":false})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{write::ZlibEncoder, Compression};
    use std::io::Write;

    fn pack(value: &Value) -> Value {
        let raw = serde_json::to_vec(value).unwrap();
        let mut writer = ZlibEncoder::new(Vec::new(), Compression::fast());
        writer.write_all(&raw).unwrap();
        json!({"codec":"zlib_json_base64_v1",
            "data":STANDARD.encode(writer.finish().unwrap()),
            "raw_bytes":raw.len(), "sha256":format!("{:x}", Sha256::digest(&raw))})
    }

    #[test]
    fn full_reader_and_hub_reach_strategy_unchanged() {
        let reader = json!({"id":7,"source_ms":2000,"hud":[{"field":"gold","value":30}],
            "shop":{"slots":[{"observed_name":"Zyra"}]}});
        let hub = json!({"timestamp_ms":1800,"spatial_map":{"own_cells":[{"id":"A1"}],
            "enemy_cells":[{"id":"A1"}],"own_bench":[],"enemy_bench":[]},
            "item_evidence":{"inventory":[{"candidate_name":"Warmog",
                "identity_verified":false}],"equipped":[]},
            "opponents":{"players":[{"name":"enemy","status":"persistent_candidate",
                "last_seen_age_ms":500},{"name":"old OCR","status":"persistent_candidate",
                "last_seen_age_ms":16000},{"name":"unconfirmed","status":"observing"}]},
            "temporal_candidates":{"units":[{"candidate_id":"Zyra",
                "identity_verified":false}]}});
        let mut hub_packed = pack(&hub);
        hub_packed["source_ms"] = json!(1800);
        hub_packed["epoch"] = json!(1);
        hub_packed["age_ms"] = json!(200);
        let aux = json!({"selected_unit_panel":{"champion_name":"Zyra",
            "slot_assignment":"unresolved"},"fast_items":{"slots":[]},
            "augment_options":{"selection_visible":true,
                "catalog":{"lookup_entry_count":762},
                "catalog_patch_verified_from_client":false,
                "options":[{"slot":0},{"slot":1},{"slot":2}]}});
        let request = json!({"id":7,"source_ms":2000,"epoch":1,"motor1":{
            "schema":"motor1_to_motor2_v1","source_ms":2000,"epoch":1,
            "reader":pack(&reader),"hub":hub_packed,"aux":pack(&aux)}});
        let evidence = Motor1Evidence::from_request(&request).unwrap().unwrap();
        assert_eq!(evidence.reader, reader);
        assert_eq!(evidence.aux, aux);
        assert_eq!(evidence.diagnostics()["augment_offer_count"], 3);
        assert_eq!(evidence.diagnostics()["augment_catalog_lookup_count"], 762);
        assert_eq!(evidence.diagnostics()["augment_patch_confirmed_from_client"], false);
        assert_eq!(evidence.diagnostics()["opponent_rows"], 1);
        assert_eq!(evidence.diagnostics()["opponent_raw_rows"], 3);
        assert_eq!(evidence.hub.unwrap(), hub);
    }

    #[test]
    fn rejects_stale_hub_and_wrong_epoch() {
        let reader = json!({"id":7,"source_ms":6000});
        let mut hub_packed = pack(&json!({"x":1}));
        hub_packed["source_ms"] = json!(1000);
        hub_packed["epoch"] = json!(1);
        let base = json!({"id":7,"source_ms":6000,"epoch":1,"motor1":{
            "schema":"motor1_to_motor2_v1","source_ms":6000,"epoch":1,
            "reader":pack(&reader),"hub":hub_packed}});
        assert!(Motor1Evidence::from_request(&base).is_err());
        let mut wrong = base;
        wrong["motor1"]["epoch"] = json!(2);
        assert!(Motor1Evidence::from_request(&wrong).is_err());
    }

    #[test]
    fn accepts_fractional_frame_timestamp_from_hub() {
        let reader = json!({"id":7,"source_ms":2000});
        let hub = json!({"timestamp_ms":1800.5,"spatial_map":{"own_cells":[]}});
        let mut hub_packed = pack(&hub);
        hub_packed["source_ms"] = json!(1800.5);
        hub_packed["epoch"] = json!(1);
        let request = json!({"id":7,"source_ms":2000,"epoch":1,"motor1":{
            "schema":"motor1_to_motor2_v1","source_ms":2000,"epoch":1,
            "reader":pack(&reader),"hub":hub_packed}});
        let evidence = Motor1Evidence::from_request(&request).unwrap().unwrap();
        assert_eq!(evidence.hub, Some(hub));
        assert_eq!(evidence.hub_age_ms, Some(200));
    }
}
