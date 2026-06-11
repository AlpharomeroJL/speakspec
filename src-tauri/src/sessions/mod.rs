//! Session library (Phase 10): SQLite via sqlx with FTS5 full-text search.
//!
//! Sessions persist across restarts; search must answer in <500ms for 100
//! sessions (FTS5 makes this trivial); delete removes the row, the FTS row,
//! and every file in the session directory.

use anyhow::{Context, Result};
use serde::Serialize;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};
use sqlx::{Row, SqlitePool};
use std::path::{Path, PathBuf};

/// A stored session, as listed in the library.
#[derive(Debug, Clone, Serialize)]
pub struct SessionSummary {
    pub id: String,
    pub created_at: i64,
    pub title: String,
    pub dir: String,
    pub has_spec: bool,
}

/// Cloneable handle to the session database.
#[derive(Clone)]
pub struct SessionStore {
    pool: SqlitePool,
}

impl SessionStore {
    /// Open (creating if needed) the database at `<app_data>/speakspec.db`.
    pub async fn open(app_data_dir: &Path) -> Result<Self> {
        std::fs::create_dir_all(app_data_dir).context("could not create the app data dir")?;
        let options = SqliteConnectOptions::new()
            .filename(app_data_dir.join("speakspec.db"))
            .create_if_missing(true);
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .context("could not open the session database")?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                transcript TEXT NOT NULL DEFAULT '',
                spec_json TEXT NOT NULL DEFAULT '',
                dir TEXT NOT NULL
            )",
        )
        .execute(&pool)
        .await?;
        sqlx::query(
            "CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts
             USING fts5(id UNINDEXED, title, transcript)",
        )
        .execute(&pool)
        .await?;
        Ok(Self { pool })
    }

    /// Insert or update a session (called when a pipeline run completes).
    pub async fn save(
        &self,
        id: &str,
        title: &str,
        transcript: &str,
        spec_json: &str,
        dir: &str,
    ) -> Result<()> {
        let created_at: i64 = id.parse().unwrap_or(0);
        sqlx::query(
            "INSERT INTO sessions (id, created_at, title, transcript, spec_json, dir)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(id) DO UPDATE SET
               title = excluded.title,
               transcript = excluded.transcript,
               spec_json = excluded.spec_json",
        )
        .bind(id)
        .bind(created_at)
        .bind(title)
        .bind(transcript)
        .bind(spec_json)
        .bind(dir)
        .execute(&self.pool)
        .await?;
        sqlx::query("DELETE FROM sessions_fts WHERE id = ?1")
            .bind(id)
            .execute(&self.pool)
            .await?;
        sqlx::query("INSERT INTO sessions_fts (id, title, transcript) VALUES (?1, ?2, ?3)")
            .bind(id)
            .bind(title)
            .bind(transcript)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    /// All sessions, newest first.
    pub async fn list(&self) -> Result<Vec<SessionSummary>> {
        let rows = sqlx::query(
            "SELECT id, created_at, title, dir, length(spec_json) > 2 AS has_spec
             FROM sessions ORDER BY created_at DESC",
        )
        .fetch_all(&self.pool)
        .await?;
        Ok(rows.iter().map(row_to_summary).collect())
    }

    /// FTS5 search over titles and transcripts, newest first.
    pub async fn search(&self, query: &str) -> Result<Vec<SessionSummary>> {
        // Quote each term so user punctuation cannot break FTS syntax.
        let sanitized = query
            .split_whitespace()
            .map(|term| format!("\"{}\"", term.replace('"', "")))
            .collect::<Vec<_>>()
            .join(" ");
        if sanitized.is_empty() {
            return self.list().await;
        }
        let rows = sqlx::query(
            "SELECT s.id, s.created_at, s.title, s.dir, length(s.spec_json) > 2 AS has_spec
             FROM sessions_fts f JOIN sessions s ON s.id = f.id
             WHERE sessions_fts MATCH ?1
             ORDER BY s.created_at DESC",
        )
        .bind(sanitized)
        .fetch_all(&self.pool)
        .await?;
        Ok(rows.iter().map(row_to_summary).collect())
    }

    /// Full stored payload for re-opening a session.
    pub async fn load(&self, id: &str) -> Result<Option<(String, String, String)>> {
        let row = sqlx::query("SELECT transcript, spec_json, dir FROM sessions WHERE id = ?1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.map(|r| {
            (
                r.get::<String, _>("transcript"),
                r.get::<String, _>("spec_json"),
                r.get::<String, _>("dir"),
            )
        }))
    }

    /// Delete the session row, its FTS entry, and all files on disk.
    pub async fn delete(&self, id: &str) -> Result<()> {
        let dir: Option<String> = sqlx::query("SELECT dir FROM sessions WHERE id = ?1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await?
            .map(|r| r.get("dir"));
        sqlx::query("DELETE FROM sessions WHERE id = ?1")
            .bind(id)
            .execute(&self.pool)
            .await?;
        sqlx::query("DELETE FROM sessions_fts WHERE id = ?1")
            .bind(id)
            .execute(&self.pool)
            .await?;
        if let Some(dir) = dir {
            let path = PathBuf::from(&dir);
            if path.is_dir() {
                std::fs::remove_dir_all(&path)
                    .with_context(|| format!("could not delete session files at {dir}"))?;
            }
        }
        Ok(())
    }
}

fn row_to_summary(row: &sqlx::sqlite::SqliteRow) -> SessionSummary {
    SessionSummary {
        id: row.get("id"),
        created_at: row.get("created_at"),
        title: row.get("title"),
        dir: row.get("dir"),
        has_spec: row.get::<i64, _>("has_spec") != 0,
    }
}
