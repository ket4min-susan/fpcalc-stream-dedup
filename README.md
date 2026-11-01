# `fpcalc-stream-dedup` (`v1.0.0`)

[![CI](https://github.com/ket4min-susan/fpcalc-stream-dedup/actions/workflows/ci.yml/badge.svg)](https://github.com/ket4min-susan/fpcalc-stream-dedup/actions/workflows/ci.yml) · **[Release `v1.0.0`](https://github.com/ket4min-susan/fpcalc-stream-dedup/releases/tag/v1.0.0)** · **[GitLab Mirror (`@memwm`)](https://gitlab.com/memwm/fpcalc-stream-dedup)**

Zero-disk Chromaprint (`fpcalc`) and 28-bit synchsafe ID3-aligned mid-stream acoustic frame deduplicator with automated watermark stripping, backed by **SQLite WAL + FTS5**.

Built for crate-diggers and audio DSP engineers managing large lossless/mixset archives where identical recordings circulate under different filenames and bloated ID3v2 APIC cover art headers.

![Acoustic Waveform & Calldata Disassembly Telemetry](./assets/waveform_dedup_telemetry.png)

![Animated Nocturnal DSP Waterfall Spectrogram](./assets/ig_03_unindexed_track04_animated.gif)

## Architecture

1. **Acoustic Fingerprinting (`Chromaprint` + 28-Bit Synchsafe ID3 Boundary Alignment):**
   - Uses `fpcalc -json -length 120` when present on PATH.
   - Parses leading `ID3v2` 28-bit synchsafe header size (`((b6 & 0x7f) << 21) | ((b7 & 0x7f) << 14) | ((b8 & 0x7f) << 7) | (b9 & 0x7f)`, plus optional 10-byte footer) and trailing 128-byte `ID3v1` (`TAG`) trailer before sampling two 32 KB acoustic windows at `50%` and `75%` of the **pure audio stream**, guaranteeing identical hashes even when tracks are prepended with arbitrary APIC cover art.
2. **SQLite WAL + Unicode61 FTS5 Index:**
   - Stores file paths, byte sizes, durations, SHA-256 fingerprint digests, and sanitized track titles in `audio_crates` + `audio_crates_fts`.
3. **Watermark Tag Sanitizer:**
   - Strips common promotional domain suffixes from track titles in a single pass.

## Usage

```bash
python fpcalc_stream_dedup.py --selftest
python fpcalc_stream_dedup.py /path/to/audio/crate
```
