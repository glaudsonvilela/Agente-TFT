//! Resident native visual inference. Conditional coaching never confirms identity.
use super::*;
use std::io::{self, BufRead, Read, Write};

const MAX_FRAME_BYTES: usize = 1920 * 1080 * 3;
const MAX_BATCH: usize = 12;

fn checked_file(root: &Path, relative: &str, expected: &str, budget: u64) -> Result<Vec<u8>> {
    let path = root.join(relative).canonicalize()?;
    if !path.starts_with(root) || fs::metadata(&path)?.len() > budget {
        return Err("native visual asset path/budget".into());
    }
    let bytes = fs::read(path)?;
    if hash(&bytes) != expected {
        return Err("native visual asset checksum".into());
    }
    Ok(bytes)
}

pub fn conditional_tip(row: &Value, catalog: &Value) -> Option<Value> {
    let id = row["candidate_id"].as_str()?;
    let unit = &catalog["champions"][id];
    // Require a purchasable seasonal champion; no advice for HUD negatives/forms.
    if !unit["purchase_blocker"].is_null()
        || !unit["cost"].as_u64().is_some_and(|v| (1..=5).contains(&v))
    {
        return None;
    }
    let name = unit["name"].as_str()?;
    let range = unit["combat"]["range"].as_f64()?;
    let instruction = if range >= 3.0 {
        "mantenha essa unidade atrás da linha de frente para aproveitar seu alcance"
    } else if range >= 1.0 && range < 3.0 {
        "aproxime essa unidade da linha de frente para que consiga atacar"
    } else {
        return None;
    };
    let text = format!("Se a unidade destacada for {name}, {instruction}.");
    Some(
        json!({"status":"conditional_action","actionable":true,"conditional":true,
        "text":text,"speech_text":text,"decision_key":format!("visual-position:{id}"),
        "speech_max_age_ms":3000,"basis":["dino_int8_candidate","seasonal_attack_range"],
        "strategy_basis":"conditional_visual_attribute_hint","unit_id":id,
        "marker_id":row["marker_id"],"box":row["box"],"identity_verified":false,
        "learned_ranker":false,"visual_model":"dinov2_int8",
        "scope":"conditional_position_principle_not_complete_board_optimization"}),
    )
}

struct Observer {
    session: Session,
    labels: Vec<String>,
    gallery: Vec<Vec<f32>>,
    catalog: Value,
    sha: String,
    reference_sha: String,
}

impl Observer {
    fn load(root: &Path) -> Result<Self> {
        let plan: Value = serde_json::from_slice(&fs::read(
            root.join("configs/catalog/active-unit-native-v1.json"),
        )?)?;
        if plan["schema_version"] != 1
            || plan["mode"] != "conditional_coaching"
            || plan["input_size"] != 140
            || plan["threshold"] != 0.8
            || plan["margin"] != 0.08
        {
            return Err("native visual profile mismatch".into());
        }
        let files = plan["files"].as_object().ok_or("native visual files")?;
        let mut loaded = HashMap::new();
        for (name, budget) in [
            ("encoder.onnx", 32 * 1024 * 1024),
            ("gallery.f32le", 4 * 1024 * 1024),
            ("gallery.json", 1024 * 1024),
        ] {
            loaded.insert(
                name,
                checked_file(
                    root,
                    &format!("models/unit-native/{name}"),
                    str_field(&plan["files"], name)?,
                    budget,
                )?,
            );
        }
        if files.len() != 3 {
            return Err("unexpected native visual asset".into());
        }
        let meta: Value = serde_json::from_slice(&loaded["gallery.json"])?;
        let labels: Vec<String> = serde_json::from_value(meta["labels"].clone())?;
        if !(2..=4096).contains(&labels.len())
            || meta["rows"] != labels.len()
            || meta["dimensions"] != 384
            || meta["dtype"] != "float32_le"
            || loaded["gallery.f32le"].len() != labels.len() * 384 * 4
        {
            return Err("native visual gallery shape".into());
        }
        let active: Value = serde_json::from_slice(&fs::read(
            root.join("configs/catalog/active-visual-reference-v1.json"),
        )?)?;
        let reference = root.join(str_field(&active, "reference")?);
        let reference_doc: Value =
            serde_json::from_slice(&fs::read(reference.join("reference.json"))?)?;
        if plan["set_key"] != active["set_key"]
            || plan["reference_sha256"] != reference_doc["reference_sha256"]
        {
            return Err("native visual catalog binding".into());
        }
        let champ_bytes = checked_file(
            root,
            &format!("{}/champions.json", str_field(&active, "reference")?),
            str_field(&reference_doc["components"]["champions"], "sha256")?,
            8 * 1024 * 1024,
        )?;
        let champ: Value = serde_json::from_slice(&champ_bytes)?;
        let ids: HashSet<_> = champ["entries"]
            .as_array()
            .ok_or("champion entries")?
            .iter()
            .filter_map(|r| r["id"].as_str())
            .collect();
        if labels
            .iter()
            .any(|id| id != "__unknown__" && !ids.contains(id.as_str()))
        {
            return Err("native visual unknown catalog ID".into());
        }
        let coach_plan: Value =
            serde_json::from_slice(&fs::read(root.join("configs/coaching/active.json"))?)?;
        let catalog: Value = serde_json::from_slice(&checked_file(
            root,
            str_field(&coach_plan["catalog"], "path")?,
            str_field(&coach_plan["catalog"], "sha256")?,
            8 * 1024 * 1024,
        )?)?;
        if catalog["set_key"] != plan["set_key"] {
            return Err("coach/visual set mismatch".into());
        }
        let mut gallery = Vec::new();
        for bytes in loaded["gallery.f32le"].chunks_exact(384 * 4) {
            let mut v: Vec<f32> = bytes
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
                .collect();
            if !normalize(&mut v) {
                return Err("invalid gallery vector".into());
            }
            gallery.push(v);
        }
        let library = std::env::var("AGENTE_TFT_ORT_LIBRARY")?;
        ort::init_from(library).commit()?;
        let session = Session::builder()?
            .with_intra_threads(1)?
            .with_inter_threads(1)?
            .with_intra_op_spinning(false)?
            .with_inter_op_spinning(false)?
            .commit_from_file(root.join("models/unit-native/encoder.onnx"))?;
        Ok(Self {
            session,
            labels,
            gallery,
            catalog,
            sha: str_field(&plan["files"], "encoder.onnx")?.into(),
            reference_sha: str_field(&plan, "reference_sha256")?.into(),
        })
    }

    fn observe(&mut self, header: &Value, pixels: Vec<u8>) -> Result<Value> {
        let start = Instant::now();
        let frame = FrameEnvelope {
            frame_id: header["id"].as_u64().ok_or("frame ID")?,
            captured_at_ms: header["source_ms"].as_u64().ok_or("frame timestamp")?,
            width: 1920,
            height: 1080,
            stride_bytes: 1920 * 3,
            pixel_format: PixelFormat::Rgb8,
            source_id: "screen".into(),
            pixels,
        };
        let markers = header["markers"].as_array().ok_or("markers")?;
        if markers.len() > 128 {
            return Err("marker budget".into());
        }
        let mut seen = HashSet::new();
        let mut proposals = Vec::new();
        let mut green_count = 0;
        for marker in markers {
            if marker["color"] != "green" {
                continue;
            }
            green_count += 1;
            let key = marker["id"].as_u64().ok_or("marker ID")?;
            if !seen.insert(key) {
                return Err("duplicate marker".into());
            }
            let rect = &marker["rect"];
            let (x, y, w, h) = (
                num(rect, "x")?,
                num(rect, "y")?,
                num(rect, "width")?,
                num(rect, "height")?,
            );
            if !(1..=90).contains(&w) || !(1..=8).contains(&h) {
                continue;
            }
            let Some(left) = x.checked_add(w / 2).and_then(|c| c.checked_sub(64)) else {
                continue;
            };
            let Some(top) = y.checked_add(8) else {
                continue;
            };
            let rect = PixelRect {
                x: left,
                y: top,
                width: 128,
                height: 144,
            };
            if let Ok(crop) = UnitCrop::from_frame(&frame, rect) {
                if proposals.len() < MAX_BATCH {
                    proposals.push((key, rect, crop));
                }
            }
        }
        let mut vectors = Vec::new();
        // Match the offline INT8 batch grouping; dynamic quantization is batch-sensitive.
        for chunk in proposals.chunks(4) {
            let crops: Vec<_> = chunk.iter().map(|(_, _, c)| (c.clone(), true)).collect();
            vectors.extend(embeddings(&mut self.session, &crops, 140, false, false)?);
        }
        let gallery: Vec<_> = self
            .labels
            .iter()
            .zip(&self.gallery)
            .map(|(l, v)| (l.as_str(), v))
            .collect();
        let mut records = Vec::new();
        for ((key, rect, _), v) in proposals.iter().zip(&vectors) {
            let mut row = rank(v, &gallery);
            row["marker_id"] = json!(key);
            row["box"] = json!([rect.x, rect.y, rect.x + 128, rect.y + 144]);
            row["status"] = json!(if row["candidate_id"].is_null() {
                "unknown"
            } else {
                "identity_candidate"
            });
            row["candidate_name"] = self.catalog["champions"]
                [row["candidate_id"].as_str().unwrap_or("")]["name"]
                .clone();
            records.push(row);
        }
        let tip = records
            .iter()
            .find_map(|r| conditional_tip(r, &self.catalog));
        Ok(
            json!({"active":true,"records":records,"conditional_tip":tip,
            "model_sha256":self.sha,"processing_ms":start.elapsed().as_secs_f64()*1000.0,
            "recognizer":"rust_dinov2_int8_gallery","mode":"conditional_coaching",
            "scores_are_calibrated":false,"game_state_write_allowed":false,
            "trained_champions":self.labels.iter().filter(|s|s.as_str()!="__unknown__").collect::<HashSet<_>>().len(),
            "catalog_champions":self.catalog["champions"].as_object().map_or(0,|c|c.len()),
            "proposals_skipped":green_count-proposals.len(),"reference_sha256":self.reference_sha}),
        )
    }
}

pub fn run() -> Result<()> {
    let configs = PathBuf::from(std::env::args().nth(2).ok_or("configs")?).canonicalize()?;
    let root = configs
        .parent()
        .ok_or("configuration root")?
        .canonicalize()?;
    let mut observer = Observer::load(&root)?;
    let input = io::stdin();
    let mut reader = input.lock();
    let output = io::stdout();
    let mut writer = output.lock();
    writeln!(
        writer,
        "{}",
        json!({"ready":true,"protocol":1,"native_visual":true,
        "model_sha256":observer.sha,"mode":"conditional_coaching"})
    )?;
    writer.flush()?;
    loop {
        let mut line = String::new();
        let count = reader.by_ref().take(65537).read_line(&mut line)?;
        if count == 0 {
            break;
        }
        if count > 65536 || !line.ends_with('\n') {
            return Err("visual IPC header budget".into());
        }
        let header: Value = serde_json::from_str(&line)?;
        if header["op"] != "frame"
            || header["width"] != 1920
            || header["height"] != 1080
            || header["bytes"] != MAX_FRAME_BYTES
        {
            return Err("visual IPC frame budget".into());
        }
        let mut pixels = vec![0; MAX_FRAME_BYTES];
        reader.read_exact(&mut pixels)?;
        let response = match observer.observe(&header, pixels) {
            Ok(neural) => {
                json!({"id":header["id"],"source_ms":header["source_ms"],"neural_units":neural})
            }
            Err(e) => {
                json!({"id":header["id"],"source_ms":header["source_ms"],"error":e.to_string()})
            }
        };
        writeln!(writer, "{response}")?;
        writer.flush()?;
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ambiguous_identity_never_becomes_a_tip() {
        assert!(conditional_tip(&json!({"candidate_id":null}), &json!({})).is_none());
    }
    #[test]
    fn accepted_candidate_produces_conditional_text_and_voice_not_verified_state() {
        let catalog = json!({"champions":{"a":{"name":"Camille","cost":1,"combat":{"range":1}}}});
        let tip = conditional_tip(
            &json!({"candidate_id":"a","marker_id":4,"box":[1,2,129,146]}),
            &catalog,
        )
        .unwrap();
        assert!(tip["text"]
            .as_str()
            .unwrap()
            .starts_with("Se a unidade destacada for Camille"));
        assert_eq!(tip["speech_text"], tip["text"]);
        assert_eq!(tip["identity_verified"], false);
        assert_eq!(tip["conditional"], true);
    }
}
