//! Native offline feature experiment. No Python interpreter or OpenCV dependency.
use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use agente_tft_image_preprocess::unit_features::{cosine, normalize, UnitCrop, HEIGHT, WIDTH};
use image::RgbImage;
use ort::{session::Session, value::Tensor};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::Instant,
};
pub type Result<T> = std::result::Result<T, Box<dyn Error>>;
/// Historical datasets used four crops per dynamic INT8 encoder call.
/// New candidates can explicitly select one to avoid cross-crop batch coupling.
pub fn embedding_batch_size(value: Option<&Value>) -> Result<usize> {
    match value {
        None => Ok(4),
        Some(v) => {
            Ok(v.as_u64()
                .filter(|n| (1..=4).contains(n))
                .ok_or("embedding batch size must be an integer in 1..4")? as usize)
        }
    }
}
pub mod crop_transform;
pub mod ocr_names;
pub mod retrieval;
mod live;
pub mod training;
#[derive(Clone)]
pub struct Sample {
    pub crop: UnitCrop,
    pub label: String,
    pub split: String,
    pub image: String,
    pub key: String,
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn str_field<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("missing {key}").into())
}
fn num(v: &Value, key: &str) -> Result<u32> {
    Ok(u32::try_from(v[key].as_u64().ok_or("missing number")?)?)
}
fn bounds(v: &Value) -> Result<PixelRect> {
    let a = v.as_array().ok_or("box array")?;
    if a.len() != 4 {
        return Err("box size".into());
    }
    let a: Vec<u32> = a
        .iter()
        .map(|x| {
            x.as_u64()
                .and_then(|n| u32::try_from(n).ok())
                .ok_or("box coordinate")
        })
        .collect::<std::result::Result<_, _>>()?;
    Ok(PixelRect {
        x: a[0],
        y: a[1],
        width: a[2].checked_sub(a[0]).ok_or("box width")?,
        height: a[3].checked_sub(a[1]).ok_or("box height")?,
    })
}
fn partition_guard(groups: &mut HashMap<String, String>, value: &str, split: &str) -> Result<()> {
    if let Some(old) = groups.insert(value.to_owned(), split.to_owned()) {
        if old != split {
            return Err("source/match/session leakage".into());
        }
    }
    Ok(())
}
fn quarantine_guard(frame: &Value, key: &str, crop_box: &Value) -> Result<()> {
    if let Some(excluded) = frame.get("excluded_entities") {
        for record in excluded.as_array().ok_or("invalid excluded entities")? {
            if record["key"] == key || &record["box"] == crop_box {
                return Err("quarantined crop cannot re-enter champion training/evaluation".into());
            }
        }
    }
    Ok(())
}
pub fn load_samples(path: &Path, root: &Path, reference: &Path) -> Result<Vec<Sample>> {
    load_samples_with_scope(path, root, reference, false)
}
/// Standalone frozen evaluation; training callers still require all three splits.
pub fn load_evaluation_samples(path: &Path, root: &Path, reference: &Path) -> Result<Vec<Sample>> {
    load_samples_with_scope(path, root, reference, true)
}
fn validate_split_scope(splits: &HashSet<&str>, evaluation_only: bool) -> Result<()> {
    if evaluation_only {
        if splits.len() != 1 || !splits.contains("test") {
            return Err("evaluation requires nonempty test split only".into());
        }
    } else if ["train", "validation", "test"]
        .iter()
        .any(|s| !splits.contains(s))
    {
        return Err("three nonempty splits required".into());
    }
    Ok(())
}
fn load_samples_with_scope(
    path: &Path,
    root: &Path,
    reference: &Path,
    evaluation_only: bool,
) -> Result<Vec<Sample>> {
    let doc: Value = serde_json::from_slice(&fs::read(path)?)?;
    if doc["review_status"] == "superseded" || doc["schema_version"] != 2 {
        return Err("unsupported/superseded review".into());
    }
    let reference_doc: Value =
        serde_json::from_slice(&fs::read(reference.join("reference.json"))?)?;
    let cat_bytes = fs::read(reference.join("champions.json"))?;
    if hash(&cat_bytes) != str_field(&reference_doc["components"]["champions"], "sha256")? {
        return Err("catalog hash".into());
    }
    let cat: Value = serde_json::from_slice(&cat_bytes)?;
    let ids: HashSet<_> = cat["entries"]
        .as_array()
        .ok_or("catalog entries")?
        .iter()
        .map(|c| str_field(c, "id"))
        .collect::<Result<_>>()?;
    let root = root.canonicalize()?;
    let mut groups = HashMap::new();
    let mut seen = HashSet::new();
    let mut pixels = HashSet::new();
    let mut result = Vec::new();
    for frame in doc["frames"].as_array().ok_or("frames")? {
        let split = str_field(frame, "identity_split")?;
        if !["train", "validation", "test"].contains(&split) {
            return Err("split".into());
        }
        for key in ["match_group", "session_id", "source_video_id"] {
            if key == "source_video_id" && frame[key].is_null() {
                continue;
            }
            partition_guard(
                &mut groups,
                &format!("{key}:{}", str_field(frame, key)?),
                split,
            )?;
        }
        if frame["review"]["model_predictions_used_as_labels"] != false
            || frame["patch_binding"]["set_key"] != cat["set_key"]
        {
            return Err("review/set provenance".into());
        }
        let relative = str_field(frame, "image")?;
        let filename = root.join(relative).canonicalize()?;
        if !filename.starts_with(&root) {
            return Err("image outside dataset".into());
        }
        let bytes = fs::read(&filename)?;
        if hash(&bytes) != str_field(frame, "sha256")? || !seen.insert(hash(&bytes)) {
            return Err("source checksum/duplicate".into());
        }
        let rgb = image::load_from_memory(&bytes)?.to_rgb8();
        if hash(rgb.as_raw()) != str_field(frame, "pixel_sha256")?
            || !pixels.insert(hash(rgb.as_raw()))
        {
            return Err("pixel checksum/duplicate".into());
        }
        if frame["image_size"] != json!([rgb.width(), rgb.height()]) {
            return Err("image dimensions".into());
        }
        let f = FrameEnvelope {
            frame_id: 0,
            captured_at_ms: 0,
            width: rgb.width(),
            height: rgb.height(),
            stride_bytes: rgb.width() * 3,
            pixel_format: PixelFormat::Rgb8,
            source_id: relative.into(),
            pixels: rgb.into_raw(),
        };
        let units = frame["layout"]["units"].as_array().ok_or("unit layout")?;
        for entity in frame["entities"].as_array().ok_or("entities")? {
            let key = str_field(entity, "key")?;
            let u = units
                .iter()
                .find(|u| u["key"] == key)
                .ok_or("entity without layout")?;
            quarantine_guard(frame, key, &u["box"])?;
            let rect = bounds(&u["box"])?;
            let b = &u["bar_rect"];
            let (x, y, w, h) = (
                num(b, "x")?,
                num(b, "y")?,
                num(b, "width")?,
                num(b, "height")?,
            );
            let cx = x.checked_add(w / 2).ok_or("bar overflow")?;
            if !(1..=90).contains(&w)
                || !(1..=8).contains(&h)
                || rect.width != 128
                || rect.height != 144
                || Some(rect.x) != cx.checked_sub(64)
                || Some(rect.y) != y.checked_add(8)
            {
                return Err("crop contract mismatch".into());
            }
            let label = if entity["identity"]["state"] == "known" {
                str_field(&entity["identity"], "id")?
            } else {
                "__unknown__"
            };
            if label != "__unknown__" && !ids.contains(label) {
                return Err("unit absent from catalog".into());
            }
            let crop = UnitCrop::from_frame(&f, rect)?;
            if let Some(expected) = entity.get("crop_pixel_sha256") {
                if expected.as_str() != Some(hash(&crop.rgb).as_str()) {
                    return Err("reviewed identity/crop pixel binding mismatch".into());
                }
            }
            result.push(Sample {
                crop,
                label: label.into(),
                split: split.into(),
                image: relative.into(),
                key: key.into(),
            });
        }
        if let Some(negatives) = frame["identity_negatives"].as_array() {
            for (i, n) in negatives.iter().enumerate() {
                if n["basis"] != "assistant_reviewed_nonunit_hud"
                    && n["basis"] != "assistant_reviewed_nonunit_crop"
                {
                    return Err("unreviewed negative".into());
                }
                result.push(Sample {
                    crop: UnitCrop::from_frame(&f, bounds(&n["box"])?)?,
                    label: "__unknown__".into(),
                    split: split.into(),
                    image: relative.into(),
                    key: format!("negative-{i}"),
                });
            }
        }
    }
    let splits: HashSet<_> = result.iter().map(|s| s.split.as_str()).collect();
    validate_split_scope(&splits, evaluation_only)?;
    Ok(result)
}
fn prepare(crop: &UnitCrop, mode: &str) -> Result<(UnitCrop, bool)> {
    let mut c = crop.clone();
    let mut valid = true;
    if mode.starts_with("blur") {
        valid = !c
            .blur_background(mode.ends_with("outline"), mode.contains("background_mono"))?
            .empty;
    } else if mode.ends_with("outline") {
        valid = !c.outline_overlay(mode.starts_with("mask"))?.empty;
    } else if mode.starts_with("mask") {
        valid = !c.foreground()?.empty;
    }
    if mode.ends_with("gray") {
        c.grayscale()?;
    }
    Ok((c, valid))
}
pub fn embeddings(
    session: &mut Session,
    crops: &[(UnitCrop, bool)],
    size: usize,
    gradient: bool,
    contour_fusion: bool,
) -> Result<Vec<Vec<f32>>> {
    if gradient {
        return crops
            .iter()
            .map(|(c, valid)| {
                let mut v = c.gradient_vector()?;
                if !valid {
                    v.fill(0.0);
                }
                Ok(v)
            })
            .collect();
    }
    let mut data = Vec::with_capacity(crops.len() * 3 * size * size);
    for (crop, _) in crops {
        data.extend(crop.tensor(size)?);
    }
    let tensor = Tensor::from_array(([crops.len(), 3, size, size], data))?;
    let out = session.run(ort::inputs![tensor])?;
    let (shape, values) = out["embeddings"].try_extract_tensor::<f32>()?;
    if shape.len() != 2 || shape[0] as usize != crops.len() || !(1..=4096).contains(&shape[1]) {
        return Err("encoder output shape".into());
    }
    let mut result = Vec::new();
    for ((crop, valid), v) in crops.iter().zip(values.chunks_exact(shape[1] as usize)) {
        let mut v = v.to_vec();
        if !*valid || !normalize(&mut v) {
            v.fill(0.0);
        }
        if contour_fusion {
            v = fuse_contour(&v, &crop.contour_view()?.gradient_vector()?);
        }
        result.push(v);
    }
    Ok(result)
}

// Fixed before evaluation: 80% color similarity, 20% contour similarity.
// sqrt weights on unit vectors make cosine of their concatenation that mixture.
// Reject missing branches rather than silently changing the comparison weights.
fn fuse_contour(color: &[f32], contour: &[f32]) -> Vec<f32> {
    let mut color = color.to_vec();
    let mut contour = contour.to_vec();
    if !normalize(&mut color) || !normalize(&mut contour) {
        return vec![0.0; color.len() + contour.len()];
    }
    color.iter_mut().for_each(|x| *x *= 0.8f32.sqrt());
    color.extend(contour.iter().map(|x| x * 0.2f32.sqrt()));
    color
}
pub fn rank(v: &[f32], gallery: &[(&str, &Vec<f32>)]) -> Value {
    let mut classes: BTreeMap<&str, f32> = BTreeMap::new();
    for (label, g) in gallery {
        if let Ok(score) = cosine(v, g) {
            let e = classes.entry(label).or_insert(-1.0);
            *e = e.max(score);
        }
    }
    let mut scores: Vec<_> = classes.into_iter().collect();
    scores.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(b.0)));
    if scores.len() < 2 {
        return json!({"candidate_id":null,"candidates":[],"identity_verified":false,"status":"insufficient_features"});
    }
    let accepted =
        scores[0].0 != "__unknown__" && scores[0].1 >= 0.8 && scores[0].1 - scores[1].1 >= 0.08;
    json!({"candidate_id":if accepted {Some(scores[0].0)}else{None},"identity_verified":false,
        "candidates":scores.iter().take(3).map(|(id,sim)|json!({"unit_id":id,"similarity":sim})).collect::<Vec<_>>()})
}
fn stats(rows: &[Value]) -> Value {
    let named: Vec<_> = rows
        .iter()
        .filter(|r| r["label"] != "__unknown__")
        .collect();
    json!({"named":named.len(),"top1_correct":named.iter().filter(|r|r["candidates"][0]["unit_id"]==r["label"]).count(),
        "accepted":named.iter().filter(|r|!r["candidate_id"].is_null()).count(),
        "wrong_accepted":named.iter().filter(|r|!r["candidate_id"].is_null() && r["candidate_id"]!=r["label"]).count(),
        "accepted_on_unreviewed":rows.iter().filter(|r|r["label"]=="__unknown__" && !r["candidate_id"].is_null()).count()})
}
fn run() -> Result<()> {
    let a: Vec<_> = std::env::args().skip(1).collect();
    if a.len() % 2 != 0 {
        return Err("use --annotations PATH --images DIR --reference DIR --encoder PATH --onnxruntime LIB --size N --output NEWDIR".into());
    }
    let args: HashMap<_, _> = a
        .chunks_exact(2)
        .map(|x| (x[0].as_str(), x[1].as_str()))
        .collect();
    let arg = |key| {
        args.get(key)
            .copied()
            .ok_or_else(|| format!("missing {key}"))
    };
    let out = PathBuf::from(arg("--output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }
    let side: usize = arg("--size")?.parse()?;
    if !(64..=224).contains(&side) {
        return Err("input budget".into());
    }
    let samples = load_samples(
        Path::new(arg("--annotations")?),
        Path::new(arg("--images")?),
        Path::new(arg("--reference")?),
    )?;
    ort::init_from(arg("--onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(arg("--encoder")?)?;
    fs::create_dir_all(&out)?;
    let mut report = BTreeMap::new();
    let mut predictions = BTreeMap::new();
    for (mode, gradient) in [
        ("rgb", false),
        ("gray", false),
        ("mask_rgb", false),
        ("mask_gray", false),
        ("gray", true),
        ("mask_gray", true),
        ("rgb_outline", false),
        ("mask_rgb_outline", false),
        ("rgb_contour_fused", false),
        ("blur_rgb", false),
        ("blur_rgb_outline", false),
        ("blur_background_mono", false),
        ("blur_background_mono_outline", false),
        ("blur_gray", false),
    ] {
        let contour_fusion = mode.ends_with("fused");
        let name = format!("{}-{mode}", if gradient { "gradient" } else { "encoder" });
        let prepared = samples
            .iter()
            .map(|s| prepare(&s.crop, mode))
            .collect::<Result<Vec<_>>>()?;
        let mut features = Vec::new();
        for batch in prepared.chunks(4) {
            features.extend(embeddings(
                &mut session,
                batch,
                side,
                gradient,
                contour_fusion,
            )?);
        }
        let gallery: Vec<_> = samples
            .iter()
            .zip(&features)
            .filter(|(s, _)| s.split == "train")
            .map(|(s, v)| (s.label.as_str(), v))
            .collect();
        let mut variant_preds = BTreeMap::new();
        let mut variant = BTreeMap::new();
        for split in ["validation", "test"] {
            let mut rows = Vec::new();
            for (s, v) in samples
                .iter()
                .zip(&features)
                .filter(|(s, _)| s.split == split)
            {
                let mut row = rank(v, &gallery);
                row["label"] = json!(s.label);
                row["image"] = json!(s.image);
                row["key"] = json!(s.key);
                rows.push(row);
            }
            let vod: Vec<_> = rows
                .iter()
                .filter(|r| r["image"].as_str().unwrap_or("").contains("subzero"))
                .cloned()
                .collect();
            variant.insert(
                split.to_owned(),
                json!({"all":stats(&rows),"separate_vod":stats(&vod)}),
            );
            variant_preds.insert(split, rows);
        }
        let batch: Vec<_> = samples
            .iter()
            .filter(|s| s.split == "test")
            .take(12)
            .collect();
        let mut timings = Vec::new();
        for i in 0..11 {
            let start = Instant::now();
            let p = batch
                .iter()
                .map(|s| prepare(&s.crop, mode))
                .collect::<Result<Vec<_>>>()?;
            let t1 = start.elapsed().as_secs_f64() * 1000.0;
            let v = embeddings(&mut session, &p, side, gradient, contour_fusion)?;
            let t2 = start.elapsed().as_secs_f64() * 1000.0;
            for row in &v {
                std::hint::black_box(rank(row, &gallery));
            }
            let total = start.elapsed().as_secs_f64() * 1000.0;
            if i > 0 {
                timings.push([t1, t2 - t1, total - t2, total]);
            }
        }
        let mut measures = BTreeMap::new();
        for (c, label) in ["preparation", "vector_extraction", "comparison", "total"]
            .iter()
            .enumerate()
        {
            let mut values: Vec<_> = timings.iter().map(|t| t[c]).collect();
            values.sort_by(f64::total_cmp);
            measures.insert(
                *label,
                json!({"median":(values[4]+values[5])/2.0,"p95":values[8]*0.45+values[9]*0.55}),
            );
        }
        variant.insert("timing_ms".into(), json!(measures));
        variant.insert("vector_dimensions".into(), json!(features[0].len()));
        if mode.starts_with("blur") {
            variant.insert(
                "filter".into(),
                json!({
                    "background_blur_radius":5,"exclude_foreground_from_blur":true,
                    "grayscale_scope":if mode.contains("background_mono") {"estimated_background"}
                        else if mode.ends_with("gray") {"whole_crop"} else {"none"},
                    "outline":mode.ends_with("outline"),"mask_from_original_rgb":true
                }),
            );
        }
        if contour_fusion {
            variant.insert("fusion_weights".into(), json!({"color":0.8,"contour":0.2}));
        }
        variant.insert(
            "empty_features".into(),
            json!(samples
                .iter()
                .zip(&features)
                .filter(|(_, v)| v.iter().all(|&x| x == 0.0))
                .count()),
        );
        let mut vectors = Vec::new();
        for (_, v) in &gallery {
            for value in *v {
                vectors.extend_from_slice(&value.to_le_bytes());
            }
        }
        fs::write(out.join(format!("{name}-gallery.f32le")), &vectors)?;
        variant.insert("gallery_bytes".into(), json!(vectors.len()));
        variant.insert("gallery_sha256".into(), json!(hash(&vectors)));
        fs::write(
            out.join(format!("{name}-gallery.json")),
            serde_json::to_vec_pretty(
                &json!({"rows":gallery.len(),"dimensions":features[0].len(),"labels":gallery.iter().map(|(l,_)|l).collect::<Vec<_>>(),"dtype":"float32_le","unit_identity_verified":false}),
            )?,
        )?;
        let mut preview = RgbImage::new(WIDTH as u32 * 4, HEIGHT as u32 * 2);
        for (n, (_, (crop, _))) in samples
            .iter()
            .zip(&prepared)
            .filter(|(s, _)| s.split == "test")
            .take(8)
            .enumerate()
        {
            let im = RgbImage::from_raw(WIDTH as u32, HEIGHT as u32, crop.rgb.clone())
                .ok_or("preview size")?;
            image::imageops::replace(
                &mut preview,
                &im,
                (n % 4 * WIDTH) as i64,
                (n / 4 * HEIGHT) as i64,
            );
        }
        preview.save(out.join(format!("{name}-preview.png")))?;
        if contour_fusion {
            let mut contours = RgbImage::new(WIDTH as u32 * 4, HEIGHT as u32 * 2);
            for (n, s) in samples
                .iter()
                .filter(|s| s.split == "test")
                .take(8)
                .enumerate()
            {
                let contour = s.crop.contour_view()?;
                let im = RgbImage::from_raw(WIDTH as u32, HEIGHT as u32, contour.rgb)
                    .ok_or("contour preview size")?;
                image::imageops::replace(
                    &mut contours,
                    &im,
                    (n % 4 * WIDTH) as i64,
                    (n / 4 * HEIGHT) as i64,
                );
            }
            contours.save(out.join("contour-only-preview.png"))?;
        }
        println!("{}", json!({"variant":name,"results":variant}));
        report.insert(name.clone(), variant);
        predictions.insert(name, variant_preds);
    }
    let summary = json!({"schema_version":1,"implementation":"rust_native_onnxruntime","python_required":false,"opencv_required":false,
        "encoder_sha256":hash(&fs::read(arg("--encoder")?)?),"annotations_sha256":hash(&fs::read(arg("--annotations")?)?),"threads":1,"batch":12,"input_size":side,
        "threshold":0.8,"margin":0.08,"runtime_approved":false,"new_training_performed":false,"variants":report,
        "limitations":["Reused development images with assistant-reviewed labels; no independent human ground truth.","Border-color connected flood mask is a heuristic, NOT GrabCut or a trained segmenter.","Contours are inner mask boundaries, not verified character outlines; board lines and occlusion remain.","Fusion uses fixed 80/20 color/contour weights, with unchanged uncalibrated threshold/margin; no test-based parameter selection.","Native bilinear resize is not pixel-identical to the old Pillow bicubic pipeline; use this run's native RGB baseline.","Timings include in-memory crop preprocessing, vector extraction and ranking, exclude screen capture and localization.","Gradient histogram is an untrained nearest-gallery descriptor, not canonical HOG/SVM.","No temporal identity memory or automatic model promotion."]});
    fs::write(
        out.join("report.json"),
        serde_json::to_vec_pretty(&summary)?,
    )?;
    fs::write(
        out.join("predictions.json"),
        serde_json::to_vec_pretty(&predictions)?,
    )?;
    Ok(())
}
pub fn main() {
    let result = if std::env::args().nth(1).as_deref() == Some("--configs") {
        live::run()
    } else {
        run()
    };
    if let Err(e) = result {
        eprintln!("UNIT_FEATURES_LAB_ERROR: {e}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn embedding_batch_policy_is_explicit_and_bounded() {
        assert_eq!(embedding_batch_size(None).unwrap(), 4);
        assert_eq!(embedding_batch_size(Some(&json!(1))).unwrap(), 1);
        for value in [json!(0), json!(5), json!(1.5), json!("1"), Value::Null] {
            assert!(embedding_batch_size(Some(&value)).is_err());
        }
    }
    #[test]
    fn standalone_evaluation_does_not_relax_training_split_requirements() {
        let test_only = HashSet::from(["test"]);
        let all = HashSet::from(["train", "validation", "test"]);
        assert!(validate_split_scope(&test_only, true).is_ok());
        assert!(validate_split_scope(&test_only, false).is_err());
        assert!(validate_split_scope(&all, false).is_ok());
        assert!(validate_split_scope(&all, true).is_err());
        assert!(validate_split_scope(&HashSet::new(), true).is_err());
    }
    #[test]
    fn quarantined_summon_cannot_return_as_champion_under_a_different_key() {
        let frame = json!({"excluded_entities":[{"key":"marker-2","box":[10,20,138,164]}]});
        assert!(quarantine_guard(&frame, "marker-2", &json!([0, 0, 128, 144])).is_err());
        assert!(quarantine_guard(&frame, "renamed", &json!([10, 20, 138, 164])).is_err());
        assert!(quarantine_guard(&frame, "marker-3", &json!([200, 20, 328, 164])).is_ok());
    }
    #[test]
    fn same_video_cannot_change_partition() {
        let mut map = HashMap::new();
        partition_guard(&mut map, "video:one", "train").unwrap();
        assert!(partition_guard(&mut map, "video:one", "test").is_err());
    }
    #[test]
    fn empty_vector_cannot_become_identity() {
        let v = vec![1.0, 0.0];
        let g = vec![("a", &v), ("b", &v)];
        assert!(rank(&[0.0, 0.0], &g)["candidate_id"].is_null());
        assert!(rank(&v, &g)["candidate_id"].is_null());
    }

    #[test]
    fn fusion_is_weighted_cosine_and_rejects_missing_contour() {
        let a = fuse_contour(&[1.0, 0.0], &[1.0, 0.0]);
        let b = fuse_contour(&[1.0, 0.0], &[0.0, 1.0]);
        assert!((cosine(&a, &b).unwrap() - 0.8).abs() < 1e-6);
        assert!(fuse_contour(&[1.0, 0.0], &[0.0, 0.0])
            .iter()
            .all(|&x| x == 0.0));
    }
}
