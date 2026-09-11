mod catalog;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};

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
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineHealth {
    engine: String,
    source_found: bool,
    runtime_found: bool,
    model_found: bool,
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
    format!(
        "{}_{}",
        cache_component(&game.source_language),
        cache_component(&game.target_language)
    )
}

fn game_root(game: &Game) -> Result<PathBuf, String> {
    native_game_path(Path::new(&game.executable_path))
        .parent()
        .map(Path::to_path_buf)
        .ok_or("Pasta do jogo inválida.".into())
}

fn unity_cache_language(code: &str) -> String {
    match code.trim().to_ascii_lowercase().as_str() {
        "pb" | "pt-br" | "pt_br" => "pt-BR".into(),
        value if value.is_empty() => "unknown".into(),
        value => value.into(),
    }
}

fn game_cache_directory(game: &Game) -> Result<PathBuf, String> {
    let root = game_root(game)?;
    if game.engine == "Unity" {
        Ok(root
            .join("BepInEx/Translation")
            .join(unity_cache_language(&game.target_language))
            .join("Text"))
    } else {
        Ok(root.join("uat/caches"))
    }
}

#[cfg(not(windows))]
fn native_game_path(path: &Path) -> PathBuf {
    path.to_path_buf()
}

fn contains_files(dir: &Path, extensions: &[&str]) -> bool {
    let Ok(entries) = fs::read_dir(dir) else {
        return false;
    };
    entries.flatten().any(|entry| {
        let path = entry.path();
        path.is_file()
            && path
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| extensions.iter().any(|x| e.eq_ignore_ascii_case(x)))
    })
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
    if !executable.is_file() {
        return Err("O executável selecionado não existe.".into());
    }
    let root = executable.parent().ok_or("Pasta do jogo inválida.")?;
    let stem = executable
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or("Nome de arquivo inválido.")?;
    let unity_data = root.join(format!("{stem}_Data"));
    let any_unity_data = fs::read_dir(root)
        .ok()
        .into_iter()
        .flatten()
        .flatten()
        .any(|e| e.path().is_dir() && e.file_name().to_string_lossy().ends_with("_Data"));
    if unity_data.is_dir()
        || root.join("UnityPlayer.dll").is_file()
        || (root.join("GameAssembly.dll").is_file() && any_unity_data)
    {
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
        return Ok((
            "Unity".into(),
            Some(runtime.into()),
            pe_architecture(executable),
        ));
    }
    let game_dir = root.join("game");
    if root.join("renpy").is_dir()
        || (game_dir.is_dir() && contains_files(&game_dir, &["rpy", "rpyc", "rpa"]))
    {
        return Ok((
            "Ren'Py".into(),
            Some("Ren'Py".into()),
            pe_architecture(executable),
        ));
    }
    Err("Não foi possível reconhecer este jogo como Unity ou Ren'Py.".into())
}

fn inspect_language(executable: &Path, engine: &str) -> (String, f64) {
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

fn integration_state(game: &Game) -> (bool, String) {
    let executable = native_game_path(Path::new(&game.executable_path));
    let root = executable.parent().unwrap_or(Path::new("."));
    if game.engine == "Unity" {
        let bep_in_ex = root.join("BepInEx");
        let core_ready = bep_in_ex.join("core").is_dir();
        let xunity_ready = directory_contains(&bep_in_ex.join("plugins"), "autotranslator");
        if core_ready && xunity_ready {
            (
                true,
                format!(
                    "BepInEx/XUnity {} instalado no jogo",
                    game.runtime.as_deref().unwrap_or("")
                ),
            )
        } else {
            (
                false,
                format!(
                    "BepInEx/XUnity {} será instalado ao iniciar",
                    game.runtime.as_deref().unwrap_or("")
                ),
            )
        }
    } else {
        let ready =
            root.join("game/uat_hook.rpy").is_file() && root.join("uat/uat_hook.py").is_file();
        if ready {
            (true, "Hook Ren'Py instalado na pasta do jogo".into())
        } else {
            (false, "Hook compatível será instalado ao iniciar".into())
        }
    }
}

#[tauri::command]
fn list_games(app: AppHandle) -> Result<Vec<Game>, String> {
    let mut games = load_games(&app)?;
    let installed = catalog::installed_packages(&models_directory(&app)?.join("argos-translate"));
    let mut changed = false;
    for game in &mut games {
        let model_installed = installed.contains_key(&format!("{}-{}", game.source_language, game.target_language));
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
        let status = if game.model_installed && integration_ready {
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
fn add_game(app: AppHandle, executable_path: String) -> Result<Game, String> {
    let executable = PathBuf::from(&executable_path);
    let canonical = executable
        .canonicalize()
        .map_err(|_| "O executável selecionado não existe.".to_string())?;
    let canonical = native_game_path(&canonical);
    let (engine, runtime, architecture) = inspect_game(&canonical)?;
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
    };
    let (_, integration_status) = integration_state(&game);
    let mut game = game;
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
) -> Result<Game, String> {
    let mut games = load_games(&app)?;
    let game = games
        .iter_mut()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    game.source_language = source_language;
    game.target_language = target_language;
    game.model_installed = list_models(app.clone())?.iter().any(|model| {
        model.installed && model.from_code == game.source_language && model.to_code == game.target_language
    });
    let (integration_ready, integration_status) = integration_state(game);
    game.integration_status = Some(integration_status);
    game.status = if game.model_installed && integration_ready {
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
    let directory = game_cache_directory(&game)?;
    if game.engine == "Unity" {
        if directory.is_dir() {
            fs::remove_dir_all(&directory).map_err(|error| error.to_string())?;
        }
        return Ok(());
    }

    let pair = renpy_cache_pair(&game);
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

#[tauri::command]
fn delete_model(app: AppHandle, model_id: String) -> Result<(), String> {
    let packages = models_directory(&app)?.join("argos-translate/packages");
    let entries = fs::read_dir(&packages).map_err(|e| e.to_string())?;
    let mut removed = false;
    for entry in entries.flatten() {
        let metadata = entry.path().join("metadata.json");
        let Ok(bytes) = fs::read(metadata) else {
            continue;
        };
        let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
            continue;
        };
        let id = format!(
            "{}-{}",
            value["from_code"].as_str().unwrap_or(""),
            value["to_code"].as_str().unwrap_or("")
        );
        if id == model_id {
            fs::remove_dir_all(entry.path())
                .map_err(|e| format!("Não foi possível apagar o modelo: {e}"))?;
            removed = true;
        }
    }
    if !removed {
        return Err("Modelo não encontrado.".into());
    }
    let mut games = load_games(&app)?;
    for game in &mut games {
        if format!("{}-{}", game.source_language, game.target_language) == model_id {
            game.model_installed = false;
            game.status = "Modelo necessário".into();
        }
    }
    save_games(&app, &games)
}

#[tauri::command]
fn download_model(app: AppHandle, model_id: String) -> Result<(), String> {
    let models_root = models_directory(&app)?.join("argos-translate");
    let catalog = catalog::load_catalog(&models_root);
    let package = catalog
        .iter()
        .find(|value| {
            format!(
                "{}-{}",
                value["from_code"].as_str().unwrap_or(""),
                value["to_code"].as_str().unwrap_or("")
            ) == model_id
        })
        .ok_or("Fluxo não encontrado no catálogo Argos.")?;
    let url = package["links"]
        .as_array()
        .and_then(|links| {
            links
                .iter()
                .filter_map(|link| link.as_str())
                .find(|link| link.starts_with("https://"))
        })
        .ok_or("Este pacote não possui uma fonte HTTPS compatível.")?;
    let mut response =
        reqwest::blocking::get(url).map_err(|e| format!("Falha no download: {e}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "Servidor Argos respondeu com {}.",
            response.status()
        ));
    }
    let total = response.content_length().unwrap_or(0);
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = response
            .read(&mut buffer)
            .map_err(|e| format!("Download incompleto: {e}"))?;
        if count == 0 {
            break;
        }
        bytes.extend_from_slice(&buffer[..count]);
        let progress = if total > 0 {
            ((bytes.len() as u64 * 100) / total).min(99)
        } else {
            0
        };
        app.emit(
            "model-download-progress",
            serde_json::json!({"modelId": model_id, "progress": progress}),
        )
        .ok();
    }
    let packages = models_root.join("packages");
    fs::create_dir_all(&packages).map_err(|e| e.to_string())?;
    let staging = packages.join(format!(".download-{model_id}"));
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| e.to_string())?;
    }
    fs::create_dir_all(&staging).map_err(|e| e.to_string())?;
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes))
        .map_err(|e| format!("Pacote Argos inválido: {e}"))?;
    for index in 0..archive.len() {
        let mut file = archive.by_index(index).map_err(|e| e.to_string())?;
        let Some(relative) = file.enclosed_name() else {
            continue;
        };
        let output = staging.join(relative);
        if file.is_dir() {
            fs::create_dir_all(&output).map_err(|e| e.to_string())?;
        } else {
            if let Some(parent) = output.parent() {
                fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            let mut target = fs::File::create(output).map_err(|e| e.to_string())?;
            std::io::copy(&mut file, &mut target).map_err(|e| e.to_string())?;
        }
    }
    fn find_package_root(directory: &Path) -> Option<PathBuf> {
        if directory.join("metadata.json").is_file() {
            return Some(directory.to_path_buf());
        }
        fs::read_dir(directory).ok()?.flatten().find_map(|entry| {
            let path = entry.path();
            if path.is_dir() {
                find_package_root(&path)
            } else {
                None
            }
        })
    }
    let Some(package_root) = find_package_root(&staging) else {
        fs::remove_dir_all(&staging).ok();
        return Err("O pacote baixado não contém metadata.json.".into());
    };
    let version = package["package_version"]
        .as_str()
        .unwrap_or("unknown")
        .replace('.', "_");
    let destination = packages.join(format!(
        "translate-{}-{}",
        model_id.replace('-', "_"),
        version
    ));
    if destination.exists() {
        fs::remove_dir_all(&staging).ok();
        return Ok(());
    }
    if package_root == staging {
        fs::rename(&staging, destination)
            .map_err(|e| format!("Falha ao instalar o modelo: {e}"))?;
    } else {
        fs::rename(&package_root, &destination)
            .map_err(|e| format!("Falha ao instalar o modelo: {e}"))?;
        fs::remove_dir_all(&staging).ok();
    }
    app.emit(
        "model-download-progress",
        serde_json::json!({"modelId": model_id, "progress": 100}),
    )
    .ok();
    Ok(())
}

fn session_log(app: &AppHandle, kind: &str, text: impl Into<String>) {
    app.emit(
        "session-log",
        serde_json::json!({"kind":kind,"text":text.into()}),
    )
    .ok();
}

fn hide_console(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
}

fn spawn_streaming(
    mut command: Command,
    app: &AppHandle,
    label: &str,
) -> Result<std::process::Child, String> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    hide_console(&mut command);
    let mut child = command
        .spawn()
        .map_err(|error| format!("Falha ao iniciar {label}: {error}"))?;
    if let Some(stdout) = child.stdout.take() {
        let handle = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                session_log(&handle, "output", line);
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        let handle = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                session_log(&handle, "error", line);
            }
        });
    }
    Ok(child)
}

fn run_stage(command: Command, app: &AppHandle, label: &str) -> Result<(), String> {
    session_log(app, "system", format!("{label}…"));
    let mut child = spawn_streaming(command, app, label)?;
    let status = child
        .wait()
        .map_err(|error| format!("Falha durante {label}: {error}"))?;
    if status.success() {
        session_log(app, "system", format!("{label}: concluído."));
        Ok(())
    } else {
        Err(format!(
            "{label} terminou com código {}.",
            status.code().unwrap_or(-1)
        ))
    }
}

fn copy_renpy_tree(source: &Path, destination: &Path) -> Result<(), String> {
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
            copy_renpy_tree(&path, &target)?;
        } else {
            fs::copy(&path, &target)
                .map_err(|error| format!("Falha ao copiar {}: {error}", path.display()))?;
        }
    }
    Ok(())
}

fn install_renpy_hook(engine_root: &Path, game: &Game, app: &AppHandle) -> Result<(), String> {
    let game_root = game_root(game)?;
    session_log(
        app,
        "system",
        "Motor identificado: Ren'Py. Selecionando hook compatível pela versão do Python interno.",
    );
    copy_renpy_tree(&engine_root.join("uat"), &game_root.join("uat"))?;
    let hook_source = engine_root.join("game/uat_hook.rpy");
    let hook_destination = game_root.join("game/uat_hook.rpy");
    if hook_destination.is_file() {
        let backup = game_root.join("game/uat_hook.rpy.sftranslator.bak");
        if !backup.exists() {
            fs::copy(&hook_destination, &backup).map_err(|error| error.to_string())?;
        }
    }
    fs::copy(&hook_source, &hook_destination)
        .map_err(|error| format!("Falha ao instalar o hook Ren'Py: {error}"))?;

    let config_path = game_root.join("uat/uat_config.json");
    let template_path = engine_root.join("uat/uat_config.json");
    let mut config: serde_json::Value = fs::read(&config_path)
        .ok()
        .or_else(|| fs::read(template_path).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    config["provider"] = serde_json::json!("local");
    config["show_console"] = serde_json::json!(false);
    let flow_is_unchanged = config["source_language"].as_str() == Some(game.source_language.as_str())
        && config["target_language"].as_str() == Some(game.target_language.as_str());
    config["source_language"] = serde_json::json!(game.source_language);
    config["target_language"] = serde_json::json!(game.target_language);
    let cache_pair = renpy_cache_pair(game);
    fs::create_dir_all(game_root.join("uat/caches")).map_err(|error| error.to_string())?;
    if flow_is_unchanged {
        for (config_key, legacy_name, new_name) in [
            ("cache_file", "uat_cache.json", format!("uat_cache_{cache_pair}.json")),
            ("words_file", "uat_words.json", format!("uat_words_{cache_pair}.json")),
        ] {
            if config[config_key].as_str() == Some(legacy_name) {
                let legacy_path = game_root.join("uat").join(legacy_name);
                let new_path = game_root.join("uat/caches").join(new_name);
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
    fs::write(
        engine_root.join("uat/uat_config.json"),
        serde_json::to_vec_pretty(&config).map_err(|error| error.to_string())?,
    )
    .map_err(|error| format!("Falha ao configurar o servidor central Ren'Py: {error}"))?;
    session_log(
        app,
        "system",
        "Hook moderno e legado instalados dentro da pasta do jogo.",
    );
    Ok(())
}

fn tail_translation_log(
    app: AppHandle,
    path: PathBuf,
    stop: Arc<AtomicBool>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut offset = fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
        while !stop.load(Ordering::Relaxed) {
            if let Ok(mut file) = OpenOptions::new().read(true).open(&path) {
                if file.metadata().map(|meta| meta.len()).unwrap_or(0) < offset {
                    offset = 0;
                }
                if file.seek(SeekFrom::Start(offset)).is_ok() {
                    let mut bytes = Vec::new();
                    if file.read_to_end(&mut bytes).is_ok() && !bytes.is_empty() {
                        offset += bytes.len() as u64;
                        for line in String::from_utf8_lossy(&bytes).lines() {
                            session_log(&app, "translation", line.to_string());
                        }
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(350));
        }
    })
}

fn session_marker_is_fresh(path: &Path) -> bool {
    path.metadata()
        .and_then(|metadata| metadata.modified())
        .and_then(|modified| modified.elapsed().map_err(std::io::Error::other))
        .map(|elapsed| elapsed <= Duration::from_secs(30))
        .unwrap_or(false)
}

fn wait_for_game_exit(
    child: &mut std::process::Child,
    session_marker: Option<&Path>,
    app: &AppHandle,
) -> i32 {
    let Some(marker) = session_marker else {
        return child
            .wait()
            .ok()
            .and_then(|status| status.code())
            .unwrap_or(-1);
    };

    let mut marker_seen = false;
    let mut launcher_exit: Option<(Instant, i32)> = None;
    loop {
        let marker_active = session_marker_is_fresh(marker);
        if marker_active && !marker_seen {
            marker_seen = true;
            session_log(
                app,
                "system",
                "Hook conectado. A sessão acompanhará o processo real do jogo.",
            );
        }

        if launcher_exit.is_none() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    let code = status.code().unwrap_or(-1);
                    launcher_exit = Some((Instant::now(), code));
                    if marker_active {
                        session_log(
                            app,
                            "system",
                            "Launcher concluído; o jogo continua ativo pelo hook.",
                        );
                    }
                }
                Ok(None) => {}
                Err(_) => launcher_exit = Some((Instant::now(), -1)),
            }
        }

        if let Some((exited_at, code)) = launcher_exit {
            if marker_seen {
                if !marker_active {
                    return code;
                }
            } else if exited_at.elapsed() >= Duration::from_secs(5) {
                return code;
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn update_integration_record(app: &AppHandle, game_id: &str) {
    let Ok(mut games) = load_games(app) else {
        return;
    };
    let Some(game) = games.iter_mut().find(|game| game.id == game_id) else {
        return;
    };
    let (ready, status) = integration_state(game);
    game.integration_status = Some(status);
    game.status = if game.model_installed && ready {
        "Pronto".into()
    } else {
        "Instalação pendente".into()
    };
    save_games(app, &games).ok();
}

fn wait_for_local_server(
    app: &AppHandle,
    child: &mut std::process::Child,
    port: u16,
) -> Result<(), String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let started = Instant::now();
    session_log(
        app,
        "system",
        format!("Aguardando o servidor local responder na porta {port}…"),
    );
    loop {
        if TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok() {
            session_log(
                app,
                "system",
                format!("Servidor local online na porta {port}."),
            );
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "O servidor local encerrou antes de ficar pronto ({status})."
            ));
        }
        if started.elapsed() >= Duration::from_secs(90) {
            return Err(format!(
                "O servidor local não respondeu na porta {port} em 90 segundos."
            ));
        }
        std::thread::sleep(Duration::from_millis(300));
    }
}

fn run_game_session(app: AppHandle, game: Game, project: PathBuf) -> Result<i32, String> {
    let executable = native_game_path(Path::new(&game.executable_path));
    let game_root = executable.parent().ok_or("Pasta do jogo inválida.")?;
    let mut translation_server;
    let mut log_tail = None;
    let stop_tail = Arc::new(AtomicBool::new(false));
    let server_port = if game.engine == "Unity" { 5001 } else { 5000 };

    if game.engine == "Unity" {
        let launcher = project.join("uat-unity/dist/UAT-Unity/lt.exe");
        if !launcher.is_file() {
            return Err(format!(
                "Runtime Unity não encontrado em {}",
                launcher.display()
            ));
        }
        let universal_models = models_directory(&app)?;
        session_log(
            &app,
            "system",
            format!(
                "Unity detectado: {} {}.",
                game.runtime.as_deref().unwrap_or("runtime desconhecido"),
                game.architecture
                    .as_deref()
                    .unwrap_or("arquitetura desconhecida")
            ),
        );

        let (integration_ready, _) = integration_state(&game);
        if !integration_ready {
            let mut install = Command::new(&launcher);
            install
                .arg("install")
                .arg(game.runtime.as_deref().unwrap_or("Mono"))
                .arg(game.architecture.as_deref().unwrap_or("x64"))
                .current_dir(launcher.parent().unwrap_or(&project))
                .env("UAT_GAME_DIR", game_root)
                .env("UAT_MODELS_DIR", &universal_models)
                .env("PYTHONIOENCODING", "utf-8");
            run_stage(install, &app, "Instalando BepInEx e XUnity dentro do jogo")?;
        } else {
            session_log(
                &app,
                "system",
                "BepInEx e XUnity já estão instalados e compatíveis.",
            );
        }

        let mut config = Command::new(&launcher);
        config
            .arg("config")
            .arg(&game.source_language)
            .arg(&game.target_language)
            .current_dir(launcher.parent().unwrap_or(&project))
            .env("UAT_GAME_DIR", game_root)
            .env("UAT_MODELS_DIR", &universal_models)
            .env("PYTHONIOENCODING", "utf-8");
        run_stage(config, &app, "Configurando XUnity e o fluxo universal")?;
        update_integration_record(&app, &game.id);

        let mut server = Command::new(&launcher);
        server
            .arg("server")
            .current_dir(launcher.parent().unwrap_or(&project))
            .env("UAT_GAME_DIR", game_root)
            .env("UAT_MODELS_DIR", &universal_models)
            .env("PYTHONIOENCODING", "utf-8");
        translation_server = spawn_streaming(server, &app, "servidor Unity")?;
    } else {
        let engine_root = project.join("uat-renpy");
        let launcher = engine_root.join("lt.exe");
        if !launcher.is_file() {
            return Err(format!(
                "Runtime Ren'Py não encontrado em {}",
                launcher.display()
            ));
        }
        install_renpy_hook(&engine_root, &game, &app)?;
        update_integration_record(&app, &game.id);
        log_tail = Some(tail_translation_log(
            app.clone(),
            game_root.join("uat/UAlogs/uat_log.txt"),
            stop_tail.clone(),
        ));
        let mut server = Command::new(&launcher);
        server
            .arg("__server__")
            .current_dir(&engine_root)
            .env("UAT_MODELS_DIR", models_directory(&app)?)
            .env("PYTHONIOENCODING", "utf-8");
        translation_server = spawn_streaming(server, &app, "servidor Ren'Py")?;
    }

    if let Err(error) = wait_for_local_server(&app, &mut translation_server, server_port) {
        translation_server.kill().ok();
        translation_server.wait().ok();
        stop_tail.store(true, Ordering::Relaxed);
        if let Some(tail) = log_tail {
            tail.join().ok();
        }
        return Err(error);
    }

    let session_marker = if game.engine == "Ren'Py" {
        let path = game_root.join("uat/uat_session.active");
        fs::remove_file(&path).ok();
        Some(path)
    } else {
        None
    };
    session_log(&app, "system", format!("Abrindo o jogo: {}", game.name));
    let mut command = Command::new(&executable);
    command.current_dir(game_root);
    let mut child = spawn_streaming(command, &app, "jogo")?;
    let code = wait_for_game_exit(&mut child, session_marker.as_deref(), &app);
    session_log(
        &app,
        "system",
        "Jogo encerrado. Finalizando o servidor local.",
    );
    translation_server.kill().ok();
    translation_server.wait().ok();
    stop_tail.store(true, Ordering::Relaxed);
    if let Some(tail) = log_tail {
        tail.join().ok();
    }
    Ok(code)
}

#[tauri::command]
fn launch_game(app: AppHandle, game_id: String) -> Result<(), String> {
    let mut games = load_games(&app)?;
    let game = games
        .iter_mut()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    if !game.model_installed {
        return Err("Instale o modelo configurado antes de iniciar o jogo.".into());
    }
    game.last_launch = Some(chrono::Utc::now().to_rfc3339());
    let game = game.clone();
    save_games(&app, &games)?;
    let project = project_root().ok_or("Pasta dos motores não encontrada.")?;
    session_log(
        &app,
        "system",
        format!("Preparando sessão para {}…", game.name),
    );
    std::thread::spawn(move || {
        let result = run_game_session(app.clone(), game, project);
        match result {
            Ok(code) => {
                app.emit("session-ended", serde_json::json!({"code":code}))
                    .ok();
            }
            Err(error) => {
                session_log(&app, "error", error);
                app.emit("session-ended", serde_json::json!({"code":-1}))
                    .ok();
            }
        }
    });
    Ok(())
}

fn project_root() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok();
    let cwd = std::env::current_dir().ok();
    executable.as_deref().and_then(Path::parent).into_iter()
        .chain(cwd.as_deref())
        .chain(Some(Path::new(env!("CARGO_MANIFEST_DIR"))))
        .find_map(|base| base.ancestors().find(|candidate| {
            candidate.join("uat-renpy").is_dir() && candidate.join("uat-unity").is_dir()
        }).map(Path::to_path_buf))
}

fn models_directory(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(root) = project_root() {
        return Ok(root.join("uat-renpy/models"));
    }
    Ok(app.path().app_data_dir().map_err(|e| e.to_string())?.join("models"))
}

#[tauri::command]
fn engine_health() -> Vec<EngineHealth> {
    let Some(root) = project_root() else {
        return vec![
            EngineHealth {
                engine: "Ren'Py".into(),
                source_found: false,
                runtime_found: false,
                model_found: false,
                details: "Fontes legadas fora do ambiente de desenvolvimento.".into(),
            },
            EngineHealth {
                engine: "Unity".into(),
                source_found: false,
                runtime_found: false,
                model_found: false,
                details: "Fontes legadas fora do ambiente de desenvolvimento.".into(),
            },
        ];
    };
    let renpy = root.join("uat-renpy");
    let unity = root.join("uat-unity");
    vec![
        EngineHealth {
            engine: "Ren'Py".into(),
            source_found: renpy.join("uat/uat_hook.py").is_file(),
            runtime_found: renpy.join("lt.exe").is_file(),
            model_found: renpy.join("models/argos-translate/packages").is_dir(),
            details: "Hook moderno e legado; servidor local LibreTranslate/Argos.".into(),
        },
        EngineHealth {
            engine: "Unity".into(),
            source_found: unity.join("uat_unity.py").is_file(),
            runtime_found: unity.join("dist/UAT-Unity/lt.exe").is_file(),
            model_found: renpy.join("models/argos-translate/packages").is_dir(),
            details: "Instalador BepInEx/XUnity para Mono e IL2CPP usando a biblioteca universal."
                .into(),
        },
    ]
}

#[tauri::command]
fn list_models(app: AppHandle) -> Result<Vec<TranslationModel>, String> {
    let games = load_games(&app).unwrap_or_default();
    let models_root = models_directory(&app)?.join("argos-translate");
    let installed = catalog::installed_packages(&models_root);
    let mut catalog = catalog::load_catalog(&models_root);
    for value in installed.values() {
        catalog.retain(|entry| catalog::pair_id(entry) != catalog::pair_id(value));
        catalog.push(value.clone());
    }
    Ok(catalog
        .into_iter()
        .filter_map(|value| {
            let from_code = value.get("from_code")?.as_str()?.to_string();
            let to_code = value.get("to_code")?.as_str()?.to_string();
            let id = format!("{from_code}-{to_code}");
            let used_by = games
                .iter()
                .filter(|game| {
                    game.model_installed
                        && game.source_language == from_code
                        && game.target_language == to_code
                })
                .count();
            Some(TranslationModel {
                installed: installed.contains_key(&id),
                id,
                from_name: value
                    .get("from_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or(&from_code)
                    .to_string(),
                to_name: value
                    .get("to_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or(&to_code)
                    .to_string(),
                version: value
                    .get("package_version")
                    .and_then(|v| v.as_str())
                    .unwrap_or("—")
                    .to_string(),
                from_code,
                to_code,
                used_by,
            })
        })
        .collect())
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
            delete_model,
            download_model,
            launch_game,
            engine_health,
            list_models
        ])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar UAT Desktop");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_missing_game() {
        assert!(inspect_game(Path::new("missing.exe")).is_err());
    }
}
