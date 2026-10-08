#![cfg_attr(windows, windows_subsystem = "windows")]

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const MAGIC: &[u8; 8] = b"AGTFT001";
const TRAILER_LEN: u64 = 48;
const PAGE: &[u8] = include_bytes!("../../../ui/tauri-design/bootstrap.html");
const CSS: &[u8] = include_bytes!("../../../ui/tauri-design/style.css");
const SCRIPT: &[u8] = include_bytes!("../../../ui/tauri-design/bootstrap.js");
const PENGU: &[u8] = include_bytes!("../../../ui/tauri-design/assets/pengu.png");
const BRAND: &[u8] = include_bytes!("../../../ui/tauri-design/assets/agente-pengu.png");
const FONT_400: &[u8] = include_bytes!("../../../ui/tauri-design/assets/manrope-400.ttf");
const FONT_600: &[u8] = include_bytes!("../../../ui/tauri-design/assets/manrope-600.ttf");
const FONT_800: &[u8] = include_bytes!("../../../ui/tauri-design/assets/manrope-800.ttf");

#[derive(Clone)]
struct State {
    phase: &'static str,
    message: String,
    error: String,
    url: String,
}

impl State {
    fn new() -> Self {
        Self {
            phase: "verifying",
            message: "Verificando o pacote incluído…".into(),
            error: String::new(),
            url: String::new(),
        }
    }
    fn json(&self) -> Value {
        json!({"phase": self.phase, "message": self.message, "error": self.error, "url": self.url})
    }
}

fn set_state(state: &Arc<Mutex<State>>, phase: &'static str, message: &str) {
    let mut current = state.lock().unwrap();
    current.phase = phase;
    current.message = message.into();
}

fn bundled_payload(executable: &Path) -> Result<(u64, u64, [u8; 32]), String> {
    let mut file = File::open(executable).map_err(|e| e.to_string())?;
    let size = file.metadata().map_err(|e| e.to_string())?.len();
    if size < TRAILER_LEN {
        return Err("O instalador está incompleto.".into());
    }
    file.seek(SeekFrom::End(-(TRAILER_LEN as i64)))
        .map_err(|e| e.to_string())?;
    let mut expected = [0; 32];
    let mut length = [0; 8];
    let mut magic = [0; 8];
    file.read_exact(&mut expected).map_err(|e| e.to_string())?;
    file.read_exact(&mut length).map_err(|e| e.to_string())?;
    file.read_exact(&mut magic).map_err(|e| e.to_string())?;
    if &magic != MAGIC {
        return Err("O pacote de instalação está ausente ou inválido.".into());
    }
    let payload_len = u64::from_le_bytes(length);
    if payload_len < 1024 * 1024 || payload_len > size - TRAILER_LEN {
        return Err("O tamanho do pacote de instalação é inválido.".into());
    }
    Ok((size - TRAILER_LEN - payload_len, payload_len, expected))
}

fn extract_verified(executable: &Path, destination: Option<&Path>) -> Result<String, String> {
    let (offset, length, expected) = bundled_payload(executable)?;
    let mut source = File::open(executable).map_err(|e| e.to_string())?;
    source
        .seek(SeekFrom::Start(offset))
        .map_err(|e| e.to_string())?;
    let mut reader = source.take(length);
    let mut target = match destination {
        Some(path) => Some(
            File::create(path)
                .map_err(|e| format!("Não foi possível preparar o instalador temporário: {e}"))?,
        ),
        None => None,
    };
    let mut hash = Sha256::new();
    // The Windows GUI main thread has a small default stack. Keep the copy
    // buffer on the heap; a 1 MiB stack array crashed the packaged EXE before
    // it could show a useful error.
    let mut buffer = vec![0u8; 1024 * 1024];
    let mut consumed = 0u64;
    loop {
        let count = reader.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
        if let Some(file) = target.as_mut() {
            file.write_all(&buffer[..count])
                .map_err(|e| e.to_string())?;
        }
        consumed += count as u64;
    }
    if consumed != length || hash.finalize().as_slice() != expected {
        drop(target.take());
        if let Some(path) = destination {
            let _ = fs::remove_file(path);
        }
        return Err("A verificação SHA-256 do pacote falhou. Baixe o instalador novamente.".into());
    }
    if let Some(file) = target.as_mut() {
        file.flush().map_err(|e| e.to_string())?;
    }
    Ok(expected.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn response(stream: &mut TcpStream, code: &str, mime: &str, body: &[u8]) -> std::io::Result<()> {
    write!(stream, "HTTP/1.1 {code}\r\nContent-Type: {mime}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n", body.len())?;
    stream.write_all(body)
}

fn serve_one(mut stream: TcpStream, token: &str, state: &Arc<Mutex<State>>) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(4)));
    let mut request = [0u8; 4096];
    let count = match stream.read(&mut request) {
        Ok(count) => count,
        Err(_) => return,
    };
    let first = String::from_utf8_lossy(&request[..count]);
    let path = match first
        .lines()
        .next()
        .and_then(|line| line.strip_prefix("GET "))
        .and_then(|line| line.split(' ').next())
    {
        Some(path) => path.split('?').next().unwrap_or(""),
        None => return,
    };
    let prefix = format!("/{token}/");
    if !path.starts_with(&prefix) {
        let _ = response(&mut stream, "404 Not Found", "text/plain", b"Not found");
        return;
    }
    let relative = &path[prefix.len()..];
    let (mime, body): (&str, &[u8]) = match relative {
        "" | "bootstrap.html" => ("text/html; charset=utf-8", PAGE),
        "style.css" => ("text/css; charset=utf-8", CSS),
        "bootstrap.js" => ("application/javascript; charset=utf-8", SCRIPT),
        "assets/pengu.png" => ("image/png", PENGU),
        "assets/agente-pengu.png" => ("image/png", BRAND),
        "assets/manrope-400.ttf" | "assets/manrope-500.ttf" => ("font/ttf", FONT_400),
        "assets/manrope-600.ttf" | "assets/manrope-700.ttf" => ("font/ttf", FONT_600),
        "assets/manrope-800.ttf" => ("font/ttf", FONT_800),
        "api/state" => {
            let data = state.lock().unwrap().json().to_string();
            let _ = response(
                &mut stream,
                "200 OK",
                "application/json; charset=utf-8",
                data.as_bytes(),
            );
            return;
        }
        _ => {
            let _ = response(&mut stream, "404 Not Found", "text/plain", b"Not found");
            return;
        }
    };
    let _ = response(&mut stream, "200 OK", mime, body);
}

fn start_server(state: Arc<Mutex<State>>) -> Result<String, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("Não foi possível abrir a interface local: {e}"))?;
    let token = format!("{:032x}", rand::random::<u128>());
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let serving_token = token.clone();
    thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let status = state.clone();
            let token = serving_token.clone();
            thread::spawn(move || serve_one(stream, &token, &status));
        }
    });
    Ok(format!("http://127.0.0.1:{port}/{token}/"))
}

fn local_data() -> PathBuf {
    env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(env::temp_dir)
}

fn log_line(message: &str) {
    let path = local_data().join("AgenteTFT-HM45");
    let _ = fs::create_dir_all(&path);
    if let Ok(mut log) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path.join("bootstrap.log"))
    {
        let _ = writeln!(log, "{message}");
    }
}

fn browser(url: &str) -> Result<(), String> {
    let roots = [
        env::var_os("ProgramFiles(x86)"),
        env::var_os("ProgramFiles"),
        env::var_os("LOCALAPPDATA"),
    ];
    for root in roots.into_iter().flatten() {
        for relative in [
            "Microsoft/Edge/Application/msedge.exe",
            "Google/Chrome/Application/chrome.exe",
        ] {
            let exe = PathBuf::from(&root).join(relative);
            if exe.is_file() {
                let profile = local_data().join("AgenteTFT-HUD-HM4").join("setup-browser");
                fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
                Command::new(&exe)
                    .arg(format!("--app={url}"))
                    .arg("--new-window")
                    .arg(format!("--user-data-dir={}", profile.display()))
                    .arg("--no-first-run")
                    .arg("--no-default-browser-check")
                    .arg("--window-size=1120,800")
                    .spawn()
                    .map_err(|e| e.to_string())?;
                return Ok(());
            }
        }
    }
    #[cfg(windows)]
    {
        Command::new("cmd")
            .args(["/C", "start", "", url])
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[cfg(not(windows))]
    {
        Err("Nenhum navegador disponível para mostrar a instalação.".into())
    }
}

fn install(state: &Arc<Mutex<State>>) -> Result<(), String> {
    let self_path = env::current_exe().map_err(|e| e.to_string())?;
    let temporary =
        env::temp_dir().join(format!("AgenteTFT-HM45-inner-{}.exe", std::process::id()));
    set_state(state, "extracting", "Preparando e verificando os arquivos…");
    let digest = extract_verified(&self_path, Some(&temporary))?;
    log_line(&format!("Inner installer SHA-256: {digest}"));
    set_state(
        state,
        "installing",
        "Instalando o aplicativo Windows e criando os atalhos…",
    );
    let destination = local_data().join("AgenteTFT-HM45");
    let result = Command::new(&temporary)
        .arg("/VERYSILENT")
        .arg("/SUPPRESSMSGBOXES")
        .arg("/NORESTART")
        .arg(format!("/DIR={}", destination.display()))
        .status()
        .map_err(|e| format!("O instalador interno não iniciou: {e}"));
    let _ = fs::remove_file(&temporary);
    let exit = result?;
    if !exit.success() {
        return Err(format!("A instalação do aplicativo falhou (código {:?}). Veja o log em %TEMP%\\Setup Log*.txt.", exit.code()));
    }
    let app = destination.join("AgenteTFT-HUD-HM4-Auto.exe");
    if !app.is_file() {
        return Err(format!(
            "O aplicativo não foi encontrado após instalar: {}",
            app.display()
        ));
    }
    let handoff =
        env::temp_dir().join(format!("AgenteTFT-HM45-handoff-{}.txt", std::process::id()));
    let _ = fs::remove_file(&handoff);
    set_state(state, "starting", "Abrindo a configuração e o teste da VM…");
    let mut child = Command::new(&app)
        .arg("--setup-assistant")
        .env("AGENTE_TFT_BOOTSTRAP_URL_FILE", &handoff)
        .spawn()
        .map_err(|e| format!("O assistente da VM não iniciou: {e}"))?;
    let deadline = Instant::now() + Duration::from_secs(90);
    loop {
        if let Ok(url) = fs::read_to_string(&handoff) {
            let url = url.trim();
            if url.starts_with("http://127.0.0.1:") && url.contains("realInstaller=1") {
                state.lock().unwrap().url = url.into();
                set_state(state, "handoff", "Configuração da VM aberta.");
                let _ = fs::remove_file(&handoff);
                return Ok(());
            }
        }
        if let Ok(Some(exit)) = child.try_wait() {
            return Err(format!(
                "O assistente da VM encerrou cedo (código {:?}).",
                exit.code()
            ));
        }
        if Instant::now() >= deadline {
            return Err("A configuração da VM não abriu em 90 segundos. Veja o registro de inicialização do aplicativo.".into());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

fn main() {
    if env::args_os()
        .nth(1)
        .is_some_and(|arg| arg == "--bootstrap-smoke-output")
    {
        let output = env::args_os()
            .nth(2)
            .map(PathBuf::from)
            .expect("smoke output path required");
        let executable = env::current_exe().expect("current executable");
        let result = extract_verified(&executable, None).expect("bundled installer integrity");
        fs::write(output, json!({"payload_verified": true, "payload_sha256": result,
            "designer_embedded": std::str::from_utf8(PAGE).unwrap().contains("installer-stage") && CSS.len() > 1000,
            "bootstrap_api_embedded": SCRIPT.windows(9).any(|part| part == b"api/state")}).to_string()).expect("write smoke output");
        return;
    }
    let state = Arc::new(Mutex::new(State::new()));
    let url = match start_server(state.clone()) {
        Ok(url) => url,
        Err(error) => {
            log_line(&error);
            return;
        }
    };
    if let Err(error) = browser(&url) {
        log_line(&error);
        return;
    }
    match install(&state) {
        Ok(()) => thread::sleep(Duration::from_secs(30)),
        Err(error) => {
            log_line(&error);
            let mut current = state.lock().unwrap();
            current.phase = "error";
            current.error = format!(
                "{error} Registro: {}",
                local_data()
                    .join("AgenteTFT-HM45")
                    .join("bootstrap.log")
                    .display()
            );
            drop(current);
            thread::sleep(Duration::from_secs(300));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn embedded_design_is_dark_and_complete() {
        assert!(std::str::from_utf8(PAGE)
            .unwrap()
            .contains("installer-stage"));
        assert!(std::str::from_utf8(CSS)
            .unwrap()
            .contains(".real-installer"));
        assert!(std::str::from_utf8(SCRIPT).unwrap().contains("api/state"));
        assert!(!PENGU.is_empty());
    }
    #[test]
    fn rejects_unbundled_binary() {
        let path = env::current_exe().unwrap();
        assert!(bundled_payload(&path).is_err());
    }
    #[test]
    fn verifies_overlay_and_rejects_corruption() {
        let path = env::temp_dir().join(format!("agente-tft-overlay-test-{}", std::process::id()));
        let payload = vec![42u8; 1024 * 1024];
        let mut file = File::create(&path).unwrap();
        file.write_all(b"bootstrap").unwrap();
        file.write_all(&payload).unwrap();
        file.write_all(Sha256::digest(&payload).as_slice()).unwrap();
        file.write_all(&(payload.len() as u64).to_le_bytes())
            .unwrap();
        file.write_all(MAGIC).unwrap();
        file.flush().unwrap();
        assert!(extract_verified(&path, None).is_ok());
        file.seek(SeekFrom::Start(9)).unwrap();
        file.write_all(b"x").unwrap();
        file.flush().unwrap();
        assert!(extract_verified(&path, None).is_err());
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn serves_first_designer_page_and_live_status_on_loopback() {
        let state = Arc::new(Mutex::new(State::new()));
        let base = start_server(state).unwrap();
        let authority = base
            .trim_start_matches("http://")
            .split('/')
            .next()
            .unwrap();
        for (relative, marker) in [("", "installer-stage"), ("api/state", "verifying")] {
            let mut stream = TcpStream::connect(authority).unwrap();
            stream
                .write_all(
                    format!(
                        "GET /{}/{} HTTP/1.1\r\nHost: {authority}\r\n\r\n",
                        base.rsplit('/').nth(1).unwrap(),
                        relative
                    )
                    .as_bytes(),
                )
                .unwrap();
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes).unwrap();
            let reply = String::from_utf8_lossy(&bytes);
            assert!(reply.contains("200 OK"), "{reply}");
            assert!(reply.contains(marker), "{reply}");
        }
    }
}
