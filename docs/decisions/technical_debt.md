# Technical Debt & System Bottlenecks

This document identifies known technical debt, performance bottlenecks, coupling risks, and recommended refactoring targets in Verse.

---

## 1. Performance Bottlenecks

### A. Single-Threaded Sequential Folder Scanning
- **Issue**: `ScanWorker` processes files sequentially in a single thread. For large libraries (>10,000 tracks), computing SHA-256 hashes, running `ffprobe`, and computing librosa features sequentially takes significant time.
- **Impact**: Initial indexing of large music collections can be slow.
- **Recommendation**: Refactor `ScanWorker` to use a `concurrent.futures.ProcessPoolExecutor` or worker pool to parallelize `ffprobe` and `librosa` feature extraction across CPU cores.

### B. In-Memory SQLite Serialization of Acoustic Blobs
- **Issue**: `AudioFeatures` stores STFT chromagrams, MFCCs, and spectral vectors as pickled binary BLOBs inside SQLite.
- **Impact**: Reading feature records requires unpickling binary blobs in Python memory.
- **Recommendation**: Consider migrating heavy numpy arrays to a dedicated HDF5, Zarr, or binary memory-mapped file cache if database file size exceeds several gigabytes.

---

## 2. Code Coupling & Refactoring Targets

### A. Synchronous Subprocess Spawning for `ffprobe`
- **Issue**: `extract_technical_metadata()` calls `subprocess.run(["ffprobe", ...])` synchronously per file.
- **Impact**: Subprocess creation overhead per file adds processing latency.
- **Recommendation**: Re-use persistent `ffmpeg` C-bindings via `av` (PyAV) for faster in-process technical metadata parsing.

### B. Ollama HTTP Timeout Tuning
- **Issue**: Complex LLMs on CPU-only hardware may exceed the 120-second read timeout during first-time model loading.
- **Impact**: Can trigger connection timeout errors on low-spec hardware.
- **Recommendation**: Implement streaming response parsing (`"stream": true`) to receive tokens progressively and reset watchdog timeouts dynamically.

---

## 3. Potential Edge Cases & Scalability Concerns

- **File Renames Outside App**: Renaming a file on disk creates a new path. SHA-256 hash matching reconciles content, but requires cleaning up old invalid paths.
- **Multi-User Playback Sessions**: Currently, playback sessions assume a single local user. Multi-user ACLs are out of scope for the current architecture.
