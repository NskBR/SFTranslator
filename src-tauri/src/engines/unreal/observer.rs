use std::{
    fs::{self, OpenOptions},
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    sync::{atomic::{AtomicBool, Ordering}, Arc},
    thread,
    time::Duration,
};

use tauri::{AppHandle, Manager};

use crate::{native_game_path, session::session_log, Game};
use super::{bridge, detect};

const MARKER: &str = ".sftranslator-observer";
const VERSION: &str = "ue4ss-v3.0.1-1147-g919ffaca";

pub(super) fn installed(project: &Path) -> bool {
    let bin = project.join("Binaries/Win64");
    bin.join(MARKER).is_file()
        && bin.join("dwmapi.dll").is_file()
        && bin.join("ue4ss/UE4SS.dll").is_file()
        && bin.join("ue4ss/Mods/SFTranslatorObserver/Scripts/main.lua").is_file()
}

fn install(game: &Game, runtimes: &Path, log_path: &Path, bridge_path: &Path, translate: bool) -> Result<PathBuf, String> {
    let executable = native_game_path(Path::new(&game.executable_path));
    let project = detect::packaged_root(&executable).ok_or("Pacote Unreal não encontrado.")?;
    let project_name = project.file_name().and_then(|name| name.to_str()).unwrap_or("");
    if !matches!(project_name, "CatIslandPetrichor" | "WomanSimulator") {
        return Err("O observador Unreal inicial foi preparado apenas para os jogos de teste conhecidos; nenhum hook foi instalado neste jogo.".into());
    }
    let bin = project.join("Binaries/Win64");
    if !bin.join(format!("{project_name}-Win64-Shipping.exe")).is_file() {
        return Err(format!("Binário Shipping do {project_name} não encontrado."));
    }
    let source = runtimes.join("unreal");
    let files = ["dwmapi.dll", "ue4ss/UE4SS.dll", "ue4ss/UE4SS-settings.ini",
        "ue4ss/LICENSE", "ue4ss/Mods/mods.txt", "ue4ss/Mods/mods.json"];
    for relative in files.iter().chain(std::iter::once(&"ue4ss/Mods/SFTranslatorObserver/Scripts/main.lua")) {
        if !source.join(relative).is_file() {
            return Err(format!("Observador Unreal ausente no aplicativo: {relative}. Execute npm run runtimes antes do build."));
        }
    }
    let marker = bin.join(MARKER);
    if !marker.is_file() && (bin.join("dwmapi.dll").exists() || bin.join("ue4ss").exists()) {
        return Err("Já existe dwmapi.dll ou ue4ss no jogo. O SFTranslator não vai sobrescrever outra instalação.".into());
    }
    if marker.is_file() && fs::read_to_string(&marker).ok().as_deref() != Some(VERSION) {
        return Err("Integração Unreal existente de outra versão; nenhum arquivo foi sobrescrito.".into());
    }
    let template = fs::read_to_string(source.join("ue4ss/Mods/SFTranslatorObserver/Scripts/main.lua"))
        .map_err(|error| error.to_string())?;
    if template.matches("OBSERVER_LOG_PATH").count() != 1
        || template.matches("OBSERVER_BRIDGE_PATH").count() != 1
        || template.matches("OBSERVER_TRANSLATE_ENABLED").count() != 1
        || template.matches("OBSERVER_PROFILE").count() != 1 {
        return Err("Template do observador Unreal inválido.".into());
    }
    let lua_path = serde_json::to_string(&log_path.to_string_lossy().to_string())
        .map_err(|error| error.to_string())?;
    let lua_bridge = serde_json::to_string(&bridge_path.to_string_lossy().to_string())
        .map_err(|error| error.to_string())?;
    // Mark ownership before copying so a failed installation can be retried safely.
    fs::write(&marker, VERSION).map_err(|error| error.to_string())?;
    for relative in files {
        let destination = bin.join(relative);
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::copy(source.join(relative), &destination)
            .map_err(|error| format!("Falha ao instalar {}: {error}", destination.display()))?;
    }
    let script_path = bin.join("ue4ss/Mods/SFTranslatorObserver/Scripts/main.lua");
    if let Some(parent) = script_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(script_path, template.replace("OBSERVER_LOG_PATH", &lua_path)
        .replace("OBSERVER_BRIDGE_PATH", &lua_bridge)
        .replace("OBSERVER_TRANSLATE_ENABLED", if translate { "true" } else { "false" })
        .replace("OBSERVER_PROFILE", if project_name == "WomanSimulator" { "\"woman\"" } else { "\"cat\"" }))
        .map_err(|error| error.to_string())?;
    Ok(project)
}

fn tail(app: AppHandle, path: PathBuf, stop: Arc<AtomicBool>, translate: bool) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut offset = 0;
        let mut remainder = Vec::new();
        let mut captured = 0;
        let mut ready = false;
        loop {
            if let Ok(mut file) = OpenOptions::new().read(true).open(&path) {
                if file.metadata().is_ok_and(|meta| meta.len() < offset) {
                    offset = 0;
                    remainder.clear();
                }
                if file.seek(SeekFrom::Start(offset)).is_ok() {
                    let mut bytes = Vec::new();
                    if file.read_to_end(&mut bytes).is_ok() {
                        offset += bytes.len() as u64;
                        remainder.extend(bytes);
                        while let Some(end) = remainder.iter().position(|byte| *byte == b'\n') {
                            let line = String::from_utf8_lossy(&remainder[..end]).trim_end_matches('\r').to_string();
                            remainder.drain(..=end);
                            let mut parts = line.splitn(3, '\t');
                            let kind = parts.next().unwrap_or("");
                            let widget = parts.next().unwrap_or("");
                            let value = parts.next().unwrap_or("");
                            match kind {
                                "READY" => {
                                    ready = true;
                                    session_log(&app, "system", if translate {
                                        "Hook Unreal conectado; aguardando textos para tradução."
                                    } else {
                                        "Observador Unreal conectado; capturando textos somente para análise."
                                    });
                                }
                                "HOOK" => session_log(&app, "system", format!("Observando {widget}: {value}")),
                                "TEXT" | "RICH" | "SNAP" => {
                                    captured += 1;
                                    let category = if widget.contains("NekoScript") || widget.contains("HeroineBubble") || widget.contains("Talk") || widget.contains("Messenger") {
                                        "diálogo provável"
                                    } else { "texto de interface" };
                                    session_log(&app, "output", format!("[UNREAL] {category} [{kind}] {value} ({widget})"));
                                }
                                "QUEUE" => session_log(&app, "system", format!("[UNREAL] Enviado para tradução: {value}")),
                                "APPLY" => session_log(&app, "translation", format!("[UNREAL] Widget atualizado: {value}")),
                                "STABLE" => session_log(&app, "system", format!("[UNREAL] Texto ainda no widget: {value}")),
                                "INTERCEPT" => session_log(&app, "translation", format!("[UNREAL] Substituído antes de SetText: {value}")),
                                "RETRY" => session_log(&app, "system", format!("[UNREAL] Reaplicando texto atualizado: {value}")),
                                "UNMAPPED" => session_log(&app, "system", format!("[UNREAL] Texto UMG sem regra [{widget}]: {value}")),
                                "MISS" | "REVERT" => session_log(&app, "error", format!("[UNREAL] {kind}: {value} ({widget})")),
                                "ERROR" => session_log(&app, "error", format!("Observador Unreal: {widget}: {value}")),
                                _ => {}
                            }
                        }
                    }
                }
            }
            if stop.load(Ordering::Relaxed) { break; }
            thread::sleep(Duration::from_millis(250));
        }
        if !ready {
            session_log(&app, "error", "O observador Unreal não confirmou conexão. Nenhum texto foi identificado nesta sessão.");
        } else if captured == 0 {
            session_log(&app, "system", "Observador conectado, mas nenhum texto passou pelos hooks UMG testados nesta sessão.");
        } else {
            session_log(&app, "system", format!("Unreal identificou {captured} texto(s) UMG nesta sessão."));
        }
    })
}

pub(super) fn start(app: &AppHandle, game: &Game, runtimes: &Path, port: Option<u16>, stop: Arc<AtomicBool>)
    -> Result<thread::JoinHandle<()>, String> {
    let log_dir = app.path().app_data_dir().map_err(|error| error.to_string())?.join("unreal-observer");
    fs::create_dir_all(&log_dir).map_err(|error| error.to_string())?;
    let log_path = log_dir.join(format!("{}.log", game.id));
    fs::write(&log_path, b"").map_err(|error| error.to_string())?;
    let bridge_path = log_dir.join(&game.id).join("bridge");
    for subdir in ["requests", "responses"] {
        let dir = bridge_path.join(subdir);
        fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
        for entry in fs::read_dir(&dir).map_err(|error| error.to_string())?.flatten() {
            if entry.file_type().is_ok_and(|kind| kind.is_file()) {
                fs::remove_file(entry.path()).ok();
            }
        }
    }
    let project = install(game, runtimes, &log_path, &bridge_path, port.is_some())?;
    session_log(app, "system", format!(
        "Hook Unreal instalado em {}. {}",
        project.display(), if port.is_some() { "Diálogos e menus selecionados usarão o Argos local." }
            else { "Captura somente leitura para mapear os widgets deste jogo." }
    ));
    let log_thread = tail(app.clone(), log_path, stop.clone(), port.is_some());
    let bridge_thread = port.map(|port| bridge::start(app.clone(), game.clone(), bridge_path, port, stop));
    Ok(thread::spawn(move || {
        log_thread.join().ok();
        if let Some(bridge_thread) = bridge_thread { bridge_thread.join().ok(); }
    }))
}
