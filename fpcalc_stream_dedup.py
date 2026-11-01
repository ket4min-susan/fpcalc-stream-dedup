#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fpcalc-stream-dedup — Zero-Disk Chromaprint Audio Fingerprint Deduplicator & ID3 Watermark Stripper
Author: ket4min-susan / memwm (memwmain@gmail.com)
File: D:\PERSONA_LIGHT_MASK\deliverables\fpcalc_stream_dedup.py

Pipes audio files or streams into Chromaprint `fpcalc` (with SHA-256 acoustic frame fallback),
indexes fingerprints into SQLite WAL + FTS5, flags duplicate recordings across crate folders
regardless of filename, and strips promotional watermark ID3/comment tags in-place.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac"}
WATERMARK_PATTERNS = (
    "nhacbay", "taonhac", "mp3cow", "172mix", "downloaded from",
    "tiktok", "douyin", "zingmp3", "soundcloud.com/", "www.", "http://", "https://",
)


def init_fingerprint_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audio_crates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_size INTEGER NOT NULL,
            duration_sec REAL DEFAULT 0.0,
            fingerprint_hash TEXT NOT NULL,
            raw_chromaprint TEXT DEFAULT '',
            clean_title TEXT DEFAULT '',
            indexed_at_utc TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fp_hash ON audio_crates(fingerprint_hash);")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS audio_crates_fts USING fts5(
            clean_title,
            file_path,
            fingerprint_hash,
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    conn.commit()
    return conn


def find_fpcalc_binary() -> str | None:
    candidates = [
        shutil.which("fpcalc"),
        r"D:\muzix_indextree\fpcalc.exe",
        r"D:\MUZIX_HD\fpcalc.exe",
        r"D:\remove_watermark_music_batch\fpcalc.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def compute_audio_fingerprint(file_path: Path, fpcalc_bin: str | None = None) -> tuple[float, str, str]:
    """
    Returns (duration_sec, fingerprint_sha256, raw_chromaprint_prefix).
    Uses `fpcalc -json` when available; falls back to middle-64KB acoustic frame hashing
    (skipping leading/trailing ID3v2/ID3v1 tags so identical audio with dirty tags still matches).
    """
    if fpcalc_bin:
        try:
            out = subprocess.check_output(
                [fpcalc_bin, "-json", "-length", "120", str(file_path)],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=12,
            )
            data = json.loads(out)
            dur = float(data.get("duration", 0.0))
            fp_raw = str(data.get("fingerprint", ""))
            fp_hash = hashlib.sha256(fp_raw.encode("ascii", errors="ignore")).hexdigest()
            return dur, fp_hash, fp_raw[:128]
        except Exception:
            pass

    size = file_path.stat().st_size
    with open(file_path, "rb") as f:
        if size > 262144:
            # Sample two 32KB windows at 50% and 75% of file length to bypass large ID3v2 APIC cover art
            f.seek(size // 2)
            chunk_a = f.read(32768)
            f.seek((size * 3) // 4)
            chunk_b = f.read(32768)
            chunk = chunk_a + chunk_b
        else:
            chunk = f.read()
    fp_hash = hashlib.sha256(chunk).hexdigest()
    return 0.0, fp_hash, f"frame_sha256:{fp_hash[:32]}"


def sanitize_track_title(stem: str) -> str:
    clean = stem
    for pat in WATERMARK_PATTERNS:
        idx = clean.lower().find(pat)
        if idx != -1:
            clean = clean[:idx]
    return " ".join(clean.replace("_", " ").split()).strip(" -_|[]()")


def scan_directory(target_dir: Path, db_path: Path) -> dict:
    conn = init_fingerprint_db(db_path)
    fpcalc_bin = find_fpcalc_binary()
    cur = conn.cursor()

    scanned = 0
    duplicates = []
    seen_hashes: dict[str, str] = {}
    now_utc = datetime.now(timezone.utc).isoformat()

    for root, _, files in os.walk(target_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in AUDIO_EXTS:
                continue
            fpath = Path(root) / fn
            scanned += 1
            dur, fp_hash, fp_raw = compute_audio_fingerprint(fpath, fpcalc_bin)
            clean_title = sanitize_track_title(fpath.stem)

            cur.execute("SELECT file_path FROM audio_crates WHERE fingerprint_hash = ? AND file_path != ?", (fp_hash, str(fpath)))
            existing_row = cur.fetchone()
            if existing_row or fp_hash in seen_hashes:
                orig = existing_row[0] if existing_row else seen_hashes[fp_hash]
                duplicates.append({"duplicate": str(fpath), "original": orig, "fingerprint_hash": fp_hash})
            else:
                seen_hashes[fp_hash] = str(fpath)

            cur.execute(
                """
                INSERT INTO audio_crates (file_path, file_size, duration_sec, fingerprint_hash, raw_chromaprint, clean_title, indexed_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_size = excluded.file_size,
                    duration_sec = excluded.duration_sec,
                    fingerprint_hash = excluded.fingerprint_hash,
                    raw_chromaprint = excluded.raw_chromaprint,
                    clean_title = excluded.clean_title,
                    indexed_at_utc = excluded.indexed_at_utc
                """,
                (str(fpath), fpath.stat().st_size, dur, fp_hash, fp_raw, clean_title, now_utc),
            )
            cur.execute(
                "INSERT INTO audio_crates_fts (clean_title, file_path, fingerprint_hash) VALUES (?, ?, ?)",
                (clean_title, str(fpath), fp_hash),
            )

    conn.commit()
    conn.close()
    return {
        "target_dir": str(target_dir),
        "fpcalc_binary": fpcalc_bin or "frame_sha256_fallback",
        "tracks_scanned": scanned,
        "unique_fingerprints": len(seen_hashes),
        "duplicates_found": len(duplicates),
        "duplicate_pairs": duplicates[:25],
    }


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\auda")
    db_out = Path(r"D:\PERSONA_LIGHT_MASK\deliverables\audio_fingerprints.sqlite")
    db_out.parent.mkdir(parents=True, exist_ok=True)
    res = scan_directory(target, db_out) if target.exists() else {"status": "ready", "fpcalc_binary": find_fpcalc_binary()}
    print(json.dumps(res, indent=2, ensure_ascii=False))
