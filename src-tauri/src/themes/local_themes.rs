use std::{collections::{HashMap, HashSet}, io::Read, path::PathBuf};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, WebviewWindow};

const MAX_PACKAGE: u64 = 80 * 1024 * 1024;
#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
pub struct Variant {
    pub name: String,
    pub image: String,
    pub preview: String,
    pub medium: Option<String>,
    pub compact: Option<String>,
    pub preset: String,
    pub appearance: serde_json::Value,
    pub darkness: u8,
    pub panel_opacity: u8,
    pub position: String,
}
#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
pub struct LocalTheme {
    pub schema_version: u8,
    #[serde(default)] pub id: String,
    pub name: String,
    pub author: String,
    pub variants: Vec<Variant>,
}
fn folder(app:&AppHandle)->Result<PathBuf,String>{Ok(app.path().app_data_dir().map_err(|e|e.to_string())?.join("local-themes"))}
fn valid_id(id:&str)->bool{id.len()==64&&id.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b))}
fn safe_path(path:&str)->bool{
    !path.is_empty() && path.len()<=160 && !path.contains('\\') && !path.contains(':') &&
    path.split('/').all(|part|!part.is_empty()&&part!="."&&part!=".."&&part.bytes().all(|b|b.is_ascii_alphanumeric()||b"-_.".contains(&b)))
}
fn validate_config(theme:&LocalTheme)->Result<(),String>{
    if theme.schema_version!=1||theme.name.trim().is_empty()||theme.name.len()>100||theme.author.len()>100||theme.variants.is_empty()||theme.variants.len()>20{return Err("Configuração de tema inválida (schemaVersion 1, até 20 variações).".into());}
    for v in &theme.variants {
        if v.name.trim().is_empty()||v.name.len()>100||!matches!(v.preset.as_str(),"custom"|"botanical")||!matches!(v.position.as_str(),"center"|"left"|"right")||!(30..=85).contains(&v.darkness)||!(60..=100).contains(&v.panel_opacity){return Err("Variação de tema inválida.".into());}
        let appearance=v.appearance.as_object().ok_or("appearance deve ser um objeto")?;
        if appearance.keys().any(|key|!matches!(key.as_str(),"palette"|"geometry"|"font")){return Err("Propriedade visual desconhecida.".into());}
        let palette=appearance.get("palette").and_then(|p|p.as_object()).ok_or("Informe a paleta do tema")?;
        for key in ["surface","raised","accent","strong"]{
            let color=palette.get(key).and_then(|c|c.as_str()).ok_or("Cor ausente na paleta")?;
            if color.len()!=7||!color.starts_with('#')||!color.as_bytes()[1..].iter().all(|b|b.is_ascii_hexdigit()){return Err("Use cores hexadecimais de seis dígitos.".into());}
        }
        // Appearance values are parsed again by the frontend's restricted token compiler.
        if serde_json::to_vec(&v.appearance).map_err(|e|e.to_string())?.len()>4096{return Err("Configuração visual muito grande.".into());}
    }
    Ok(())
}
fn import_package(app:&AppHandle,path:String)->Result<LocalTheme,String>{
    let file=std::fs::File::open(path).map_err(|e|e.to_string())?;
    if file.metadata().map_err(|e|e.to_string())?.len()>MAX_PACKAGE{return Err("O ZIP deve ter até 80 MB.".into());}
    let mut zip=zip::ZipArchive::new(file).map_err(|_|"ZIP inválido")?;
    if zip.len()>100{return Err("Use até 100 arquivos por pacote.".into());}
    let mut files=HashMap::new();let mut total=0u64;
    for i in 0..zip.len(){
        let mut entry=zip.by_index(i).map_err(|e|e.to_string())?;
        if entry.is_dir(){continue;}
        let name=entry.name().to_owned();
        if !safe_path(&name)||entry.unix_mode().map(|m|m&0o170000==0o120000).unwrap_or(false){return Err("Caminho não permitido no ZIP.".into());}
        if name!="theme.json"&&!name.ends_with(".png")&&!name.ends_with(".gif"){return Err("O pacote só aceita theme.json e imagens PNG/GIF.".into());}
        let limit=if name=="theme.json"{128*1024}else{20*1024*1024};
        if entry.size()>limit{return Err("Arquivo acima do limite permitido.".into());}
        let mut bytes=Vec::new();entry.by_ref().take(limit+1).read_to_end(&mut bytes).map_err(|e|e.to_string())?;
        total+=bytes.len() as u64;
        if bytes.len() as u64>limit||total>MAX_PACKAGE||files.contains_key(&name){return Err("ZIP muito grande ou com arquivos duplicados.".into());}
        if name!="theme.json"{super::theme_images::validate(&bytes)?;}
        files.insert(name,bytes);
    }
    let mut theme:LocalTheme=serde_json::from_slice(files.get("theme.json").ok_or("theme.json não encontrado na raiz do ZIP")?).map_err(|e|format!("theme.json inválido: {e}"))?;
    validate_config(&theme)?;
    let mut used=HashSet::new();
    for v in &theme.variants{for path in [Some(&v.image),Some(&v.preview),v.medium.as_ref(),v.compact.as_ref()].into_iter().flatten(){if !safe_path(path)||!files.contains_key(path)||path=="theme.json"{return Err("Imagem referenciada não encontrada no ZIP.".into());}used.insert(path.clone());}}
    let images=app.path().app_data_dir().map_err(|e|e.to_string())?.join("theme-images");std::fs::create_dir_all(&images).map_err(|e|e.to_string())?;
    let mut hashes=HashMap::new();
    for path in used {let bytes=&files[&path];let hash=format!("{:x}",Sha256::digest(bytes));std::fs::write(images.join(format!("{hash}.image")),bytes).map_err(|e|e.to_string())?;hashes.insert(path,hash);}
    theme.id=format!("{:x}",Sha256::digest(files.get("theme.json").unwrap()));
    for v in &mut theme.variants{v.image=hashes[&v.image].clone();v.preview=hashes[&v.preview].clone();v.medium=v.medium.as_ref().map(|p|hashes[p].clone());v.compact=v.compact.as_ref().map(|p|hashes[p].clone());}
    let root=folder(app)?;std::fs::create_dir_all(&root).map_err(|e|e.to_string())?;
    std::fs::write(root.join(format!("{}.json",theme.id)),serde_json::to_vec(&theme).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    Ok(theme)
}
#[tauri::command]
pub async fn import_local_theme(app:AppHandle,window:WebviewWindow,path:String)->Result<LocalTheme,String>{
    if window.label()!="main"{return Err("Importe temas pelas configurações.".into());}
    tauri::async_runtime::spawn_blocking(move||import_package(&app,path)).await.map_err(|e|e.to_string())?
}
#[tauri::command]
pub fn list_local_themes(app:AppHandle)->Result<Vec<LocalTheme>,String>{
    let root=folder(&app)?;if !root.exists(){return Ok(vec![]);}
    let mut themes=vec![];
    for entry in std::fs::read_dir(root).map_err(|e|e.to_string())?.flatten(){
        if entry.file_type().map(|t|!t.is_file()||t.is_symlink()).unwrap_or(true)||entry.metadata().map(|m|m.len()>128*1024).unwrap_or(true){continue;}
        if let Ok(bytes)=std::fs::read(entry.path()){if let Ok(theme)=serde_json::from_slice::<LocalTheme>(&bytes){if valid_id(&theme.id)&&validate_config(&theme).is_ok(){themes.push(theme);}}}
    }
    themes.sort_by(|a,b|a.name.cmp(&b.name));Ok(themes)
}
#[tauri::command]
pub fn delete_local_theme(app:AppHandle,window:WebviewWindow,id:String)->Result<(),String>{
    if window.label()!="main"||!valid_id(&id){return Err("Tema local inválido.".into());}
    let path=folder(&app)?.join(format!("{id}.json"));if path.exists(){std::fs::remove_file(path).map_err(|e|e.to_string())?;}Ok(())
}

#[cfg(test)]mod tests{use super::*;#[test]fn rejects_zip_escape_paths(){for path in ["../escape.png","C:/file.png","images/../a.png","images\\a.png","/a.png"]{assert!(!safe_path(path));}assert!(safe_path("images/sarah.png"));}}
