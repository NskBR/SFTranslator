//! Exercise the Unreal detector in isolation while the Tauri test binary is unavailable.

use std::fs;

mod detector {
    include!(concat!(env!("CARGO_MANIFEST_DIR"), "/src/engines/unreal/detect.rs"));

    pub fn find(path: &std::path::Path) -> Option<std::path::PathBuf> { packaged_root(path) }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::temp_dir().join(format!("sftranslator-unreal-example-{}", uuid::Uuid::new_v4()));
    let project = root.join("Example");
    fs::create_dir_all(project.join("Binaries/Win64"))?;
    fs::create_dir_all(project.join("Content/Paks"))?;
    let launcher = root.join("Example.exe");
    let shipping = project.join("Binaries/Win64/Example-Win64-Shipping.exe");
    fs::write(&launcher, b"fixture")?;
    fs::write(&shipping, b"fixture")?;
    let result = (|| {
        if detector::find(&launcher).is_some() { return Err("Um pacote sem dados foi reconhecido.".into()); }
        fs::write(project.join("Content/Paks/Example-Windows.utoc"), b"fixture")
            .map_err(|error| error.to_string())?;
        if detector::find(&launcher).as_deref() != Some(project.as_path())
            || detector::find(&shipping).as_deref() != Some(project.as_path()) {
            return Err("Launcher ou binário Shipping não foi reconhecido.".into());
        }
        Ok::<(), String>(())
    })();
    fs::remove_dir_all(root).ok();
    result?;
    println!("PASS: Unreal reconhece launcher e Shipping com Content/Paks, sem falso positivo vazio.");
    Ok(())
}
