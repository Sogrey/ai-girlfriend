// Tauri 2 desktop shell for the 3D AI girlfriend (Phase 46, Tauri migration).
//
// Replaces the Electron main process (preserved on the `electron` branch).
// Feature parity map:
//   app:// protocol        -> register_uri_scheme_protocol (serves repo files)
//   BrowserWindow(main)    -> dynamic WebviewWindow "main" (transparent frameless topmost)
//   BrowserWindow(heart)   -> dynamic WebviewWindow "heart" (hidden mini window)
//   preload + ipcMain      -> #[tauri::command]s + renderer/core/desktop-bridge.js
//   Tray / Menu            -> tauri tray-icon (menu + left-click wake)
//   globalShortcut         -> tauri-plugin-global-shotcut (hot re-register)
//   single-instance lock   -> tauri-plugin-single-instance (2nd launch wakes 1st)
//   setLoginItemSettings   -> tauri-plugin-autostart
//   desktopCapturer        -> xcap screen capture (capture.rs, P38 screen awareness)
//   mouse polling 33ms     -> GetCursorPos loop (mouse.rs) emits `global-mouse`
//                             (the renderer's proximity model runs on THIS event,
//                             not on forwarded mousemove — so Tauri's
//                             set_ignore_cursor_events without forwarding is fine)
//   Python backend spawn   -> backend.rs (reuse-or-spawn on 8765 + tree kill)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicBool, Ordering};

use lazy_static::lazy_static;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindowBuilder};

mod backend;
mod capture;
mod commands;
mod mouse;

lazy_static! {
    /// Repo root that `app://local/<path>` resolves against: AGF_ROOT env,
    /// else walk up from the exe until a dir containing backend/main.py.
    /// (Matches the Electron protocol root so the renderer's absolute
    /// /renderer/... and importmap app://local/node_modules/... paths keep
    /// working unchanged.)
    pub static ref ROOT: std::path::PathBuf = resolve_root();
    /// Set to false on app exit: stops the mouse polling thread.
    pub static ref RUNNING: AtomicBool = AtomicBool::new(true);
}

fn resolve_root() -> std::path::PathBuf {
    if let Ok(p) = std::env::var("AGF_ROOT") {
        let p = std::path::PathBuf::from(p);
        if p.join("backend").join("main.py").exists() {
            return p;
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        while let Some(d) = dir {
            if d.join("backend").join("main.py").exists() {
                return d;
            }
            dir = d.parent().map(|p| p.to_path_buf());
        }
    }
    std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
}

pub fn main_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    app.get_webview_window("main")
}

pub fn heart_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    app.get_webview_window("heart")
}

/// Electron setHeartMode(false): un-hide the girl, wake the renderer so it
/// plays the walk-in animation (app:awaken — the renderer must NOT call
/// setHeartMode back in response, no callback loop).
pub fn set_heart_mode_impl(app: &AppHandle, show_heart: bool) {
    if show_heart {
        if let Some(m) = main_window(app) {
            let _ = m.hide();
        }
        if let Some(h) = heart_window(app) {
            let _ = h.show();
        }
    } else {
        if let Some(h) = heart_window(app) {
            let _ = h.hide();
        }
        if let Some(m) = main_window(app) {
            let _ = m.show();
            let _ = app.emit("app:awaken", ());
        }
    }
}

/// Wake up from tray / shortcut / second-instance launch.
pub fn awaken(app: &AppHandle) {
    set_heart_mode_impl(app, false);
}

// ---------------- app:// protocol (Electron protocol.handle parity) ----------------

const MIME_MAP: &[(&str, &str)] = &[
    (".html", "text/html"),
    (".js", "text/javascript"),
    (".mjs", "text/javascript"),
    (".css", "text/css"),
    (".json", "application/json"),
    (".txt", "text/plain"),
    (".png", "image/png"),
    (".jpg", "image/jpeg"),
    (".jpeg", "image/jpeg"),
    (".webp", "image/webp"),
    (".svg", "image/svg+xml"),
    (".vrm", "model/gltf-binary"),
    (".glb", "model/gltf-binary"),
    (".gltf", "model/gltf+json"),
    (".bin", "application/octet-stream"),
    (".mp3", "audio/mpeg"),
    (".wav", "audio/wav"),
    (".ttf", "font/ttf"),
    (".otf", "font/otf"),
    (".woff", "font/woff"),
    (".woff2", "font/woff2"),
    (".ktx2", "image/ktx2"),
];

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(b.len());
    let mut i = 0usize;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            let hex = |c: u8| -> Option<u8> {
                match c {
                    b'0'..=b'9' => Some(c - b'0'),
                    b'a'..=b'f' => Some(c - b'a' + 10),
                    b'A'..=b'F' => Some(c - b'A' + 10),
                    _ => None,
                }
            };
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn serve_app_path(rel: &str) -> tauri::http::Response<Vec<u8>> {
    let build = |status: u16, body: &str| -> tauri::http::Response<Vec<u8>> {
        tauri::http::Response::builder()
            .status(status)
            .header("Content-Type", "text/plain; charset=utf-8")
            .header("Access-Control-Allow-Origin", "*")
            .body(body.as_bytes().to_vec())
            .unwrap()
    };
    let rel = rel.trim_start_matches('/').replace('\\', "/");
    if rel.is_empty() || rel.contains("..") {
        return build(403, "Forbidden");
    }
    let full = ROOT.join(&rel);
    // traversal guard (canonicalize resolves symlinks / .. leftovers)
    let canon = full.canonicalize().unwrap_or_else(|_| full.clone());
    let root_canon = ROOT.canonicalize().unwrap_or_else(|_| ROOT.clone());
    if !canon.starts_with(&root_canon) {
        return build(403, "Forbidden");
    }
    match std::fs::read(&full) {
        Ok(bytes) => {
            let ext = std::path::Path::new(&rel)
                .extension()
                .and_then(|e| e.to_str())
                .map(|e| format!(".{}", e.to_ascii_lowercase()))
                .unwrap_or_default();
            let mime = MIME_MAP
                .iter()
                .find(|(k, _)| *k == ext.as_str())
                .map(|(_, v)| *v)
                .unwrap_or("application/octet-stream");
            tauri::http::Response::builder()
                .status(200)
                .header("Content-Type", mime)
                .header("Access-Control-Allow-Origin", "*")
                .header("Cache-Control", "no-store, max-age=0")
                .body(bytes)
                .unwrap()
        }
        Err(_) => build(404, &format!("Not Found: {}", rel)),
    }
}

// ---------------- tray ----------------

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let wake = MenuItem::with_id(app, "wake", "唤醒", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "隐藏", true, None::<&str>)?;
    let reset = MenuItem::with_id(app, "reset", "位置复位", true, None::<&str>)?;
    let rest = MenuItem::with_id(app, "leave", "休息", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;

    let costumes: Vec<(&str, &str)> = vec![
        ("日常装", "casual"),
        ("水手服", "school"),
        ("时尚装", "stylish"),
        ("洋装", "gothic"),
        ("未来科技装", "seed"),
    ];
    let costume_items: Vec<MenuItem<tauri::Wry>> = costumes
        .iter()
        .map(|(label, id)| {
            MenuItem::with_id(app, format!("costume:{}", id), label, true, None::<&str>)
        })
        .collect::<tauri::Result<Vec<_>>>()?;
    // tauri 2.12 Submenu::with_id takes no items — append after creation
    let costume_sub = Submenu::with_id(app, "costumes", "换装", true)?;
    for ci in &costume_items {
        let _ = costume_sub.append(ci);
    }

    let menu = Menu::with_items(
        app,
        &[
            &wake,
            &hide,
            &PredefinedMenuItem::separator(app)?,
            &reset,
            &costume_sub,
            &rest,
            &PredefinedMenuItem::separator(app)?,
            &settings,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    let _tray = TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().unwrap_or_else(|| {
            // pink fallback pixel block if the bundle icon failed to load
            tauri::image::Image::new_owned([255, 120, 170, 255].repeat(32 * 32), 32, 32)
        }))
        .tooltip("AI 女友")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            let id = event.id().as_ref().to_string();
            match id.as_str() {
                "quit" => {
                    backend::kill_backend();
                    app.exit(0);
                }
                "wake" => awaken(app),
                "hide" => {
                    if let Some(m) = main_window(app) {
                        let _ = m.hide();
                    }
                }
                "reset" => {
                    if let Some(m) = main_window(app) {
                        let _ = m.set_position(LogicalPosition::new(0.0, 0.0));
                    }
                }
                "leave" => {
                    let _ = app.emit("tray:action", serde_json::json!({ "action": "leave" }));
                }
                "settings" => {
                    let _ = app.emit("tray:action", serde_json::json!({ "action": "open_settings" }));
                }
                other if other.starts_with("costume:") => {
                    let c = other.split(':').nth(1).unwrap_or("casual");
                    let _ = app.emit(
                        "tray:action",
                        serde_json::json!({ "action": "change_costume", "costume": c }),
                    );
                }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                awaken(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

// ---------------- global shortcut (Ctrl+Alt+G summon) ----------------

/// Register (or re-register after a settings change) the summon shortcut.
/// Electron accelerators like "Control+Alt+G" are normalized for Tauri.
pub fn register_hotkey(app: &AppHandle, accel: &str) -> bool {
    use tauri_plugin_global_shortcut::GlobalShortcutExt;
    let gs = app.global_shortcut();
    let _ = gs.unregister_all();
    let accel = accel.trim();
    if accel.is_empty() {
        return false;
    }
    let norm = accel.replace("Control", "Ctrl").replace("Command", "Cmd");
    let res = gs.on_shortcut(norm.as_str(), move |app, _shortcut, _event| {
        let heart_vis = heart_window(app)
            .and_then(|w| w.is_visible().ok())
            .unwrap_or(false);
        let main_vis = main_window(app)
            .and_then(|w| w.is_visible().ok())
            .unwrap_or(false);
        if heart_vis || !main_vis {
            // bring her back; renderer animates on app:awaken
            set_heart_mode_impl(app, false);
        } else {
            // renderer plays the leave transition and will call
            // set_heart_mode(true) when ready
            let _ = app.emit("shortcut-toggle", serde_json::json!({ "reason": "leave" }));
        }
    });
    match res {
        Ok(_) => {
            println!("[hotkey] registered: {}", norm);
            true
        }
        Err(e) => {
            println!("[hotkey] register failed ({}): {}", norm, e);
            false
        }
    }
}

fn main() {
    // single-instance lock: a 2nd launch wakes the existing girl and exits.
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            println!("[main] second instance launch - waking existing window");
            awaken(app);
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_shell::init())
        .register_uri_scheme_protocol("app", |_app, request| {
            // app://local/renderer/index.html -> ROOT/renderer/index.html
            let rel = percent_decode(request.uri().path());
            serve_app_path(&rel)
        })
        .invoke_handler(tauri::generate_handler![
            commands::config_get,
            commands::config_update,
            commands::window_info,
            commands::window_move_by,
            commands::window_apply_pos,
            commands::window_show,
            commands::window_set_ignore_mouse,
            commands::set_heart_mode,
            commands::set_launch_at_startup,
            commands::screen_capture,
            commands::quit_app,
            commands::open_devtools,
            commands::open_external,
            commands::heart_summon,
            commands::heart_set_hover,
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let cfg = commands::load_merged_config();

            // -------- main window (transparent frameless topmost, hidden until
            // the renderer reports the model is ready — see window_show cmd) ----
            let (sw, sh) = commands::primary_logical_size(&handle);
            let url: tauri::Url = "app://local/renderer/index.html".parse().unwrap();
            let win = WebviewWindowBuilder::new(&handle, "main", WebviewUrl::External(url))
                .title("AI Girlfriend")
                .inner_size(sw, sh)
                .position(0.0, 0.0)
                .transparent(true)
                .decorations(false)
                .resizable(false)
                .minimizable(false)
                .maximizable(false)
                .shadow(false)
                .skip_taskbar(true)
                .always_on_top(true)
                .visible(false)
                .build()?;
            let _ = win.set_ignore_cursor_events(true);
            // restore the remembered position (clamped so a slice always
            // stays on screen); the window is created at (0,0) and repositioned
            // like the Electron shell did
            let wx = cfg.get("window").and_then(|w| w.get("x")).and_then(|v| v.as_f64());
            let wy = cfg.get("window").and_then(|w| w.get("y")).and_then(|v| v.as_f64());
            if let (Some(x), Some(y)) = (wx, wy) {
                let (cx, cy) = commands::clamp_pos(x, y, sw, sh);
                let _ = win.set_position(LogicalPosition::new(cx, cy));
                let _ = win.set_size(LogicalSize::new(sw, sh));
            }

            // -------- heart window (leave-mode mini floating heart) --------
            let hurl: tauri::Url = "app://local/heart/heart.html".parse().unwrap();
            WebviewWindowBuilder::new(&handle, "heart", WebviewUrl::External(hurl))
                .title("AI Girlfriend Heart")
                .inner_size(120.0, 140.0)
                .position(sw - 140.0, sh - 180.0)
                .transparent(true)
                .decorations(false)
                .resizable(false)
                .minimizable(false)
                .maximizable(false)
                .shadow(false)
                .skip_taskbar(true)
                .always_on_top(true)
                .visible(false)
                .build()?;

            // -------- tray --------
            build_tray(&handle)?;

            // -------- global shortcut (from config, default Ctrl+Alt+G) ----
            let hotkey = cfg
                .get("hotkey")
                .and_then(|v| v.as_str())
                .unwrap_or("Control+Alt+G")
                .to_string();
            register_hotkey(&handle, &hotkey);

            // -------- Python backend: reuse an already-running 8765 listener
            // (e.g. the Electron-era backend), else spawn managed -------
            backend::ensure_backend_threaded(handle.clone());

            // -------- mouse polling -> `global-mouse` events --------
            mouse::start(handle.clone());

            // -------- boot safety net: force-show after 15s so error toasts
            // stay visible even when the renderer never reports ready -------
            {
                let h = handle.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(15));
                    if let Some(m) = main_window(&h) {
                        if !m.is_visible().unwrap_or(true) {
                            let _ = m.show();
                            println!("[boot] safety net: window force-shown after 15s");
                        }
                    }
                });
            }

            println!("[main] ready (root={})", ROOT.display());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                RUNNING.store(false, Ordering::Relaxed);
                backend::kill_backend();
                let _ = app; // silence unused in this arm
            }
        });
}
