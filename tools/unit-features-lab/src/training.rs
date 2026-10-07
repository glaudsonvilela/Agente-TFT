//! Supervised lightweight heads on frozen native features. No pseudo-label training.
use super::*;
use serde::{Deserialize, Serialize};

const COLOR_DIM: usize = 4 * 52;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct OptimizerConfig {
    learning_rate: f32,
    weight_decay: f32,
    max_epochs: usize,
    checkpoints: Vec<usize>,
}

impl Default for OptimizerConfig {
    fn default() -> Self {
        Self {
            learning_rate: 2.,
            weight_decay: 0.001,
            max_epochs: 800,
            checkpoints: vec![50, 100, 200, 400, 800],
        }
    }
}

impl OptimizerConfig {
    fn validate(&self) -> Result<()> {
        if !self.learning_rate.is_finite()
            || !(0. < self.learning_rate && self.learning_rate <= 10.)
            || !self.weight_decay.is_finite()
            || !(0. ..=1.).contains(&self.weight_decay)
            || !(1..=10_000).contains(&self.max_epochs)
            || self.checkpoints.is_empty()
            || self
                .checkpoints
                .iter()
                .any(|&n| n == 0 || n > self.max_epochs)
            || self.checkpoints.windows(2).any(|w| w[0] >= w[1])
            || self.checkpoints.last() != Some(&self.max_epochs)
        {
            return Err("invalid optimizer budget or checkpoint schedule".into());
        }
        Ok(())
    }
}


#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AutonomousTrainingConfig {
    collection: String,
    source_id: String,
    gold_labels: String,
    silver_labels: String,
    gold_weight: f32,
    silver_weight: f32,
    #[serde(default)]
    use_declared_silver_weights: bool,
}

fn validate_autonomous_weight(value: f32, name: &str) -> Result<()> {
    if !value.is_finite() || !(0.0 < value && value <= 1.0) {
        return Err(format!("{name} must be finite in (0,1]").into());
    }
    Ok(())
}

fn load_autonomous_rows(
    file: &Path,
    collection: &Path,
    source_id: &str,
    ids: &HashSet<&str>,
    tier: &str,
    weight: f32,
    use_declared_silver_weights: bool,
    seen_pixels: &mut HashSet<String>,
) -> Result<Vec<(Sample, f32)>> {
    validate_autonomous_weight(weight, tier)?;
    let rows: Value = serde_json::from_slice(&fs::read(file)?)?;
    let rows = rows.as_array().ok_or("autonomous labels must be a JSON array")?;
    let collection = collection.canonicalize()?;
    let mut result = Vec::new();
    for (i, row) in rows.iter().enumerate() {
        let mut row_weight = weight;
        if row["source_id"].as_str() != Some(source_id)
            || row["human_review_required"] != false
            || row["training_eligible"] != true
        {
            return Err(format!("autonomous {tier} provenance mismatch at row {i}").into());
        }
        match tier {
            "gold_auto" => {
                if row["decision"] != "supported" && row["decision"] != "bootstrap_supported"
                    || (row["label_source"] != "autonomous_shop_purchase_bench_consensus_v1"
                        && row["label_source"] != "autonomous_tooltip_temporal_consensus_v1")
                    || row["model_prediction_used_as_label"] != false
                {
                    return Err(format!("unsupported gold provenance at row {i}").into());
                }
            }
            "silver_auto" => {
                if row["supervision_tier"] != "silver_auto"
                    || (row["label_source"] != "silver_auto_dino_frozen_temporal_consensus_v1"
                        && row["label_source"] != "silver_auto_shop_multiteacher_temporal_v1")
                    || row["human_review_required"] != false
                {
                    return Err(format!("unsupported silver provenance at row {i}").into());
                }
                let declared = row["recommended_training_weight"]
                    .as_f64()
                    .ok_or("silver recommended weight")? as f32;
                validate_autonomous_weight(declared, "silver declared weight")?;
                if declared > weight + 1e-6 {
                    return Err("silver declared weight exceeds configured maximum".into());
                }
                if use_declared_silver_weights {
                    row_weight = declared;
                } else if (declared - weight).abs() > 1e-6 {
                    return Err("silver declared/configured weight mismatch".into());
                }
            }
            _ => return Err("unknown autonomous supervision tier".into()),
        }

        let label = row["unit_id"].as_str().ok_or("autonomous unit_id")?;
        if !ids.contains(label) {
            return Err(format!("autonomous label absent from catalog: {label}").into());
        }
        let relative = row["crop"].as_str().ok_or("autonomous crop path")?;
        let filename = collection.join(relative).canonicalize()?;
        if !filename.starts_with(&collection) {
            return Err("autonomous crop escapes collection root".into());
        }
        let rgb = image::open(&filename)?.to_rgb8();
        if (rgb.width(), rgb.height()) != (WIDTH as u32, HEIGHT as u32) {
            return Err("autonomous crop geometry mismatch".into());
        }
        let pixel = hash(rgb.as_raw());
        if row["pixel_sha256"].as_str() != Some(pixel.as_str()) {
            return Err("autonomous crop pixel hash mismatch".into());
        }
        if !seen_pixels.insert(pixel.clone()) {
            return Err("duplicate autonomous/base crop pixels".into());
        }
        let time = row["source_seconds_nominal"]
            .as_u64()
            .ok_or("autonomous source time")?;
        result.push((
            Sample {
                crop: UnitCrop { rgb: rgb.into_raw() },
                label: label.to_owned(),
                split: "train".into(),
                image: format!("autonomous:{source_id}:{time}"),
                key: format!("{tier}:{i}:{pixel}"),
            },
            row_weight,
        ));
    }
    Ok(result)
}

fn load_autonomous_training(
    spec: &Value,
    reference: &Path,
    base_samples: &[Sample],
) -> Result<Vec<(Sample, f32)>> {
    let single = spec.get("autonomous_training").filter(|v| !v.is_null());
    let multiple = spec
        .get("autonomous_training_sources")
        .filter(|v| !v.is_null());

    if single.is_some() && multiple.is_some() {
        return Err("use autonomous_training or autonomous_training_sources, not both".into());
    }

    let configs: Vec<AutonomousTrainingConfig> = if let Some(value) = multiple {
        let rows = value
            .as_array()
            .ok_or("autonomous_training_sources must be an array")?;
        if rows.is_empty() || rows.len() > 512 {
            return Err("autonomous_training_sources count outside 1..=512".into());
        }
        rows.iter()
            .map(|v| serde_json::from_value(v.clone()))
            .collect::<std::result::Result<_, _>>()?
    } else if let Some(value) = single {
        vec![serde_json::from_value(value.clone())?]
    } else {
        return Ok(Vec::new());
    };

    let cat: Value = serde_json::from_slice(&fs::read(reference.join("champions.json"))?)?;
    let ids: HashSet<_> = cat["entries"]
        .as_array()
        .ok_or("catalog entries")?
        .iter()
        .map(|x| str_field(x, "id"))
        .collect::<Result<_>>()?;

    let mut seen_pixels: HashSet<String> =
        base_samples.iter().map(|s| hash(&s.crop.rgb)).collect();
    let mut seen_sources = HashSet::new();
    let mut result = Vec::new();

    for config in configs {
        if !seen_sources.insert(config.source_id.clone()) {
            return Err("duplicate autonomous source_id".into());
        }
        validate_autonomous_weight(config.gold_weight, "gold_weight")?;
        validate_autonomous_weight(config.silver_weight, "silver_weight")?;
        if config.gold_weight < config.silver_weight {
            return Err("gold autonomous weight must be >= silver weight".into());
        }
        let collection = PathBuf::from(&config.collection);
        result.extend(load_autonomous_rows(
            Path::new(&config.gold_labels),
            &collection,
            &config.source_id,
            &ids,
            "gold_auto",
            config.gold_weight,
            false,
            &mut seen_pixels,
        )?);
        result.extend(load_autonomous_rows(
            Path::new(&config.silver_labels),
            &collection,
            &config.source_id,
            &ids,
            "silver_auto",
            config.silver_weight,
            config.use_declared_silver_weights,
            &mut seen_pixels,
        )?);
    }
    Ok(result)
}

fn effective_class_weights(
    samples: &[Sample],
    sample_weights: &[f32],
    labels: &[String],
) -> Result<(Vec<usize>, Vec<f32>)> {
    if samples.len() != sample_weights.len() {
        return Err("sample/weight count mismatch".into());
    }
    let targets: Vec<_> = samples
        .iter()
        .map(|s| labels.binary_search(&s.label).map_err(|_| "target label missing"))
        .collect::<std::result::Result<_, _>>()?;
    let mut totals = vec![0f32; labels.len()];
    for (&target, &weight) in targets.iter().zip(sample_weights) {
        if !weight.is_finite() || weight <= 0.0 {
            return Err("invalid training sample weight".into());
        }
        totals[target] += weight;
    }
    if totals.iter().any(|x| !x.is_finite() || *x <= 0.0) {
        return Err("invalid weighted class total".into());
    }
    Ok((targets, totals))
}

fn augment_training(samples: &mut Vec<Sample>, sample_weights: &mut Vec<f32>) -> Result<usize> {
    if samples.len() != sample_weights.len() {
        return Err("sample/weight count mismatch before augmentation".into());
    }
    let originals: Vec<_> = samples
        .iter()
        .zip(sample_weights.iter().copied())
        .filter(|(s, _)| s.split == "train")
        .map(|(s, w)| (s.clone(), w))
        .collect();
    let mut added = 0;
    for (original, original_weight) in originals {
        for mode in ["mirror", "dim", "bright", "mask"] {
            let mut s = original.clone();
            match mode {
                "mirror" => {
                    for y in 0..HEIGHT {
                        for x in 0..WIDTH {
                            for c in 0..3 {
                                s.crop.rgb[(y * WIDTH + x) * 3 + c] =
                                    original.crop.rgb[(y * WIDTH + WIDTH - 1 - x) * 3 + c];
                            }
                        }
                    }
                }
                "mask" => {
                    if s.crop.foreground()?.empty {
                        continue;
                    }
                }
                _ => {
                    let scale = if mode == "dim" { 0.75 } else { 1.25 };
                    for v in &mut s.crop.rgb {
                        *v = (*v as f32 * scale).round().clamp(0., 255.) as u8;
                    }
                }
            }
            s.key = format!("{}@augmentation:{mode}", s.key);
            samples.push(s);
            sample_weights.push(original_weight);
            added += 1;
        }
    }
    Ok(added)
}

fn augment_vertical_alignment(
    samples: &mut Vec<Sample>,
    sample_weights: &mut Vec<f32>,
    originals: &[(Sample, f32)],
    transform: crate::crop_transform::CropTransform,
) -> Result<usize> {
    let mut added = 0;
    for (original, original_weight) in originals.iter().filter(|(s, _)| s.split == "train") {
        for offset in [-12, 12] {
            let mut view = original.clone();
            view.crop = transform.vertical_training_view(&original.crop, offset)?;
            view.key = format!("{}@augmentation:vertical:{offset}", view.key);
            samples.push(view);
            sample_weights.push(*original_weight);
            added += 1;
        }
    }
    Ok(added)
}

/// Spatial HSV histogram with separate achromatic bins. Square-root frequencies
/// give a Hellinger embedding. This describes the central crop, not a true mask.
pub fn colors(crop: &UnitCrop) -> Vec<f32> {
    let mut out = vec![0f32; COLOR_DIM];
    for y in 0..120 {
        for x in 16..112 {
            let p = (y * WIDTH + x) * 3;
            let r = crop.rgb[p] as f32 / 255.;
            let g = crop.rgb[p + 1] as f32 / 255.;
            let b = crop.rgb[p + 2] as f32 / 255.;
            let hi = r.max(g).max(b);
            let lo = r.min(g).min(b);
            let d = hi - lo;
            let s = if hi > 0. { d / hi } else { 0. };
            let bin = if s < 0.12 || hi < 0.08 {
                48 + ((hi * 4.) as usize).min(3)
            } else {
                let h = if hi == r {
                    (g - b) / d
                } else if hi == g {
                    (b - r) / d + 2.
                } else {
                    (r - g) / d + 4.
                };
                let hue = ((h.rem_euclid(6.) * 2.) as usize).min(11);
                hue * 4 + usize::from(s >= 0.5) * 2 + usize::from(hi >= 0.5)
            };
            let cell = (y / 60) * 2 + (x - 16) / 48;
            out[cell * 52 + bin] += 1.;
        }
    }
    for x in &mut out {
        *x = x.sqrt();
    }
    normalize(&mut out);
    out
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Head {
    pub labels: Vec<String>,
    pub dimensions: usize,
    pub weights: Vec<f32>,
    pub biases: Vec<f32>,
}
impl Head {
    pub fn probabilities(&self, x: &[f32]) -> Result<Vec<f32>> {
        if self.labels.len() < 2
            || x.len() != self.dimensions
            || self.weights.len() != self.labels.len() * self.dimensions
            || self.biases.len() != self.labels.len()
            || x.iter()
                .chain(&self.weights)
                .chain(&self.biases)
                .any(|v| !v.is_finite())
        {
            return Err("invalid classifier dimensions/nonfinite values".into());
        }
        let mut scores: Vec<f32> = self
            .weights
            .chunks_exact(self.dimensions)
            .zip(&self.biases)
            .map(|(w, b)| w.iter().zip(x).map(|(a, b)| a * b).sum::<f32>() + b)
            .collect();
        let max = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        scores.iter_mut().for_each(|v| *v = (*v - max).exp());
        let sum: f32 = scores.iter().sum();
        if !sum.is_finite() || sum <= 0. {
            return Err("nonfinite classifier output".into());
        }
        scores.iter_mut().for_each(|v| *v /= sum);
        Ok(scores)
    }
}

pub fn metrics(head: &Head, rows: &[(&Sample, &Vec<f32>)]) -> Result<Value> {
    metrics_with_predictor(&head.labels, rows, |x| head.probabilities(x))
}

pub fn metrics_with_predictor(
    labels: &[String],
    rows: &[(&Sample, &Vec<f32>)],
    predict: impl Fn(&[f32]) -> Result<Vec<f32>>,
) -> Result<Value> {
    let mut per_class: BTreeMap<String, (u64, u64)> = BTreeMap::new();
    let mut confusion: BTreeMap<String, u64> = BTreeMap::new();
    let mut predictions = Vec::new();
    let mut loss = 0.;
    for (sample, x) in rows {
        let p = predict(x)?;
        if p.len() != labels.len() || p.is_empty() || p.iter().any(|x| !x.is_finite() || *x < 0.) {
            return Err("invalid prediction distribution".into());
        }
        let mut order: Vec<_> = (0..p.len()).collect();
        order.sort_by(|&a, &b| p[b].total_cmp(&p[a]).then(a.cmp(&b)));
        let k = order[0];
        let second = order[1];
        let correct = labels[k] == sample.label;
        let counts = per_class.entry(sample.label.clone()).or_default();
        counts.0 += 1;
        counts.1 += u64::from(correct);
        if !correct {
            *confusion
                .entry(format!("{} -> {}", sample.label, labels[k]))
                .or_default() += 1;
        }
        let truth = labels.iter().position(|s| s == &sample.label);
        loss -= truth.map(|i| p[i]).unwrap_or(0.).max(1e-12).ln() as f64;
        predictions.push(
            json!({"image":sample.image,"key":sample.key,"label":sample.label,
            "predicted":labels[k],"softmax_score_uncalibrated":p[k],
            "runner_up":labels[second],"runner_up_score_uncalibrated":p[second],
            "softmax_margin_uncalibrated":p[k]-p[second],
            "identity_verified":false}),
        );
    }
    let named: Vec<_> = per_class
        .iter()
        .filter(|(id, _)| id.as_str() != "__unknown__")
        .collect();
    let macro_recall = if named.is_empty() {
        0.
    } else {
        named
            .iter()
            .map(|(_, (n, c))| *c as f64 / *n as f64)
            .sum::<f64>()
            / named.len() as f64
    };
    Ok(
        json!({"samples":rows.len(),"named":named.iter().map(|(_,p)|p.0).sum::<u64>(),
        "named_top1_correct":named.iter().map(|(_,p)|p.1).sum::<u64>(),"named_macro_recall":macro_recall,
        "cross_entropy":loss/rows.len().max(1) as f64,"per_class":per_class,"confusions":confusion,"predictions":predictions}),
    )
}

fn fit(
    samples: &[Sample],
    sample_weights: &[f32],
    features: &[Vec<f32>],
    optimizer: &OptimizerConfig,
) -> Result<(Head, usize, Vec<Value>)> {
    optimizer.validate()?;
    if samples.len() != features.len() || samples.len() != sample_weights.len() {
        return Err("sample/feature/weight count mismatch".into());
    }
    let train: Vec<_> = samples
        .iter()
        .zip(features)
        .zip(sample_weights)
        .filter(|((s, _), _)| s.split == "train")
        .map(|((s, x), w)| (s, x, *w))
        .collect();
    let validation: Vec<_> = samples
        .iter()
        .zip(features)
        .filter(|(s, _)| s.split == "validation")
        .collect();
    if train.is_empty() || validation.is_empty() {
        return Err("training and validation samples required".into());
    }
    let mut labels: Vec<_> = train.iter().map(|(s, _, _)| s.label.clone()).collect();
    labels.sort();
    labels.dedup();
    let dimensions = features.first().ok_or("empty features")?.len();
    let mut head = Head {
        weights: vec![0.; labels.len() * dimensions],
        biases: vec![0.; labels.len()],
        dimensions,
        labels,
    };
    let train_samples: Vec<_> = train.iter().map(|(s, _, _)| (*s).clone()).collect();
    let train_weights: Vec<_> = train.iter().map(|(_, _, w)| *w).collect();
    let (targets, weighted_class_totals) =
        effective_class_weights(&train_samples, &train_weights, &head.labels)?;
    // Fixed class-balanced full-batch gradient descent; only validation selects
    // an epoch. Test examples never take part in gradient/checkpoint selection.
    let mut best: Option<(f64, f64, usize, Head)> = None;
    let mut history = Vec::new();
    for epoch in 1..=optimizer.max_epochs {
        let mut dw = vec![0.; head.weights.len()];
        let mut db = vec![0.; head.labels.len()];
        for ((_, x, sample_weight), &target) in train.iter().zip(&targets) {
            let p = head.probabilities(x)?;
            let weight = *sample_weight
                / (weighted_class_totals[target] * head.labels.len() as f32);
            for k in 0..head.labels.len() {
                let error = (p[k] - if k == target { 1. } else { 0. }) * weight;
                db[k] += error;
                for (g, value) in dw[k * dimensions..(k + 1) * dimensions].iter_mut().zip(*x) {
                    *g += error * value;
                }
            }
        }
        for (w, g) in head.weights.iter_mut().zip(dw) {
            *w -= optimizer.learning_rate * (g + optimizer.weight_decay * *w);
        }
        for (b, g) in head.biases.iter_mut().zip(db) {
            *b -= optimizer.learning_rate * g;
        }
        if optimizer.checkpoints.contains(&epoch) {
            let m = metrics(&head, &validation)?;
            let score = m["named_macro_recall"].as_f64().ok_or("validation score")?;
            let loss = m["cross_entropy"].as_f64().ok_or("validation loss")?;
            history.push(
                json!({"epoch":epoch,"validation_macro_recall":score,"validation_loss":loss}),
            );
            println!(
                "{}",
                json!({"training_checkpoint":epoch,"validation_macro_recall":score,"validation_loss":loss})
            );
            if best
                .as_ref()
                .is_none_or(|(s, l, _, _)| score > *s || score == *s && loss < *l)
            {
                best = Some((score, loss, epoch, head.clone()));
            }
        }
    }
    let (_, _, epoch, head) = best.ok_or("no selected classifier")?;
    Ok((head, epoch, history))
}

pub fn run_cli() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec training.json".into());
    }
    let spec_bytes = fs::read(&args[2])?;
    let spec: Value = serde_json::from_slice(&spec_bytes)?;
    let optimizer: OptimizerConfig = match spec.get("optimizer") {
        Some(value) => serde_json::from_value(value.clone())?,
        None => OptimizerConfig::default(),
    };
    optimizer.validate()?;
    let out = PathBuf::from(str_field(&spec, "output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }
    let reference_path = Path::new(str_field(&spec, "reference")?);
    let mut samples = load_samples(
        Path::new(str_field(&spec, "annotations")?),
        Path::new(str_field(&spec, "images")?),
        reference_path,
    )?;
    let reviewed_samples = samples.len();
    let autonomous_rows = load_autonomous_training(&spec, reference_path, &samples)?;
    let autonomous_source_samples = autonomous_rows.len();
    let mut sample_weights = vec![1.0f32; samples.len()];
    for (sample, weight) in autonomous_rows {
        samples.push(sample);
        sample_weights.push(weight);
    }
    if spec["retrieval_only"] == true && spec["augmentation"].as_str().unwrap_or("none") != "none" {
        return Err("retrieval experiment requires unaugmented reviewed samples".into());
    }
    let transform: crate::crop_transform::CropTransform = match spec.get("crop_transform") {
        Some(value) => serde_json::from_value(value.clone())?,
        None => Default::default(),
    };
    let crop_transform = transform.name();
    let alignment_originals: Vec<_> = if spec["augmentation"] == "vertical_alignment_v1" {
        samples
            .iter()
            .zip(sample_weights.iter().copied())
            .filter(|(s, _)| s.split == "train")
            .map(|(s, w)| (s.clone(), w))
            .collect()
    } else {
        Vec::new()
    };
    for sample in &mut samples {
        sample.crop = transform.apply(&sample.crop)?;
    }
    let source_samples = samples.len();
    let augmented = match spec["augmentation"].as_str().unwrap_or("none") {
        "none" => 0,
        "native_domain_v1" => augment_training(&mut samples, &mut sample_weights)?,
        "vertical_alignment_v1" => {
            augment_vertical_alignment(
                &mut samples,
                &mut sample_weights,
                &alignment_originals,
                transform,
            )?
        }
        _ => return Err("unknown augmentation policy".into()),
    };
    let encoder_bytes = fs::read(str_field(&spec, "encoder")?)?;
    if hash(&encoder_bytes) != str_field(&spec, "encoder_sha256")? {
        return Err("encoder hash mismatch".into());
    }
    let side = num(&spec, "input_size")? as usize;
    if !(64..=224).contains(&side) {
        return Err("input size budget".into());
    }
    ort::init_from(str_field(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(str_field(&spec, "encoder")?)?;
    fs::create_dir_all(&out)?;
    let start = Instant::now();
    let mut neural = Vec::new();
    let cache = spec["embedding_cache"].as_str().map(PathBuf::from);
    if let Some(p) = &cache {
        fs::create_dir_all(p)?;
    }
    let mut cache_hits = 0;
    let embedding_batch_size = embedding_batch_size(spec.get("embedding_batch_size"))?;
    for chunk in samples.chunks(embedding_batch_size) {
        let crops: Vec<_> = chunk.iter().map(|s| (s.crop.clone(), true)).collect();
        // Dynamic quantization can depend on the other batch members. Cache
        // the entire ordered batch, not individual pixels under a false key.
        let key = hash(
            format!(
                "rgb-bilinear-imagenet-v1:{crop_transform}:{}:{side}:{}",
                spec["encoder_sha256"],
                chunk
                    .iter()
                    .map(|s| hash(&s.crop.rgb))
                    .collect::<Vec<_>>()
                    .join(":")
            )
            .as_bytes(),
        );
        let cache_path = cache.as_ref().map(|p| p.join(format!("{key}.json")));
        let features = if let Some(p) = cache_path.as_ref().filter(|p| p.exists()) {
            let value: Value = serde_json::from_slice(&fs::read(p)?)?;
            let vectors: Vec<Vec<f32>> = serde_json::from_value(value["vectors"].clone())?;
            let encoded = serde_json::to_vec(&vectors)?;
            if value["sha256"] != hash(&encoded)
                || vectors.len() != chunk.len()
                || vectors
                    .iter()
                    .any(|v| v.is_empty() || v.iter().any(|x| !x.is_finite()))
            {
                return Err("invalid embedding cache".into());
            }
            cache_hits += 1;
            vectors
        } else {
            let vectors = embeddings(&mut session, &crops, side, false, false)?;
            if let Some(p) = cache_path {
                let sha = hash(&serde_json::to_vec(&vectors)?);
                fs::write(
                    p,
                    serde_json::to_vec(&json!({"sha256":sha,"vectors":vectors}))?,
                )?;
            }
            vectors
        };
        neural.extend(features);
    }
    if spec["retrieval_only"] == true {
        return crate::retrieval::build_experiment(
            &samples,
            &neural,
            &spec,
            &spec_bytes,
            &out,
            start,
            cache_hits,
        );
    }
    let color: Vec<_> = samples.iter().map(|s| colors(&s.crop)).collect();
    let combined: Vec<Vec<f32>> = neural
        .iter()
        .zip(&color)
        .map(|(n, c)| {
            let mut v = n.clone();
            v.extend(c);
            normalize(&mut v);
            v
        })
        .collect();
    let mut reports = BTreeMap::new();
    for (name, features) in [
        ("colors", &color),
        ("dino", &neural),
        ("dino_colors", &combined),
    ] {
        if spec["only_dino"] == true && name != "dino" {
            continue;
        }
        let (head, epoch, history) = fit(&samples, &sample_weights, features, &optimizer)?;
        let mut evaluation = BTreeMap::new();
        for split in ["train", "validation", "test"] {
            let rows: Vec<_> = samples
                .iter()
                .zip(features)
                .filter(|(s, _)| s.split == split)
                .collect();
            evaluation.insert(split, metrics(&head, &rows)?);
        }
        let model = json!({"schema_version":1,"supervision_policy":crate::SUPERVISION_POLICY,"feature_mode":name,"head":head,"selected_epoch":epoch,
            "encoder_sha256":spec["encoder_sha256"],"annotations_sha256":hash(&fs::read(str_field(&spec,"annotations")?)?),
            "input_size":side,"crop_transform":crop_transform,"embedding_batch_size":embedding_batch_size,
            "runtime_approved":false,"probabilities_calibrated":false,"augmentation":spec["augmentation"],"optimizer":optimizer,
            "autonomous_training":spec.get("autonomous_training")});
        let bytes = serde_json::to_vec(&model)?;
        fs::write(out.join(format!("{name}-head.json")), &bytes)?;
        let report = json!({"selected_epoch":epoch,"checkpoints":history,"evaluation":evaluation,
            "artifact_bytes":bytes.len(),"artifact_sha256":hash(&bytes)});
        println!(
            "{}",
            json!({"variant":name,"epoch":epoch,"test_named":report["evaluation"]["test"]["named"],
            "test_correct":report["evaluation"]["test"]["named_top1_correct"]})
        );
        reports.insert(name, report);
    }
    let report = json!({"schema_version":1,"supervision_policy":crate::SUPERVISION_POLICY,"implementation":"rust_native","training_performed":true,
        "backbone_finetuned":false,
        "training_algorithm":"class_balanced_weighted_multiclass_softmax_gradient_descent",
        "learning_rate":optimizer.learning_rate,"weight_decay":optimizer.weight_decay,"max_epochs":optimizer.max_epochs,
        "optimizer":optimizer,"checkpoint_selection":"validation_macro_recall_then_loss",
        "variants":reports,"elapsed_seconds":start.elapsed().as_secs_f64(),"spec_sha256":hash(&spec_bytes),
        "source_samples":source_samples,"reviewed_source_samples":reviewed_samples,
        "autonomous_source_samples":autonomous_source_samples,
        "autonomous_training":spec.get("autonomous_training"),
        "crop_transform":crop_transform,"embedding_batch_size":embedding_batch_size,
        "synthetic_training_views":augmented,"embedding_cache_hit_batches":cache_hits,
        "encoder_sha256":spec["encoder_sha256"],"runtime_approved":false,
        "limitations":["Existing small assistant-reviewed dataset; no independent human ground truth.",
        "A supervised classification head is trained; frozen DINO weights are unchanged.",
        "Spatial color histograms contain some background; not a segmentation mask.",
        "Softmax scores are uncalibrated; no identity confirmation or coaching activation.",
        "Held-out source separation is enforced; repeated development test use still limits generalization claims.",
        "The new six-hour VOD is not used as training data or automatic labels."]});
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&report)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn optimizer_rejects_ambiguous_or_unbounded_schedules() {
        OptimizerConfig::default().validate().unwrap();
        for value in [
            json!({"max_epochs":0}),
            json!({"max_epochs":10001}),
            json!({"learning_rate":0}),
            json!({"weight_decay":-0.1}),
            json!({"checkpoints":[50,50,800]}),
            json!({"checkpoints":[50,400]}),
            json!({"checkpoints":[0,800]}),
            json!({"checkpoints":[800,50]}),
            json!({"checkpoints":[]}),
        ] {
            assert!(serde_json::from_value::<OptimizerConfig>(value)
                .unwrap()
                .validate()
                .is_err());
        }
        assert!(serde_json::from_value::<OptimizerConfig>(json!({"learnig_rate":2})).is_err());
    }

    #[test]
    fn held_out_test_changes_cannot_change_trained_weights_or_selection() {
        let make = |label: &str, split: &str| Sample {
            crop: UnitCrop {
                rgb: vec![0; WIDTH * HEIGHT * 3],
            },
            label: label.into(),
            split: split.into(),
            image: split.into(),
            key: label.into(),
        };
        let mut samples = vec![
            make("a", "train"),
            make("b", "train"),
            make("a", "validation"),
            make("b", "validation"),
            make("a", "test"),
        ];
        let mut features = vec![
            vec![1., 0.],
            vec![0., 1.],
            vec![1., 0.],
            vec![0., 1.],
            vec![1., 0.],
        ];
        let optimizer = OptimizerConfig {
            max_epochs: 4,
            checkpoints: vec![2, 4],
            ..Default::default()
        };
        let weights = vec![1.0; samples.len()];
        let (first, epoch, history) = fit(&samples, &weights, &features, &optimizer).unwrap();
        samples[4].label = "unseen-test-class".into();
        features[4] = vec![100., -100.];
        let second_weights = vec![1.0; samples.len()];
        let (second, second_epoch, second_history) =
            fit(&samples, &second_weights, &features, &optimizer).unwrap();
        assert_eq!(first.weights, second.weights);
        assert_eq!(first.biases, second.biases);
        assert_eq!(epoch, second_epoch);
        assert_eq!(history, second_history);
        assert_eq!(first.labels, vec!["a", "b"]);
    }

    #[test]
    fn weighted_class_balance_preserves_class_mass_and_downweights_silver() {
        let make = |label: &str| Sample {
            crop: UnitCrop { rgb: vec![0; WIDTH * HEIGHT * 3] },
            label: label.into(),
            split: "train".into(),
            image: label.into(),
            key: label.into(),
        };
        let samples = vec![make("a"), make("a"), make("b")];
        let weights = vec![1.0, 0.35, 1.0];
        let labels = vec!["a".to_owned(), "b".to_owned()];
        let (targets, totals) = effective_class_weights(&samples, &weights, &labels).unwrap();
        assert_eq!(targets, vec![0, 0, 1]);
        assert!((totals[0] - 1.35).abs() < 1e-6);
        assert!((totals[1] - 1.0).abs() < 1e-6);
        let gold_share = weights[0] / totals[0];
        let silver_share = weights[1] / totals[0];
        assert!(gold_share > silver_share);
    }

    #[test]
    fn color_histogram_distinguishes_palette_and_position() {
        let red = UnitCrop {
            rgb: [255, 0, 0].repeat(WIDTH * HEIGHT),
        };
        let blue = UnitCrop {
            rgb: [0, 0, 255].repeat(WIDTH * HEIGHT),
        };
        let a = colors(&red);
        let b = colors(&blue);
        assert!(cosine(&a, &b).unwrap().abs() < 1e-6);
        assert!((cosine(&a, &a).unwrap() - 1.).abs() < 1e-6);
        let black = UnitCrop {
            rgb: vec![0; WIDTH * HEIGHT * 3],
        };
        assert!(colors(&black).iter().all(|v| v.is_finite()));
    }
    #[test]
    fn classifier_rejects_invalid_features() {
        let head = Head {
            labels: vec!["a".into(), "b".into()],
            dimensions: 2,
            weights: vec![1., 0., 0., 1.],
            biases: vec![0.; 2],
        };
        assert!(head.probabilities(&[f32::NAN, 1.]).is_err());
        assert!(head.probabilities(&[1.]).is_err());
        let p = head.probabilities(&[1., 0.]).unwrap();
        assert!(p[0] > p[1]);
        assert!((p.iter().sum::<f32>() - 1.).abs() < 1e-6);
    }

    #[test]
    fn vertical_augmentation_keeps_held_out_examples_and_provenance() {
        let make = |split: &str| Sample {
            crop: UnitCrop {
                rgb: [10, 50, 80].repeat(WIDTH * HEIGHT),
            },
            label: "a".into(),
            split: split.into(),
            image: split.into(),
            key: "one".into(),
        };
        let originals = vec![make("train"), make("validation"), make("test")];
        let original_weights = vec![1.0, 1.0, 1.0];
        let weighted_originals: Vec<_> = originals
            .iter()
            .cloned()
            .zip(original_weights.iter().copied())
            .collect();
        let mut prepared = originals.clone();
        let mut prepared_weights = original_weights.clone();
        assert_eq!(
            augment_vertical_alignment(
                &mut prepared,
                &mut prepared_weights,
                &weighted_originals,
                crate::crop_transform::CropTransform::Upper88x80V1
            )
            .unwrap(),
            2
        );
        assert_eq!(prepared[1].crop, originals[1].crop);
        assert_eq!(prepared[2].crop, originals[2].crop);
        assert!(prepared[3..]
            .iter()
            .all(|s| s.split == "train" && s.image == "train" && s.label == "a"));
    }
    #[test]
    fn augmentation_cannot_modify_validation_or_test() {
        let sample = |split: &str| Sample {
            crop: UnitCrop {
                rgb: [30, 70, 120].repeat(WIDTH * HEIGHT),
            },
            label: "a".into(),
            split: split.into(),
            image: split.into(),
            key: "one".into(),
        };
        let mut samples = vec![sample("train"), sample("validation"), sample("test")];
        let mut weights = vec![0.35, 1.0, 1.0];
        let before = samples[1].crop.clone();
        let n = augment_training(&mut samples, &mut weights).unwrap();
        assert!(n >= 3);
        assert_eq!(samples[1].crop, before);
        assert!(samples[3..].iter().all(|s| s.split == "train"));
        assert!(weights[3..].iter().all(|w| (*w - 0.35).abs() < 1e-6));
    }
}
