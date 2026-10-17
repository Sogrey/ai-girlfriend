// Primary-display capture for screen awareness (P38) — the Tauri
// replacement for Electron's desktopCapturer. Grabs the primary monitor
// via xcap, downscales to ~1120px wide (the sweet spot for glm-4v /
// qwen-vl class vision models), encodes JPEG q85 -> base64.
// Never written to disk; only ever triggered on explicit user action.
use std::io::Cursor;

use base64::Engine as _;

pub fn capture_primary_jpeg_b64() -> Result<String, String> {
    let monitors = xcap::Monitor::all().map_err(|e| format!("枚举屏幕失败: {}", e))?;
    let monitor = monitors
        .iter()
        .find(|m| m.is_primary().unwrap_or(false))
        .or_else(|| monitors.first())
        .ok_or("没有可用的屏幕采集源")?;
    let img = monitor
        .capture_image()
        .map_err(|e| format!("截图失败: {}", e))?;
    let (w, h) = (img.width(), img.height());
    if w == 0 || h == 0 {
        return Err("截图内容为空".into());
    }
    // downscale to the Electron parity target (1120px class, keep ratio)
    let tw = w.min(1120);
    let th = ((h as f64 * (tw as f64 / w as f64)).round() as u32).max(1);
    let scaled = image::imageops::resize(&img, tw, th, image::imageops::FilterType::Triangle);
    let rgb = image::DynamicImage::ImageRgba8(scaled).to_rgb8();
    let mut buf = Cursor::new(Vec::new());
    let enc = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buf, 85);
    rgb.write_with_encoder(enc)
        .map_err(|e| format!("JPEG 编码失败: {}", e))?;
    let bytes = buf.into_inner();
    if bytes.is_empty() {
        return Err("截图内容为空".into());
    }
    Ok(base64::engine::general_purpose::STANDARD.encode(bytes))
}
