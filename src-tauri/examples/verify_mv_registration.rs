//! Validate MV plugin registration on a temporary copy of the real plugin list.

use std::{fs, path::PathBuf};

struct Game {
    id: String,
    source_language: String,
    target_language: String,
    flow_mode: String,
    intermediate_language: Option<String>,
}

mod mz {
    include!(concat!(env!("CARGO_MANIFEST_DIR"), "/src/engines/rpgmaker/mz.rs"));
}

fn main() -> Result<(), String> {
    let game_root = PathBuf::from(std::env::args().nth(1).ok_or("Informe a pasta do jogo MV.")?);
    let source = game_root.join("www/js/plugins.js");
    let workspace = std::env::temp_dir().join(format!("sftranslator-mv-check-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(workspace.join("www/js/plugins")).map_err(|error| error.to_string())?;
    let outcome = (|| {
        fs::copy(&source, workspace.join("www/js/plugins.js")).map_err(|error| error.to_string())?;
        let game = Game { id: "verify-mv".into(), source_language: "en".into(), target_language: "pb".into(),
            flow_mode: "direct".into(), intermediate_language: None };
        mz::install_variant(&workspace, &game, 5002, "MV")?;
        if !mz::integration_ready(&workspace) { return Err("Plugin MV não foi registrado.".into()); }
        mz::install_variant(&workspace, &game, 5003, "MV")?;
        let registry = fs::read_to_string(workspace.join("www/js/plugins.js"))
            .map_err(|error| error.to_string())?;
        if registry.matches("// SFTranslator BEGIN").count() != 1 || !registry.contains("5003") {
            return Err("O registro duplicou o plugin ou não atualizou a porta.".into());
        }
        let backup = fs::read(workspace.join("www/js/plugins.js.sftranslator.bak"))
            .map_err(|error| error.to_string())?;
        if backup != fs::read(&source).map_err(|error| error.to_string())? {
            return Err("A cópia de segurança difere do original.".into());
        }
        println!("PASS: registro MV instalado duas vezes sem duplicação; backup preservado; jogo original intacto.");
        Ok(())
    })();
    fs::remove_dir_all(workspace).ok();
    outcome
}
