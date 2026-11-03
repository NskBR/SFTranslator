use std::{collections::HashMap, fs, sync::{Mutex, OnceLock}};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

#[derive(Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct GameMetrics {
    words: u64,
    worked: bool,
    failed: bool,
}

#[derive(Default, Serialize, Deserialize)]
struct MetricsStore {
    #[serde(default)]
    games: HashMap<String, GameMetrics>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MetricsSnapshot {
    translated_words: u64,
    worked_games: usize,
    failed_games: usize,
}

static STORE: OnceLock<Mutex<Option<MetricsStore>>> = OnceLock::new();

fn path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app.path().app_data_dir().map_err(|e| e.to_string())?.join("translation-metrics.json"))
}

fn with_store<T>(app: &AppHandle, f: impl FnOnce(&mut MetricsStore) -> T) -> Result<T, String> {
    let mut guard = STORE.get_or_init(|| Mutex::new(None)).lock().map_err(|e| e.to_string())?;
    if guard.is_none() {
        let data = match fs::read(path(app)?) {
            Ok(bytes) => serde_json::from_slice(&bytes).map_err(|e| format!("Métricas inválidas: {e}"))?,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => MetricsStore::default(),
            Err(error) => return Err(error.to_string()),
        };
        *guard = Some(data);
    }
    Ok(f(guard.as_mut().unwrap()))
}

fn persist(app: &AppHandle, store: &MetricsStore) -> Result<(), String> {
    let path = path(app)?;
    if let Some(parent) = path.parent() { fs::create_dir_all(parent).map_err(|e| e.to_string())?; }
    fs::write(path, serde_json::to_vec_pretty(store).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

pub(crate) fn record_words(app: &AppHandle, game_id: &str, words: u64) -> Result<(), String> {
    if words == 0 { return Ok(()); }
    with_store(app, |store| {
        let game = store.games.entry(game_id.to_owned()).or_default();
        game.words = game.words.saturating_add(words);
        game.worked = true;
        game.failed = false;
        persist(app, store)
    })?
}

pub(crate) fn record_failure(app: &AppHandle, game_id: &str) -> Result<(), String> {
    with_store(app, |store| {
        let game = store.games.entry(game_id.to_owned()).or_default();
        game.failed = true;
        game.worked = false;
        persist(app, store)
    })?
}

pub(crate) fn word_marker(line: &str) -> Option<u64> {
    let number = line.split_once("[METRIC] words=").map(|(_, tail)| tail)
        .or_else(|| line.split_once("TRAD_METRIC: ").map(|(_, tail)| tail))?;
    number.trim().parse().ok()
}

#[tauri::command]
pub(crate) fn translation_metrics(app: AppHandle) -> Result<MetricsSnapshot, String> {
    with_store(&app, |store| MetricsSnapshot {
        translated_words: store.games.values().map(|game| game.words).sum(),
        worked_games: store.games.values().filter(|game| game.worked).count(),
        failed_games: store.games.values().filter(|game| game.failed).count(),
    })
}

#[cfg(test)]
mod tests {
    use super::word_marker;
    #[test]
    fn parses_only_explicit_success_markers() {
        assert_eq!(word_marker("[METRIC] words=12"), Some(12));
        assert_eq!(word_marker("[12:03] [ OK ] TRAD_METRIC: 7"), Some(7));
        assert_eq!(word_marker("[TRAD] failed words=7"), None);
    }
}
