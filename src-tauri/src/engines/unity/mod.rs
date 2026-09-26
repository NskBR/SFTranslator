use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::{atomic::AtomicBool, Arc},
};
use tauri::AppHandle;

use super::{EngineAdapter, EngineMatch, EngineSession};
use crate::session::{run_stage, session_log, spawn_streaming, update_integration_record};
use crate::{
    game_root, models_directory, native_game_path, pe_architecture, renpy_cache_pair, EngineHealth,
    Game,
};

pub(super) struct Unity;

fn directory_contains(root: &Path, needle: &str) -> bool {
    let Ok(entries) = fs::read_dir(root) else {
        return false;
    };
    entries.flatten().any(|entry| {
        let path = entry.path();
        if path.is_dir() {
            directory_contains(&path, needle)
        } else {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.to_ascii_lowercase().contains(needle))
        }
    })
}

impl EngineAdapter for Unity {
    fn name(&self) -> &'static str {
        "Unity"
    }

    fn inspect(&self, executable: &Path) -> Option<EngineMatch> {
        let root = executable.parent()?;
        let stem = executable.file_stem()?.to_str()?;
        let unity_data = root.join(format!("{stem}_Data"));
        let any_unity_data = fs::read_dir(root)
            .ok()
            .into_iter()
            .flatten()
            .flatten()
            .any(|entry| {
                entry.path().is_dir() && entry.file_name().to_string_lossy().ends_with("_Data")
            });
        if !(unity_data.is_dir()
            || root.join("UnityPlayer.dll").is_file()
            || (root.join("GameAssembly.dll").is_file() && any_unity_data))
        {
            return None;
        }
        let runtime = if root.join("GameAssembly.dll").is_file()
            || unity_data
                .join("il2cpp_data/Metadata/global-metadata.dat")
                .is_file()
        {
            "IL2CPP"
        } else if unity_data.join("Managed/Assembly-CSharp.dll").is_file()
            || root.join("MonoBleedingEdge").is_dir()
        {
            "Mono"
        } else {
            "Desconhecido"
        };
        Some(EngineMatch {
            runtime: Some(runtime.into()),
            architecture: pe_architecture(executable),
        })
    }

    fn integration_state(&self, game: &Game) -> (bool, String) {
        let executable = native_game_path(Path::new(&game.executable_path));
        let root = executable.parent().unwrap_or(Path::new("."));
        let bep_in_ex = root.join("BepInEx");
        let ready = bep_in_ex.join("core").is_dir()
            && directory_contains(&bep_in_ex.join("plugins"), "autotranslator");
        let runtime = game.runtime.as_deref().unwrap_or("");
        if ready {
            (true, format!("BepInEx/XUnity {runtime} instalado no jogo"))
        } else {
            (
                false,
                format!("BepInEx/XUnity {runtime} será instalado ao iniciar"),
            )
        }
    }

    fn cache_directory(&self, game: &Game) -> Result<PathBuf, String> {
        let root = game_root(game)?;
        let cache = if game.flow_mode == "chain" {
            root.join("BepInEx/Translation/SFTranslator")
                .join(renpy_cache_pair(game))
        } else {
            root.join("BepInEx/Translation").join(&game.target_language)
        };
        Ok(cache.join("Text"))
    }

    fn clear_cache(&self, game: &Game) -> Result<(), String> {
        let directory = self.cache_directory(game)?;
        if directory.is_dir() {
            fs::remove_dir_all(directory).map_err(|error| error.to_string())?;
        }
        Ok(())
    }

    fn start_session(
        &self,
        app: &AppHandle,
        game: &Game,
        runtimes: &Path,
        _stop_tail: Arc<AtomicBool>,
    ) -> Result<EngineSession, String> {
        let launcher = runtimes.join("unity/lt.exe");
        if !launcher.is_file() {
            return Err(format!(
                "Runtime Unity não encontrado em {}",
                launcher.display()
            ));
        }
        let game_root = game_root(game)?;
        let universal_models = models_directory(app)?;
        session_log(
            app,
            "system",
            format!(
                "Unity detectado: {} {}.",
                game.runtime.as_deref().unwrap_or("runtime desconhecido"),
                game.architecture
                    .as_deref()
                    .unwrap_or("arquitetura desconhecida")
            ),
        );

        let (integration_ready, _) = self.integration_state(game);
        if !integration_ready {
            let mut install = Command::new(&launcher);
            install
                .arg("install")
                .arg(game.runtime.as_deref().unwrap_or("Mono"))
                .arg(game.architecture.as_deref().unwrap_or("x64"))
                .current_dir(launcher.parent().unwrap_or(runtimes))
                .env("UAT_GAME_DIR", &game_root)
                .env("UAT_STATE_DIR", game_root.join("uat-unity"))
                .env("UAT_MODELS_DIR", &universal_models)
                .env("PYTHONIOENCODING", "utf-8");
            run_stage(install, app, "Instalando BepInEx e XUnity dentro do jogo")?;
        } else {
            session_log(
                app,
                "system",
                "BepInEx e XUnity já estão instalados e compatíveis.",
            );
        }

        let mut config = Command::new(&launcher);
        config
            .arg("config")
            .arg(&game.source_language)
            .arg(&game.target_language)
            .arg(&game.flow_mode)
            .arg(game.intermediate_language.as_deref().unwrap_or(""))
            .current_dir(launcher.parent().unwrap_or(runtimes))
            .env("UAT_GAME_DIR", &game_root)
            .env("UAT_STATE_DIR", game_root.join("uat-unity"))
            .env("UAT_MODELS_DIR", &universal_models)
            .env("PYTHONIOENCODING", "utf-8");
        run_stage(config, app, "Configurando XUnity e o fluxo universal")?;
        update_integration_record(app, &game.id);

        let mut server = Command::new(&launcher);
        server
            .arg("server")
            .current_dir(launcher.parent().unwrap_or(runtimes))
            .env("UAT_GAME_DIR", &game_root)
            .env("UAT_STATE_DIR", game_root.join("uat-unity"))
            .env("UAT_MODELS_DIR", &universal_models)
            .env("PYTHONIOENCODING", "utf-8");
        Ok(EngineSession {
            server: Some(spawn_streaming(server, app, "servidor Unity")?),
            port: Some(5001),
            log_tail: None,
            marker: None,
        })
    }

    fn health(&self, runtimes: Option<&Path>, models_present: bool) -> EngineHealth {
        let root = runtimes.map(|path| path.join("unity"));
        let ready = root
            .as_ref()
            .is_some_and(|path| path.join("lt.exe").is_file());
        EngineHealth {
            engine: self.name().into(),
            source_found: ready,
            runtime_found: ready,
            model_found: models_present,
            development: false,
            details: "Instalador BepInEx/XUnity para Mono e IL2CPP usando a biblioteca universal."
                .into(),
        }
    }

    fn runtime_ready(&self, runtimes: &Path) -> bool {
        runtimes.join("unity/lt.exe").is_file()
    }
}
