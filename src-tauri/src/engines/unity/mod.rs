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

fn installed_integration(root: &Path, runtime: &str) -> (bool, String) {
    let core = root.join("BepInEx/core");
    let xunity = root.join("BepInEx/plugins/XUnity.AutoTranslator");
    let mono5 = core.join("BepInEx.dll").is_file();
    let mono6 = core.join("BepInEx.Unity.Mono.dll").is_file();
    let il2cpp = core.join("BepInEx.Unity.IL2CPP.dll").is_file();
    let xunity_core = xunity.join("XUnity.AutoTranslator.Plugin.Core.dll").is_file()
        && xunity.join("Translators/CustomTranslate.dll").is_file()
        && core.join("XUnity.Common.dll").is_file();
    let xunity_mono = xunity.join("XUnity.AutoTranslator.Plugin.BepInEx.dll").is_file();
    let xunity_il2cpp = xunity.join("XUnity.AutoTranslator.Plugin.BepInEx-IL2CPP.dll").is_file();
    let redirector = root.join("BepInEx/plugins/XUnity.ResourceRedirector");
    let compatible = match runtime {
        "Mono" => mono5 && !mono6 && !il2cpp && xunity_core && xunity_mono && !xunity_il2cpp
            && redirector.join("XUnity.ResourceRedirector.BepInEx.dll").is_file(),
        "IL2CPP" => il2cpp && !mono5 && !mono6 && xunity_core && xunity_il2cpp && !xunity_mono
            && redirector.join("XUnity.ResourceRedirector.BepInEx-IL2CPP.dll").is_file(),
        _ => false,
    };
    if compatible {
        return (true, format!("BepInEx/XUnity {runtime} encontrado; arquivos existentes serão preservados"));
    }
    if mono6 && runtime == "Mono" {
        return (false, "BepInEx 6 Mono detectado; pacote XUnity atual requer BepInEx 5. Instalação automática bloqueada".into());
    }
    if (il2cpp && runtime == "Mono") || ((mono5 || mono6) && runtime == "IL2CPP") {
        return (false, format!("BepInEx existente incompatível com o runtime {runtime}; instalação automática bloqueada"));
    }
    if mono5 || mono6 || il2cpp {
        return (false, format!("BepInEx existente detectado; XUnity {runtime} será verificado sem substituir o core"));
    }
    if root.join("BepInEx").exists() {
        return (false, "BepInEx parcial detectado; instalação automática será bloqueada até revisão".into());
    }
    (false, format!("BepInEx/XUnity {runtime} será instalado ao iniciar"))
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
        let runtime = game.runtime.as_deref().unwrap_or("");
        installed_integration(root, runtime)
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
        // The loader can be present yet too old for the game's IL2CPP metadata.
        // The installer checks its own installation record before upgrading it.
        if !integration_ready || game.runtime.as_deref() == Some("IL2CPP") {
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
            run_stage(install, app, "Verificando e instalando componentes Unity ausentes")?;
        } else {
            session_log(
                app,
                "system",
                "BepInEx e XUnity compatíveis encontrados; arquivos existentes preservados.",
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn existing_core_without_xunity_is_not_ready() {
        let root = std::env::temp_dir().join(format!("sftranslator-unity-install-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("BepInEx/core")).unwrap();
        fs::write(root.join("BepInEx/core/BepInEx.dll"), b"existing").unwrap();
        let (ready, detail) = installed_integration(&root, "Mono");
        assert!(!ready);
        assert!(detail.contains("preservado") || detail.contains("sem substituir"));
        fs::create_dir_all(root.join("BepInEx/plugins/XUnity.AutoTranslator")).unwrap();
        fs::write(root.join("BepInEx/core/XUnity.Common.dll"), b"existing").unwrap();
        fs::write(root.join("BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.Core.dll"), b"existing").unwrap();
        fs::write(root.join("BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.BepInEx.dll"), b"existing").unwrap();
        fs::create_dir_all(root.join("BepInEx/plugins/XUnity.AutoTranslator/Translators")).unwrap();
        fs::write(root.join("BepInEx/plugins/XUnity.AutoTranslator/Translators/CustomTranslate.dll"), b"existing").unwrap();
        fs::create_dir_all(root.join("BepInEx/plugins/XUnity.ResourceRedirector")).unwrap();
        fs::write(root.join("BepInEx/plugins/XUnity.ResourceRedirector/XUnity.ResourceRedirector.BepInEx.dll"), b"existing").unwrap();
        assert!(installed_integration(&root, "Mono").0);
        assert!(!installed_integration(&root, "IL2CPP").0);
        fs::remove_dir_all(root).unwrap();
    }
}
