mod mv;
mod mz;

use std::{
    fs,
    io::Read,
    net::TcpListener,
    path::{Path, PathBuf},
    process::Command,
    sync::{atomic::AtomicBool, Arc},
};
use tauri::{AppHandle, Manager};

use super::{EngineAdapter, EngineMatch, EngineSession};
use crate::{
    game_root, models_directory, pe_architecture,
    session::{session_log, spawn_streaming, update_integration_record},
    EngineHealth, Game,
};

pub(super) struct RpgMaker;

pub(super) fn cache_path(game: &Game) -> Result<PathBuf, String> {
    Ok(mz::cache_path(&game_root(game)?, game))
}

fn detect_family(root: &Path, executable: &Path) -> Option<&'static str> {
    let web = if root.join("www/js").is_dir() {
        root.join("www")
    } else {
        root.to_path_buf()
    };
    if web.join("js/rmmz_core.js").is_file() && web.join("js/rmmz_windows.js").is_file() {
        return Some("MZ");
    }
    if web.join("js/rpg_core.js").is_file() && web.join("js/rpg_windows.js").is_file() {
        return Some("MV");
    }
    if root.join("Data/Actors.rvdata2").is_file() {
        return Some("VX Ace");
    }
    if root.join("Data/Actors.rvdata").is_file() {
        return Some("VX");
    }
    if root.join("Data/Actors.rxdata").is_file() {
        return Some("XP");
    }
    if root.join("RPG_RT.ldb").is_file()
        && root.join("RPG_RT.lmt").is_file()
        && executable
            .file_name()
            .is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("RPG_RT.exe"))
    {
        return Some("2000/2003");
    }
    None
}

fn unite_runtime(root: &Path, executable: &Path) -> Option<&'static str> {
    let stem = executable.file_stem()?.to_str()?;
    let data = root.join(format!("{stem}_Data"));
    if !root.join("UnityPlayer.dll").is_file() || !data.is_dir() { return None }
    let managed = data.join("Managed");
    let named_assembly = fs::read_dir(&managed).ok().into_iter().flatten().flatten().any(|entry| {
        entry.file_name().to_string_lossy().to_ascii_lowercase().starts_with("rpgmaker.codebase")
    });
    let il2cpp = root.join("GameAssembly.dll").is_file();
    let marker_found = named_assembly || if il2cpp {
        file_contains_marker(&data.join("il2cpp_data/Metadata/global-metadata.dat"), b"RPGMaker.Codebase")
    } else {
        file_contains_marker(&managed.join("Assembly-CSharp.dll"), b"RPGMaker.Codebase")
    };
    if !marker_found { return None }
    Some(if il2cpp { "Unite IL2CPP" } else { "Unite Mono" })
}

fn file_contains_marker(path: &Path, marker: &[u8]) -> bool {
    let Ok(mut file) = fs::File::open(path) else { return false };
    let mut buffer = vec![0; 64 * 1024 + marker.len()];
    let mut prefix = 0;
    loop {
        let Ok(count) = file.read(&mut buffer[prefix..]) else { return false };
        let total = prefix + count;
        if buffer[..total].windows(marker.len()).any(|part| part == marker) { return true }
        if count == 0 { return false }
        prefix = marker.len().saturating_sub(1).min(total);
        let start = total - prefix;
        buffer.copy_within(start..start + prefix, 0);
    }
}

fn unity_game(game: &Game) -> Game {
    let mut normalized = game.clone();
    normalized.runtime = Some(if game.runtime.as_deref() == Some("Unite IL2CPP") { "IL2CPP" } else { "Mono" }.into());
    normalized
}

impl EngineAdapter for RpgMaker {
    fn name(&self) -> &'static str {
        "RPG Maker"
    }

    fn translation_available(&self, game: &Game) -> bool {
        matches!(game.runtime.as_deref(), Some("MV" | "MZ" | "Unite Mono" | "Unite IL2CPP"))
    }

    fn inspect(&self, executable: &Path) -> Option<EngineMatch> {
        let root = executable.parent()?;
        let family = unite_runtime(root, executable).or_else(|| detect_family(root, executable))?;
        Some(EngineMatch {
            runtime: Some(family.into()),
            architecture: pe_architecture(executable),
        })
    }

    fn integration_state(&self, game: &Game) -> (bool, String) {
        if matches!(game.runtime.as_deref(), Some("Unite Mono" | "Unite IL2CPP")) {
            let (ready, detail) = super::UNITY.integration_state(&unity_game(game));
            return (ready, format!("RPG Maker Unite: {detail}"));
        }
        if let Some(family @ ("MV" | "MZ")) = game.runtime.as_deref() {
            let ready = game_root(game).is_ok_and(|root| if family == "MV" {
                mv::integration_ready(&root)
            } else {
                mz::integration_ready(&root)
            });
            return if ready {
                (true, format!("Plugin experimental {family} instalado no jogo"))
            } else {
                (false, format!("Plugin experimental {family} será instalado ao iniciar"))
            };
        }
        (
            false,
            "Em desenvolvimento inicial: tradução ainda não integrada".into(),
        )
    }

    fn cache_directory(&self, game: &Game) -> Result<PathBuf, String> {
        if matches!(game.runtime.as_deref(), Some("Unite Mono" | "Unite IL2CPP")) {
            return super::UNITY.cache_directory(&unity_game(game));
        }
        cache_path(game)
    }

    fn clear_cache(&self, game: &Game) -> Result<(), String> {
        if matches!(game.runtime.as_deref(), Some("Unite Mono" | "Unite IL2CPP")) {
            return super::UNITY.clear_cache(&unity_game(game));
        }
        let directory = cache_path(game)?;
        if directory.is_dir() {
            fs::remove_dir_all(&directory).map_err(|error| error.to_string())?;
        }
        fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
        fs::write(directory.join(".generation"), uuid::Uuid::new_v4().to_string())
            .map_err(|error| error.to_string())
    }

    fn start_session(
        &self,
        app: &AppHandle,
        game: &Game,
        runtimes: &Path,
        stop_tail: Arc<AtomicBool>,
    ) -> Result<EngineSession, String> {
        if matches!(game.runtime.as_deref(), Some("Unite Mono" | "Unite IL2CPP")) {
            session_log(app, "system", "RPG Maker Unite detectado. Usando BepInEx/XUnity com o servidor Argos local.");
            return super::UNITY.start_session(app, &unity_game(game), runtimes, stop_tail);
        }
        if self.translation_available(game) {
            let launcher = runtimes.join("unity/lt.exe");
            if !launcher.is_file() {
                return Err("Servidor Argos integrado não encontrado no aplicativo.".into());
            }
            let root = game_root(game)?;
            let state = app
                .path()
                .app_data_dir()
                .map_err(|error| error.to_string())?
                .join("rpgmaker")
                .join(&game.id);
            fs::create_dir_all(&state).map_err(|error| error.to_string())?;
            let port = TcpListener::bind("127.0.0.1:0")
                .and_then(|listener| listener.local_addr())
                .map_err(|error| format!("Não foi possível reservar porta local: {error}"))?
                .port();
            let config = serde_json::json!({
                "source_language": game.source_language,
                "target_language": game.target_language,
                "flow_mode": game.flow_mode,
                "intermediate_language": game.intermediate_language.as_deref().unwrap_or("en"),
                "server": {"port": port}
            });
            fs::write(
                state.join("unity_uat_config.json"),
                serde_json::to_vec_pretty(&config).map_err(|error| error.to_string())?,
            )
            .map_err(|error| error.to_string())?;
            let family = game.runtime.as_deref().unwrap_or("MZ");
            if family == "MV" {
                mv::install(&root, game, port)?;
            } else {
                mz::install(&root, game, port)?;
            }
            let installed = if family == "MV" { mv::integration_ready(&root) } else { mz::integration_ready(&root) };
            if !installed {
                return Err(format!("O plugin RPG Maker {family} não ficou ativo em js/plugins.js. Confira permissões e antivírus antes de abrir o jogo."));
            }
            update_integration_record(app, &game.id);
            session_log(
                app,
                "system",
                format!(
                    "Plugin RPG Maker {family} configurado para {} → {}. Porta local {port}.",
                    game.source_language.to_uppercase(),
                    game.target_language.to_uppercase()
                ),
            );
            let mut command = Command::new(&launcher);
            command
                .arg("__server__")
                .current_dir(launcher.parent().unwrap_or(runtimes))
                .env("UAT_GAME_DIR", &root)
                .env("UAT_STATE_DIR", &state)
                .env("UAT_MODELS_DIR", models_directory(app)?)
                .env("PYTHONIOENCODING", "utf-8");
            return Ok(EngineSession {
                server: Some(spawn_streaming(command, app, &format!("servidor RPG Maker {family}"))?),
                port: Some(port),
                log_tail: None,
                marker: None,
            });
        }
        session_log(
            app,
            "system",
            format!(
                "RPG Maker {}: iniciando jogo para teste de reconhecimento.",
                game.runtime.as_deref().unwrap_or("não identificado")
            ),
        );
        session_log(app, "system", "Motor em desenvolvimento inicial. Esta sessão não instala hook nem traduz o texto do jogo.");
        Ok(EngineSession {
            server: None,
            port: None,
            log_tail: None,
            marker: None,
        })
    }

    fn health(&self, runtimes: Option<&Path>, models_present: bool) -> EngineHealth {
        EngineHealth {
            engine: self.name().into(),
            source_found: true,
            runtime_found: runtimes.is_some_and(|root| root.join("unity/lt.exe").is_file()),
            model_found: models_present,
            development: true,
            details: "MV/MZ usam plugin JavaScript; Unite usa BepInEx/XUnity quando identificado. 95, 2000/2003 e RGSS ainda não têm hook de tradução.".into(),
        }
    }

    fn runtime_ready(&self, runtimes: &Path) -> bool {
        runtimes.join("unity/lt.exe").is_file()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn detects_mz_fixture_and_rejects_unrelated_executable() {
        let root = std::env::temp_dir().join(format!("sftranslator-rpgm-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("js")).unwrap();
        fs::write(root.join("Game.exe"), b"fixture").unwrap();
        assert!(detect_family(&root, &root.join("Game.exe")).is_none());
        fs::write(root.join("js/rmmz_core.js"), b"fixture").unwrap();
        fs::write(root.join("js/rmmz_windows.js"), b"fixture").unwrap();
        assert_eq!(detect_family(&root, &root.join("Game.exe")), Some("MZ"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn detects_unite_without_classifying_every_unity_game_as_rpg_maker() {
        let root = std::env::temp_dir().join(format!("sftranslator-unite-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("Game_Data/Managed")).unwrap();
        fs::write(root.join("Game.exe"), b"fixture").unwrap();
        fs::write(root.join("UnityPlayer.dll"), b"fixture").unwrap();
        assert_eq!(unite_runtime(&root, &root.join("Game.exe")), None);
        fs::write(root.join("Game_Data/Managed/RPGMaker.Codebase.Runtime.dll"), b"fixture").unwrap();
        assert_eq!(unite_runtime(&root, &root.join("Game.exe")), Some("Unite Mono"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn scans_unite_marker_across_buffer_boundary() {
        let path = std::env::temp_dir().join(format!("sftranslator-unite-marker-{}", uuid::Uuid::new_v4()));
        let mut content = vec![b'x'; 64 * 1024 - 4];
        content.extend_from_slice(b"RPGMaker.Codebase");
        fs::write(&path, content).unwrap();
        assert!(file_contains_marker(&path, b"RPGMaker.Codebase"));
        fs::remove_file(path).unwrap();
    }
}
