use std::{
    fs::{self, File},
    io::{Read, Write},
    path::{Path, PathBuf},
    process::Command,
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, Manager};

const UPDATE_BASE: &str = "https://sftranslator-updates.nskbr.workers.dev/sftranslator/desktop";
const MANIFEST_LIMIT: u64 = 64 * 1024;
const INSTALLER_NAME: &str = "SFTranslator-Windows-x64-setup.exe";

#[derive(Deserialize)]
struct ReleaseManifest {
    app: String,
    platform: String,
    version: String,
    file: String,
    url: String,
    size: u64,
    sha256: String,
    notes: Option<String>,
}

fn manifest_url() -> String {
    format!("{UPDATE_BASE}/latest.json")
}

impl ReleaseManifest {
    fn installer(&self) -> Result<ApprovedInstaller, String> {
        if self.app != "SFTranslator"
            || self.platform != "windows-x64"
            || version_parts(&self.version).is_none()
            || self.file != INSTALLER_NAME
            || self.url != format!("{UPDATE_BASE}/releases/{}/{INSTALLER_NAME}", self.version)
            || self.size == 0
            || self.sha256.len() != 64
            || !self.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
        {
            return Err("Manifesto de atualização inválido.".into());
        }
        Ok(ApprovedInstaller {
            url: self.url.clone(),
            name: self.file.clone(),
            size: self.size,
            digest: self.sha256.to_ascii_lowercase(),
        })
    }
}

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
    ready: Option<(PathBuf, ApprovedInstaller)>,
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
    let mut parts = value.split('.');
    let mut version = [0; 3];
    for number in &mut version {
        let part = parts.next()?;
        *number = part.parse().ok()?;
        if number.to_string() != part {
            return None;
        }
    }
    parts.next().is_none().then_some(version)
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
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(20))
        .build().map_err(|e| e.to_string())?;
    let response = client.get(manifest_url()).send()
        .map_err(|e| format!("Não foi possível consultar o servidor de atualizações: {e}"))?;
    if response.status() != reqwest::StatusCode::OK {
        return Err(format!("Servidor de atualizações respondeu HTTP {}.", response.status()));
    }
    let mut bytes = Vec::new();
    response.take(MANIFEST_LIMIT + 1).read_to_end(&mut bytes)
        .map_err(|e| format!("Falha ao ler manifesto: {e}"))?;
    if bytes.len() as u64 > MANIFEST_LIMIT {
        return Err("Manifesto excede o tamanho permitido.".into());
    }
    let manifest: ReleaseManifest = serde_json::from_slice(&bytes)
        .map_err(|e| format!("Manifesto inválido: {e}"))?;
    let validated = manifest.installer()?;
    let latest = version_parts(&manifest.version).ok_or("Versão remota inválida.")?;
    let current = version_parts(&current_version).ok_or("Versão local inválida.")?;
    let available = latest > current;
    let installer = available.then_some(validated);
    let result = UpdateCheckResult {
        available, current_version, latest_version: manifest.version.clone(), release_url: manifest_url(),
        release_name: Some(format!("SFTranslator {}", manifest.version)),
        release_notes: manifest.notes,
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
        .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(15))
            .timeout(Duration::from_secs(900))
            .build().map_err(|e| e.to_string())?;
        let mut response = client.get(&asset.url).send()
            .map_err(|e| format!("Falha ao baixar atualização: {e}"))?
            .error_for_status().map_err(|e| format!("Servidor recusou o download: {e}"))?;
        if response.status() != reqwest::StatusCode::OK
            || response.content_length().is_some_and(|length| length != asset.size)
        {
            return Err("Resposta inválida para o instalador.".into());
        }
        let mut output = File::create(&temporary).map_err(|e| format!("Falha ao criar arquivo temporário: {e}"))?;
        let mut digest = Sha256::new();
        let mut buffer = [0_u8; 64 * 1024];
        let mut downloaded = 0_u64;
        let mut last_emit = Instant::now() - Duration::from_secs(1);
        loop {
            if cancelled.load(Ordering::Relaxed) { return Err("Download cancelado.".into()) }
            let count = response.read(&mut buffer).map_err(|e| format!("Falha no download: {e}"))?;
            if count == 0 { break }
            if count as u64 > asset.size - downloaded {
                return Err("O instalador excede o tamanho indicado no manifesto.".into());
            }
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
        state.ready = None;
        state.progress = UpdateDownloadProgress { status: "downloading".into(),
            downloaded_bytes: 0, total_bytes: Some(asset.size), installer_name: Some(asset.name.clone()), message: None };
        (asset, cancelled)
    };
    let handle = app.clone();
    std::thread::spawn(move || {
        let outcome = download_installer(&handle, &asset, &cancelled);
        if let Ok(mut state) = runtime().lock() {
            state.cancellation = None;
            state.ready = outcome.as_ref().ok().map(|path| (path.clone(), asset.clone()));
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
        let (installer, approved) = state.ready.clone().ok_or("Instalador ausente.")?;
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
        Command::new("explorer.exe").arg(manifest_url()).spawn()
            .map_err(|e| format!("Não foi possível abrir os releases: {e}"))?;
        Ok(())
    }
    #[cfg(not(windows))]
    { Err(format!("Manifesto disponível em {}", manifest_url())) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_the_versioned_official_installer() {
        let mut manifest = ReleaseManifest {
            app: "SFTranslator".into(),
            platform: "windows-x64".into(),
            version: "0.2.0".into(),
            file: INSTALLER_NAME.into(),
            url: format!("{UPDATE_BASE}/releases/0.2.0/{INSTALLER_NAME}"),
            size: 100,
            sha256: "a".repeat(64),
            notes: None,
        };
        assert!(version_parts("0.2.0") > version_parts("0.1.7"));
        assert!(manifest.installer().is_ok());
        manifest.version = "0.2.1".into();
        assert!(manifest.installer().is_err());
        manifest.url = format!("https://example.invalid/{INSTALLER_NAME}");
        assert!(manifest.installer().is_err());
        assert!(version_parts("00.2.0").is_none());
    }
}
