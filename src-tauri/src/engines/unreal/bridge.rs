use std::{
    fs,
    path::{Path, PathBuf},
    sync::{atomic::{AtomicBool, Ordering}, Arc},
    thread,
    time::{Duration, Instant, SystemTime},
};

use reqwest::blocking::Client;
use sha2::{Digest, Sha256};
use tauri::AppHandle;

use crate::{session::session_log, Game};

pub(super) fn flow_key(game: &Game) -> String {
    let mut parts = vec![crate::cache_component(&game.source_language)];
    if game.flow_mode == "chain" { parts.push("en".into()); }
    parts.push(crate::cache_component(&game.target_language));
    parts.join("_")
}

pub(super) fn cache_directory(game: &Game) -> Result<PathBuf, String> {
    Ok(super::detect::packaged_root(&crate::native_game_path(Path::new(&game.executable_path)))
        .ok_or("Pacote Unreal não encontrado.")?
        .join("uat-unreal/cache")
        .join(flow_key(game)))
}

fn translate(client: &Client, port: u16, game: &Game, text: &str) -> Result<String, String> {
    let payload = serde_json::to_vec(&serde_json::json!({
        "q": text,
        "source": game.source_language,
        "target": game.target_language,
    })).map_err(|error| error.to_string())?;
    let response = client
        .post(format!("http://127.0.0.1:{port}/translate"))
        .header("Content-Type", "application/json")
        .body(payload)
        .send()
        .map_err(|error| error.to_string())?
        .error_for_status()
        .map_err(|error| error.to_string())?;
    let body: serde_json::Value = serde_json::from_slice(
        &response.bytes().map_err(|error| error.to_string())?
    ).map_err(|error| error.to_string())?;
    body.get("translatedText")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .ok_or("Resposta de tradução sem translatedText.".into())
}

fn write_response(path: &Path, contents: &str) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, contents).map_err(|error| error.to_string())?;
    fs::rename(&temporary, path).map_err(|error| error.to_string())
}

pub(super) fn start(
    app: AppHandle,
    game: Game,
    root: PathBuf,
    port: u16,
    stop: Arc<AtomicBool>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let client = match Client::builder().timeout(Duration::from_secs(45)).build() {
            Ok(client) => client,
            Err(error) => {
                session_log(&app, "error", format!("Unreal: cliente local indisponível: {error}"));
                return;
            }
        };
        let requests = root.join("requests");
        let responses = root.join("responses");
        let cache = match cache_directory(&game) {
            Ok(cache) => cache,
            Err(error) => {
                session_log(&app, "error", format!("Unreal: {error}"));
                return;
            }
        };
        if let Err(error) = fs::create_dir_all(&cache) {
            session_log(&app, "error", format!("Unreal: cache indisponível: {error}"));
            return;
        }
        while !stop.load(Ordering::Relaxed) {
            let Ok(entries) = fs::read_dir(&requests) else {
                thread::sleep(Duration::from_millis(100));
                continue;
            };
            let mut paths: Vec<_> = entries.flatten().map(|entry| entry.path())
                .filter(|path| path.extension().is_some_and(|ext| ext == "req"))
                .collect();
            paths.sort(); // d_ (dialogue) precedes m_ (menus)
            if paths.is_empty() {
                thread::sleep(Duration::from_millis(100));
                continue;
            }
            for path in paths.into_iter().take(8) {
                if stop.load(Ordering::Relaxed) { break; }
                let Some(stem) = path.file_stem().and_then(|stem| stem.to_str()) else { continue; };
                let interactive = stem.starts_with("d_");
                let queue_wait_ms = if interactive {
                    fs::metadata(&path).ok().and_then(|meta| meta.modified().ok())
                        .and_then(|created| SystemTime::now().duration_since(created).ok())
                        .map(|elapsed| elapsed.as_millis())
                } else { None };
                let started = Instant::now();
                let response_path = responses.join(format!("{stem}.res"));
                let Ok(text) = fs::read_to_string(&path) else {
                    fs::remove_file(&path).ok();
                    continue;
                };
                if text.len() > 8192 || text.is_empty() {
                    fs::remove_file(&path).ok();
                    continue;
                }
                let digest = format!("{:x}", Sha256::digest(text.as_bytes()));
                let cached = cache.join(format!("{digest}.txt"));
                let cached_value = fs::read_to_string(&cached);
                let from_cache = cached_value.is_ok();
                let translation = match cached_value {
                    Ok(value) => value,
                    Err(_) => match translate(&client, port, &game, &text) {
                        Ok(value) => {
                            if value != text { fs::write(&cached, &value).ok(); }
                            value
                        }
                        Err(error) => {
                            session_log(&app, "error", format!("Unreal {}: {error}; texto original preservado.", flow_key(&game)));
                            text.clone()
                        }
                    },
                };
                if let Err(error) = write_response(&response_path, &translation) {
                    session_log(&app, "error", format!("Unreal: resposta não entregue: {error}"));
                }
                if interactive {
                    session_log(&app, "system", format!(
                        "[UNREAL] Diálogo: fila {} ms, resposta {} ms{}.",
                        queue_wait_ms.unwrap_or_default(), started.elapsed().as_millis(),
                        if from_cache { " (cache)" } else { "" }
                    ));
                }
                fs::remove_file(&path).ok();
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn direct_and_chained_cache_keys_differ() {
        let mut game = Game {
            id: "id".into(), name: "sample".into(), executable_path: "x".into(),
            engine: "Unreal".into(), runtime: None, architecture: None, status: String::new(),
            source_language: "ja".into(), target_language: "pb".into(),
            added_at: String::new(), last_launch: None, icon_data: None, model_installed: false,
            detected_language: None, language_confidence: None, integration_status: None,
            flow_mode: "direct".into(), intermediate_language: None,
        };
        assert_eq!(flow_key(&game), "ja_pb");
        game.flow_mode = "chain".into();
        assert_eq!(flow_key(&game), "ja_en_pb");
    }
}
