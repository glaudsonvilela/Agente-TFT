//! Recheck image/label bindings and report collection gaps without model guesses.
use agente_tft_unit_features_lab::{load_samples, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 5 {
        return Err("use ANNOTATIONS_JSON IMAGE_ROOT REFERENCE_DIRECTORY NEW_REPORT_JSON".into());
    }
    let output = Path::new(&args[4]);
    if output.exists() {
        return Err("new report required".into());
    }
    // This validates catalog hash, full-frame/crop hashes, geometry, labels and
    // source/match/session partition isolation before reporting any coverage.
    let samples = load_samples(
        Path::new(&args[1]),
        Path::new(&args[2]),
        Path::new(&args[3]),
    )?;
    let annotations = fs::read(&args[1])?;
    let doc: Value = serde_json::from_slice(&annotations)?;
    let catalog_bytes = fs::read(Path::new(&args[3]).join("champions.json"))?;
    let catalog: Value = serde_json::from_slice(&catalog_bytes)?;
    let sources: BTreeMap<_, _> = doc["frames"]
        .as_array()
        .ok_or("frames")?
        .iter()
        .map(|f| {
            (
                f["image"].as_str().unwrap_or_default(),
                f["source_video_id"]
                    .as_str()
                    .or_else(|| f["match_group"].as_str())
                    .unwrap_or_default(),
            )
        })
        .collect();
    let mut counts: BTreeMap<&str, BTreeMap<&str, usize>> = BTreeMap::new();
    let mut per_source: BTreeMap<(&str, &str), BTreeSet<&str>> = BTreeMap::new();
    for sample in &samples {
        *counts
            .entry(&sample.split)
            .or_default()
            .entry(&sample.label)
            .or_default() += 1;
        per_source
            .entry((&sample.split, &sample.label))
            .or_default()
            .insert(
                sources
                    .get(sample.image.as_str())
                    .copied()
                    .ok_or("sample without source")?,
            );
    }
    let mut classes = Vec::new();
    for entry in catalog["entries"].as_array().ok_or("catalog entries")? {
        let id = entry["id"].as_str().ok_or("catalog ID")?;
        let mut partitions = serde_json::Map::new();
        for split in ["train", "validation", "test"] {
            let n = counts
                .get(split)
                .and_then(|c| c.get(id))
                .copied()
                .unwrap_or(0);
            let src: Vec<_> = per_source
                .get(&(split, id))
                .into_iter()
                .flatten()
                .copied()
                .collect();
            partitions.insert(split.into(), json!({"samples": n, "sources": src}));
        }
        classes.push(json!({"id":id,"name":entry["name"],"partitions":partitions}));
    }
    let missing: Vec<_> = classes
        .iter()
        .filter(|c| c["partitions"]["train"]["samples"] == 0)
        .map(|c| c["id"].clone())
        .collect();
    let single_source: Vec<_> = classes
        .iter()
        .filter(|c| {
            c["partitions"]["train"]["sources"]
                .as_array()
                .is_some_and(|s| s.len() == 1)
        })
        .map(|c| c["id"].clone())
        .collect();
    let report = json!({"schema_version":1,"set_key":catalog["set_key"],
        "annotations_sha256":format!("{:x}",Sha256::digest(&annotations)),
        "catalog_sha256":format!("{:x}",Sha256::digest(&catalog_bytes)),
        "pixel_and_partition_checks_passed":true,"samples":samples.len(),"counts":counts,
        "catalog_classes":classes.len(),"missing_training_ids":missing,
        "single_training_source_ids":single_source,"classes":classes,"runtime_approved":false,
        "limitations":["Checks establish data integrity and source isolation, not label truth or model accuracy.",
            "A source may contain many correlated appearances; counts are not independent matches.",
            "This development dataset includes reused evaluation sources; a fresh final holdout is still required."]});
    fs::write(output, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "{}",
        json!({"samples":samples.len(),"missing_training_ids":missing.len(),"single_training_source_ids":single_source.len()})
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("DATASET_AUDIT_ERROR: {e}");
        std::process::exit(1);
    }
}
