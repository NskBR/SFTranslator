use std::{
    fs::{self, File},
    io::{Read, Write},
    path::{Path, PathBuf},
    process::Command,
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};

use serde::Serialize;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager};

const RELEASES_URL: &str = "https://github.com/NskBR/SFTranslator/releases";
const API_URL: &str = "https://api.github.com/repos/NskBR/SFTranslator/releases/latest";

#[derive(Clone, Serialize)]
pub(crate) struct UpdateCheckResult {
    pub available: bool,
    pub current_version: String,
    pub latest_version: String,
    pub release_url: String,
    pub release_name: Option<String>,
    pub release_notes: Option<String>,
    pub installer_name: Option<String>,
    pub installer_size: Option<u64>,
    pub install_supported: bool,
}

#[derive(Clone, Serialize)]
pub(crate) struct UpdateDownloadProgress {
    pub status: String,
    pub downloaded_bytes: u64,
    pub total_bytes: Option<u64>,
    pub installer_name: Option<String>,
    pub message: Option<String>,
}

impl Default for UpdateDownloadProgress {
    fn default() -> Self {
        Self { status: "idle".into(), downloaded_bytes: 0, total_bytes: None,
            installer_name: None, message: None }
    }
}

#[derive(Clone)]
struct ApprovedInstaller {
    url: String,
    name: String,
    size: u64,
    digest: String,
}

#[derive(Default)]
struct UpdateRuntime {
    progress: UpdateDownloadProgress,
    approved: Option<ApprovedInstaller>,
    ready_path: Option<PathBuf>,
    cancellation: Option<Arc<AtomicBool>>,
}

static UPDATE_RUNTIME: OnceLock<Mutex<UpdateRuntime>> = OnceLock::new();

fn runtime() -> &'static Mutex<UpdateRuntime> {
    UPDATE_RUNTIME.get_or_init(|| Mutex::new(UpdateRuntime::default()))
}

fn set_progress(app: &AppHandle, progress: UpdateDownloadProgress) {
    if let Ok(mut state) = runtime().lock() { state.progress = progress.clone(); }
    let _ = app.emit("update-download-progress", progress);
}

fn version_parts(value: &str) -> Option<[u64; 3]> {
    let value = value.strip_prefix('v').unwrap_or(value);
    let mut parts = value.split('.');
    let parsed = [parts.next()?.parse().ok()?, parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?];
    if parts.next().is_some() { None } else { Some(parsed) }
}

fn official_installer_url(value: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(value) else { return false };
    url.scheme() == "https" && url.host_str() == Some("github.com")
        && url.path().starts_with("/NskBR/SFTranslator/releases/download/")
        && url.path().to_ascii_lowercase().ends_with(".exe")
}

fn safe_installer_name(name: &str) -> bool {
    !name.is_empty() && name.len() <= 180 && name.ends_with(".exe")
        && name.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
        && name.to_ascii_lowercase().starts_with("sftranslator_")
        && name.to_ascii_lowercase().contains("_x64-setup.exe")
}

fn select_installer(release: &serde_json::Value, version: &str) -> Option<ApprovedInstaller> {
    let assets = release["assets"].as_array()?;
    assets.iter().find_map(|asset| {
        let name = asset["name"].as_str()?;
        let url = asset["browser_download_url"].as_str()?;
        let digest = asset["digest"].as_str()?.strip_prefix("sha256:")?;
        let size = asset["size"].as_u64()?;
        if !safe_installer_name(name) || !name.contains(&format!("_{version}_"))
            || !official_installer_url(url) || size == 0 || digest.len() != 64
            || !digest.chars().all(|c| c.is_ascii_hexdigit()) { return None }
        Some(ApprovedInstaller { url: url.into(), name: name.into(), size,
            digest: digest.to_ascii_lowercase() })
    })
}

fn updates_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let directory = app.path().app_data_dir().map_err(|e| e.to_string())?.join("updates");
    fs::create_dir_all(&directory).map_err(|e| format!("Falha ao preparar atualizações: {e}"))?;
    Ok(directory)
}

fn check_release() -> Result<(UpdateCheckResult, Option<ApprovedInstaller>), String> {
    let current_version = env!("CARGO_PKG_VERSION").to_string();
    let client = reqwest::blocking::Client::builder()
        .user_agent("SFTranslator-updater")
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(20))
        .build().map_err(|e| e.to_string())?;
    let response = client.get(API_URL).send()
        .map_err(|e| format!("Não foi possível consultar o GitHub: {e}"))?
        .error_for_status().map_err(|e| format!("GitHub recusou a consulta: {e}"))?;
    let release: serde_json::Value = serde_json::from_reader(response)
        .map_err(|e| format!("Resposta inválida do GitHub: {e}"))?;
    let tag = release["tag_name"].as_str().unwrap_or("");
    let latest = version_parts(tag).ok_or("O release mais recente não usa uma versão X.Y.Z válida.")?;
    let current = version_parts(&current_version).ok_or("Versão local inválida.")?;
    let latest_version = tag.trim_start_matches('v').to_string();
    let available = latest > current;
    let installer = available.then(|| select_installer(&release, &latest_version)).flatten();
    let release_url = release["html_url"].as_str().unwrap_or(RELEASES_URL);
    let release_url = if release_url.starts_with("https://github.com/NskBR/SFTranslator/releases/") {
        release_url.to_string()
    } else { RELEASES_URL.into() };
    let result = UpdateCheckResult {
        available, current_version, latest_version, release_url,
        release_name: release["name"].as_str().map(str::to_string),
        release_notes: release["body"].as_str().map(str::to_string),
        installer_name: installer.as_ref().map(|asset| asset.name.clone()),
        installer_size: installer.as_ref().map(|asset| asset.size),
        install_supported: !cfg!(debug_assertions),
    };
    Ok((result, installer))
}

#[tauri::command]
pub(crate) async fn check_for_updates() -> Result<UpdateCheckResult, String> {
    let (result, installer) = tauri::async_runtime::spawn_blocking(check_release)
        .await.map_err(|e| format!("Falha ao verificar atualizações: {e}"))??;
    if let Ok(mut state) = runtime().lock() { state.approved = installer; }
    Ok(result)
}

#[tauri::command]
pub(crate) fn update_download_status(app: AppHandle) -> UpdateDownloadProgress {
    let progress = runtime().lock().map(|state| state.progress.clone()).unwrap_or_default();
    if progress.status != "idle" { return progress }
    let Ok(path) = updates_dir(&app) else { return progress };
    let error_path = path.join("last-error.txt");
    let Ok(message) = fs::read_to_string(&error_path) else { return progress };
    let _ = fs::remove_file(error_path);
    UpdateDownloadProgress { status: "failed".into(), message: Some(message), ..progress }
}

fn download_installer(app: &AppHandle, asset: &ApprovedInstaller, cancelled: &AtomicBool) -> Result<PathBuf, String> {
    let directory = updates_dir(app)?;
    let destination = directory.join(&asset.name);
    let temporary = directory.join(format!("{}.part", asset.name));
    let _ = fs::remove_file(&temporary);
    let result = (|| {
        let client = reqwest::blocking::Client::builder()
            .user_agent("SFTranslator-updater")
            .connect_timeout(Duration::from_secs(15))
            .timeout(Duration::from_secs(900))
            .build().map_err(|e| e.to_string())?;
        let mut response = client.get(&asset.url).send()
            .map_err(|e| format!("Falha ao baixar atualização: {e}"))?
            .error_for_status().map_err(|e| format!("GitHub recusou o download: {e}"))?;
        let mut output = File::create(&temporary).map_err(|e| format!("Falha ao criar arquivo temporário: {e}"))?;
        let mut digest = Sha256::new();
        let mut buffer = [0_u8; 64 * 1024];
        let mut downloaded = 0_u64;
        let mut last_emit = Instant::now() - Duration::from_secs(1);
        loop {
            if cancelled.load(Ordering::Relaxed) { return Err("Download cancelado.".into()) }
            let count = response.read(&mut buffer).map_err(|e| format!("Falha no download: {e}"))?;
            if count == 0 { break }
            output.write_all(&buffer[..count]).map_err(|e| format!("Falha ao gravar atualização: {e}"))?;
            digest.update(&buffer[..count]);
            downloaded += count as u64;
            if last_emit.elapsed() >= Duration::from_millis(150) {
                set_progress(app, UpdateDownloadProgress { status: "downloading".into(),
                    downloaded_bytes: downloaded, total_bytes: Some(asset.size),
                    installer_name: Some(asset.name.clone()), message: None });
                last_emit = Instant::now();
            }
        }
        output.flush().map_err(|e| e.to_string())?;
        drop(output);
        if cancelled.load(Ordering::Relaxed) { return Err("Download cancelado.".into()) }
        if downloaded != asset.size { return Err("O instalador foi baixado de forma incompleta.".into()) }
        if format!("{:x}", digest.finalize()) != asset.digest {
            return Err("O SHA-256 do instalador não confere com o release oficial.".into())
        }
        if destination.exists() { fs::remove_file(&destination).map_err(|e| e.to_string())?; }
        fs::rename(&temporary, &destination).map_err(|e| format!("Falha ao finalizar o download: {e}"))?;
        Ok(destination)
    })();
    if result.is_err() { let _ = fs::remove_file(temporary); }
    result
}

#[tauri::command]
pub(crate) fn download_update(app: AppHandle) -> Result<(), String> {
    let (asset, cancelled) = {
        let mut state = runtime().lock().map_err(|_| "Atualizador indisponível.")?;
        if !matches!(state.progress.status.as_str(), "idle" | "failed") {
            return Err("Já existe uma atualização em andamento.".into())
        }
        let asset = state.approved.clone().ok_or("Nenhum instalador oficial verificado está disponível.")?;
        if cfg!(debug_assertions) { return Err("Instale a versão distribuída para usar atualizações automáticas.".into()) }
        let cancelled = Arc::new(AtomicBool::new(false));
        state.cancellation = Some(cancelled.clone());
        state.ready_path = None;
        state.progress = UpdateDownloadProgress { status: "downloading".into(),
            downloaded_bytes: 0, total_bytes: Some(asset.size), installer_name: Some(asset.name.clone()), message: None };
        (asset, cancelled)
    };
    let handle = app.clone();
    std::thread::spawn(move || {
        let outcome = download_installer(&handle, &asset, &cancelled);
        if let Ok(mut state) = runtime().lock() {
            state.cancellation = None;
            state.ready_path = outcome.as_ref().ok().cloned();
        }
        match outcome {
            Ok(_) => set_progress(&handle, UpdateDownloadProgress { status: "ready".into(),
                downloaded_bytes: asset.size, total_bytes: Some(asset.size),
                installer_name: Some(asset.name), message: Some("Instalador verificado e pronto.".into()) }),
            Err(message) => set_progress(&handle, UpdateDownloadProgress { status: "failed".into(),
                downloaded_bytes: 0, total_bytes: Some(asset.size),
                installer_name: Some(asset.name), message: Some(message) }),
        }
    });
    Ok(())
}

#[tauri::command]
pub(crate) fn cancel_update_download(app: AppHandle) -> Result<(), String> {
    let mut state = runtime().lock().map_err(|_| "Atualizador indisponível.")?;
    let token = state.cancellation.as_ref().ok_or("Nenhum download está ativo.")?;
    token.store(true, Ordering::Relaxed);
    state.progress.status = "cancelling".into();
    let progress = state.progress.clone();
    drop(state);
    let _ = app.emit("update-download-progress", progress);
    Ok(())
}

fn write_helper(app: &AppHandle, installer: &Path, digest: &str) -> Result<(PathBuf, PathBuf, PathBuf, PathBuf), String> {
    let root = updates_dir(app)?;
    let folder = root.join(uuid::Uuid::new_v4().to_string());
    fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let script = folder.join("install.ps1");
    let config = folder.join("config.json");
    let ready = folder.join("ready");
    let go = folder.join("go");
    let error = folder.join("error");
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    fs::write(&script, format!("\u{feff}{}", include_str!("update-helper.ps1")))
        .map_err(|e| format!("Falha ao preparar instalador: {e}"))?;
    let payload = serde_json::json!({"installer": installer, "sha256": digest,
        "executable": executable, "destination": executable.parent(),
        "parent": std::process::id(), "ready": ready, "go": go, "error": error,
        "lastError": root.join("last-error.txt")});
    fs::write(&config, serde_json::to_vec(&payload).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    Ok((script, config, ready, go))
}

#[tauri::command]
pub(crate) async fn install_downloaded_update(app: AppHandle) -> Result<(), String> {
    if cfg!(debug_assertions) { return Err("A instalação automática não está disponível no modo de desenvolvimento.".into()) }
    if crate::session::game_is_running() {
        return Err("Encerre o jogo ativo antes de instalar a atualização.".into())
    }
    let (installer, digest) = {
        let state = runtime().lock().map_err(|_| "Atualizador indisponível.")?;
        if state.progress.status != "ready" { return Err("Nenhum instalador verificado está pronto.".into()) }
        let installer = state.ready_path.clone().ok_or("Instalador ausente.")?;
        let approved = state.approved.as_ref().ok_or("Release não verificado.")?;
        if installer.file_name().and_then(|name| name.to_str()) != Some(approved.name.as_str())
            || !installer.is_file() { return Err("Instalador verificado não foi encontrado.".into()) }
        (installer, approved.digest.clone())
    };
    let (script, config, ready, go) = write_helper(&app, &installer, &digest)?;
    let error_path = script.parent().ok_or("Pasta de atualização inválida")?.join("error");
    let mut command = Command::new("powershell.exe");
    command.args(["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass", "-File"]).arg(script)
        .arg("-ConfigPath").arg(config);
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|e| format!("Falha ao iniciar atualização: {e}"))?;
    let deadline = Instant::now() + Duration::from_secs(30);
    while !ready.exists() {
        if error_path.exists() { return Err(fs::read_to_string(&error_path).unwrap_or_else(|_| "Falha ao verificar instalador.".into())) }
        if deadline <= Instant::now() || child.try_wait().map_err(|e| e.to_string())?.is_some() {
            let _ = child.kill();
            return Err("O instalador não ficou pronto. O aplicativo continua aberto.".into())
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    if crate::session::game_is_running() {
        let _ = child.kill();
        return Err("Encerre o jogo ativo antes de instalar a atualização.".into())
    }
    set_progress(&app, UpdateDownloadProgress { status: "installing".into(),
        downloaded_bytes: 0, total_bytes: None, installer_name: None,
        message: Some("Fechando o aplicativo para instalar a atualização…".into()) });
    fs::write(go, "install").map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
pub(crate) fn open_release_page() -> Result<(), String> {
    #[cfg(windows)] {
        Command::new("explorer.exe").arg(RELEASES_URL).spawn()
            .map_err(|e| format!("Não foi possível abrir os releases: {e}"))?;
        Ok(())
    }
    #[cfg(not(windows))]
    { Err("Página de releases disponível em https://github.com/NskBR/SFTranslator/releases".into()) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compares_valid_release_versions() {
        assert!(version_parts("v0.2.0") > version_parts("0.1.9"));
        assert_eq!(version_parts("test-2.0"), None);
        assert_eq!(version_parts("v0.1.0-rc1"), None);
    }

    #[test]
    fn selects_only_official_digest_verified_installer() {
        let release = serde_json::json!({"assets": [{"name": "SFTranslator_0.2.0_x64-setup.exe",
            "browser_download_url": "https://github.com/NskBR/SFTranslator/releases/download/v0.2.0/SFTranslator_0.2.0_x64-setup.exe",
            "size": 100, "digest": format!("sha256:{}", "a".repeat(64))}]});
        assert!(select_installer(&release, "0.2.0").is_some());
        assert!(select_installer(&release, "0.1.0").is_none());
        assert!(!official_installer_url("https://example.com/SFTranslator_0.2.0_x64-setup.exe"));
    }
}
