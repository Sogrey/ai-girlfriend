fn main() {
    // Application commands are exposed to the custom-protocol windows
    // (app:// == http://app.local under WebView2, a REMOTE origin for the
    // IPC ACL). Remote origins must have every command explicitly allowed,
    // which requires registering the app command list here so tauri-build
    // generates the `allow-*` permissions (core:default is NOT enough).
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&[
            "config_get",
            "config_update",
            "window_info",
            "window_move_by",
            "window_apply_pos",
            "window_show",
            "window_set_ignore_mouse",
            "set_heart_mode",
            "set_launch_at_startup",
            "screen_capture",
            "quit_app",
            "open_devtools",
            "open_external",
            "heart_summon",
            "heart_set_hover",
        ])),
    )
    .expect("failed to run tauri-build");
}
