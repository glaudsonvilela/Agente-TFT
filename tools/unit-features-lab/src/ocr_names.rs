//! Catalog-backed OCR name matching. Generic seasonal names retain all forms.
use crate::Result;
use serde_json::Value;
use std::collections::BTreeMap;

fn canonical(s: &str) -> String {
    s.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}
fn id_alias(id: &str) -> Option<String> {
    let mut s = id
        .strip_prefix("DA_18_")
        .or_else(|| id.strip_prefix("DA_"))
        .unwrap_or(id)
        .replace("18", "");
    for suffix in ["_AD", "_AP"] {
        if let Some(v) = s.strip_suffix(suffix) {
            s = v.to_owned();
        }
    }
    s = s.replace('_', " ");
    let mut out = String::new();
    let mut previous_lower = false;
    for ch in s.chars() {
        if ch.is_ascii_uppercase() && previous_lower {
            out.push(' ');
        }
        out.push(ch);
        previous_lower = ch.is_ascii_lowercase();
    }
    let out = out.split_whitespace().collect::<Vec<_>>().join(" ");
    (!out.is_empty()).then_some(out)
}

fn extra_aliases(id: &str) -> &'static [&'static str] {
    match id {
        "DA_18_ElderDragon" => &["Elder Dragon"],
        "DA_18_Lux_Coven" => &["Lux Coven"],
        "DA_18_Lux_Elderwood" => &["Lux Elderwood"],
        "DA_18_Lux_Fae" => &["Lux Fae"],
        "DA_18_Lux_Inferno" => &["Lux Inferno"],
        "DA_18_Lux_Moonbeam" => &["Lux Moonbeam", "Lux Lunar"],
        "DA_18_Lux_Primal" => &["Lux Primal"],
        "DA_18_Lux_Sunbeam" => &["Lux Sunbeam", "Lux Solar"],
        "DA_Lux18_Blackthorn" => &["Lux Blackthorn"],
        "DA_Lux18_Blossom" => &["Lux Blossom"],
        _ => &[],
    }
}

pub type Names = BTreeMap<String, Vec<String>>;
pub fn name_indexes(catalog: &Value) -> Result<(Names, Names)> {
    let mut exact = Names::new();
    let mut families = Names::new();
    for unit in catalog["entries"].as_array().ok_or("catalog entries")? {
        let name = unit["name"].as_str().ok_or("name")?;
        let id = unit["id"].as_str().ok_or("id")?;
        exact.entry(canonical(name)).or_default().push(id.into());
        if let Some(alias) = id_alias(id) {
            exact.entry(canonical(&alias)).or_default().push(id.into());
        }
        for alias in extra_aliases(id) {
            exact.entry(canonical(alias)).or_default().push(id.into());
        }
        let root = name.split('(').next().ok_or("name root")?.trim();
        families.entry(canonical(root)).or_default().push(id.into());
    }
    for ids in exact.values_mut() {
        ids.sort();
        ids.dedup();
    }
    for ids in families.values_mut() {
        ids.sort();
        ids.dedup();
    }
    Ok((exact, families))
}

pub fn match_name(
    words: &[(String, f32)],
    exact: &Names,
    families: &Names,
) -> Option<(Vec<String>, f32)> {
    for n in (1..=words.len()).rev() {
        if words[..n].iter().any(|(_, c)| *c < 70. || !c.is_finite())
            || words[n..]
                .iter()
                .any(|(s, _)| !s.chars().all(|c| c.is_ascii_digit()))
        {
            continue;
        }
        let name = canonical(
            &words[..n]
                .iter()
                .map(|(s, _)| s.as_str())
                .collect::<Vec<_>>()
                .join(" "),
        );
        let Some(ids) = exact.get(&name) else {
            continue;
        };
        // A generic name such as Lux cannot identify its seasonal form even
        // when the catalog happens to contain one entry literally named Lux.
        let ids = families.get(&name).unwrap_or(ids);
        let confidence = words[..n].iter().map(|(_, c)| *c).fold(100., f32::min);
        return Some((ids.clone(), confidence));
    }
    None
}


#[cfg(test)]
mod alias_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn id_aliases_support_english_ui_without_collapsing_lux_forms() {
        let catalog = json!({"entries":[
            {"id":"DA_18_ElderDragon","name":"Dragão Ancião"},
            {"id":"DA_18_Lux_Sunbeam","name":"Lux (Solar)"},
            {"id":"DA_18_Lux_Elderwood","name":"Lux (Sabugueiro)"},
            {"id":"DA_Lux18_Base","name":"Lux"},
            {"id":"DA_18_MasterYi_AD","name":"Master Yi"}
        ]});
        let (exact, families) = name_indexes(&catalog).unwrap();
        let words = |s: &str| s.split_whitespace().map(|s|(s.to_owned(),99.)).collect::<Vec<_>>();
        assert_eq!(match_name(&words("Elder Dragon"), &exact, &families).unwrap().0, vec!["DA_18_ElderDragon"]);
        assert_eq!(match_name(&words("Lux Solar"), &exact, &families).unwrap().0, vec!["DA_18_Lux_Sunbeam"]);
        assert_eq!(match_name(&words("Lux Elderwood"), &exact, &families).unwrap().0, vec!["DA_18_Lux_Elderwood"]);
        assert_eq!(match_name(&words("Master Yi"), &exact, &families).unwrap().0, vec!["DA_18_MasterYi_AD"]);
        assert!(match_name(&words("Lux"), &exact, &families).unwrap().0.len() > 1);
    }
}
