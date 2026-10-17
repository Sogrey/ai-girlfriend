// IPC command surface — the Tauri replacement for every ipcMain.handle/on
// channel the Electron preload exposed as `window.desktop.*` (18 members).
// Payload shapes are kept IDENTICAL so the renderer is untouched
// (renderer/core/desktop-bridge.js maps 1:1 onto these).

use lazy_static::lazy_static;
use serde_json::{json, Value};
use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager};

use crate::main_window;

const MIN_VISIBLE: f64 = 300.0;

lazy_static! {
    static ref CONFIG_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
}

// ---------------- config (config.json + user.json deep-merge, BOM tolerant) ----------------

fn strip_bom(mut s: String) -> String {
    if s.starts_with('\u{FEFF}') {
        s.remove(0);
    }
    s
}

fn read_json(path: &std::path::Path) -> Value {
    match std::fs::read_to_string(path) {
        Ok(s) => serde_json::from_str(&strip_bom(s)).unwrap_or_else(|_| json!({})),
        Err(_) => json!({}),
    }
}

fn merge_into(base: &mut Value, over: Value) {
    if let (Value::Object(b), Value::Object(o)) = (base, &over) {
        for (k, v) in o {
            match b.get_mut(k) {
                Some(slot) if slot.is_object() && v.is_object() => {
                    merge_into(slot, v.clone());
                }
                _ => {
                    b.insert(k.clone(), v.clone());
                }
            }
        }
    }
}

fn config_paths() -> (std::path::PathBuf, std::path::PathBuf) {
    let root = &*crate::ROOT;
    (
        root.join("config").join("config.json"),
        root.join("config").join("user.json"),
    )
}

pub fn load_merged_config() -> Value {
    let (base_p, user_p) = config_paths();
    let mut merged = read_json(&base_p);
    merge_into(&mut merged, read_json(&user_p));
    merged
}

#[tauri::command]
pub fn config_get() -> Result<Value, String> {
    let _g = CONFIG_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    Ok(load_merged_config())
}

#[tauri::command]
pub fn config_update(app: AppHandle, patch: Value) -> Result<Value, String> {
    let _g = CONFIG_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let (_base_p, user_p) = config_paths();

    let old_hotkey = load_merged_config()
        .get("hotkey")
        .and_then(|v| v.as_str())
        .unwrap_or("Control+Alt+G")
        .to_string();
    let raw_hotkey = patch
        .get("hotkey")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    // deep-merge the patch into user.json, write WITHOUT a BOM (the Python
    // backend's load_config silently drops a BOM'd file — 10-14 lesson)
    let mut user = read_json(&user_p);
    merge_into(&mut user, patch.clone());
    std::fs::write(
        &user_p,
        serde_json::to_string_pretty(&user).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;

    let mut merged = load_merged_config();
    // hot re-register the summon shortcut; roll back to the previous
    // accelerator when the new one is invalid/occupied
    if !raw_hotkey.is_empty() && raw_hotkey != old_hotkey {
        if crate::register_hotkey(&app, &raw_hotkey) {
            merged["_hotkey_applied"] = Value::String(raw_hotkey);
        } else {
            let mut rollback = read_json(&user_p);
            merge_into(&mut rollback, json!({ "hotkey": old_hotkey }));
            let _ = std::fs::write(
                &user_p,
                serde_json::to_string_pretty(&rollback).unwrap_or_default(),
            );
            merged["hotkey"] = Value::String(old_hotkey.clone());
            merged["_hotkey_error"] = Value::String(raw_hotkey);
        }
    }
    Ok(merged)
}

// ---------------- window geometry ----------------

/// Primary display size in LOGICAL px (DIP), matching Electron's
/// screen.getPrimaryDisplay().bounds.
pub fn primary_logical_size(app: &AppHandle) -> (f64, f64) {
    let scale = app.primary_monitor().ok().flatten().map(|m| m.scale_factor()).unwrap_or(1.0);
    app.primary_monitor()
        .ok()
        .flatten()
        .map(|m| {
            let s = m.size();
            (s.width as f64 / scale, s.height as f64 / scale)
        })
        .unwrap_or((1536.0, 864.0))
}

/// Clamp like the Electron shell: at least MIN_VISIBLE px of the window
/// stays on screen.
pub fn clamp_pos(x: f64, y: f64, sw: f64, sh: f64) -> (f64, f64) {
    let clamp = |v: f64, lo: f64, hi: f64| v.max(lo).min(hi);
    (
        clamp(x, -(sw - MIN_VISIBLE), sw - MIN_VISIBLE),
        clamp(y, -(sh - MIN_VISIBLE), sh - MIN_VISIBLE),
    )
}

#[cfg(windows)]
fn work_area_logical(scale: f64) -> Value {
    use windows::Win32::Foundation::RECT;
    use windows::Win32::UI::WindowsAndMessaging::{
        SystemParametersInfoW, SPI_GETWORKAREA, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS,
    };
    let mut rc = RECT::default();
    let ok = unsafe {
        SystemParametersInfoW(
            SPI_GETWORKAREA,
            0,
            Some(&mut rc as *mut RECT as *mut core::ffi::c_void),
            SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
        )
    };
    if ok.is_ok() {
        json!({
            "x": rc.left as f64 / scale,
            "y": rc.top as f64 / scale,
            "width": (rc.right - rc.left) as f64 / scale,
            "height": (rc.bottom - rc.top) as f64 / scale,
        })
    } else {
        json!({ "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0 })
    }
}

#[cfg(not(windows))]
fn work_area_logical(_scale: f64) -> Value {
    json!({ "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0 })
}

#[tauri::command]
pub fn window_info(app: AppHandle) -> Result<Value, String> {
    let _g = CONFIG_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let win = main_window(&app).ok_or("main window not ready")?;
    let (sw, sh) = primary_logical_size(&app);
    let scale = win.scale_factor().unwrap_or(1.0);
    let pos = win.outer_position().map_err(|e| e.to_string())?;
    let size = win.outer_size().map_err(|e| e.to_string())?;
    let bounds = json!({
        "x": pos.x as f64 / scale,
        "y": pos.y as f64 / scale,
        "width": size.width as f64 / scale,
        "height": size.height as f64 / scale,
    });
    Ok(json!({
        "bounds": bounds,
        "screen": { "width": sw, "height": sh },
        "workArea": work_area_logical(scale),
    }))
}

#[tauri::command]
pub fn window_move_by(app: AppHandle, dx: f64, dy: f64) {
    let Some(win) = main_window(&app) else { return };
    let (sw, sh) = primary_logical_size(&app);
    let scale = win.scale_factor().unwrap_or(1.0);
    let Ok(pos) = win.outer_position() else { return };
    let (cx, cy) = (pos.x as f64 / scale, pos.y as f64 / scale);
    let (nx, ny) = clamp_pos(cx + dx, cy + dy, sw, sh);
    let _ = win.set_position(LogicalPosition::new(nx, ny));
    // size lock: crossing a mixed-DPI boundary can inflate bounds; always
    // restore the canonical primary logical size (Electron parity)
    let _ = win.set_size(LogicalSize::new(sw, sh));
}

#[tauri::command]
pub fn window_apply_pos(app: AppHandle, x: f64, y: f64) {
    let Some(win) = main_window(&app) else { return };
    let (sw, sh) = primary_logical_size(&app);
    let (cx, cy) = clamp_pos(x, y, sw, sh);
    let _ = win.set_position(LogicalPosition::new(cx, cy));
    let _ = win.set_size(LogicalSize::new(sw, sh));
}

#[tauri::command]
pub fn window_show(app: AppHandle) {
    // renderer says model + textures are ready -> reveal the window
    if let Some(win) = main_window(&app) {
        let _ = win.show();
    }
}

#[tauri::command]
pub fn window_set_ignore_mouse(app: AppHandle, ignore: bool) {
    if let Some(win) = main_window(&app) {
        let _ = win.set_ignore_cursor_events(ignore);
    }
}

// ---------------- lifecycle ----------------

#[tauri::command]
pub fn set_heart_mode(app: AppHandle, show_heart: bool) -> Result<bool, String> {
    crate::set_heart_mode_impl(&app, show_heart);
    Ok(true)
}

#[tauri::command]
pub fn quit_app(app: AppHandle) {
    crate::backend::kill_backend();
    app.exit(0);
}

#[tauri::command]
pub fn set_launch_at_startup(app: AppHandle, enabled: bool) -> Result<bool, String> {
    use tauri_plugin_autostart::ManagerExt;
    let al = app.autolaunch();
    if enabled {
        al.enable().map_err(|e| e.to_string())?;
    } else {
        al.disable().map_err(|e| e.to_string())?;
    }
    Ok(true)
}

#[tauri::command]
pub fn open_devtools(app: AppHandle) {
    if let Some(win) = main_window(&app) {
        // DevTools only ship in debug builds (tauri debug feature)
        #[cfg(debug_assertions)]
        win.open_devtools();
        #[cfg(not(debug_assertions))]
        let _ = &win;
    }
}

/// Open an external http(s) link in the default browser (Electron's
/// setWindowOpenHandler parity — the bridge hooks window.open onto this).
#[tauri::command]
pub fn open_external(app: AppHandle, url: String) -> Result<(), String> {
    use tauri_plugin_shell::ShellExt;
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err("only http(s) urls can be opened".into());
    }
    app.shell()
        .open(url, None::<tauri_plugin_shell::open::Program>)
        .map_err(|e| e.to_string())
}

// ---------------- heart window side ----------------

#[tauri::command]
pub fn heart_summon(app: AppHandle) {
    // heart.html click -> wake the girl
    crate::awaken(&app);
}

#[tauri::command]
pub fn heart_set_hover(app: AppHandle, hovering: bool) {
    // keep the tiny heart window interactive only on hover (Electron parity)
    if let Some(h) = app.get_webview_window("heart") {
        let _ = h.set_ignore_cursor_events(!hovering);
    }
}

// ---------------- screen capture (P38 screen awareness) ----------------

/// Returns the SAME {ok, data|error} shape the Electron handler returned —
/// errors arrive as a resolved promise, not a rejection.
#[tauri::command]
pub fn screen_capture() -> Value {
    match crate::capture::capture_primary_jpeg_b64() {
        Ok(b64) => json!({ "ok": true, "data": b64 }),
        Err(e) => json!({ "ok": false, "error": e }),
    }
}
