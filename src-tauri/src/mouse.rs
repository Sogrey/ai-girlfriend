// 33ms global cursor polling (Electron startMousePolling parity).
// The renderer's whole proximity model (toolbar summon, near-avatar hit
// tests, drag) runs on this `global-mouse` event, NOT on forwarded
// mousemove — which is exactly why Tauri's set_ignore_cursor_events
// (no event forwarding) works without touching the renderer.
// Payload: global x/y (screen DIP) + local lx/ly (window DIP).
use std::time::Duration;

use tauri::{AppHandle, Emitter};

use crate::{main_window, RUNNING};

#[cfg(windows)]
fn cursor_physical() -> Option<(i32, i32)> {
    use windows::Win32::Foundation::POINT;
    use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;
    let mut pt = POINT::default();
    let ok = unsafe { GetCursorPos(&mut pt) };
    if ok.is_ok() {
        Some((pt.x, pt.y))
    } else {
        None
    }
}

#[cfg(not(windows))]
fn cursor_physical() -> Option<(i32, i32)> {
    None
}

pub fn start(app: AppHandle) {
    std::thread::spawn(move || {
        loop {
            if !RUNNING.load(std::sync::atomic::Ordering::Relaxed) {
                break;
            }
            let Some(win) = main_window(&app) else {
                std::thread::sleep(Duration::from_millis(200));
                continue;
            };
            if !win.is_visible().unwrap_or(false) {
                std::thread::sleep(Duration::from_millis(33));
                continue;
            }
            let Some((px, py)) = cursor_physical() else {
                std::thread::sleep(Duration::from_millis(33));
                continue;
            };
            let scale = win.scale_factor().unwrap_or(1.0);
            let origin = win.outer_position().unwrap_or_default();
            let payload = serde_json::json!({
                "x": px as f64 / scale,
                "y": py as f64 / scale,
                "lx": (px - origin.x) as f64 / scale,
                "ly": (py - origin.y) as f64 / scale,
            });
            let _ = app.emit("global-mouse", payload);
            std::thread::sleep(Duration::from_millis(33));
        }
        println!("[mouse] polling thread stopped");
    });
}
