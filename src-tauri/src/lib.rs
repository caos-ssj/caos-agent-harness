use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::os::unix::process::CommandExt;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::Wry;
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WindowEvent};

const READY_PREFIX: &str = "CAOS_DESKTOP_READY ";
const TRAY_ID: &str = "caos-tray";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BackendInfo {
    pub port: u16,
    pub url: String,
    pub token: String,
    pub workspace: Option<String>,
}

#[derive(Deserialize)]
struct ReadyPayload {
    port: u16,
    url: String,
}

#[derive(Default)]
struct Lifecycle {
    ready: Option<BackendInfo>,
    error: Option<String>,
}

pub struct BackendState {
    child: Mutex<Option<Child>>,
    lifecycle: Arc<(Mutex<Lifecycle>, Condvar)>,
    quitting: AtomicBool,
    /// Bumped on every (re)spawn so a stale reader thread never reports a deliberate stop as a crash.
    generation: AtomicU64,
    has_tray: AtomicBool,
}

/// Disabled first row of the tray menu: Linux tray icons (AppIndicator) have no tooltips, so status lives here.
struct TrayStatus(MenuItem<Wry>);

impl Default for BackendState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            lifecycle: Arc::new((Mutex::new(Lifecycle::default()), Condvar::new())),
            quitting: AtomicBool::new(false),
            generation: AtomicU64::new(0),
            has_tray: AtomicBool::new(false),
        }
    }
}

fn generate_session_token() -> String {
    let mut bytes = [0u8; 32];
    let ok = File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .is_ok();
    if !ok {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let pid = std::process::id() as u128;
        let mixed = nanos ^ (pid << 64) ^ 0x9E37_79B9_7F4A_7C15_u128;
        for (i, b) in bytes.iter_mut().enumerate() {
            *b = ((mixed >> ((i % 16) * 8)) & 0xff) as u8;
        }
    }
    let mut hex = String::with_capacity(64);
    for b in bytes {
        use std::fmt::Write;
        let _ = write!(&mut hex, "{:02x}", b);
    }
    hex
}

fn augmented_path() -> String {
    let current = env::var("PATH").unwrap_or_default();
    let mut parts: Vec<String> = current
        .split(':')
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .collect();
    if let Some(home) = env::var_os("HOME").map(PathBuf::from) {
        let mut candidates = vec![
            home.join(".local/bin"),
            home.join(".cargo/bin"),
            home.join(".npm-global/bin"),
            home.join(".opencode/bin"),
            PathBuf::from("/usr/local/bin"),
        ];
        let nvm_dir = home.join(".nvm/versions/node");
        if let Ok(entries) = std::fs::read_dir(&nvm_dir) {
            let mut vers: Vec<PathBuf> = entries
                .filter_map(|e| e.ok().map(|x| x.path().join("bin")))
                .filter(|p| p.is_dir())
                .collect();
            vers.sort();
            vers.reverse();
            candidates.extend(vers.into_iter().take(2));
        }
        for c in candidates {
            if c.is_dir() {
                let s = c.to_string_lossy().into_owned();
                if !parts.iter().any(|p| p == &s) {
                    parts.push(s);
                }
            }
        }
    }
    parts.join(":")
}

fn find_repo_root() -> Option<PathBuf> {
    let manifest_parent = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().map(Path::to_path_buf);
    if let Some(p) = manifest_parent {
        if p.join("caos_harness/__main__.py").is_file() {
            return Some(p);
        }
    }
    if let Ok(cwd) = env::current_dir() {
        for anc in cwd.ancestors() {
            if anc.join("caos_harness/__main__.py").is_file() {
                return Some(anc.to_path_buf());
            }
        }
    }
    None
}

fn resolve_command(workspace: Option<&str>, token: &str) -> Command {
    let repo_root = find_repo_root();
    let path_env = augmented_path();

    let mut cmd = if let Some(bin) = env::var_os("CAOS_HARNESS_PYTHON").filter(|v| !v.is_empty()) {
        let mut c = Command::new(bin);
        c.args(["-m", "caos_harness", "serve"]);
        c
    } else if let Some(sidecar) = env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|d| d.join("caos-harness-sidecar")))
        .filter(|p| p.is_file())
    {
        let mut c = Command::new(sidecar);
        c.arg("serve");
        c
    } else if let Some(venv_py) = repo_root
        .as_ref()
        .map(|r| r.join(".venv/bin/python"))
        .filter(|p| p.is_file())
    {
        let mut c = Command::new(venv_py);
        c.args(["-m", "caos_harness", "serve"]);
        c
    } else {
        let mut c = Command::new("python3");
        c.args(["-m", "caos_harness", "serve"]);
        c
    };

    cmd.args(["--port", "0", "--desktop"]);
    if let Some(ws) = workspace.filter(|s| !s.trim().is_empty()) {
        cmd.args(["--workspace", ws]);
    }
    if let Some(root) = repo_root {
        // No current_dir: the engine keeps the launcher's cwd, otherwise harness.toml in the repo root would
        // always win over the last-used workspace.
        let pythonpath = match env::var("PYTHONPATH") {
            Ok(cur) if !cur.is_empty() => format!("{}:{}", root.display(), cur),
            _ => root.display().to_string(),
        };
        cmd.env("PYTHONPATH", pythonpath);
    }

    cmd.env("PATH", path_env);
    cmd.env("CAOS_HARNESS_TOKEN", token);
    cmd.env("CAOS_DESKTOP", "1");
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    cmd.stdin(Stdio::null());
    // Own process group: stopping the app can signal the engine and everything it spawned in one go.
    cmd.process_group(0);
    cmd
}

fn parse_ready_line(line: &str) -> Option<ReadyPayload> {
    let json_part = line.trim().strip_prefix(READY_PREFIX)?;
    serde_json::from_str::<ReadyPayload>(json_part).ok()
}

fn spawn_backend(app: &AppHandle, state: &BackendState, workspace: Option<String>) -> Result<(), String> {
    stop_backend(state);
    let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
    {
        let (lock, cvar) = &*state.lifecycle;
        let mut guard = lock.lock().map_err(|_| "lifecycle lock poisoned")?;
        *guard = Lifecycle::default();
        cvar.notify_all();
    }

    let token = generate_session_token();
    let mut cmd = resolve_command(workspace.as_deref(), &token);
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("No se pudo lanzar el motor Python: {e}"))?;

    let stdout = child.stdout.take().ok_or("stdout del sidecar no disponible")?;
    let stderr = child.stderr.take().ok_or("stderr del sidecar no disponible")?;

    {
        let mut guard = state.child.lock().map_err(|_| "child lock poisoned")?;
        *guard = Some(child);
    }

    let stderr_buf = Arc::new(Mutex::new(VecDeque::<String>::with_capacity(30)));
    let stderr_reader_buf = Arc::clone(&stderr_buf);
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            if let Ok(mut q) = stderr_reader_buf.lock() {
                if q.len() >= 30 {
                    q.pop_front();
                }
                q.push_back(line);
            }
        }
    });

    let lifecycle = Arc::clone(&state.lifecycle);
    let app_handle = app.clone();
    let ws_clone = workspace.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut announced = false;
        for line in reader.lines().map_while(Result::ok) {
            if !announced {
                if let Some(payload) = parse_ready_line(&line) {
                    let (lock, cvar) = &*lifecycle;
                    if let Ok(mut guard) = lock.lock() {
                        guard.ready = Some(BackendInfo {
                            port: payload.port,
                            url: payload.url,
                            token: token.clone(),
                            workspace: ws_clone.clone(),
                        });
                        cvar.notify_all();
                    }
                    announced = true;
                }
            }
        }
        if announced {
            // The engine died after it was ready: tell the UI unless this was a deliberate stop/restart/quit.
            let state = app_handle.state::<BackendState>();
            if state.generation.load(Ordering::SeqCst) == generation && !state.quitting.load(Ordering::SeqCst) {
                let tail = stderr_buf
                    .lock()
                    .ok()
                    .map(|q| q.iter().rev().take(4).cloned().collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join(" | "))
                    .unwrap_or_default();
                let _ = app_handle.emit("caos://backend-exit", tail);
            }
        }
        if !announced {
            let tail = stderr_buf
                .lock()
                .ok()
                .map(|q| q.iter().cloned().collect::<Vec<_>>().join(" | "))
                .unwrap_or_default();
            let msg = if tail.is_empty() {
                "El servidor Python terminó antes de responder.".to_string()
            } else {
                format!("El servidor Python falló al iniciar: {tail}")
            };
            let current = app_handle.state::<BackendState>().generation.load(Ordering::SeqCst) == generation;
            let (lock, cvar) = &*lifecycle;
            if let Ok(mut guard) = lock.lock() {
                if current && guard.ready.is_none() && guard.error.is_none() {
                    guard.error = Some(msg);
                    cvar.notify_all();
                }
            }
        }
    });

    Ok(())
}

fn signal_group(pid: u32, sig: i32) {
    // SAFETY: plain kill(2) on the engine's own process group (it was spawned with process_group(0)).
    unsafe {
        libc::kill(-(pid as i32), sig);
    }
}

/// SIGTERM the engine's group so it cancels running agents, then SIGKILL whatever is left after a grace period.
pub fn stop_backend(state: &BackendState) {
    let child = state.child.lock().ok().and_then(|mut g| g.take());
    if let Some(mut child) = child {
        let pid = child.id();
        signal_group(pid, libc::SIGTERM);
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            match child.try_wait() {
                Ok(Some(_)) | Err(_) => break,
                Ok(None) if Instant::now() >= deadline => {
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(40)),
            }
        }
        // Agents run in their own sessions; nothing of the engine's group may survive the engine.
        signal_group(pid, libc::SIGKILL);
    }
}

#[tauri::command]
async fn wait_for_backend(state: tauri::State<'_, BackendState>) -> Result<BackendInfo, String> {
    let lifecycle = Arc::clone(&state.lifecycle);
    tauri::async_runtime::spawn_blocking(move || {
        let (lock, cvar) = &*lifecycle;
        let deadline = Instant::now() + Duration::from_secs(15);
        let mut guard = lock.lock().map_err(|_| "lock poisoned".to_string())?;
        loop {
            if let Some(info) = &guard.ready {
                return Ok(info.clone());
            }
            if let Some(err) = &guard.error {
                return Err(err.clone());
            }
            let now = Instant::now();
            if now >= deadline {
                return Err("Tiempo de espera agotado iniciando el servidor Python (15 s).".to_string());
            }
            let (next, timed_out) = cvar
                .wait_timeout(guard, deadline.saturating_duration_since(now))
                .map_err(|_| "condvar poisoned".to_string())?;
            guard = next;
            if timed_out.timed_out() && guard.ready.is_none() && guard.error.is_none() {
                return Err("Tiempo de espera agotado iniciando el servidor Python.".to_string());
            }
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn restart_backend(
    app: AppHandle,
    state: tauri::State<'_, BackendState>,
    workspace: Option<String>,
) -> Result<BackendInfo, String> {
    // stop_backend waits for the old engine to exit: keep that off the async executor.
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let st = handle.state::<BackendState>();
        spawn_backend(&handle, &st, workspace)
    })
    .await
    .map_err(|e| e.to_string())??;
    wait_for_backend(state).await
}

#[tauri::command]
fn update_tray_state(app: AppHandle, project: String, needs_you: u32, running: bool) {
    let status = if running && needs_you > 0 {
        format!("Ejecutando · {needs_you} esperando veredicto")
    } else if running {
        "Ejecutando agentes…".to_string()
    } else if needs_you > 0 {
        format!("{needs_you} esperando veredicto")
    } else {
        "Todo en calma".to_string()
    };
    if let Some(item) = app.try_state::<TrayStatus>() {
        let label = if project.is_empty() { status.clone() } else { format!("{project} — {status}") };
        let _ = item.0.set_text(label);
    }
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let mut parts = vec![if project.is_empty() {
            "CAOS Desktop".to_string()
        } else {
            format!("CAOS · {project}")
        }];
        if running {
            parts.push("ejecutando".to_string());
        }
        if needs_you > 0 {
            parts.push(format!("{needs_you} esperando veredicto"));
        }
        let _ = tray.set_tooltip(Some(parts.join(" · ")));
    }
}

#[tauri::command]
fn open_in_terminal(path: String) -> Result<(), String> {
    let dir = PathBuf::from(&path);
    if !dir.is_dir() {
        return Err(format!("Carpeta no encontrada: {path}"));
    }
    let candidates: &[(&str, &[&str])] = &[
        ("x-terminal-emulator", &["--working-directory"]),
        ("gnome-terminal", &["--working-directory"]),
        ("xfce4-terminal", &["--working-directory"]),
        ("konsole", &["--workdir"]),
        ("kitty", &["--directory"]),
        ("alacritty", &["--working-directory"]),
        ("tilix", &["--working-directory"]),
    ];
    for (bin, args) in candidates {
        let mut cmd = Command::new(bin);
        for a in *args {
            cmd.arg(a);
        }
        cmd.arg(&dir);
        cmd.current_dir(&dir);
        cmd.stdin(Stdio::null());
        cmd.stdout(Stdio::null());
        cmd.stderr(Stdio::null());
        if cmd.spawn().is_ok() {
            return Ok(());
        }
    }
    Command::new("xterm")
        .current_dir(&dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("No se encontró un emulador de terminal compatible: {e}"))
}

#[tauri::command]
fn open_in_file_manager(path: String) -> Result<(), String> {
    let dir = PathBuf::from(&path);
    if !dir.is_dir() {
        return Err(format!("Carpeta no encontrada: {path}"));
    }
    Command::new("xdg-open")
        .arg(&dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("xdg-open no disponible: {e}"))
}

fn focus_main_window(app: &AppHandle, navigate_to: Option<&str>) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.unminimize();
        let _ = win.show();
        let _ = win.set_focus();
    }
    if let Some(view) = navigate_to {
        let _ = app.emit("caos://navigate", view);
    }
}

fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let status = MenuItem::with_id(app, "status", "CAOS · iniciando…", false, None::<&str>)?;
    let show = MenuItem::with_id(app, "show", "Abrir ventana CAOS", true, None::<&str>)?;
    let console = MenuItem::with_id(app, "console", "Consola & Orquestar", true, None::<&str>)?;
    let board = MenuItem::with_id(app, "board", "Tablero & Veredictos", true, None::<&str>)?;
    let providers = MenuItem::with_id(app, "providers", "Modelos & Proveedores", true, None::<&str>)?;
    let sep0 = PredefinedMenuItem::separator(app)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Salir completamente", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&status, &sep0, &show, &console, &board, &providers, &sep, &quit])?;

    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip("CAOS Desktop · Estación de Trabajo")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => focus_main_window(app, None),
            "console" => focus_main_window(app, Some("console")),
            "board" => focus_main_window(app, Some("board")),
            "providers" => focus_main_window(app, Some("providers")),
            "quit" => {
                let state = app.state::<BackendState>();
                state.quitting.store(true, Ordering::SeqCst);
                stop_backend(&state);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                focus_main_window(tray.app_handle(), None);
            }
        });

    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;
    app.manage(TrayStatus(status));
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(BackendState::default())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            focus_main_window(app, None);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            wait_for_backend,
            restart_backend,
            update_tray_state,
            open_in_terminal,
            open_in_file_manager,
        ])
        .setup(|app| {
            let state = app.state::<BackendState>();
            // A desktop without a tray (plain GNOME) must not trap the user in a hidden window or abort startup.
            match setup_tray(app.handle()) {
                Ok(()) => state.has_tray.store(true, Ordering::SeqCst),
                Err(e) => eprintln!("CAOS: bandeja del sistema no disponible ({e}); cerrar la ventana saldrá de la app"),
            }
            let initial_ws = env::var("CAOS_WORKSPACE").ok();
            spawn_backend(app.handle(), &state, initial_ws).map_err(std::io::Error::other)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let state = window.app_handle().state::<BackendState>();
                if state.has_tray.load(Ordering::SeqCst) && !state.quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error building CAOS Desktop");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
            let state = app_handle.state::<BackendState>();
            if state.quitting.load(Ordering::SeqCst) || matches!(event, RunEvent::Exit) {
                stop_backend(&state);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_handshake_line() {
        let p = parse_ready_line(r#"CAOS_DESKTOP_READY {"port": 44219, "url": "http://127.0.0.1:44219", "desktop": true}"#).unwrap();
        assert_eq!(p.port, 44219);
        assert_eq!(p.url, "http://127.0.0.1:44219");
        assert!(parse_ready_line("caos-harness · ready").is_none());
    }

    #[test]
    fn generates_64_hex_session_token() {
        let a = generate_session_token();
        let b = generate_session_token();
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn stop_backend_terminates_the_whole_process_group() {
        let state = BackendState::default();
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "sleep 300 & echo $!; wait"]).stdout(Stdio::piped()).process_group(0);
        let mut child = cmd.spawn().unwrap();
        let mut line = String::new();
        BufReader::new(child.stdout.take().unwrap()).read_line(&mut line).unwrap();
        let grandchild: i32 = line.trim().parse().unwrap();
        *state.child.lock().unwrap() = Some(child);
        stop_backend(&state);
        std::thread::sleep(Duration::from_millis(150));
        // SAFETY: signal 0 only probes for existence.
        let alive = unsafe { libc::kill(grandchild, 0) } == 0;
        assert!(!alive, "grandchild {grandchild} survived stop_backend");
    }
}
