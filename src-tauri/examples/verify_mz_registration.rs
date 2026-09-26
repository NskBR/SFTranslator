//! Exercise the actual MZ registration code against a game's plugin list without editing the game.

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

    pub fn verify(root: &std::path::Path, game: &crate::Game) -> Result<(), String> {
        install(root, game, 5002)?;
        if !integration_ready(root) { return Err("Plugin não foi registrado.".into()); }
        install(root, game, 5003)?;
        let registry = std::fs::read_to_string(root.join("js/plugins.js"))
            .map_err(|error| error.to_string())?;
        if registry.matches("// SFTranslator BEGIN").count() != 1 || !registry.contains("5003") {
            return Err("O registro duplicou o plugin ou não atualizou a porta.".into());
        }
        Ok(())
    }
}

fn main() -> Result<(), String> {
    let game_root = PathBuf::from(std::env::args().nth(1).ok_or("Informe a pasta do jogo MZ.")?);
    let source = game_root.join("js/plugins.js");
    let workspace = std::env::temp_dir().join(format!("sftranslator-mz-check-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(workspace.join("js/plugins")).map_err(|error| error.to_string())?;
    let outcome = (|| {
        fs::copy(source, workspace.join("js/plugins.js")).map_err(|error| error.to_string())?;
        let game = Game { id: "verify-mz".into(), source_language: "ja".into(), target_language: "pb".into(),
            flow_mode: "chain".into(), intermediate_language: Some("en".into()) };
        mz::verify(&workspace, &game)?;
        let backup = fs::read(workspace.join("js/plugins.js.sftranslator.bak"))
            .map_err(|error| error.to_string())?;
        let original = fs::read(game_root.join("js/plugins.js")).map_err(|error| error.to_string())?;
        if backup != original { return Err("A cópia de segurança difere do original.".into()); }
        println!("PASS: registro MZ instalado duas vezes sem duplicação; backup preservado; jogo original intacto.");
        Ok(())
    })();
    fs::remove_dir_all(workspace).ok();
    outcome
}
