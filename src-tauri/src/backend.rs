// Python backend lifecycle (Electron launcher .bat parity, in-process):
//   - on startup: when 127.0.0.1:8765 already answers TCP, REUSE that
//     backend (e.g. one started by the old Electron .bat — the two shells
//     can even run side by side); otherwise spawn
//     `.venv/Scripts/python.exe backend/main.py` with CREATE_NO_WINDOW,
//     pipe stdout/stderr into .temp/tauri-backend.log
//   - on exit: kill OUR child's whole tree (taskkill /T /F); a REUSED
//     backend is never killed (it is not ours)
use std::io::{BufRead, BufReader, Read};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use lazy_static::lazy_static;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const BACKEND_PORT: u16 = 8765;
const START_WAIT_SECS: u32 = 40;

lazy_static! {
    /// The child WE spawned (None when the backend was reused / never started).
    static ref CHILD: Mutex<Option<Child>> = Mutex::new(None);
    static ref START_LOCK: Mutex<()> = Mutex::new(());
}

fn port_open() -> bool {
    let addr = format!("127.0.0.1:{}", BACKEND_PORT);
    let Ok(addr) = addr.parse() else { return false };
    TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok()
}

/// Fire-and-forget startup (never blocks window creation).
pub fn ensure_backend_threaded(_app: tauri::AppHandle) {
    std::thread::spawn(|| {
        let _g = START_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        if port_open() {
            println!("[backend] port {} already listening - reusing it", BACKEND_PORT);
            return;
        }
        let root = crate::ROOT.clone();
        let py = root.join(".venv").join("Scripts").join("python.exe");
        let script = root.join("backend").join("main.py");
        if !py.exists() || !script.exists() {
            println!(
                "[backend] venv/backend not found under {} — run 首次安装.bat first",
                root.display()
            );
            return;
        }
        let mut cmd = Command::new(&py);
        cmd.arg(&script)
            .current_dir(&root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);
        match cmd.spawn() {
            Ok(mut child) => {
                let pid = child.id();
                println!("[backend] spawned pid={} (python {})", pid, py.display());
                if let Some(out) = child.stdout.take() {
                    log_reader(out, "out");
                }
                if let Some(err) = child.stderr.take() {
                    log_reader(err, "err");
                }
                *CHILD.lock().unwrap_or_else(|p| p.into_inner()) = Some(child);
            }
            Err(e) => {
                println!("[backend] spawn failed: {}", e);
                return;
            }
        }
        // wait until the port answers (the STT model loads in background
        // threads; the ws endpoint comes up fast)
        for _ in 0..START_WAIT_SECS {
            if port_open() {
                println!("[backend] ready on {}", BACKEND_PORT);
                return;
            }
            std::thread::sleep(Duration::from_secs(1));
        }
        println!(
            "[backend] start timeout after {}s — check .temp/tauri-backend.log",
            START_WAIT_SECS
        );
    });
}

/// Append every backend log line to .temp/tauri-backend.log and echo to stdout.
fn log_reader<R: Read + Send + 'static>(r: R, tag: &'static str) {
    std::thread::spawn(move || {
        let root = crate::ROOT.clone();
        let _ = std::fs::create_dir_all(root.join(".temp"));
        let path = root.join(".temp").join("tauri-backend.log");
        let reader = BufReader::new(r);
        for line in reader.lines().map_while(|l| l.ok()) {
            let _ = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&path)
                .and_then(|mut f| {
                    use std::io::Write;
                    writeln!(f, "[{}] {}", tag, line)
                });
            println!("[backend:{}] {}", tag, line);
        }
    });
}

/// Kill the backend WE spawned (whole tree). A reused backend stays alive.
pub fn kill_backend() {
    let mut guard = CHILD.lock().unwrap_or_else(|p| p.into_inner());
    if let Some(child) = guard.as_mut() {
        let pid = child.id();
        let mut kill = Command::new("taskkill");
        kill.args(["/F", "/T", "/PID", &pid.to_string()])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        kill.creation_flags(CREATE_NO_WINDOW);
        let _ = kill.status();
        let _ = child.kill();
        let _ = child.wait();
        println!("[backend] killed pid={}", pid);
    }
}
