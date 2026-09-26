use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::{atomic::AtomicBool, Arc},
};
use tauri::AppHandle;

use super::{EngineAdapter, EngineMatch, EngineSession};
use crate::session::{
    session_log, spawn_streaming, tail_translation_log, update_integration_record,
};
use crate::{
    game_root, models_directory, native_game_path, pe_architecture, renpy_cache_pair, EngineHealth,
    Game,
};

pub(super) struct Renpy;

fn contains_files(dir: &Path, extensions: &[&str]) -> bool {
    let Ok(entries) = fs::read_dir(dir) else {
        return false;
    };
    entries.flatten().any(|entry| {
        let path = entry.path();
        path.is_file()
            && path
                .extension()
                .and_then(|value| value.to_str())
                .is_some_and(|value| {
                    extensions
                        .iter()
                        .any(|extension| value.eq_ignore_ascii_case(extension))
                })
    })
}

fn copy_hook_tree(source: &Path, destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;
    for entry in fs::read_dir(source).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let path = entry.path();
        let name = entry.file_name();
        let lowered = name.to_string_lossy().to_ascii_lowercase();
        if matches!(
            lowered.as_str(),
            "__pycache__"
                | ".lt-venv"
                | "ualogs"
                | "caches"
                | "uat_config.json"
                | "uat_session.active"
        ) {
            continue;
        }
        let target = destination.join(&name);
        if path.is_dir() {
            copy_hook_tree(&path, &target)?;
        } else {
            fs::copy(&path, &target)
                .map_err(|error| format!("Falha ao copiar {}: {error}", path.display()))?;
        }
    }
    Ok(())
}

pub(crate) fn copy_legacy_models(source: &Path, destination: &Path) -> Result<(), String> {
    copy_hook_tree(source, destination)
}

fn install_hook(engine_root: &Path, game: &Game, app: &AppHandle) -> Result<(), String> {
    let root = game_root(game)?;
    session_log(
        app,
        "system",
        "Motor identificado: Ren'Py. Selecionando hook compatível pela versão do Python interno.",
    );
    copy_hook_tree(&engine_root.join("uat"), &root.join("uat"))?;
    let hook_source = engine_root.join("game/uat_hook.rpy");
    let hook_destination = root.join("game/uat_hook.rpy");
    if hook_destination.is_file() {
        let backup = root.join("game/uat_hook.rpy.sftranslator.bak");
        if !backup.exists() {
            fs::copy(&hook_destination, &backup).map_err(|error| error.to_string())?;
        }
    }
    fs::copy(&hook_source, &hook_destination)
        .map_err(|error| format!("Falha ao instalar o hook Ren'Py: {error}"))?;

    let config_path = root.join("uat/uat_config.json");
    let template_path = engine_root.join("uat/uat_config.json");
    let mut config: serde_json::Value = fs::read(&config_path)
        .ok()
        .or_else(|| fs::read(template_path).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    config["provider"] = serde_json::json!("local");
    config["show_console"] = serde_json::json!(false);
    let flow_is_unchanged = config["source_language"].as_str()
        == Some(game.source_language.as_str())
        && config["target_language"].as_str() == Some(game.target_language.as_str());
    config["source_language"] = serde_json::json!(game.source_language);
    config["target_language"] = serde_json::json!(game.target_language);
    config["flow_mode"] = serde_json::json!(game.flow_mode);
    config["intermediate_language"] = serde_json::json!(game.intermediate_language);
    let cache_pair = renpy_cache_pair(game);
    fs::create_dir_all(root.join("uat/caches")).map_err(|error| error.to_string())?;
    if flow_is_unchanged {
        for (config_key, legacy_name, new_name) in [
            (
                "cache_file",
                "uat_cache.json",
                format!("uat_cache_{cache_pair}.json"),
            ),
            (
                "words_file",
                "uat_words.json",
                format!("uat_words_{cache_pair}.json"),
            ),
        ] {
            if config[config_key].as_str() == Some(legacy_name) {
                let legacy_path = root.join("uat").join(legacy_name);
                let new_path = root.join("uat/caches").join(new_name);
                if legacy_path.is_file() && !new_path.exists() {
                    fs::rename(legacy_path, new_path).map_err(|error| error.to_string())?;
                }
            }
        }
    }
    config["cache_file"] = serde_json::json!(format!("caches/uat_cache_{cache_pair}.json"));
    config["words_file"] = serde_json::json!(format!("caches/uat_words_{cache_pair}.json"));
    if !config["local"].is_object() {
        config["local"] = serde_json::json!({});
    }
    config["local"]["endpoint"] = serde_json::json!("http://127.0.0.1:5000/translate");
    fs::write(
        &config_path,
        serde_json::to_vec_pretty(&config).map_err(|error| error.to_string())?,
    )
    .map_err(|error| format!("Falha ao configurar o hook Ren'Py: {error}"))?;
    session_log(
        app,
        "system",
        "Hook moderno e legado instalados dentro da pasta do jogo.",
    );
    Ok(())
}

impl EngineAdapter for Renpy {
    fn name(&self) -> &'static str {
        "Ren'Py"
    }

    fn inspect(&self, executable: &Path) -> Option<EngineMatch> {
        let root = executable.parent()?;
        let game = root.join("game");
        if root.join("renpy").is_dir()
            || (game.is_dir() && contains_files(&game, &["rpy", "rpyc", "rpa"]))
        {
            Some(EngineMatch {
                runtime: Some("Ren'Py".into()),
                architecture: pe_architecture(executable),
            })
        } else {
            None
        }
    }

    fn integration_state(&self, game: &Game) -> (bool, String) {
        let executable = native_game_path(Path::new(&game.executable_path));
        let root = executable.parent().unwrap_or(Path::new("."));
        let ready =
            root.join("game/uat_hook.rpy").is_file() && root.join("uat/uat_hook.py").is_file();
        if ready {
            (true, "Hook Ren'Py instalado na pasta do jogo".into())
        } else {
            (false, "Hook compatível será instalado ao iniciar".into())
        }
    }

    fn cache_directory(&self, game: &Game) -> Result<PathBuf, String> {
        Ok(game_root(game)?.join("uat/caches"))
    }

    fn clear_cache(&self, game: &Game) -> Result<(), String> {
        let directory = self.cache_directory(game)?;
        let pair = renpy_cache_pair(game);
        for file in [
            directory.join(format!("uat_cache_{pair}.json")),
            directory.join(format!("uat_words_{pair}.json")),
        ] {
            if file.is_file() {
                fs::remove_file(file).map_err(|error| error.to_string())?;
            }
        }
        Ok(())
    }

    fn start_session(
        &self,
        app: &AppHandle,
        game: &Game,
        runtimes: &Path,
        stop_tail: Arc<AtomicBool>,
    ) -> Result<EngineSession, String> {
        let engine_root = runtimes.join("renpy");
        let launcher = engine_root.join("lt.exe");
        if !launcher.is_file() {
            return Err(format!(
                "Runtime Ren'Py não encontrado em {}",
                launcher.display()
            ));
        }
        let root = game_root(game)?;
        install_hook(&engine_root, game, app)?;
        update_integration_record(app, &game.id);
        let mut server = Command::new(&launcher);
        server
            .arg("__server__")
            .current_dir(root.join("uat"))
            .env("UAT_GAME_DIR", &root)
            .env("UAT_MODELS_DIR", models_directory(app)?)
            .env("PYTHONIOENCODING", "utf-8");
        let server = spawn_streaming(server, app, "servidor Ren'Py")?;
        let log_tail =
            tail_translation_log(app.clone(), root.join("uat/UAlogs/uat_log.txt"), stop_tail);
        Ok(EngineSession {
            server: Some(server),
            port: Some(5000),
            log_tail: Some(log_tail),
            marker: Some(root.join("uat/uat_session.active")),
        })
    }

    fn health(&self, runtimes: Option<&Path>, models_present: bool) -> EngineHealth {
        let root = runtimes.map(|path| path.join("renpy"));
        EngineHealth {
            engine: self.name().into(),
            source_found: root
                .as_ref()
                .is_some_and(|path| path.join("uat/uat_hook.py").is_file()),
            runtime_found: root
                .as_ref()
                .is_some_and(|path| path.join("lt.exe").is_file()),
            model_found: models_present,
            development: false,
            details: "Hook moderno e legado; servidor local LibreTranslate/Argos.".into(),
        }
    }

    fn runtime_ready(&self, runtimes: &Path) -> bool {
        runtimes.join("renpy/lt.exe").is_file()
    }
}
