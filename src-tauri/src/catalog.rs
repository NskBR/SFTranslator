use serde_json::Value;
use std::{collections::BTreeMap, fs, path::Path};

// Snapshot of https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json
// Bundled so a fresh installation can offer downloads without a pre-existing cache.
const BUNDLED_INDEX: &str = include_str!("../resources/argos-index.json");

pub fn pair_id(value: &Value) -> Option<String> {
    let from = value.get("from_code")?.as_str()?;
    let to = value.get("to_code")?.as_str()?;
    if from.is_empty() || to.is_empty() {
        return None;
    }
    Some(format!("{from}-{to}"))
}

pub fn load_catalog(root: &Path) -> Vec<Value> {
    let bundled: Vec<Value> =
        serde_json::from_str(BUNDLED_INDEX).expect("Bundled Argos catalog must be valid JSON");
    let local: Vec<Value> = fs::read(root.join("index.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default();
    let mut pairs = BTreeMap::new();
    for value in bundled.into_iter().chain(local) {
        if let Some(id) = pair_id(&value) {
            if value["links"].as_array().is_some_and(|links| {
                links
                    .iter()
                    .any(|link| link.as_str().is_some_and(|url| url.starts_with("https://")))
            }) {
                pairs.insert(id, value);
            }
        }
    }
    pairs.into_values().collect()
}

pub fn installed_packages(root: &Path) -> BTreeMap<String, Value> {
    fs::read_dir(root.join("packages"))
        .ok()
        .into_iter()
        .flatten()
        .flatten()
        .filter(|entry| !entry.file_name().to_string_lossy().starts_with('.'))
        .filter_map(|entry| {
            let value: Value =
                serde_json::from_slice(&fs::read(entry.path().join("metadata.json")).ok()?).ok()?;
            Some((pair_id(&value)?, value))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fresh_install_has_downloadable_flows() {
        let root = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
        let catalog = load_catalog(&root);
        assert!(catalog.len() > 50);
        assert!(catalog
            .iter()
            .any(|value| pair_id(value).as_deref() == Some("en-pt")));
        assert!(installed_packages(&root).is_empty());
    }

    #[test]
    fn corrupt_index_preserves_catalog_and_installed_packages() {
        let root = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
        let package = root.join("packages/custom");
        fs::create_dir_all(&package).unwrap();
        fs::write(root.join("index.json"), b"invalid").unwrap();
        fs::write(
            package.join("metadata.json"),
            br#"{"from_code":"xx","to_code":"yy","package_version":"1"}"#,
        )
        .unwrap();
        let staging = root.join("packages/.download-en-pt");
        fs::create_dir_all(&staging).unwrap();
        fs::write(
            staging.join("metadata.json"),
            br#"{"from_code":"en","to_code":"pt"}"#,
        )
        .unwrap();
        assert!(!load_catalog(&root).is_empty());
        let installed = installed_packages(&root);
        assert_eq!(installed.len(), 1);
        assert!(installed.contains_key("xx-yy"));
        fs::remove_dir_all(root).unwrap();
    }
}
