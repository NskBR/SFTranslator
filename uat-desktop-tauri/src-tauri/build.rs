fn main() {
    if std::env::var("PROFILE").as_deref() == Ok("release") {
        for asset in ["unity/lt.exe", "renpy/lt.exe", "manifest.json", "minisbd/en.onnx"] {
            assert!(std::path::Path::new("resources/runtimes").join(asset).is_file(),
                "Motor integrado ausente: {asset}. Execute npm run runtimes antes do build de distribuição.");
        }
    }
    tauri_build::build()
}
