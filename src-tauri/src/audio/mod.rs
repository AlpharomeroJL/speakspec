//! Audio capture (Phase 7): CPAL recording with pause/resume, live levels,
//! silence auto-stop, and duration limits.
//!
//! `cpal::Stream` is `!Send`, so a dedicated audio thread owns the stream and
//! is driven by commands over a channel. The CPAL callback only forwards raw
//! samples; all bookkeeping (mono downmix, WAV writing, level aggregation,
//! silence tracking, limits) happens on the audio thread.
//!
//! Pause keeps the stream open and discards samples, so resuming continues
//! the same WAV file with no gap and no duplicate content.

use std::path::PathBuf;
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter};

/// Tauri events pushed by the recorder.
pub mod events {
    /// ~20 Hz level updates. Payload: `{ rms, peak, elapsed_ms, paused }`.
    pub const AUDIO_LEVEL: &str = "audio://level";
    /// State changes. Payload: `{ state: idle|recording|paused|stopped, .. }`.
    pub const AUDIO_STATE: &str = "audio://state";
    /// Time-limit warning. Payload: `{ kind: duration-warning, elapsed_ms }`.
    pub const AUDIO_WARNING: &str = "audio://warning";
}

/// Why a recording ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum StopReason {
    /// The user pressed stop.
    User,
    /// Sustained silence crossed the configured threshold.
    Silence,
    /// The 30-minute hard limit was reached.
    HardLimit,
}

/// Result of a finished recording.
#[derive(Debug, Clone, Serialize)]
pub struct RecordingResult {
    /// Path of the written WAV file.
    pub path: String,
    /// Recorded (non-paused) duration in milliseconds.
    pub duration_ms: u64,
    /// Why the recording stopped.
    pub reason: StopReason,
    /// Sample rate of the WAV file.
    pub sample_rate: u32,
}

/// Tunables; defaults follow the PRD. Overridable via `RecorderConfig::from_env`.
#[derive(Debug, Clone)]
pub struct RecorderConfig {
    /// RMS below this (dBFS) counts as silence.
    pub silence_threshold_dbfs: f32,
    /// Continuous silence longer than this auto-stops the recording.
    pub silence_duration: Duration,
    /// Emit a warning event at this elapsed recording time.
    pub warn_at: Duration,
    /// Hard-stop the recording at this elapsed time.
    pub hard_stop_at: Duration,
}

impl Default for RecorderConfig {
    fn default() -> Self {
        Self {
            silence_threshold_dbfs: -40.0,
            silence_duration: Duration::from_secs(4),
            warn_at: Duration::from_secs(25 * 60),
            hard_stop_at: Duration::from_secs(30 * 60),
        }
    }
}

impl RecorderConfig {
    /// Defaults with optional env overrides (useful for tests):
    /// `SPEAKSPEC_SILENCE_MS`, `SPEAKSPEC_WARN_MS`, `SPEAKSPEC_HARDSTOP_MS`.
    pub fn from_env() -> Self {
        let mut config = Self::default();
        if let Some(ms) = env_ms("SPEAKSPEC_SILENCE_MS") {
            config.silence_duration = ms;
        }
        if let Some(ms) = env_ms("SPEAKSPEC_WARN_MS") {
            config.warn_at = ms;
        }
        if let Some(ms) = env_ms("SPEAKSPEC_HARDSTOP_MS") {
            config.hard_stop_at = ms;
        }
        config
    }
}

fn env_ms(name: &str) -> Option<Duration> {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .map(Duration::from_millis)
}

enum AudioCmd {
    Start {
        path: PathBuf,
        reply: Sender<Result<(), String>>,
    },
    Pause {
        reply: Sender<Result<(), String>>,
    },
    Resume {
        reply: Sender<Result<(), String>>,
    },
    Stop {
        reply: Sender<Result<RecordingResult, String>>,
    },
}

/// Cloneable, `Send + Sync` controller stored in Tauri state. Talks to the
/// audio thread over a channel.
#[derive(Clone)]
pub struct AudioController {
    cmd_tx: Sender<AudioCmd>,
}

impl AudioController {
    /// Spawn the audio thread and return its controller.
    pub fn new(app: AppHandle, config: RecorderConfig) -> Self {
        let (cmd_tx, cmd_rx) = std::sync::mpsc::channel();
        std::thread::Builder::new()
            .name("speakspec-audio".into())
            .spawn(move || audio_thread(app, config, cmd_rx))
            .map_err(|e| eprintln!("[audio] could not spawn audio thread: {e}"))
            .ok();
        Self { cmd_tx }
    }

    fn round_trip<T>(&self, make: impl FnOnce(Sender<Result<T, String>>) -> AudioCmd) -> Result<T, String> {
        let (tx, rx) = std::sync::mpsc::channel();
        self.cmd_tx
            .send(make(tx))
            .map_err(|_| "the audio thread is not running".to_string())?;
        rx.recv_timeout(Duration::from_secs(10))
            .map_err(|_| "the audio thread did not respond".to_string())?
    }

    /// Start recording into `path` (a `.wav` file).
    pub fn start(&self, path: PathBuf) -> Result<(), String> {
        self.round_trip(|reply| AudioCmd::Start { path, reply })
    }

    /// Pause: keep the stream open, discard samples.
    pub fn pause(&self) -> Result<(), String> {
        self.round_trip(|reply| AudioCmd::Pause { reply })
    }

    /// Resume appending to the same file.
    pub fn resume(&self) -> Result<(), String> {
        self.round_trip(|reply| AudioCmd::Resume { reply })
    }

    /// Stop and finalize the WAV file.
    pub fn stop(&self) -> Result<RecordingResult, String> {
        self.round_trip(|reply| AudioCmd::Stop { reply })
    }
}

struct ActiveRecording {
    _stream: cpal::Stream, // held to keep capturing; dropped on stop
    sample_rx: Receiver<Vec<f32>>,
    writer: hound::WavWriter<std::io::BufWriter<std::fs::File>>,
    path: PathBuf,
    sample_rate: u32,
    channels: u16,
    paused: Arc<std::sync::atomic::AtomicBool>,
    written_frames: u64,
    silence_run_ms: f64,
    warned: bool,
    level_window: Vec<f32>,
}

fn audio_thread(app: AppHandle, config: RecorderConfig, cmd_rx: Receiver<AudioCmd>) {
    let mut active: Option<ActiveRecording> = None;
    loop {
        // Drain pending samples frequently; poll commands with a short wait.
        match cmd_rx.recv_timeout(Duration::from_millis(25)) {
            Ok(AudioCmd::Start { path, reply }) => {
                if active.is_some() {
                    let _ = reply.send(Err("a recording is already in progress".into()));
                    continue;
                }
                match begin_recording(&path) {
                    Ok(rec) => {
                        emit_state(&app, "recording", json!({ "path": path.to_string_lossy() }));
                        active = Some(rec);
                        let _ = reply.send(Ok(()));
                    }
                    Err(err) => {
                        let _ = reply.send(Err(format!("{err:#}")));
                    }
                }
            }
            Ok(AudioCmd::Pause { reply }) => {
                let _ = reply.send(match active.as_mut() {
                    Some(rec) => {
                        rec.paused.store(true, std::sync::atomic::Ordering::SeqCst);
                        rec.silence_run_ms = 0.0;
                        emit_state(&app, "paused", json!({}));
                        Ok(())
                    }
                    None => Err("no recording is in progress".into()),
                });
            }
            Ok(AudioCmd::Resume { reply }) => {
                let _ = reply.send(match active.as_mut() {
                    Some(rec) => {
                        rec.paused.store(false, std::sync::atomic::Ordering::SeqCst);
                        emit_state(&app, "recording", json!({}));
                        Ok(())
                    }
                    None => Err("no recording is in progress".into()),
                });
            }
            Ok(AudioCmd::Stop { reply }) => {
                let _ = reply.send(match active.take() {
                    Some(rec) => finalize(&app, rec, StopReason::User).map_err(|e| format!("{e:#}")),
                    None => Err("no recording is in progress".into()),
                });
            }
            Err(RecvTimeoutError::Disconnected) => return,
            Err(RecvTimeoutError::Timeout) => {}
        }

        // Pump captured samples into the writer and run the bookkeeping.
        if let Some(mut rec) = active.take() {
            match pump(&app, &config, &mut rec) {
                Ok(None) => active = Some(rec),
                Ok(Some(reason)) => match finalize(&app, rec, reason) {
                    Ok(result) => {
                        emit_state(
                            &app,
                            "stopped",
                            json!({ "reason": reason, "result": result }),
                        );
                    }
                    Err(err) => eprintln!("[audio] finalize after auto-stop failed: {err:#}"),
                },
                Err(err) => {
                    eprintln!("[audio] recording error: {err:#}");
                    emit_state(&app, "error", json!({ "message": format!("{err:#}") }));
                    // Best effort: finalize what we have.
                    if let Ok(result) = finalize(&app, rec, StopReason::User) {
                        emit_state(&app, "stopped", json!({ "reason": "user", "result": result }));
                    }
                }
            }
        }
    }
}

/// Open the default input device and start capturing into a channel.
fn begin_recording(path: &PathBuf) -> Result<ActiveRecording> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).context("could not create the recording directory")?;
    }
    let host = cpal::default_host();
    let device = host.default_input_device().ok_or_else(|| {
        anyhow!(
            "No microphone was found. Connect one, or check that apps are \
             allowed to use the microphone in Windows privacy settings."
        )
    })?;
    let device_config = device.default_input_config().map_err(|e| {
        anyhow!(
            "The microphone could not be opened ({e}). Check Windows privacy \
             settings: Settings > Privacy & security > Microphone."
        )
    })?;
    let sample_rate = device_config.sample_rate().0;
    let channels = device_config.channels();

    let spec = hound::WavSpec {
        channels: 1,
        sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let writer = hound::WavWriter::create(path, spec)
        .with_context(|| format!("could not create {}", path.display()))?;

    let (sample_tx, sample_rx) = std::sync::mpsc::channel::<Vec<f32>>();
    let paused = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let err_flag = Arc::new(Mutex::new(None::<String>));

    let err_cb = Arc::clone(&err_flag);
    let on_err = move |err: cpal::StreamError| {
        if let Ok(mut slot) = err_cb.lock() {
            *slot = Some(err.to_string());
        }
    };

    let stream = match device_config.sample_format() {
        cpal::SampleFormat::F32 => {
            let tx = sample_tx.clone();
            device.build_input_stream(
                &device_config.into(),
                move |data: &[f32], _| {
                    let _ = tx.send(data.to_vec());
                },
                on_err,
                None,
            )
        }
        cpal::SampleFormat::I16 => {
            let tx = sample_tx.clone();
            device.build_input_stream(
                &device_config.into(),
                move |data: &[i16], _| {
                    let _ = tx.send(data.iter().map(|s| f32::from(*s) / 32768.0).collect());
                },
                on_err,
                None,
            )
        }
        cpal::SampleFormat::U16 => {
            let tx = sample_tx.clone();
            device.build_input_stream(
                &device_config.into(),
                move |data: &[u16], _| {
                    let _ = tx.send(
                        data.iter()
                            .map(|s| (f32::from(*s) - 32768.0) / 32768.0)
                            .collect(),
                    );
                },
                on_err,
                None,
            )
        }
        other => {
            return Err(anyhow!(
                "The microphone uses an unsupported sample format ({other:?})."
            ))
        }
    }
    .context("could not open the microphone input stream")?;

    stream
        .play()
        .context("could not start the microphone stream")?;

    Ok(ActiveRecording {
        _stream: stream,
        sample_rx,
        writer,
        path: path.clone(),
        sample_rate,
        channels,
        paused,
        written_frames: 0,
        silence_run_ms: 0.0,
        warned: false,
        level_window: Vec::with_capacity(4096),
    })
}

/// Drain captured samples; returns `Some(reason)` when an auto-stop fires.
fn pump(
    app: &AppHandle,
    config: &RecorderConfig,
    rec: &mut ActiveRecording,
) -> Result<Option<StopReason>> {
    let paused = rec.paused.load(std::sync::atomic::Ordering::SeqCst);
    let mut mono: Vec<f32> = Vec::new();
    while let Ok(chunk) = rec.sample_rx.try_recv() {
        let ch = rec.channels as usize;
        for frame in chunk.chunks_exact(ch) {
            mono.push(frame.iter().sum::<f32>() / ch as f32);
        }
    }
    if mono.is_empty() {
        return Ok(None);
    }

    rec.level_window.extend_from_slice(&mono);
    let window_len = (rec.sample_rate as usize / 20).max(1); // ~50ms
    while rec.level_window.len() >= window_len {
        let window: Vec<f32> = rec.level_window.drain(..window_len).collect();
        let rms = (window.iter().map(|s| s * s).sum::<f32>() / window.len() as f32).sqrt();
        let peak = window.iter().fold(0.0_f32, |m, s| m.max(s.abs()));
        let elapsed_ms = rec.written_frames * 1000 / u64::from(rec.sample_rate);
        let _ = app.emit(
            events::AUDIO_LEVEL,
            json!({ "rms": rms, "peak": peak, "elapsed_ms": elapsed_ms, "paused": paused }),
        );
        if !paused {
            let dbfs = 20.0 * rms.max(1e-9).log10();
            if dbfs < config.silence_threshold_dbfs {
                rec.silence_run_ms += 50.0;
            } else {
                rec.silence_run_ms = 0.0;
            }
        }
    }

    if !paused {
        for sample in &mono {
            let value = (sample.clamp(-1.0, 1.0) * 32767.0) as i16;
            rec.writer
                .write_sample(value)
                .context("could not write audio samples to disk")?;
        }
        rec.written_frames += mono.len() as u64;

        let elapsed = Duration::from_millis(rec.written_frames * 1000 / u64::from(rec.sample_rate));
        if !rec.warned && elapsed >= config.warn_at {
            rec.warned = true;
            let _ = app.emit(
                events::AUDIO_WARNING,
                json!({ "kind": "duration-warning", "elapsed_ms": elapsed.as_millis() as u64 }),
            );
        }
        if elapsed >= config.hard_stop_at {
            return Ok(Some(StopReason::HardLimit));
        }
        // Only auto-stop once something was actually recorded (>= 2s) so an
        // open mic in a quiet room does not instantly stop.
        if rec.silence_run_ms >= config.silence_duration.as_millis() as f64
            && elapsed >= Duration::from_secs(2)
        {
            return Ok(Some(StopReason::Silence));
        }
    }
    Ok(None)
}

fn finalize(
    _app: &AppHandle,
    rec: ActiveRecording,
    reason: StopReason,
) -> Result<RecordingResult> {
    let duration_ms = rec.written_frames * 1000 / u64::from(rec.sample_rate);
    let path = rec.path.to_string_lossy().to_string();
    let sample_rate = rec.sample_rate;
    rec.writer
        .finalize()
        .context("could not finalize the WAV file")?;
    Ok(RecordingResult {
        path,
        duration_ms,
        reason,
        sample_rate,
    })
}

fn emit_state(app: &AppHandle, state: &str, mut extra: serde_json::Value) {
    if let Some(obj) = extra.as_object_mut() {
        obj.insert("state".into(), json!(state));
    }
    if let Err(err) = app.emit(events::AUDIO_STATE, extra) {
        eprintln!("[audio] could not emit state event: {err}");
    }
}

/// Magic-byte sniffing for audio imports; returns the detected format name.
pub fn sniff_audio_format(bytes: &[u8]) -> Option<&'static str> {
    if bytes.len() < 12 {
        return None;
    }
    if &bytes[0..4] == b"RIFF" && &bytes[8..12] == b"WAVE" {
        return Some("wav");
    }
    if &bytes[0..3] == b"ID3" || (bytes[0] == 0xFF && (bytes[1] & 0xE0) == 0xE0) {
        return Some("mp3");
    }
    if &bytes[4..8] == b"ftyp" {
        return Some("m4a");
    }
    if &bytes[0..4] == b"fLaC" {
        return Some("flac");
    }
    if &bytes[0..4] == b"OggS" {
        return Some("ogg");
    }
    if bytes[0..4] == [0x1A, 0x45, 0xDF, 0xA3] {
        return Some("webm");
    }
    None
}

/// Formats accepted for import.
pub const SUPPORTED_IMPORT_FORMATS: &[&str] = &["wav", "mp3", "m4a", "flac", "ogg", "webm"];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sniffs_wav_and_mp3() {
        let mut wav = b"RIFF\x00\x00\x00\x00WAVEfmt ".to_vec();
        assert_eq!(sniff_audio_format(&wav), Some("wav"));
        wav[0..4].copy_from_slice(b"ID3\x04");
        assert_eq!(sniff_audio_format(&wav), Some("mp3"));
        assert_eq!(sniff_audio_format(b"not audio at all"), None);
    }

    #[test]
    fn config_defaults_match_contract() {
        let config = RecorderConfig::default();
        assert_eq!(config.warn_at, Duration::from_secs(1500));
        assert_eq!(config.hard_stop_at, Duration::from_secs(1800));
    }
}
