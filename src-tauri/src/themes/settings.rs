use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct ThemePreferences {
    accent: Option<String>,
    background: Option<String>,
    panel: Option<String>,
    surface: Option<String>,
    font: String,
    gradient: String,
    gradient_angle: u16,
    animations: bool,
    animated_icons: bool,
    icon_style: String,
    image_id: Option<String>,
    local_theme_id: Option<String>,
    official_theme_id: Option<String>,
    local_theme_variant: usize,
    custom_css: String,
}

impl Default for ThemePreferences {
    fn default() -> Self {
        Self { accent: None, background: None, panel: None, surface: None,
            font: "system".into(), gradient: "none".into(), gradient_angle: 135,
            animations: true, animated_icons: true, icon_style: "default".into(), image_id: None,
            local_theme_id: None, official_theme_id: None, local_theme_variant: 0, custom_css: String::new() }
    }
}

fn valid_hex(value: &str) -> bool {
    value.len() == 7 && value.starts_with('#') && value.as_bytes()[1..].iter().all(u8::is_ascii_hexdigit)
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub fn validate_appearance(value: &ThemePreferences) -> Result<(), String> {
    for color in [&value.accent, &value.background, &value.panel, &value.surface].into_iter().flatten() {
        if !valid_hex(color) { return Err("Use cores hexadecimais de seis dígitos.".into()); }
    }
    if !matches!(value.font.as_str(), "system" | "serif" | "mono")
        || !matches!(value.icon_style.as_str(), "default" | "accent" | "soft")
        || !matches!(value.gradient.as_str(), "none" | "aurora" | "sunset" | "ocean" | "cyberpunk")
        || value.gradient_angle > 360 || value.local_theme_variant > 19
        || value.custom_css.len() > 8192
        || value.image_id.as_deref().is_some_and(|id| !valid_hash(id))
        || value.local_theme_id.as_deref().is_some_and(|id| !valid_hash(id))
        || value.official_theme_id.as_deref().is_some_and(|id| !super::official_themes::known_theme(id)) {
        return Err("Preferências de aparência inválidas.".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_defaults_and_rejects_invalid_values() {
        assert!(validate_appearance(&ThemePreferences::default()).is_ok());
        let mut prefs = ThemePreferences::default();
        prefs.accent = Some("red".into());
        assert!(validate_appearance(&prefs).is_err());
        prefs.accent = Some("#aabbcc".into());
        prefs.local_theme_id = Some("../invalid".into());
        assert!(validate_appearance(&prefs).is_err());
    }
}
