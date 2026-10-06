//! Adjudicate autonomous gold anchors against two frozen teachers:
//! 1) the selected linear classifier;
//! 2) nearest supervised training exemplars on the same frozen DINO space.
//!
//! The game-derived gold label is never replaced. This tool only decides
//! whether an anchor is supported strongly enough to remain training-eligible.

use agente_tft_image_preprocess::unit_features::UnitCrop;
use agente_tft_unit_features_lab::{
    crop_transform::CropTransform, embedding_batch_size, embeddings, load_samples,
    training::Head, Result, Sample,
};
use ort::session::Session;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    fs,
    path::{Path, PathBuf},
};

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn s<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().ok_or_else(|| format!("missing {key}").into())
}
fn read_sealed(spec: &Value, key: &str) -> Result<Vec<u8>> {
    let bytes = fs::read(s(spec, key)?)?;
    if hash(&bytes) != s(spec, &format!("{key}_sha256"))? {
        return Err(format!("{key} checksum mismatch").into());
    }
    Ok(bytes)
}
fn cosine(a: &[f32], b: &[f32]) -> Result<f32> {
    if a.len() != b.len() || a.is_empty() {
        return Err("embedding dimension mismatch".into());
    }
    let mut dot=0f64; let mut aa=0f64; let mut bb=0f64;
    for (&x,&y) in a.iter().zip(b) {
        if !x.is_finite() || !y.is_finite() { return Err("nonfinite embedding".into()); }
        dot += x as f64 * y as f64; aa += (x as f64).powi(2); bb += (y as f64).powi(2);
    }
    if aa <= 1e-12 || bb <= 1e-12 { return Err("zero embedding".into()); }
    Ok((dot/(aa.sqrt()*bb.sqrt())) as f32)
}
fn load_crop(path:&Path, expected:&str)->Result<UnitCrop>{
    let rgb=image::open(path)?.to_rgb8();
    if (rgb.width(),rgb.height())!=(128,144){return Err("anchor crop geometry".into());}
    let raw=rgb.into_raw();
    if hash(&raw)!=expected{return Err("anchor crop pixel hash mismatch".into());}
    Ok(UnitCrop{rgb:raw})
}

fn run() -> Result<()> {
    let args:Vec<_>=std::env::args().collect();
    if args.len()!=3 || args[1]!="--spec" { return Err("use --spec ADJUDICATE.json".into()); }
    let spec:Value=serde_json::from_slice(&fs::read(&args[2])?)?;
    let out=PathBuf::from(s(&spec,"output")?);
    if out.exists(){return Err("new output directory required".into());}

    let model_bytes=read_sealed(&spec,"model")?;
    let model:Value=serde_json::from_slice(&model_bytes)?;
    let head:Head=serde_json::from_value(model["head"].clone())?;
    let transform:CropTransform=model.get("crop_transform")
        .map(|v|serde_json::from_value(v.clone())).transpose()?.unwrap_or_default();
    let batch=embedding_batch_size(model.get("embedding_batch_size"))?;
    let side=model["input_size"].as_u64().ok_or("model input_size")? as usize;

    let encoder_bytes=read_sealed(&spec,"encoder")?;
    if model["encoder_sha256"]!=hash(&encoder_bytes){return Err("encoder/model mismatch".into());}
    ort::init_from(s(&spec,"onnxruntime")?).commit()?;
    let mut session=Session::builder()?
        .with_intra_threads(1)?.with_inter_threads(1)?
        .with_intra_op_spinning(false)?.with_inter_op_spinning(false)?
        .commit_from_file(s(&spec,"encoder")?)?;

    let annotations=Path::new(s(&spec,"annotations")?);
    let images=Path::new(s(&spec,"images")?);
    let reference=Path::new(s(&spec,"reference")?);
    let samples=load_samples(annotations,images,reference)?;
    let train:Vec<&Sample>=samples.iter().filter(|x|x.split=="train" && x.label!="__unknown__").collect();
    if train.is_empty(){return Err("no supervised training support".into());}

    let mut train_features=Vec::with_capacity(train.len());
    for chunk in train.chunks(batch){
        let mut prepared=Vec::with_capacity(chunk.len());
        for sample in chunk {
            prepared.push((transform.apply(&sample.crop)?,true));
        }
        train_features.extend(embeddings(&mut session,&prepared,side,false,false)?);
    }
    if train_features.len()!=train.len(){return Err("training feature count mismatch".into());}

    let anchors_doc:Value=serde_json::from_slice(&fs::read(s(&spec,"anchors")?)?)?;
    let rows=anchors_doc.as_array().ok_or("anchors array")?;
    if rows.is_empty(){return Err("no anchors".into());}

    let collection=PathBuf::from(s(&spec,"collection")?);
    let mut decisions=Vec::new();
    let mut counts=BTreeMap::<String,u64>::new();

    for row in rows {
        if row["label_source"]!="autonomous_shop_purchase_bench_consensus_v1"
            || row["human_review_required"]!=false
            || row["model_prediction_used_as_label"]!=false
            || row["training_eligible"]!=true {
            return Err("anchor provenance mismatch".into());
        }
        let label=s(row,"unit_id")?.to_owned();
        let crop_rel=s(row,"crop")?.to_owned();
        let pixel=s(row,"pixel_sha256")?.to_owned();
        let crop=load_crop(&collection.join(&crop_rel),&pixel)?;
        let feature=embeddings(&mut session,&[(transform.apply(&crop)?,true)],side,false,false)?
            .pop().ok_or("missing anchor feature")?;

        let p=head.probabilities(&feature)?;
        let mut order:Vec<_>=(0..p.len()).collect();
        order.sort_by(|&a,&b|p[b].total_cmp(&p[a]).then(a.cmp(&b)));
        let classifier=head.labels[order[0]].clone();
        let classifier_margin=p[order[0]]-p[order[1]];

        let mut class_best=HashMap::<String,f32>::new();
        let mut same_label_support=0usize;
        for (sample,vec) in train.iter().zip(&train_features) {
            let sim=cosine(&feature,vec)?;
            class_best.entry(sample.label.clone())
                .and_modify(|x|*x=x.max(sim)).or_insert(sim);
            if sample.label==label { same_label_support+=1; }
        }
        let mut ranked:Vec<_>=class_best.into_iter().collect();
        ranked.sort_by(|a,b|b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
        let retrieval_label=ranked.first().map(|x|x.0.clone());
        let retrieval_similarity=ranked.first().map(|x|x.1);
        let retrieval_second=ranked.get(1).map(|x|x.1);
        let retrieval_margin=match(retrieval_similarity.zip(retrieval_second){
            Some((a,b))=>Some(a-b), _=>None
        };
        let classifier_agrees=classifier==label;
        let retrieval_agrees=retrieval_label.as_deref()==Some(label.as_str());

        let decision=if same_label_support==0 {
            "quarantine_no_supervised_support"
        } else if classifier_agrees && retrieval_agrees {
            "supported"
        } else if classifier_agrees || retrieval_agrees {
            "mixed"
        } else {
            "quarantine_teacher_disagreement"
        };
        *counts.entry(decision.to_owned()).or_default()+=1;

        decisions.push(json!({
            "source_id":row["source_id"],
            "unit_id":label,
            "source_seconds_nominal":row["source_seconds_nominal"],
            "crop":crop_rel,
            "pixel_sha256":pixel,
            "original_label_source":row["label_source"],
            "decision":decision,
            "training_eligible":decision=="supported",
            "human_review_required":false,
            "model_prediction_used_as_label":false,
            "teachers":{
                "frozen_classifier":{
                    "label":classifier,
                    "probability_uncalibrated":p[order[0]],
                    "margin_uncalibrated":classifier_margin,
                    "agrees_with_gold":classifier_agrees
                },
                "supervised_retrieval":{
                    "label":retrieval_label,
                    "similarity":retrieval_similarity,
                    "margin":retrieval_margin,
                    "same_label_training_support":same_label_support,
                    "agrees_with_gold":retrieval_agrees
                }
            }
        }));
    }

    fs::create_dir_all(&out)?;
    fs::write(out.join("anchor-decisions.json"),serde_json::to_vec_pretty(&decisions)?)?;
    let supported:Vec<_>=decisions.iter().filter(|r|r["decision"]=="supported").cloned().collect();
    fs::write(out.join("supported-gold-anchors.json"),serde_json::to_vec_pretty(&supported)?)?;
    let summary=json!({
        "schema_version":1,
        "policy":"autonomous_gold_anchor_adjudication_v1",
        "anchors":rows.len(),
        "decision_counts":counts,
        "supported_gold_anchors":supported.len(),
        "frozen_model_sha256":hash(&model_bytes),
        "encoder_sha256":hash(&encoder_bytes),
        "supervised_training_support":train.len(),
        "human_review_required":false,
        "training_performed":false,
        "runtime_approved":false,
        "limitations":[
            "This gate does not change game-derived gold labels; it only controls whether they can train the next challenger.",
            "Classifier and retrieval share the same frozen encoder, but retrieval uses supervised exemplars rather than classifier weights.",
            "Mixed or unsupported anchors are quarantined automatically rather than sent for manual review."
        ]
    });
    fs::write(out.join("report.json"),serde_json::to_vec_pretty(&summary)?)?;
    println!("{summary}");
    Ok(())
}
fn main(){if let Err(e)=run(){eprintln!("AUTONOMOUS_GOLD_ADJUDICATION_ERROR: {e}");std::process::exit(1);}}
