use std::{io::Read, path::PathBuf, time::Duration};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, WebviewWindow};

const MAX_IMAGE: usize = 20 * 1024 * 1024;
const BASE: &str = "https://raw.githubusercontent.com/NskBR/SFDownloader-App/main/themes/wallpapers/";

#[derive(Clone, Deserialize, Serialize)]
pub struct OfficialAsset {
    pub id: String,
    pub file: String,
    pub sha256: String,
    pub bytes: u64,
}

fn catalog() -> Result<Vec<OfficialAsset>, String> {
    let assets: Vec<OfficialAsset> = serde_json::from_str(include_str!("official_manifest.json"))
        .map_err(|e| format!("Catálogo de temas inválido: {e}"))?;
    for asset in &assets {
        let valid_id = !asset.id.is_empty()
            && asset.id.len() <= 80
            && asset.id.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-');
        let valid_file = !asset.file.is_empty()
            && !asset.file.contains("..")
            && asset.file.ends_with(".png")
            && asset.file.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-' || c == b'/' || c == b'.');
        let valid_hash = asset.sha256.len() == 64 && asset.sha256.bytes().all(|c| c.is_ascii_hexdigit());
        if !valid_id || !valid_file || !valid_hash || asset.bytes == 0 || asset.bytes > MAX_IMAGE as u64 {
            return Err("O catálogo de temas contém um arquivo inválido.".into());
        }
    }
    Ok(assets)
}

fn root(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app.path().app_data_dir().map_err(|e| e.to_string())?.join("official-themes"))
}

fn group<'a>(assets: &'a [OfficialAsset], id: &str) -> Result<[&'a OfficialAsset; 3], String> {
    if id.ends_with("-medium") || id.ends_with("-compact") { return Err("Tema desconhecido.".into()); }
    let find = |suffix: &str| assets.iter().find(|asset| asset.id == format!("{id}{suffix}"));
    match (find(""), find("-medium"), find("-compact")) {
        (Some(main), Some(medium), Some(compact)) => Ok([main, medium, compact]),
        _ => Err("Tema desconhecido ou incompleto no catálogo.".into()),
    }
}

pub(super) fn known_theme(id: &str) -> bool {
    catalog().is_ok_and(|assets| group(&assets, id).is_ok())
}

fn valid_cached(path: &std::path::Path, asset: &OfficialAsset) -> bool {
    let Ok(bytes) = std::fs::read(path) else { return false; };
    bytes.len() as u64 == asset.bytes && format!("{:x}", Sha256::digest(&bytes)) == asset.sha256
}

#[tauri::command]
pub fn official_theme_catalog() -> Result<Vec<OfficialAsset>, String> { catalog() }

#[tauri::command]
pub async fn installed_official_themes(app: AppHandle) -> Result<Vec<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let assets = catalog()?;
        let folder = root(&app)?;
        Ok(assets.iter().filter(|asset| !asset.id.ends_with("-medium") && !asset.id.ends_with("-compact"))
            .filter(|asset| group(&assets, &asset.id).is_ok_and(|parts| parts.iter().all(|part|
                valid_cached(&folder.join(format!("{}.image", part.sha256)), part))))
            .map(|asset| asset.id.clone()).collect())
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn download_official_theme(app: AppHandle, window: WebviewWindow, id: String) -> Result<(), String> {
    if window.label() != "main" { return Err("Baixe temas pelas configurações.".into()); }
    tauri::async_runtime::spawn_blocking(move || {
        let assets = catalog()?;
        let entries = group(&assets, &id)?;
        let folder = root(&app)?;
        std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(60))
            .redirect(reqwest::redirect::Policy::none())
            .build().map_err(|e| e.to_string())?;
        for asset in entries {
            let destination = folder.join(format!("{}.image", asset.sha256));
            if valid_cached(&destination, asset) { continue; }
            let url = format!("{BASE}{}", asset.file);
            let mut response = client.get(url).send().map_err(|_| "Não foi possível baixar o tema. Verifique sua conexão.")?
                .error_for_status().map_err(|_| "Imagem do tema indisponível no GitHub.")?;
            let mut bytes = Vec::new();
            response.by_ref().take(MAX_IMAGE as u64 + 1).read_to_end(&mut bytes)
                .map_err(|_| "Download do tema interrompido.")?;
            super::theme_images::validate(&bytes)?;
            if bytes.len() as u64 != asset.bytes || format!("{:x}", Sha256::digest(&bytes)) != asset.sha256 {
                return Err("A imagem do tema não passou na verificação de integridade.".into());
            }
            let temporary = folder.join(format!("{}.pending", asset.sha256));
            std::fs::write(&temporary, bytes).map_err(|e| e.to_string())?;
            if destination.exists() { std::fs::remove_file(&destination).map_err(|e| e.to_string())?; }
            std::fs::rename(&temporary, &destination).map_err(|e| e.to_string())?;
        }
        Ok(())
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub fn delete_official_theme(app: AppHandle, window: WebviewWindow, id: String) -> Result<(), String> {
    if window.label() != "main" { return Err("Gerencie temas pelas configurações.".into()); }
    let assets = catalog()?;
    let entries = group(&assets, &id)?;
    let folder = root(&app)?;
    for asset in entries {
        match std::fs::remove_file(folder.join(format!("{}.image", asset.sha256))) {
            Ok(()) => (),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(())
}

pub(super) fn official_image_path(app: &AppHandle, id: &str) -> Result<PathBuf, String> {
    Ok(root(app)?.join(format!("{id}.image")))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn catalog_has_complete_groups_and_rejects_suffix_as_theme() {
        let assets = catalog().unwrap();
        assert!(group(&assets, "cyberpunk").is_ok());
        assert!(group(&assets, "cyberpunk--v-sunset").is_ok());
        assert!(group(&assets, "cyberpunk-medium").is_err());
        assert!(group(&assets, "../escape").is_err());
    }
}
