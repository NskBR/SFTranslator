mod renpy;
mod rpgmaker;
mod unreal;
mod unity;

use std::{
    path::{Path, PathBuf},
    process::Child,
    sync::{atomic::AtomicBool, Arc},
    thread::JoinHandle,
};
use tauri::AppHandle;

use crate::{EngineHealth, Game};

pub(super) struct EngineMatch {
    pub runtime: Option<String>,
    pub architecture: Option<String>,
}

pub(super) struct EngineSession {
    pub server: Option<Child>,
    pub port: Option<u16>,
    pub log_tail: Option<JoinHandle<()>>,
    pub marker: Option<PathBuf>,
}

pub(super) trait EngineAdapter: Sync {
    fn name(&self) -> &'static str;
    fn translation_available(&self, _game: &Game) -> bool { true }
    fn launch_path(&self, game: &Game) -> PathBuf {
        crate::native_game_path(Path::new(&game.executable_path))
    }
    fn inspect(&self, executable: &Path) -> Option<EngineMatch>;
    fn integration_state(&self, game: &Game) -> (bool, String);
    fn cache_directory(&self, game: &Game) -> Result<PathBuf, String>;
    fn clear_cache(&self, game: &Game) -> Result<(), String>;
    fn start_session(
        &self,
        app: &AppHandle,
        game: &Game,
        runtimes: &Path,
        stop_tail: Arc<AtomicBool>,
    ) -> Result<EngineSession, String>;
    fn start_observer(
        &self,
        _app: &AppHandle,
        _game: &Game,
        _runtimes: &Path,
        _pid: u32,
    ) -> Result<Option<Child>, String> { Ok(None) }
    fn health(&self, runtimes: Option<&Path>, models_present: bool) -> EngineHealth;
    fn runtime_ready(&self, runtimes: &Path) -> bool;
}

static UNITY: unity::Unity = unity::Unity;
static RENPY: renpy::Renpy = renpy::Renpy;
static RPGMAKER: rpgmaker::RpgMaker = rpgmaker::RpgMaker;
static UNREAL: unreal::Unreal = unreal::Unreal;
// Unite é um build Unity, mas deve ser reconhecido antes do adaptador Unity genérico.
static ADAPTERS: [&'static dyn EngineAdapter; 4] = [&RPGMAKER, &UNREAL, &UNITY, &RENPY];

pub(super) fn all() -> &'static [&'static dyn EngineAdapter] {
    &ADAPTERS
}

pub(super) fn by_name(name: &str) -> Result<&'static dyn EngineAdapter, String> {
    all()
        .iter()
        .copied()
        .find(|adapter| adapter.name() == name)
        .ok_or_else(|| format!("Motor não suportado: {name}"))
}

pub(super) fn inspect(
    executable: &Path,
) -> Result<(String, Option<String>, Option<String>), String> {
    if !executable.is_file() {
        return Err("O executável selecionado não existe.".into());
    }
    for adapter in all() {
        if let Some(found) = adapter.inspect(executable) {
            return Ok((adapter.name().into(), found.runtime, found.architecture));
        }
    }
    Err("Não foi possível reconhecer o motor deste jogo. Se for RPG Maker, use o cadastro manual de teste em Diagnósticos.".into())
}

pub(super) fn health(runtimes: Option<&Path>, models_present: bool) -> Vec<EngineHealth> {
    all()
        .iter()
        .map(|adapter| adapter.health(runtimes, models_present))
        .collect()
}

pub(super) fn copy_legacy_models(source: &Path, destination: &Path) -> Result<(), String> {
    renpy::copy_legacy_models(source, destination)
}
