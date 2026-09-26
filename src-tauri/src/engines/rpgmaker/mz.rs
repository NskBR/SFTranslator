use std::{
    fs,
    path::{Path, PathBuf},
};

use crate::Game;

const PLUGIN_SOURCE: &str = include_str!("../../../../engines/rpgmaker/js/SFTranslator.js");
const PLUGIN_MARKER: &str = "SFTRANSLATOR_RPGMAKER_JS_V1";
const LEGACY_MARKER: &str = "SFTRANSLATOR_RPGMAKER_MZ_V1";
const BEGIN: &str = "\n// SFTranslator BEGIN\n";
const END: &str = "\n// SFTranslator END\n";

fn cache_component(value: &str) -> String {
    let normalized: String = value.trim().chars().map(|character| {
        if character.is_ascii_alphanumeric() { character.to_ascii_lowercase() } else { '_' }
    }).collect();
    if normalized.is_empty() { "unknown".into() } else { normalized }
}

pub(super) fn cache_path(root: &Path, game: &Game) -> PathBuf {
    let source = cache_component(&game.source_language);
    let target = cache_component(&game.target_language);
    let flow = if game.flow_mode == "chain" {
        format!("{source}_en_{target}")
    } else {
        format!("{source}_{target}")
    };
    root.join("uat-rpgmaker/cache").join(flow)
}

fn web_root(root: &Path) -> PathBuf {
    if root.join("www/js").is_dir() {
        root.join("www")
    } else {
        root.to_path_buf()
    }
}

fn paths(root: &Path) -> (PathBuf, PathBuf) {
    let web = web_root(root);
    (
        web.join("js/plugins.js"),
        web.join("js/plugins/SFTranslator.js"),
    )
}

pub(super) fn integration_ready(root: &Path) -> bool {
    let (registry, plugin) = paths(root);
    fs::read_to_string(registry).is_ok_and(|text| {
        let Some(start) = text.find(BEGIN) else { return false };
        let Some(end_offset) = text[start + BEGIN.len()..].find(END) else { return false };
        let entry = text[start + BEGIN.len()..start + BEGIN.len() + end_offset].trim();
        let Some(json) = entry.strip_prefix("$plugins.push(").and_then(|value| value.strip_suffix(");")) else { return false };
        serde_json::from_str::<serde_json::Value>(json).is_ok_and(|value| {
            value["name"] == "SFTranslator" && value["status"] == true
        })
    })
        && fs::read_to_string(plugin)
            .is_ok_and(|text| text.contains(PLUGIN_MARKER) || text.contains(LEGACY_MARKER))
}

pub(super) fn install(root: &Path, game: &Game, port: u16) -> Result<(), String> {
    install_variant(root, game, port, "MZ")
}

pub(super) fn install_variant(root: &Path, game: &Game, port: u16, family: &str) -> Result<(), String> {
    let (registry_path, plugin_path) = paths(root);
    let registry = fs::read_to_string(&registry_path)
        .map_err(|error| format!("Não foi possível ler {}: {error}", registry_path.display()))?;
    if !registry.contains("$plugins") {
        return Err(format!("Lista de plugins {family} inválida; o jogo não foi alterado."));
    }
    if plugin_path.is_file() {
        let existing = fs::read_to_string(&plugin_path).map_err(|error| error.to_string())?;
        if !existing.contains(PLUGIN_MARKER) && !existing.contains(LEGACY_MARKER) {
            return Err(format!(
                "Já existe outro plugin com o nome SFTranslator em {}. O jogo não foi alterado.",
                plugin_path.display()
            ));
        }
    }

    let original = if let Some(start) = registry.find(BEGIN) {
        let end_offset = registry[start + BEGIN.len()..]
            .find(END)
            .ok_or("Registro anterior do SFTranslator está incompleto; o jogo não foi alterado.")?;
        let end = start + BEGIN.len() + end_offset + END.len();
        format!("{}{}", &registry[..start], &registry[end..])
    } else {
        registry.clone()
    };

    let backup = registry_path.with_file_name("plugins.js.sftranslator.bak");
    if !backup.exists() {
        fs::copy(&registry_path, &backup).map_err(|error| {
            format!(
                "Falha ao salvar cópia de {}: {error}",
                registry_path.display()
            )
        })?;
    }
    fs::create_dir_all(plugin_path.parent().ok_or("Pasta de plugins inválida")?)
        .map_err(|error| error.to_string())?;
    fs::write(&plugin_path, PLUGIN_SOURCE)
        .map_err(|error| format!("Falha ao instalar plugin {family}: {error}"))?;

    let entry = serde_json::json!({
        "name": "SFTranslator",
        "status": true,
        "description": format!("Tradução local experimental {family} do SFTranslator"),
        "parameters": {
            "gameId": game.id,
            "source": game.source_language,
            "target": game.target_language,
            "flowMode": game.flow_mode,
            "intermediate": game.intermediate_language.as_deref().unwrap_or(""),
            "port": port.to_string(),
            "cacheFile": cache_path(root, game).join("translations.json").to_string_lossy(),
            "cacheVersion": fs::read_to_string(cache_path(root, game).join(".generation"))
                .unwrap_or_else(|_| "0".into()),
        }
    });
    fs::write(
        &registry_path,
        format!("{original}{BEGIN}$plugins.push({entry});{END}"),
    )
    .map_err(|error| format!("Falha ao ativar plugin {family}: {error}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_append_keeps_original_and_creates_backup() {
        let root = std::env::temp_dir().join(format!("sftranslator-mz-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("js/plugins")).unwrap();
        fs::write(root.join("js/plugins.js"), "var $plugins = [];\n").unwrap();
        let game = Game {
            id: "test".into(),
            name: "Test".into(),
            executable_path: String::new(),
            engine: "RPG Maker".into(),
            runtime: Some("MZ".into()),
            architecture: None,
            status: String::new(),
            source_language: "ja".into(),
            target_language: "pb".into(),
            added_at: String::new(),
            last_launch: None,
            icon_data: None,
            model_installed: true,
            detected_language: None,
            language_confidence: None,
            integration_status: None,
            flow_mode: "chain".into(),
            intermediate_language: Some("en".into()),
        };
        install(&root, &game, 5002).unwrap();
        install(&root, &game, 5003).unwrap();
        let registry = fs::read_to_string(root.join("js/plugins.js")).unwrap();
        assert_eq!(registry.matches(BEGIN).count(), 1);
        assert!(registry.contains("5003"));
        assert!(registry.contains("var $plugins = [];"));
        assert_eq!(
            fs::read_to_string(root.join("js/plugins.js.sftranslator.bak")).unwrap(),
            "var $plugins = [];\n"
        );
        assert!(integration_ready(&root));
        fs::write(root.join("js/plugins.js"), registry.replace("\"status\":true", "\"status\":false")).unwrap();
        assert!(!integration_ready(&root));
        fs::remove_dir_all(root).unwrap();
    }
}
