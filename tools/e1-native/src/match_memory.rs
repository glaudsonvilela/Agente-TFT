//! Per-capture-session observation memory. Screen hypotheses remain hypotheses.
//! The database is local, bounded, and never uses a model prediction as a label.
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::path::PathBuf;

const MAX_ROWS: i64 = 10_000;

pub struct MatchMemory {
    root: Option<PathBuf>,
    active: Option<(String, Connection)>,
}

#[derive(Default)]
pub struct History {
    pub hp_loss_90s: i64,
    pub hp_loss_match: i64,
    pub gold_change_90s: Option<i64>,
    pub observed_rows_90s: usize,
    pub observed_rows_match: i64,
    pub stages_seen: i64,
    pub last_stage: Option<String>,
}

impl MatchMemory {
    pub fn new(root: Option<PathBuf>) -> Self { Self { root, active: None } }

    fn connection(&mut self, match_id: &str) -> Result<&Connection, String> {
        if match_id.len() != 32 || !match_id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("invalid match memory identity".into());
        }
        if self.active.as_ref().map_or(true, |(id, _)| id != match_id) {
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
                    ON observations(epoch, source_ms);")
                .map_err(|e| format!("match memory schema: {e}"))?;
            self.active = Some((match_id.to_owned(), conn));
        }
        Ok(&self.active.as_ref().unwrap().1)
    }

    pub fn history(&mut self, match_id: &str, epoch: i64, source_ms: i64) -> Result<History, String> {
        let conn = self.connection(match_id)?;
        let mut query = conn.prepare("SELECT source_ms, stage, gold, hp FROM observations
            WHERE epoch=?1 AND source_ms BETWEEN ?2 AND ?3
            ORDER BY source_ms DESC LIMIT 96").map_err(|e| e.to_string())?;
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
        conn.query_row("SELECT COUNT(*) FROM observations WHERE epoch=?1
            AND source_ms BETWEEN ?2 AND ?3 AND selected_key=?4",
            params![epoch, source_ms.saturating_sub(60_000), source_ms, key], |row| row.get(0))
            .map_err(|e| e.to_string())
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
        if frame_id % 256 == 0 {
            conn.execute("DELETE FROM observations WHERE frame_id NOT IN
                (SELECT frame_id FROM observations ORDER BY frame_id DESC LIMIT ?1)",
                params![MAX_ROWS]).map_err(|e| e.to_string())?;
        }
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
            "observation":{"stage":"2-1","gold":30,"hp":100,"items":[{"candidate_id":"x","identity_verified":false}]}});
        let second = json!({"id":2,"source_ms":2000,"epoch":0,"match_id":id,
            "observation":{"stage":"2-2","gold":24,"hp":92}});
        let mut store = MatchMemory::new(Some(root.clone()));
        store.record(&first, Some(("buy:x", "buy_pair", 0.5))).unwrap();
        store.record(&second, None).unwrap();
        drop(store);
        let mut reopened = MatchMemory::new(Some(root.clone()));
        let state = reopened.history(id, 0, 2500).unwrap();
        assert_eq!(state.hp_loss_90s, 8);
        assert_eq!(state.hp_loss_match, 8);
        assert_eq!(state.stages_seen, 2);
        assert_eq!(state.gold_change_90s, Some(-6));
        assert_eq!(reopened.recent_repeats(id, 0, 2500, "buy:x").unwrap(), 1);
        assert_eq!(reopened.history("fedcba9876543210fedcba9876543210", 0, 2500).unwrap().observed_rows_90s, 0);
        drop(reopened);
        std::fs::remove_dir_all(root).unwrap();
    }
}
