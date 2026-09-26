use crate::{catalog, engines, load_games, required_model_ids, save_games, TranslationModel};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
};
use tauri::{AppHandle, Emitter, Manager};

fn project_root() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok();
    let cwd = std::env::current_dir().ok();
    executable
        .as_deref()
        .and_then(Path::parent)
        .into_iter()
        .chain(cwd.as_deref())
        .chain(Some(Path::new(env!("CARGO_MANIFEST_DIR"))))
        .find_map(|base| {
            base.ancestors()
                .find(|candidate| {
                    candidate.join("engines/uat-renpy").is_dir()
                        && candidate.join("engines/uat-unity").is_dir()
                })
                .map(Path::to_path_buf)
        })
}

pub(crate) fn models_directory(app: &AppHandle) -> Result<PathBuf, String> {
    let destination = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("models");
    if !destination.exists() {
        if let Some(root) = project_root() {
            let legacy = root.join("engines/uat-renpy/models");
            if legacy.is_dir() {
                engines::copy_legacy_models(&legacy, &destination)?;
            }
        }
        fs::create_dir_all(&destination).map_err(|e| e.to_string())?;
    }
    Ok(destination)
}

#[tauri::command]
pub(crate) fn delete_model(app: AppHandle, model_id: String) -> Result<(), String> {
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
    let installed = catalog::installed_packages(&models_directory(&app)?.join("argos-translate"));
    for game in &mut games {
        if required_model_ids(game).iter().any(|id| id == &model_id) {
            game.model_installed = required_model_ids(game)
                .iter()
                .all(|id| installed.contains_key(id));
            if !game.model_installed {
                game.status = "Modelo necessário".into();
            }
        }
    }
    save_games(&app, &games)
}

#[tauri::command]
pub(crate) fn download_model(app: AppHandle, model_id: String) -> Result<(), String> {
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

#[tauri::command]
pub(crate) fn list_models(app: AppHandle) -> Result<Vec<TranslationModel>, String> {
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
                    game.model_installed && required_model_ids(game).iter().any(|pair| pair == &id)
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
