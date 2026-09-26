mod catalog;
mod engines;
mod models;
mod session;
mod updater;
use models::models_directory;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
use tauri::{AppHandle, Manager};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Game {
    id: String,
    name: String,
    executable_path: String,
    engine: String,
    runtime: Option<String>,
    architecture: Option<String>,
    status: String,
    source_language: String,
    target_language: String,
    added_at: String,
    last_launch: Option<String>,
    #[serde(default)]
    icon_data: Option<String>,
    #[serde(default)]
    model_installed: bool,
    #[serde(default)]
    detected_language: Option<String>,
    #[serde(default)]
    language_confidence: Option<f64>,
    #[serde(default)]
    integration_status: Option<String>,
    #[serde(default = "default_flow_mode")]
    flow_mode: String,
    #[serde(default)]
    intermediate_language: Option<String>,
}

fn default_flow_mode() -> String { "direct".into() }

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AppSettings {
    #[serde(default)]
    enable_experimental_chained_flow: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self { enable_experimental_chained_flow: false }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineHealth {
    engine: String,
    source_found: bool,
    runtime_found: bool,
    model_found: bool,
    development: bool,
    details: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TranslationModel {
    id: String,
    from_code: String,
    from_name: String,
    to_code: String,
    to_name: String,
    version: String,
    installed: bool,
    used_by: usize,
}

fn database_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("games.json"))
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("settings.json"))
}

fn load_settings(app: &AppHandle) -> Result<AppSettings, String> {
    let path = settings_path(app)?;
    if !path.exists() { return Ok(AppSettings::default()); }
    serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
        .map_err(|e| format!("Configurações inválidas: {e}"))
}

fn save_settings(app: &AppHandle, settings: &AppSettings) -> Result<(), String> {
    let path = settings_path(app)?;
    fs::write(path, serde_json::to_vec_pretty(settings).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

fn load_games(app: &AppHandle) -> Result<Vec<Game>, String> {
    let path = database_path(app)?;
    if !path.exists() {
        return Ok(Vec::new());
    }
    let bytes = fs::read(path).map_err(|e| e.to_string())?;
    serde_json::from_slice(&bytes).map_err(|e| format!("Biblioteca inválida: {e}"))
}

fn save_games(app: &AppHandle, games: &[Game]) -> Result<(), String> {
    let path = database_path(app)?;
    let temporary = path.with_extension("json.tmp");
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(games).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    fs::rename(temporary, path).map_err(|e| e.to_string())
}

#[cfg(windows)]
fn native_game_path(path: &Path) -> PathBuf {
    let value = path.to_string_lossy();
    if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = value.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path.to_path_buf()
    }
}

fn cache_component(value: &str) -> String {
    let normalized: String = value
        .trim()
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect();
    if normalized.is_empty() { "unknown".into() } else { normalized }
}

fn renpy_cache_pair(game: &Game) -> String {
    let mut parts = vec![cache_component(&game.source_language)];
    if game.flow_mode == "chain" {
        parts.push(cache_component(game.intermediate_language.as_deref().unwrap_or("en")));
    }
    parts.push(cache_component(&game.target_language));
    parts.join("_")
}

fn required_model_ids(game: &Game) -> Vec<String> {
    if game.flow_mode == "chain" {
        let middle = game.intermediate_language.as_deref().unwrap_or("en");
        vec![
            format!("{}-{middle}", game.source_language),
            format!("{middle}-{}", game.target_language),
        ]
    } else {
        vec![format!("{}-{}", game.source_language, game.target_language)]
    }
}

fn game_root(game: &Game) -> Result<PathBuf, String> {
    native_game_path(Path::new(&game.executable_path))
        .parent()
        .map(Path::to_path_buf)
        .ok_or("Pasta do jogo inválida.".into())
}

fn game_cache_directory(game: &Game) -> Result<PathBuf, String> {
    engines::by_name(&game.engine)?.cache_directory(game)
}

#[cfg(not(windows))]
fn native_game_path(path: &Path) -> PathBuf {
    path.to_path_buf()
}

fn pe_architecture(path: &Path) -> Option<String> {
    let bytes = fs::read(path).ok()?;
    if bytes.len() < 64 || &bytes[0..2] != b"MZ" {
        return None;
    }
    let offset = u32::from_le_bytes(bytes[60..64].try_into().ok()?) as usize;
    if offset + 6 > bytes.len() || &bytes[offset..offset + 4] != b"PE\0\0" {
        return None;
    }
    match u16::from_le_bytes(bytes[offset + 4..offset + 6].try_into().ok()?) {
        0x8664 => Some("x64".into()),
        0x014c => Some("x86".into()),
        _ => None,
    }
}

fn inspect_game(executable: &Path) -> Result<(String, Option<String>, Option<String>), String> {
    engines::inspect(executable)
}

fn inspect_language(executable: &Path, engine: &str) -> (String, f64) {
    if engine == "RPG Maker" {
        let root = executable.parent().unwrap_or(Path::new("."));
        let web = if root.join("www/data/System.json").is_file() { root.join("www") } else { root.to_path_buf() };
        if let Ok(bytes) = fs::read(web.join("data/System.json")) {
            if let Ok(system) = serde_json::from_slice::<serde_json::Value>(&bytes) {
                if let Some(locale) = system["locale"].as_str() {
                    let language = locale.split(['_', '-']).next().unwrap_or("").to_ascii_lowercase();
                    let code = match language.as_str() {
                        "zh" => Some("zh"), "ja" => Some("ja"), "ko" => Some("ko"),
                        "en" => Some("en"), "pt" if locale.to_ascii_lowercase().contains("br") => Some("pb"),
                        "pt" => Some("pt"), "es" => Some("es"),
                        "fr" => Some("fr"), "de" => Some("de"), "ru" => Some("ru"),
                        _ => None,
                    };
                    if let Some(code) = code { return (code.into(), 0.98) }
                }
            }
        }
        return ("en".into(), 0.0);
    }
    let root = executable.parent().unwrap_or(Path::new("."));
    let candidates = [root.join("settings.json"), root.join("config.json")];
    for path in candidates {
        if let Ok(text) = fs::read_to_string(path) {
            let lower = text.to_lowercase();
            for (needle, code) in [
                ("japanese", "ja"),
                ("english", "en"),
                ("portuguese", "pt"),
                ("\"ja\"", "ja"),
                ("\"en\"", "en"),
            ] {
                if lower.contains(needle) {
                    return (code.into(), 0.92);
                }
            }
        }
    }
    if engine == "Ren'Py" {
        ("en".into(), 0.62)
    } else {
        ("en".into(), 0.55)
    }
}

fn integration_state(game: &Game) -> (bool, String) {
    engines::by_name(&game.engine)
        .map(|adapter| adapter.integration_state(game))
        .unwrap_or((false, "Motor não suportado".into()))
}

#[tauri::command]
fn list_games(app: AppHandle) -> Result<Vec<Game>, String> {
    let mut games = load_games(&app)?;
    let installed = catalog::installed_packages(&models_directory(&app)?.join("argos-translate"));
    let mut changed = false;
    for game in &mut games {
        if game.engine == "RPG Maker" {
            let (detected, confidence) = inspect_language(Path::new(&game.executable_path), &game.engine);
            if confidence > game.language_confidence.unwrap_or(0.0)
                && (game.detected_language.as_deref() != Some(&detected)
                    || game.language_confidence != Some(confidence)) {
                game.detected_language = Some(detected);
                game.language_confidence = Some(confidence);
                changed = true;
            }
        }
        let model_installed = required_model_ids(game).iter().all(|id| installed.contains_key(id));
        if game.model_installed != model_installed {
            game.model_installed = model_installed;
            changed = true;
        }
        let normalized = native_game_path(Path::new(&game.executable_path));
        let normalized = normalized.to_string_lossy().into_owned();
        if game.executable_path != normalized {
            game.executable_path = normalized;
            changed = true;
        }
        if game.icon_data.is_none() {
            game.icon_data = extract_icon(Path::new(&game.executable_path));
            changed |= game.icon_data.is_some();
        }
        let (integration_ready, integration_status) = integration_state(game);
        if game.integration_status.as_deref() != Some(&integration_status) {
            game.integration_status = Some(integration_status);
            changed = true;
        }
        let status = if engines::by_name(&game.engine).is_ok_and(|adapter| !adapter.translation_available(game)) {
            "Em desenvolvimento"
        } else if game.model_installed && integration_ready {
            "Pronto"
        } else if game.model_installed {
            "Instalação pendente"
        } else {
            "Modelo necessário"
        };
        if game.status != status {
            game.status = status.into();
            changed = true;
        }
    }
    if changed {
        save_games(&app, &games)?;
    }
    Ok(games)
}

#[tauri::command]
fn add_game(app: AppHandle, executable_path: String, engine_hint: Option<String>) -> Result<Game, String> {
    let executable = PathBuf::from(&executable_path);
    let canonical = executable
        .canonicalize()
        .map_err(|_| "O executável selecionado não existe.".to_string())?;
    let canonical = native_game_path(&canonical);
    let (engine, runtime, architecture) = if engine_hint.as_deref() == Some("RPG Maker") {
        let detected = engines::by_name("RPG Maker")?.inspect(&canonical);
        ("RPG Maker".into(), detected.as_ref().and_then(|found| found.runtime.clone()).or(Some("Não identificado (teste)".into())), detected.and_then(|found| found.architecture).or_else(|| pe_architecture(&canonical)))
    } else if engine_hint.as_deref() == Some("Unreal") {
        let detected = engines::by_name("Unreal")?.inspect(&canonical)
            .ok_or("Não encontrei Content/Paks com arquivos .pak ou .utoc para confirmar que este executável é Unreal.")?;
        ("Unreal".into(), detected.runtime, detected.architecture)
    } else {
        inspect_game(&canonical)?
    };
    let (detected_language, language_confidence) = inspect_language(&canonical, &engine);
    let mut games = load_games(&app)?;
    if games
        .iter()
        .any(|g| Path::new(&g.executable_path) == canonical)
    {
        return Err("Este jogo já está na biblioteca.".into());
    }
    let game = Game {
        id: uuid::Uuid::new_v4().to_string(),
        name: canonical
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("Jogo")
            .to_string(),
        executable_path: canonical.to_string_lossy().into_owned(),
        engine,
        runtime,
        architecture,
        status: "Novo".into(),
        source_language: detected_language.clone(),
        target_language: String::new(),
        added_at: chrono::Utc::now().to_rfc3339(),
        last_launch: None,
        icon_data: extract_icon(&canonical),
        model_installed: false,
        detected_language: Some(detected_language),
        language_confidence: Some(language_confidence),
        integration_status: None,
        flow_mode: default_flow_mode(),
        intermediate_language: None,
    };
    let (_, integration_status) = integration_state(&game);
    let mut game = game;
    if engines::by_name(&game.engine).is_ok_and(|adapter| !adapter.translation_available(&game)) {
        game.status = "Em desenvolvimento".into();
    }
    if game.engine == "RPG Maker" {
        if matches!(game.runtime.as_deref(), Some("MV" | "MZ" | "Unite Mono" | "Unite IL2CPP")) {
            game.status = "Modelo necessário".into();
        }
        if matches!(game.name.as_str(), "Game" | "RPG_RT") {
            if let Some(folder) = canonical.parent().and_then(|path| path.file_name()).and_then(|name| name.to_str()) { game.name = folder.to_string(); }
        }
    }
    game.integration_status = Some(integration_status);
    games.push(game.clone());
    save_games(&app, &games)?;
    Ok(game)
}

#[cfg(windows)]
fn extract_icon(executable: &Path) -> Option<String> {
    let raw = executable.to_string_lossy();
    let explorer_path = raw.strip_prefix(r"\\?\").map(PathBuf::from);
    explorer_path
        .as_deref()
        .into_iter()
        .chain(std::iter::once(executable))
        .find_map(|path| {
            windows_icons::get_icon_base64_by_path_with_size(path, windows_icons::IconSize::Large)
                .ok()
        })
        .map(|encoded| format!("data:image/png;base64,{encoded}"))
}

#[cfg(not(windows))]
fn extract_icon(_executable: &Path) -> Option<String> {
    None
}

#[tauri::command]
fn remove_game(app: AppHandle, game_id: String) -> Result<(), String> {
    let mut games = load_games(&app)?;
    let original_len = games.len();
    games.retain(|game| game.id != game_id);
    if games.len() == original_len {
        return Err("Jogo não encontrado na biblioteca.".into());
    }
    save_games(&app, &games)
}

#[tauri::command]
fn configure_game(
    app: AppHandle,
    game_id: String,
    source_language: String,
    target_language: String,
    flow_mode: String,
    intermediate_language: Option<String>,
) -> Result<Game, String> {
    if flow_mode != "direct" && flow_mode != "chain" {
        return Err("Modo de fluxo inválido.".into());
    }
    if flow_mode == "chain" && intermediate_language.as_deref() != Some("en") {
        return Err("O fluxo experimental usa inglês como idioma intermediário.".into());
    }
    let mut games = load_games(&app)?;
    let game = games
        .iter_mut()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    if flow_mode == "chain" && !load_settings(&app)?.enable_experimental_chained_flow && game.flow_mode != "chain" {
        return Err("Ative o fluxo experimental nas Configurações antes de criar uma cadeia.".into());
    }
    game.source_language = source_language;
    game.target_language = target_language;
    game.flow_mode = flow_mode;
    game.intermediate_language = if game.flow_mode == "chain" { Some("en".into()) } else { None };
    let installed = catalog::installed_packages(&models_directory(&app)?.join("argos-translate"));
    game.model_installed = required_model_ids(game).iter().all(|id| installed.contains_key(id));
    let (integration_ready, integration_status) = integration_state(game);
    game.integration_status = Some(integration_status);
    game.status = if engines::by_name(&game.engine).is_ok_and(|adapter| !adapter.translation_available(game)) {
        "Em desenvolvimento".into()
    } else if game.model_installed && integration_ready {
        "Pronto".into()
    } else if game.model_installed {
        "Instalação pendente".into()
    } else {
        "Modelo necessário".into()
    };
    let result = game.clone();
    save_games(&app, &games)?;
    Ok(result)
}

#[tauri::command]
fn get_settings(app: AppHandle) -> Result<AppSettings, String> { load_settings(&app) }

#[tauri::command]
fn update_settings(app: AppHandle, settings: AppSettings) -> Result<AppSettings, String> {
    save_settings(&app, &settings)?;
    Ok(settings)
}

#[tauri::command]
fn open_game_cache(app: AppHandle, game_id: String) -> Result<(), String> {
    let game = load_games(&app)?
        .into_iter()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    let directory = game_cache_directory(&game)?;
    fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
    #[cfg(windows)]
    Command::new("explorer.exe")
        .arg(&directory)
        .spawn()
        .map_err(|error| format!("Não foi possível abrir a pasta do cache: {error}"))?;
    #[cfg(not(windows))]
    return Err("Abrir a pasta do cache está disponível apenas no Windows.".into());
    Ok(())
}

#[tauri::command]
fn open_game_folder(app: AppHandle, game_id: String) -> Result<(), String> {
    let game = load_games(&app)?
        .into_iter()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    let executable = PathBuf::from(&game.executable_path);
    let directory = executable
        .parent()
        .filter(|path| path.is_dir())
        .ok_or("A pasta do executável do jogo não foi encontrada.")?;
    #[cfg(windows)]
    Command::new("explorer.exe")
        .arg(directory)
        .spawn()
        .map_err(|error| format!("Não foi possível abrir a pasta do jogo: {error}"))?;
    #[cfg(not(windows))]
    return Err("Abrir a pasta do jogo está disponível apenas no Windows.".into());
    Ok(())
}

#[tauri::command]
fn clear_game_cache(app: AppHandle, game_id: String) -> Result<(), String> {
    let game = load_games(&app)?
        .into_iter()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    engines::by_name(&game.engine)?.clear_cache(&game)
}

fn runtime_directory(app: &AppHandle) -> Result<PathBuf, String> {
    let mut candidates = vec![app.path().resource_dir().map_err(|e| e.to_string())?.join("runtimes")];
    if cfg!(debug_assertions) {
        candidates.push(Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/runtimes"));
    }
    candidates.into_iter().find(|root| root.is_dir())
        .ok_or_else(|| "Motores integrados ausentes. Reinstale o SFTranslator usando o instalador completo.".into())
}

#[tauri::command]
fn engine_health(app: AppHandle) -> Vec<EngineHealth> {
    let runtimes = runtime_directory(&app).ok();
    let models_present = models_directory(&app)
        .map(|path| !catalog::installed_packages(&path.join("argos-translate")).is_empty())
        .unwrap_or(false);
    engines::health(runtimes.as_deref(), models_present)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            list_games,
            add_game,
            remove_game,
            configure_game,
            open_game_cache,
            open_game_folder,
            clear_game_cache,
            get_settings,
            update_settings,
            models::delete_model,
            models::download_model,
            session::launch_game,
            session::stop_game_session,
            engine_health,
            models::list_models,
            updater::check_for_updates,
            updater::update_download_status,
            updater::download_update,
            updater::cancel_update_download,
            updater::install_downloaded_update,
            updater::open_release_page
        ])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar UAT Desktop");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn game(flow_mode: &str, middle: Option<&str>) -> Game {
        Game {
            id: "id".into(), name: "game".into(), executable_path: "game.exe".into(), engine: "Unity".into(),
            runtime: None, architecture: None, status: "Novo".into(), source_language: "ja".into(), target_language: "pb".into(),
            added_at: "now".into(), last_launch: None, icon_data: None, model_installed: false, detected_language: None,
            language_confidence: None, integration_status: None, flow_mode: flow_mode.into(), intermediate_language: middle.map(str::to_string),
        }
    }
    #[test]
    fn rejects_missing_game() {
        assert!(inspect_game(Path::new("missing.exe")).is_err());
    }

    #[test]
    fn chained_flow_requires_both_models_and_uses_a_distinct_cache_key() {
        let chained = game("chain", Some("en"));
        assert_eq!(required_model_ids(&chained), ["ja-en", "en-pb"]);
        assert_eq!(renpy_cache_pair(&chained), "ja_en_pb");
        assert_eq!(required_model_ids(&game("direct", None)), ["ja-pb"]);
    }

    #[test]
    fn rpg_maker_locale_identifies_chinese_before_configuring_models() {
        let root = std::env::temp_dir().join(format!("sftranslator-locale-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("Game.exe"), b"fixture").unwrap();
        fs::write(root.join("data/System.json"), br#"{"locale":"zh_CN"}"#).unwrap();
        assert_eq!(inspect_language(&root.join("Game.exe"), "RPG Maker"), ("zh".into(), 0.98));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn registered_engines_recognize_existing_games() {
        let root = std::env::temp_dir().join(format!("sftranslator-engines-{}", uuid::Uuid::new_v4()));
        let renpy_root = root.join("renpy-game");
        let unity_root = root.join("unity-game");
        fs::create_dir_all(renpy_root.join("game")).unwrap();
        fs::create_dir_all(unity_root.join("Sample_Data/Managed")).unwrap();
        let renpy_exe = renpy_root.join("Sample.exe");
        let unity_exe = unity_root.join("Sample.exe");
        fs::write(&renpy_exe, b"fixture").unwrap();
        fs::write(renpy_root.join("game/script.rpyc"), b"fixture").unwrap();
        fs::write(&unity_exe, b"fixture").unwrap();
        fs::write(unity_root.join("Sample_Data/Managed/Assembly-CSharp.dll"), b"fixture").unwrap();

        let result = (|| {
            assert_eq!(inspect_game(&renpy_exe)?.0, "Ren'Py");
            let unity = inspect_game(&unity_exe)?;
            assert_eq!(unity.0, "Unity");
            assert_eq!(unity.1.as_deref(), Some("Mono"));
            Ok::<_, String>(())
        })();
        fs::remove_dir_all(root).unwrap();
        result.unwrap();
    }
}
