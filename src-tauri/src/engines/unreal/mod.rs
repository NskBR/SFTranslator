mod detect;
mod observer;
mod bridge;

use std::{fs, net::TcpListener, path::{Path, PathBuf}, process::Command, sync::{atomic::AtomicBool, Arc}};

use tauri::{AppHandle, Manager};

use super::{EngineAdapter, EngineMatch, EngineSession};
use crate::{models_directory, pe_architecture, session::{session_log, spawn_streaming}, EngineHealth, Game};

pub(super) struct Unreal;

impl EngineAdapter for Unreal {
    fn name(&self) -> &'static str { "Unreal" }

    fn translation_available(&self, game: &Game) -> bool {
        let selected = crate::native_game_path(Path::new(&game.executable_path));
        detect::packaged_root(&selected).is_some_and(|root| {
            matches!(root.file_name().and_then(|name| name.to_str()),
                Some("CatIslandPetrichor" | "WomanSimulator"))
        })
    }

    fn launch_path(&self, game: &Game) -> PathBuf {
        let selected = crate::native_game_path(Path::new(&game.executable_path));
        if let Some(project) = detect::packaged_root(&selected) {
            if let Some(name) = project.file_name().and_then(|name| name.to_str()) {
                if matches!(name, "CatIslandPetrichor" | "WomanSimulator") {
                    let shipping = project.join(format!("Binaries/Win64/{name}-Win64-Shipping.exe"));
                    if shipping.is_file() { return shipping; }
                }
            }
        }
        selected
    }

    fn inspect(&self, executable: &Path) -> Option<EngineMatch> {
        detect::packaged_root(executable)?;
        Some(EngineMatch {
            runtime: Some("Pacote Windows (teste)".into()),
            architecture: pe_architecture(executable),
        })
    }

    fn integration_state(&self, game: &Game) -> (bool, String) {
        let executable = crate::native_game_path(Path::new(&game.executable_path));
        let project = detect::packaged_root(&executable);
        let name = project.as_ref().and_then(|root| root.file_name()).and_then(|name| name.to_str()).unwrap_or("").to_owned();
        if !matches!(name.as_str(), "CatIslandPetrichor" | "WomanSimulator") {
            return (false, "Reconhecimento Unreal disponível; hook ainda não preparado para este jogo".into());
        }
        let installed = project.is_some_and(|root| observer::installed(&root));
        (installed, if installed {
            "Hook experimental instalado; Argos será iniciado junto com o jogo".into()
        } else {
            "Hook experimental será instalado ao iniciar o jogo".into()
        })
    }

    fn cache_directory(&self, game: &Game) -> Result<PathBuf, String> {
        bridge::cache_directory(game)
    }

    fn clear_cache(&self, game: &Game) -> Result<(), String> {
        let cache = bridge::cache_directory(game)?;
        if cache.is_dir() { fs::remove_dir_all(&cache).map_err(|error| error.to_string())?; }
        Ok(())
    }

    fn start_session(
        &self,
        app: &AppHandle,
        game: &Game,
        runtimes: &Path,
        stop_tail: Arc<AtomicBool>,
    ) -> Result<EngineSession, String> {
        let executable = crate::native_game_path(Path::new(&game.executable_path));
        let project_name = detect::packaged_root(&executable)
            .and_then(|root| root.file_name().and_then(|name| name.to_str()).map(str::to_owned));
        if !matches!(project_name.as_deref(), Some("CatIslandPetrichor" | "WomanSimulator")) {
            session_log(app, "system", "Unreal: este jogo ainda abre sem observador. A captura inicial está restrita aos jogos de teste conhecidos.");
            return Ok(EngineSession { server: None, port: None, log_tail: None, marker: None });
        }
        let launcher = runtimes.join("unity/lt.exe");
        if !launcher.is_file() {
            return Err("Servidor Argos integrado não encontrado no aplicativo.".into());
        }
        let state = app.path().app_data_dir().map_err(|error| error.to_string())?
            .join("unreal").join(&game.id);
        fs::create_dir_all(&state).map_err(|error| error.to_string())?;
        let port = TcpListener::bind("127.0.0.1:0")
            .and_then(|listener| listener.local_addr())
            .map_err(|error| format!("Não foi possível reservar porta local: {error}"))?.port();
        let config = serde_json::json!({
            "source_language": game.source_language,
            "target_language": game.target_language,
            "flow_mode": game.flow_mode,
            "intermediate_language": game.intermediate_language.as_deref().unwrap_or("en"),
            "server": {"port": port}
        });
        fs::write(state.join("unity_uat_config.json"),
            serde_json::to_vec_pretty(&config).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
        let mut command = Command::new(&launcher);
        command.arg("__server__")
            .current_dir(launcher.parent().unwrap_or(runtimes))
            .env("UAT_STATE_DIR", &state)
            .env("UAT_MODELS_DIR", models_directory(app)?)
            .env("PYTHONIOENCODING", "utf-8");
        let mut server = spawn_streaming(command, app, "servidor Unreal")?;
        let log_tail = match observer::start(app, game, runtimes, Some(port), stop_tail) {
            Ok(log_tail) => log_tail,
            Err(error) => {
                server.kill().ok();
                server.wait().ok();
                return Err(error);
            }
        };
        session_log(app, "system", format!("Unreal: Argos local {} → {} na porta {port}.",
            game.source_language.to_uppercase(), game.target_language.to_uppercase()));
        Ok(EngineSession { server: Some(server), port: Some(port), log_tail: Some(log_tail), marker: None })
    }

    fn health(&self, runtimes: Option<&Path>, models_present: bool) -> EngineHealth {
        EngineHealth {
            engine: self.name().into(),
            source_found: true,
            runtime_found: runtimes.is_some_and(|root| root.join("unreal/ue4ss/UE4SS.dll").is_file()
                && root.join("unity/lt.exe").is_file()),
            model_found: models_present,
            development: true,
            details: "Tradução UMG experimental para CatIslandPetrichor e Woman Simulator (UE 5.6), ainda pendente de validação visual no Woman Simulator. Outros títulos Unreal permanecem sem hook.".into(),
        }
    }

    fn runtime_ready(&self, runtimes: &Path) -> bool {
        runtimes.join("unreal/ue4ss/UE4SS.dll").is_file() && runtimes.join("unity/lt.exe").is_file()
    }
}
