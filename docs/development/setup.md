# Developer Setup & Configuration Guide

This document provides instructions for setting up the Verse development environment on Linux/macOS systems.

---

## 1. System Requirements & Prerequisites

- **Operating System**: Linux (Ubuntu 22.04+, Fedora 38+, Arch) or macOS (12.0+)
- **Python**: Python 3.13+ (or 3.10+)
- **System Tools**: `ffprobe` / `ffmpeg` (required for technical metadata extraction)
- **Local LLM Server**: Ollama (required for AI Assistant & Semantic Tag Enrichment)
- **C++ Compiler**: GCC / Clang (required for `faiss-cpu` compilation)

---

## 2. Step-by-Step Installation

### Step 1: Clone Repository & Create Virtual Environment
```bash
git clone https://github.com/your-org/music-rec.git
cd music-rec

python3 -m venv .venv
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
# Install package in editable mode with development tools
pip install -e ".[dev]"
```

### Step 3: Install System Audio Utilities
- **Ubuntu/Debian**:
  ```bash
  sudo apt update && sudo apt install -y ffmpeg libgomp1
  ```
- **macOS**:
  ```bash
  brew install ffmpeg
  ```

---

## 3. Ollama Setup & Model Configuration

Verse relies on local Ollama for natural language parsing and semantic tagging.

### Step 1: Install & Start Ollama
Follow instructions at [ollama.com](https://ollama.com/):
```bash
# Start Ollama background service
ollama serve
```

### Step 2: Download Recommended Model
Download your preferred open-weights LLM model:
```bash
# Recommended default model
ollama pull mistral

# Alternative supported models
ollama pull llama3
ollama pull gemma
```

### Step 3: Configure Active Model in Verse
Use the Verse CLI to set and persist the target LLM model in `.env`:
```bash
python -m app.main set-model mistral
```

Output:
```text
Successfully updated project LLM model to 'mistral'.
Persisted in: /home/user/projects/music-rec/.env
Ollama Server Status:  Connected
Installed Models:       mistral:latest
```

---

## 4. Configuration & Environment Variables

Configuration settings are defined in [app/config/settings.py](file:///home/hisham/projects/music-rec/app/config/settings.py). Default values can be overridden via system environment variables or a root `.env` file:

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///<PROJECT_ROOT>/data/music_rec.db` | SQLAlchemy SQLite connection string |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FILE` | `<PROJECT_ROOT>/data/music_rec.log` | Application log file path |
| `SUPPORTED_FORMATS` | `.mp3,.flac,.wav,.m4a,.ogg` | Comma-separated list of allowed extensions |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Local Ollama generation API endpoint |
| `OLLAMA_MODEL` | `mistral` | Active Ollama model name |
| `OLLAMA_CONNECT_TIMEOUT` | `5.0` | Connection timeout in seconds |
| `OLLAMA_READ_TIMEOUT` | `120.0` | Inference/read timeout in seconds |
| `OLLAMA_KEEP_ALIVE` | `20m` | Model memory retention duration |

---

## 5. Running the Application

### A. Command Line Interface (CLI)
- **View Configuration & Ollama Status**:
  ```bash
  python -m app.main get-model
  ```
- **Scan & Index Music Folder**:
  ```bash
  python -m app.main scan ~/Music
  ```
- **Run Semantic Enrichment**:
  ```bash
  python -m app.main enrich-semantic --limit 50
  ```

### B. FastAPI Web Server
```bash
python -m app.main web --host 127.0.0.1 --port 8000 --reload
```
Open `http://127.0.0.1:8000` in your web browser.

### C. PySide6 Desktop GUI
```bash
python -m app.main gui
```
