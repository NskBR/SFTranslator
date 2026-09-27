use crate::{
    engines, integration_state, load_games, runtime_directory, save_games, Game,
};
use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};

static ACTIVE_GAME_PID: Mutex<Option<u32>> = Mutex::new(None);
static ACTIVE_SESSION: AtomicBool = AtomicBool::new(false);

pub(crate) fn game_is_running() -> bool {
    ACTIVE_SESSION.load(Ordering::SeqCst)
}

pub(crate) fn session_log(app: &AppHandle, kind: &str, text: impl Into<String>) {
    app.emit(
        "session-log",
        serde_json::json!({"kind":kind,"text":text.into()}),
    )
    .ok();
}

fn hide_console(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
}

pub(crate) fn spawn_streaming(
    mut command: Command,
    app: &AppHandle,
    label: &str,
) -> Result<std::process::Child, String> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    command.env("SFTRANSLATOR_MANAGED_RUNTIME", "1");
    if let Ok(runtime) = runtime_directory(app) {
        command.env("UAT_SBD_DIR", runtime.join("minisbd"));
    }
    hide_console(&mut command);
    let mut child = command
        .spawn()
        .map_err(|error| format!("Falha ao iniciar {label}: {error}"))?;
    if let Some(stdout) = child.stdout.take() {
        let handle = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                session_log(&handle, "output", line);
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        let handle = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                session_log(&handle, "error", line);
            }
        });
    }
    Ok(child)
}

pub(crate) fn run_stage(command: Command, app: &AppHandle, label: &str) -> Result<(), String> {
    session_log(app, "system", format!("{label}…"));
    let mut child = spawn_streaming(command, app, label)?;
    let status = child
        .wait()
        .map_err(|error| format!("Falha durante {label}: {error}"))?;
    if status.success() {
        session_log(app, "system", format!("{label}: concluído."));
        Ok(())
    } else {
        Err(format!(
            "{label} terminou com código {}.",
            status.code().unwrap_or(-1)
        ))
    }
}

pub(crate) fn tail_translation_log(
    app: AppHandle,
    path: PathBuf,
    stop: Arc<AtomicBool>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut offset = fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
        while !stop.load(Ordering::Relaxed) {
            if let Ok(mut file) = OpenOptions::new().read(true).open(&path) {
                if file.metadata().map(|meta| meta.len()).unwrap_or(0) < offset {
                    offset = 0;
                }
                if file.seek(SeekFrom::Start(offset)).is_ok() {
                    let mut bytes = Vec::new();
                    if file.read_to_end(&mut bytes).is_ok() && !bytes.is_empty() {
                        offset += bytes.len() as u64;
                        for line in String::from_utf8_lossy(&bytes).lines() {
                            session_log(&app, "translation", line.to_string());
                        }
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(350));
        }
    })
}

fn session_marker_is_fresh(path: &Path) -> bool {
    path.metadata()
        .and_then(|metadata| metadata.modified())
        .and_then(|modified| modified.elapsed().map_err(std::io::Error::other))
        .map(|elapsed| elapsed <= Duration::from_secs(30))
        .unwrap_or(false)
}

fn wait_for_game_exit(
    child: &mut std::process::Child,
    session_marker: Option<&Path>,
    app: &AppHandle,
) -> i32 {
    let Some(marker) = session_marker else {
        return child
            .wait()
            .ok()
            .and_then(|status| status.code())
            .unwrap_or(-1);
    };

    let mut marker_seen = false;
    let mut launcher_exit: Option<(Instant, i32)> = None;
    loop {
        let marker_active = session_marker_is_fresh(marker);
        if marker_active && !marker_seen {
            marker_seen = true;
            session_log(
                app,
                "system",
                "Hook conectado. A sessão acompanhará o processo real do jogo.",
            );
        }

        if launcher_exit.is_none() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    let code = status.code().unwrap_or(-1);
                    launcher_exit = Some((Instant::now(), code));
                    if marker_active {
                        session_log(
                            app,
                            "system",
                            "Launcher concluído; o jogo continua ativo pelo hook.",
                        );
                    }
                }
                Ok(None) => {}
                Err(_) => launcher_exit = Some((Instant::now(), -1)),
            }
        }

        if let Some((exited_at, code)) = launcher_exit {
            if marker_seen {
                if !marker_active {
                    return code;
                }
            } else if exited_at.elapsed() >= Duration::from_secs(5) {
                return code;
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

pub(crate) fn update_integration_record(app: &AppHandle, game_id: &str) {
    let Ok(mut games) = load_games(app) else {
        return;
    };
    let Some(game) = games.iter_mut().find(|game| game.id == game_id) else {
        return;
    };
    let (ready, status) = integration_state(game);
    game.integration_status = Some(status);
    game.status = if game.engine == "RPG Maker" && matches!(game.runtime.as_deref(), Some("95" | "2000/2003" | "XP" | "VX" | "VX Ace")) && game.model_installed {
        "Em teste".into()
    } else if game.model_installed && ready {
        "Pronto".into()
    } else {
        "Instalação pendente".into()
    };
    save_games(app, &games).ok();
}

fn wait_for_local_server(
    app: &AppHandle,
    child: &mut std::process::Child,
    port: u16,
) -> Result<(), String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let started = Instant::now();
    session_log(
        app,
        "system",
        format!("Aguardando o servidor local responder na porta {port}…"),
    );
    loop {
        if TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok() {
            session_log(
                app,
                "system",
                format!("Servidor local online na porta {port}."),
            );
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "O servidor local encerrou antes de ficar pronto ({status})."
            ));
        }
        if started.elapsed() >= Duration::from_secs(90) {
            return Err(format!(
                "O servidor local não respondeu na porta {port} em 90 segundos."
            ));
        }
        std::thread::sleep(Duration::from_millis(300));
    }
}

fn run_game_session(app: AppHandle, game: Game, project: PathBuf) -> Result<i32, String> {
    if game.engine == "RPG Maker" && game.language_confidence.unwrap_or(0.0) >= 0.9
        && game.detected_language.as_deref().is_some_and(|detected| detected != game.source_language) {
        session_log(&app, "error", format!(
            "Idioma configurado {} difere do idioma {} detectado nos dados do jogo. Corrija o fluxo no editor; textos incompatíveis permanecerão originais.",
            game.source_language.to_uppercase(), game.detected_language.as_deref().unwrap_or("").to_uppercase()
        ));
    }
    let adapter = engines::by_name(&game.engine)?;
    let executable = adapter.launch_path(&game);
    let game_root = executable.parent().ok_or("Pasta do jogo inválida.")?;
    let stop_tail = Arc::new(AtomicBool::new(false));
    let engines::EngineSession {
        server,
        port,
        log_tail,
        marker,
    } = adapter.start_session(&app, &game, &project, stop_tail.clone())?;

    let mut server = server;
    if let (Some(server_process), Some(port)) = (server.as_mut(), port) {
        if let Err(error) = wait_for_local_server(&app, server_process, port) {
            server_process.kill().ok();
            server_process.wait().ok();
            stop_tail.store(true, Ordering::Relaxed);
            if let Some(tail) = log_tail { tail.join().ok(); }
            return Err(error);
        }
    }

    if let Some(path) = marker.as_deref() {
        fs::remove_file(path).ok();
    }
    session_log(&app, "system", format!("Abrindo o jogo: {}", game.name));
    let mut command = Command::new(&executable);
    command
        .current_dir(game_root)
        .env("SFTRANSLATOR_MANAGED_RUNTIME", "1");
    let mut child = match spawn_streaming(command, &app, "jogo") {
        Ok(child) => child,
        Err(error) => {
            if let Some(server_process) = server.as_mut() {
                server_process.kill().ok();
                server_process.wait().ok();
            }
            stop_tail.store(true, Ordering::Relaxed);
            if let Some(tail) = log_tail {
                tail.join().ok();
            }
            return Err(error);
        }
    };
    *ACTIVE_GAME_PID
        .lock()
        .map_err(|_| "Não foi possível registrar o processo do jogo.")? = Some(child.id());
    let mut observer = match adapter.start_observer(&app, &game, &project, child.id()) {
        Ok(observer) => observer,
        Err(error) => {
            session_log(&app, "error", format!("Observador de tradução não iniciou: {error}"));
            None
        }
    };
    let code = wait_for_game_exit(&mut child, marker.as_deref(), &app);
    if let Some(process) = observer.as_mut() {
        process.kill().ok();
        process.wait().ok();
        if let Ok(data) = app.path().app_data_dir() {
            fs::remove_file(data.join("rpgmaker").join(&game.id).join("ocr-capture.png")).ok();
        }
    }
    if let Ok(mut pid) = ACTIVE_GAME_PID.lock() {
        *pid = None;
    }
    session_log(&app, "system", if server.is_some() {
        "Jogo encerrado. Finalizando o servidor local."
    } else {
        "Jogo encerrado. Teste de abertura finalizado."
    });
    if let Some(server_process) = server.as_mut() {
        server_process.kill().ok();
        server_process.wait().ok();
    }
    stop_tail.store(true, Ordering::Relaxed);
    if let Some(tail) = log_tail {
        tail.join().ok();
    }
    Ok(code)
}

#[tauri::command]
pub(crate) fn launch_game(app: AppHandle, game_id: String) -> Result<(), String> {
    let mut games = load_games(&app)?;
    let game = games
        .iter_mut()
        .find(|game| game.id == game_id)
        .ok_or("Jogo não encontrado.")?;
    let adapter = engines::by_name(&game.engine)?;
    if adapter.translation_available(game) && !game.model_installed {
        return Err("Instale o modelo configurado antes de iniciar o jogo.".into());
    }
    game.last_launch = Some(chrono::Utc::now().to_rfc3339());
    let game = game.clone();
    save_games(&app, &games)?;
    let project = runtime_directory(&app).unwrap_or_default();
    if adapter.translation_available(&game) && !adapter.runtime_ready(&project) {
        return Err(format!(
            "Runtime {} não encontrado no aplicativo.",
            game.engine
        ));
    }
    if ACTIVE_SESSION.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst).is_err() {
        return Err("Já existe uma sessão de jogo em andamento.".into());
    }
    session_log(
        &app,
        "system",
        format!("Preparando sessão para {}…", game.name),
    );
    std::thread::spawn(move || {
        let result = run_game_session(app.clone(), game, project);
        ACTIVE_SESSION.store(false, Ordering::SeqCst);
        match result {
            Ok(code) => {
                app.emit("session-ended", serde_json::json!({"code":code}))
                    .ok();
            }
            Err(error) => {
                session_log(&app, "error", error);
                app.emit("session-ended", serde_json::json!({"code":-1}))
                    .ok();
            }
        }
    });
    Ok(())
}

#[tauri::command]
pub(crate) fn stop_game_session() -> Result<(), String> {
    let pid = ACTIVE_GAME_PID
        .lock()
        .map_err(|_| "Não foi possível acessar a sessão atual.")?
        .ok_or("Nenhum jogo está em execução.")?;
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill.exe");
        command.args(["/PID", &pid.to_string(), "/T", "/F"]);
        hide_console(&mut command);
        let status = command
            .status()
            .map_err(|error| format!("Não foi possível encerrar o jogo: {error}"))?;
        if !status.success() {
            return Err("O Windows não conseguiu encerrar o jogo.".into());
        }
    }
    #[cfg(not(windows))]
    return Err("Encerrar jogos pela interface está disponível apenas no Windows.".into());
    Ok(())
}
