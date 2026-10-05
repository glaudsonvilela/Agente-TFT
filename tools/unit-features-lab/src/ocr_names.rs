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
pub type Names = BTreeMap<String, Vec<String>>;
pub fn name_indexes(catalog: &Value) -> Result<(Names, Names)> {
    let mut exact = Names::new();
    let mut families = Names::new();
    for unit in catalog["entries"].as_array().ok_or("catalog entries")? {
        let name = unit["name"].as_str().ok_or("name")?;
        let id = unit["id"].as_str().ok_or("id")?;
        exact.entry(canonical(name)).or_default().push(id.into());
        let root = name.split('(').next().ok_or("name root")?.trim();
        families.entry(canonical(root)).or_default().push(id.into());
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
