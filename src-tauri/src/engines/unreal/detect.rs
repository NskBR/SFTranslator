use std::{fs, path::{Path, PathBuf}};

fn has_packaged_content(root: &Path) -> bool {
    fs::read_dir(root.join("Content/Paks")).is_ok_and(|entries| entries.flatten().any(|entry| {
        entry.path().extension().is_some_and(|extension| {
            extension.eq_ignore_ascii_case("pak") || extension.eq_ignore_ascii_case("utoc")
        })
    }))
}

pub(super) fn packaged_root(executable: &Path) -> Option<PathBuf> {
    let parent = executable.parent()?;
    let stem = executable.file_stem()?.to_str()?;
    let project = stem.strip_suffix("-Win64-Shipping").unwrap_or(stem);
    // Launchers live beside <Project>/Content/Paks; shipping binaries live three levels below it.
    if has_packaged_content(&parent.join(project)) { return Some(parent.join(project)); }
    for candidate in parent.ancestors().take(4) {
        if has_packaged_content(candidate) { return Some(candidate.to_path_buf()); }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_launcher_and_shipping_binary_only_with_packaged_content() {
        let root = std::env::temp_dir().join(format!("sftranslator-unreal-{}", uuid::Uuid::new_v4()));
        let project = root.join("Example");
        fs::create_dir_all(project.join("Binaries/Win64")).unwrap();
        fs::create_dir_all(project.join("Content/Paks")).unwrap();
        let launcher = root.join("Example.exe");
        let shipping = project.join("Binaries/Win64/Example-Win64-Shipping.exe");
        fs::write(&launcher, b"fixture").unwrap();
        fs::write(&shipping, b"fixture").unwrap();
        assert!(packaged_root(&launcher).is_none());
        fs::write(project.join("Content/Paks/Example-Windows.utoc"), b"fixture").unwrap();
        assert_eq!(packaged_root(&launcher), Some(project.clone()));
        assert_eq!(packaged_root(&shipping), Some(project));
        fs::remove_dir_all(root).unwrap();
    }
}
