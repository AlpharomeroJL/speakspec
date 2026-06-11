// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(err) = speakspec_lib::run() {
        eprintln!("Speakspec failed to start: {err:#}");
        std::process::exit(1);
    }
}
