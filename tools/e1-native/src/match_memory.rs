//! Per-capture-session observation memory. Screen hypotheses remain hypotheses.
//! The disk ledger keeps every observed frame and assessed option in a match.
//! Only the fast in-process window is bounded; predictions are never labels.
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::path::PathBuf;

pub struct MatchMemory {
    root: Option<PathBuf>,
    active: Option<(String, Connection)>,
    recent: VecDeque<(i64, i64, Value)>,
}

#[derive(Default)]
pub struct History {
    pub hp_loss_90s: i64,
    pub hp_loss_match: i64,
    pub gold_change_90s: Option<i64>,
    pub latest_hp: Option<i64>,
    pub oldest_gold_90s: Option<i64>,
    pub observed_rows_90s: usize,
    pub observed_rows_match: i64,
    pub stages_seen: i64,
    pub last_stage: Option<String>,
}

impl MatchMemory {
    pub fn new(root: Option<PathBuf>) -> Self { Self { root, active: None, recent: VecDeque::new() } }

    fn connection(&mut self, match_id: &str) -> Result<&Connection, String> {
        if match_id.len() != 32 || !match_id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("invalid match memory identity".into());
        }
        if self.active.as_ref().map_or(true, |(id, _)| id != match_id) {
            self.recent.clear();
            let conn = if let Some(root) = &self.root {
                std::fs::create_dir_all(root).map_err(|e| format!("match memory directory: {e}"))?;
                Connection::open(root.join(format!("{match_id}.sqlite")))
            } else { Connection::open_in_memory() }.map_err(|e| e.to_string())?;
            conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS observations (
                    frame_id INTEGER PRIMARY KEY, source_ms INTEGER NOT NULL,
                    epoch INTEGER NOT NULL, stage TEXT, gold INTEGER, hp INTEGER,
                    snapshot_json TEXT NOT NULL, selected_key TEXT, selected_kind TEXT,
                    selected_utility REAL);
                CREATE INDEX IF NOT EXISTS observations_epoch_time
                    ON observations(epoch, source_ms);
                CREATE TABLE IF NOT EXISTS emissions (
                    id INTEGER PRIMARY KEY, source_ms INTEGER NOT NULL,
                    epoch INTEGER NOT NULL, stage TEXT, decision_key TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS emissions_key_stage
                    ON emissions(epoch, decision_key, stage, source_ms);
                CREATE UNIQUE INDEX IF NOT EXISTS emissions_once
                    ON emissions(epoch, source_ms, decision_key);
                CREATE TABLE IF NOT EXISTS assessments (
                    frame_id INTEGER PRIMARY KEY, options_json TEXT NOT NULL,
                    ranked_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidate_memory (
                    frame_id INTEGER NOT NULL, source_ms INTEGER NOT NULL,
                    epoch INTEGER NOT NULL, decision_key TEXT NOT NULL,
                    action_type TEXT,
                    PRIMARY KEY(frame_id, decision_key));
                CREATE INDEX IF NOT EXISTS candidate_memory_recent
                    ON candidate_memory(epoch, decision_key, source_ms);
                CREATE TABLE IF NOT EXISTS match_events (
                    frame_id INTEGER PRIMARY KEY, source_ms INTEGER NOT NULL,
                    epoch INTEGER NOT NULL, event_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS match_events_epoch_time
                    ON match_events(epoch, source_ms);
                CREATE TABLE IF NOT EXISTS match_pool (
                    epoch INTEGER NOT NULL, field TEXT NOT NULL,
                    source_ms INTEGER NOT NULL, value_json TEXT NOT NULL,
                    PRIMARY KEY(epoch, field));")
                .map_err(|e| format!("match memory schema: {e}"))?;
            let mut recent = VecDeque::new();
            {
                let mut statement = conn.prepare("SELECT source_ms, epoch, snapshot_json FROM observations
                    ORDER BY frame_id DESC LIMIT 24").map_err(|e| e.to_string())?;
                let rows = statement.query_map([], |row| Ok((row.get::<_, i64>(0)?,
                    row.get::<_, i64>(1)?, row.get::<_, String>(2)?)))
                    .map_err(|e| e.to_string())?;
                for row in rows {
                    let (ms, epoch, raw) = row.map_err(|e| e.to_string())?;
                    if let Ok(snapshot) = serde_json::from_str(&raw) {
                        recent.push_front((ms, epoch, snapshot));
                    }
                }
            }
            self.recent = recent;
            self.active = Some((match_id.to_owned(), conn));
        }
        Ok(&self.active.as_ref().unwrap().1)
    }

    pub fn recent_snapshots(&mut self, match_id: &str) -> Result<&VecDeque<(i64, i64, Value)>, String> {
        self.connection(match_id)?;
        Ok(&self.recent)
    }

    /// Last observed facts for this replay segment. Empty reads never erase
    /// earlier evidence; callers must still check the age before acting on it.
    pub fn pool(&mut self, match_id: &str, epoch: i64, source_ms: i64) -> Result<Value, String> {
        let conn = self.connection(match_id)?;
        let mut statement = conn.prepare("SELECT field, source_ms, value_json FROM match_pool
            WHERE epoch=?1 AND source_ms<=?2").map_err(|e| e.to_string())?;
        let rows = statement.query_map(params![epoch, source_ms], |row| Ok((
            row.get::<_, String>(0)?, row.get::<_, i64>(1)?, row.get::<_, String>(2)?)))
            .map_err(|e| e.to_string())?;
        let mut facts = serde_json::Map::new();
        let mut traits = serde_json::Map::new();
        for row in rows {
            let (field, at, raw) = row.map_err(|e| e.to_string())?;
            let value: Value = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
            let fact = json!({"value":value,"source_ms":at,"age_ms":source_ms-at});
            if let Some(name) = field.strip_prefix("trait:") {
                traits.insert(name.to_owned(), fact);
            } else if let Some(name) = field.strip_prefix("unit:") {
                facts.entry("units").or_insert_with(|| json!({}))[name] = fact;
            } else if let Some(name) = field.strip_prefix("item:") {
                facts.entry("items").or_insert_with(|| json!({}))[name] = fact;
            } else { facts.insert(field, fact); }
        }
        facts.insert("traits".into(), Value::Object(traits));
        Ok(Value::Object(facts))
    }

    pub fn history(&mut self, match_id: &str, epoch: i64, source_ms: i64) -> Result<History, String> {
        let conn = self.connection(match_id)?;
        let mut query = conn.prepare("SELECT source_ms, stage, gold, hp FROM observations
            WHERE epoch=?1 AND source_ms BETWEEN ?2 AND ?3
            ORDER BY source_ms DESC LIMIT 256").map_err(|e| e.to_string())?;
        let rows = query.query_map(params![epoch, source_ms.saturating_sub(90_000), source_ms],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, Option<String>>(1)?,
                row.get::<_, Option<i64>>(2)?, row.get::<_, Option<i64>>(3)?)))
            .map_err(|e| e.to_string())?;
        let mut gold_newest = None;
        let mut gold_oldest = None;
        let mut hp_newest = None;
        let mut hp_oldest = None;
        let mut result = History::default();
        for row in rows {
            let (_, stage, gold, hp) = row.map_err(|e| e.to_string())?;
            result.observed_rows_90s += 1;
            if result.last_stage.is_none() { result.last_stage = stage; }
            if let Some(value) = gold {
                if gold_newest.is_none() { gold_newest = Some(value); }
                gold_oldest = Some(value);
            }
            if let Some(value) = hp {
                if hp_newest.is_none() { hp_newest = Some(value); }
                hp_oldest = Some(value);
            }
        }
        result.hp_loss_90s = match (hp_oldest, hp_newest) {
            (Some(old), Some(new)) => (old - new).max(0), _ => 0,
        };
        result.gold_change_90s = gold_newest.zip(gold_oldest).map(|(new, old)| new - old);
        result.latest_hp = hp_newest;
        result.oldest_gold_90s = gold_oldest;
        let (rows, stages): (i64, i64) = conn.query_row(
            "SELECT COUNT(*), COUNT(DISTINCT stage) FROM observations WHERE epoch=?1",
            params![epoch], |row| Ok((row.get(0)?, row.get(1)?)))
            .map_err(|e| e.to_string())?;
        result.observed_rows_match = rows;
        result.stages_seen = stages;
        let first_hp: Option<i64> = conn.query_row(
            "SELECT hp FROM observations WHERE epoch=?1 AND hp IS NOT NULL
             ORDER BY source_ms ASC LIMIT 1", params![epoch], |row| row.get(0))
            .optional().map_err(|e| e.to_string())?;
        let latest_hp: Option<i64> = conn.query_row(
            "SELECT hp FROM observations WHERE epoch=?1 AND hp IS NOT NULL
             ORDER BY source_ms DESC LIMIT 1", params![epoch], |row| row.get(0))
            .optional().map_err(|e| e.to_string())?;
        result.hp_loss_match = match (first_hp, latest_hp) {
            (Some(first), Some(current)) => (first - current).max(0), _ => 0,
        };
        Ok(result)
    }

    pub fn recent_repeats(&mut self, match_id: &str, epoch: i64, source_ms: i64,
                          key: &str) -> Result<i64, String> {
        let conn = self.connection(match_id)?;
        conn.query_row("SELECT COUNT(*) FROM emissions WHERE epoch=?1
            AND source_ms BETWEEN ?2 AND ?3 AND decision_key=?4",
            params![epoch, source_ms.saturating_sub(60_000), source_ms, key], |row| row.get(0))
            .map_err(|e| e.to_string())
    }

    pub fn already_emitted(&mut self, match_id: &str, epoch: i64, source_ms: i64,
                           stage: Option<&str>, key: &str,
                           same_goal_across_stages: bool) -> Result<bool, String> {
        let conn = self.connection(match_id)?;
        let previous: Option<i64> = if same_goal_across_stages {
            conn.query_row("SELECT source_ms FROM emissions WHERE epoch=?1
                AND decision_key=?2 AND source_ms<=?3 ORDER BY source_ms DESC LIMIT 1",
                params![epoch,key,source_ms], |row| row.get(0))
                .optional().map_err(|e| e.to_string())?
        } else {
            conn.query_row("SELECT source_ms FROM emissions WHERE epoch=?1 AND decision_key=?2
                AND stage IS ?3 AND source_ms<=?4 ORDER BY source_ms DESC LIMIT 1",
                params![epoch, key, stage, source_ms], |row| row.get(0))
                .optional().map_err(|e| e.to_string())?
        };
        Ok(previous.is_some_and(|at| same_goal_across_stages || stage.is_some() ||
            source_ms - at < 30_000))
    }

    pub fn mark_emitted(&mut self, match_id: &str, epoch: i64, source_ms: i64,
                        stage: Option<&str>, key: &str) -> Result<(), String> {
        let conn = self.connection(match_id)?;
        conn.execute("INSERT OR IGNORE INTO emissions(source_ms,epoch,stage,decision_key)
            VALUES (?1,?2,?3,?4)", params![source_ms, epoch, stage, key])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn was_selected(&mut self, match_id: &str, frame_id: i64, epoch: i64,
                        source_ms: i64, key: &str) -> Result<bool, String> {
        let conn = self.connection(match_id)?;
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM observations
            WHERE frame_id=?1 AND epoch=?2 AND source_ms=?3 AND selected_key=?4",
            params![frame_id, epoch, source_ms, key], |row| row.get(0))
            .map_err(|e| e.to_string())?;
        Ok(count == 1)
    }

    pub fn record_assessment(&mut self, match_id: &str, frame_id: i64,
                             options: &[Value], ranked: &[Value]) -> Result<(), String> {
        if options.len() > 32 { return Err("assessment option budget exceeded".into()); }
        let conn = self.connection(match_id)?;
        let options_json = serde_json::to_string(options).map_err(|e| e.to_string())?;
        let ranked_json = serde_json::to_string(ranked).map_err(|e| e.to_string())?;
        if options_json.len() > 65_536 || ranked_json.len() > 65_536 {
            return Err("assessment exceeds local storage budget".into());
        }
        conn.execute("INSERT OR REPLACE INTO assessments(frame_id,options_json,ranked_json)
            VALUES (?1,?2,?3)", params![frame_id, options_json, ranked_json])
            .map_err(|e| e.to_string())?;
        let source: (i64, i64) = conn.query_row(
            "SELECT source_ms,epoch FROM observations WHERE frame_id=?1",
            params![frame_id], |row| Ok((row.get(0)?, row.get(1)?)))
            .map_err(|e| e.to_string())?;
        for option in options {
            let key = option["decision_key"].as_str().map(str::to_owned)
                .unwrap_or_else(|| option["action"].to_string());
            if key.len() > 256 || key.is_empty() { continue; }
            conn.execute("INSERT OR IGNORE INTO candidate_memory
                (frame_id,source_ms,epoch,decision_key,action_type) VALUES (?1,?2,?3,?4,?5)",
                params![frame_id, source.0, source.1, key,
                    option["action"]["type"].as_str()]).map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    pub fn recent_candidate_sightings(&mut self, match_id: &str, epoch: i64,
                                      source_ms: i64, key: &str) -> Result<i64, String> {
        let conn = self.connection(match_id)?;
        conn.query_row("SELECT COUNT(*) FROM candidate_memory WHERE epoch=?1
            AND decision_key=?2 AND source_ms BETWEEN ?3 AND ?4",
            params![epoch, key, source_ms.saturating_sub(90_000), source_ms],
            |row| row.get(0)).map_err(|e| e.to_string())
    }

    pub fn record_event(&mut self, match_id: &str, frame_id: i64, epoch: i64,
                        source_ms: i64, event: &Value) -> Result<(), String> {
        if event["event"] != "combat_loss_observed" ||
           !event["damage"].as_i64().is_some_and(|n| (1..=100).contains(&n)) ||
           event["cause_status"] != "unresolved" {
            return Err("unsupported or unverified match event".into());
        }
        let raw = serde_json::to_string(event).map_err(|e| e.to_string())?;
        if raw.len() > 4096 { return Err("match event exceeds budget".into()); }
        let conn = self.connection(match_id)?;
        conn.execute("INSERT OR REPLACE INTO match_events(frame_id,source_ms,epoch,event_json)
            VALUES (?1,?2,?3,?4)", params![frame_id, source_ms, epoch, raw])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn latest_event(&mut self, match_id: &str, epoch: i64,
                        source_ms: i64) -> Result<Option<Value>, String> {
        let conn = self.connection(match_id)?;
        let raw: Option<String> = conn.query_row("SELECT event_json FROM match_events
            WHERE epoch=?1 AND source_ms BETWEEN ?2 AND ?3
            ORDER BY source_ms DESC LIMIT 1",
            params![epoch, source_ms.saturating_sub(90_000), source_ms], |row| row.get(0))
            .optional().map_err(|e| e.to_string())?;
        raw.map(|value| serde_json::from_str(&value).map_err(|e| e.to_string())).transpose()
    }

    pub fn record(&mut self, request: &Value, selected: Option<(&str, &str, f32)>) -> Result<(), String> {
        let match_id = request["match_id"].as_str().ok_or("match_id missing")?;
        let conn = self.connection(match_id)?;
        let frame_id = request["id"].as_i64().ok_or("frame id missing")?;
        let source_ms = request["source_ms"].as_i64().ok_or("source time missing")?;
        let epoch = request["epoch"].as_i64().ok_or("epoch missing")?;
        let observation = &request["observation"];
        let serialized = serde_json::to_string(observation).map_err(|e| e.to_string())?;
        if serialized.len() > 32_768 { return Err("observation exceeds local memory budget".into()); }
        let (key, kind, score) = selected.map_or((None, None, None),
            |(key, kind, score)| (Some(key), Some(kind), Some(score)));
        conn.execute("INSERT OR REPLACE INTO observations
            (frame_id,source_ms,epoch,stage,gold,hp,snapshot_json,selected_key,selected_kind,selected_utility)
            VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
            params![frame_id, source_ms, epoch, observation["stage"].as_str(),
                observation["gold"].as_i64(), observation["hp"].as_i64(), serialized,
                key, kind, score]).map_err(|e| e.to_string())?;
        for field in ["stage", "gold", "hp", "level", "xp", "shop", "board",
            "inventory", "equipped", "opponents"] {
            let value = &observation[field];
            let present = match field {
                "shop" => observation["shop_fresh"] == true &&
                    value.as_array().is_some_and(|rows| !rows.is_empty()),
                "board" | "inventory" | "equipped" =>
                    value.as_array().is_some_and(|rows| !rows.is_empty()),
                "opponents" => value["players"].as_array()
                    .is_some_and(|rows| !rows.is_empty()),
                _ => !value.is_null(),
            };
            if present {
                let raw = serde_json::to_string(value).map_err(|e| e.to_string())?;
                conn.execute("INSERT INTO match_pool(epoch,field,source_ms,value_json)
                    VALUES (?1,?2,?3,?4) ON CONFLICT(epoch,field) DO UPDATE SET
                    source_ms=excluded.source_ms,value_json=excluded.value_json
                    WHERE excluded.source_ms>=match_pool.source_ms",
                    params![epoch, field, source_ms, raw]).map_err(|e| e.to_string())?;
            }
        }
        if let Some(traits) = observation["trait_counts"].as_object() {
            for (name, count) in traits {
                if !count.as_i64().is_some_and(|n| (0..=10).contains(&n)) ||
                    name.is_empty() || name.len() > 100 { continue; }
                let field = format!("trait:{name}");
                conn.execute("INSERT INTO match_pool(epoch,field,source_ms,value_json)
                    VALUES (?1,?2,?3,?4) ON CONFLICT(epoch,field) DO UPDATE SET
                    source_ms=excluded.source_ms,value_json=excluded.value_json
                    WHERE excluded.source_ms>=match_pool.source_ms",
                    params![epoch, field, source_ms, count.to_string()])
                    .map_err(|e| e.to_string())?;
            }
        }
        for (group, prefix) in [("board", "unit"), ("inventory", "item"),
            ("equipped", "item")] {
            let Some(rows) = observation[group].as_array() else { continue };
            for row in rows {
                let identity = if group == "board" { &row["candidate_id"] }
                    else { &row["current_candidate_id"] };
                let Some(id) = identity.as_str() else { continue };
                if row["status"] != "persistent_candidate" ||
                    !row["support_frames"].as_i64().is_some_and(|n| n >= 2) { continue; }
                let Some(position) = row["position"].as_array() else { continue };
                if position.len() != 3 { continue; }
                let Some(area) = position[0].as_str() else { continue };
                if !matches!(area, "board" | "bench" | "inventory") { continue; }
                let coordinates = format!("{}:{}:{}", area, position[1], position[2]);
                if coordinates.len() > 60 || id.len() > 100 { continue; }
                let slot = row["slot"].as_i64().unwrap_or(0);
                let field = format!("{prefix}:{coordinates}:{slot}");
                let raw = serde_json::to_string(row).map_err(|e| e.to_string())?;
                conn.execute("INSERT INTO match_pool(epoch,field,source_ms,value_json)
                    VALUES (?1,?2,?3,?4) ON CONFLICT(epoch,field) DO UPDATE SET
                    source_ms=excluded.source_ms,value_json=excluded.value_json
                    WHERE excluded.source_ms>=match_pool.source_ms",
                    params![epoch, field, source_ms, raw]).map_err(|e| e.to_string())?;
            }
        }
        self.recent.push_back((source_ms, epoch, observation.clone()));
        while self.recent.len() > 24 { self.recent.pop_front(); }
        Ok(())
    }

    pub fn location(&self) -> &'static str {
        if self.root.is_some() { "local_sqlite" } else { "memory_only" }
    }
}

pub fn from_environment() -> MatchMemory {
    let root = std::env::var_os("AGENTE_TFT_MATCH_CACHE_ROOT").map(PathBuf::from);
    MatchMemory::new(root)
}

pub fn summary_json(history: &History, persistence: &str) -> Value {
    json!({"persistence":persistence,"observed_rows_90s":history.observed_rows_90s,
        "observed_rows_match":history.observed_rows_match,"stages_seen":history.stages_seen,
        "hp_loss_90s":history.hp_loss_90s,"hp_loss_match":history.hp_loss_match,
        "gold_change_90s":history.gold_change_90s,
        "last_stage":history.last_stage})
}

#[cfg(test)] mod tests {
    use super::*;
    #[test]
    fn persists_observations_and_keeps_sessions_isolated() {
        let root = std::env::temp_dir().join(format!("tft-match-memory-{}-{}",
            std::process::id(), std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        let id = "0123456789abcdef0123456789abcdef";
        let first = json!({"id":1,"source_ms":1000,"epoch":0,"match_id":id,
            "observation":{"stage":"2-1","gold":30,"hp":100,
                "trait_counts":{"Defendente":3},
                "board":[{"candidate_id":"x","identity_verified":false,
                    "status":"persistent_candidate","support_frames":3,
                    "position":["board",0,4]}]}});
        let second = json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "observation":{"stage":"2-2","gold":24,"hp":92}});
        let mut store = MatchMemory::new(Some(root.clone()));
        store.record(&first, Some(("buy:x", "buy_pair", 0.5))).unwrap();
        store.record_assessment(id, 1, &[json!({"action":{"type":"buy_pair"}})],
            &[json!({"utility":0.5})]).unwrap();
        store.record_event(id, 3, 0, 2200, &json!({"event":"combat_loss_observed",
            "damage":8,"cause_status":"unresolved"})).unwrap();
        store.mark_emitted(id, 0, 1000, Some("2-1"), "buy:x").unwrap();
        store.record(&second, None).unwrap();
        drop(store);
        let mut reopened = MatchMemory::new(Some(root.clone()));
        let state = reopened.history(id, 0, 2500).unwrap();
        assert_eq!(state.hp_loss_90s, 8);
        assert_eq!(state.hp_loss_match, 8);
        assert_eq!(state.stages_seen, 2);
        assert_eq!(state.gold_change_90s, Some(-6));
        let pool = reopened.pool(id, 0, 2500).unwrap();
        assert_eq!(pool["stage"]["value"], "2-2");
        assert_eq!(pool["gold"]["value"], 24);
        assert_eq!(pool["hp"]["value"], 92);
        assert_eq!(pool["board"]["value"][0]["identity_verified"], false);
        assert_eq!(pool["units"]["board:0:4:0"]["value"]["candidate_id"], "x");
        assert_eq!(pool["traits"]["Defendente"]["value"], 3);
        assert!(reopened.pool(id, 1, 2500).unwrap()["board"].is_null());
        assert_eq!(reopened.recent_repeats(id, 0, 2500, "buy:x").unwrap(), 1);
        assert_eq!(reopened.latest_event(id, 0, 2500).unwrap().unwrap()["damage"], 8);
        assert!(reopened.already_emitted(id, 0, 2500, Some("2-1"), "buy:x", false).unwrap());
        assert!(!reopened.already_emitted(id, 0, 2500, Some("2-2"), "buy:x", false).unwrap());
        assert!(reopened.already_emitted(id, 0, 2500, Some("2-2"), "buy:x", true).unwrap());
        let conn = reopened.connection(id).unwrap();
        assert_eq!(conn.query_row("SELECT COUNT(*) FROM assessments", [],
            |row| row.get::<_, i64>(0)).unwrap(), 1);
        assert_eq!(reopened.history("fedcba9876543210fedcba9876543210", 0, 2500).unwrap().observed_rows_90s, 0);
        drop(reopened);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn fast_window_is_bounded_but_every_observation_and_unspoken_option_remains_on_disk() {
        let root = std::env::temp_dir().join(format!("tft-full-ledger-{}-{}",
            std::process::id(), std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        let id = "0123456789abcdef0123456789abcdef";
        let mut store = MatchMemory::new(Some(root.clone()));
        for frame in 1..=40 {
            store.record(&json!({"id":frame,"source_ms":frame*1000,"epoch":0,
                "match_id":id,"observation":{"stage":"2-1","gold":frame}}), None).unwrap();
            store.record_assessment(id, frame, &[json!({"decision_key":format!("unspoken-{frame}")})],
                &[]).unwrap();
        }
        assert_eq!(store.recent_snapshots(id).unwrap().len(), 24);
        drop(store);
        let mut reopened = MatchMemory::new(Some(root.clone()));
        assert_eq!(reopened.recent_snapshots(id).unwrap().len(), 24);
        let conn = reopened.connection(id).unwrap();
        let counts: (i64, i64) = conn.query_row(
            "SELECT (SELECT COUNT(*) FROM observations), (SELECT COUNT(*) FROM assessments)",
            [], |row| Ok((row.get(0)?, row.get(1)?))).unwrap();
        assert_eq!(counts, (40, 40));
        let oldest: String = conn.query_row("SELECT options_json FROM assessments WHERE frame_id=1",
            [], |row| row.get(0)).unwrap();
        assert!(oldest.contains("unspoken-1"));
        drop(reopened);
        std::fs::remove_dir_all(root).unwrap();
    }
}
