# AI-Powered Local Music Recommendation System

> **Goal:** Build a desktop music player that understands the user's music library using Machine Learning, Audio Processing, Vector Search, and an LLM for natural language interaction.

---

# Project Vision

Unlike a traditional music player that only sorts songs by artist or album, this application will **understand how songs sound**.

Examples:

* "Play something similar to Interstellar."
* "Give me energetic songs for the gym."
* "Recommend songs like this one."
* "Create a rainy day playlist."

The application achieves this by extracting audio features, generating embeddings for every song, indexing them with FAISS, and retrieving similar music using vector search.

---

# Design Goals

* Fully offline after initial indexing
* Runs smoothly on CPU (Intel i7-1255U)
* Uses local ML models
* Modular architecture
* Easy to extend
* Production-quality codebase
* Portfolio-worthy

---

# Hardware Constraints

Target Machine

* Intel i7-1255U
* Intel Iris Xe Graphics
* 16 GB RAM
* Fedora Linux
* No NVIDIA GPU

### Design Decisions

✅ CPU inference only

✅ Pretrained models

✅ SQLite database

✅ FAISS vector search

✅ Offline indexing

❌ No model training

❌ No GPU dependencies

---

# High-Level Architecture

```text
                    ┌────────────────────────────┐
                    │      Local Music Folder    │
                    └──────────────┬─────────────┘
                                   │
                            File Scanner
                                   │
                    ┌──────────────▼─────────────┐
                    │      Music Indexer         │
                    └──────────────┬─────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
 Metadata Extraction        Audio Feature Extraction     Album Art
 (mutagen)                  (librosa / Essentia)
        │                          │
        └──────────────┬───────────┘
                       ▼
               Feature Database
                  (SQLite)
                       │
        ┌──────────────┼──────────────┐
        │                             │
        ▼                             ▼
 Genre Classifier             Embedding Generator
   (MusicNN)                  (OpenL3 / CLAP)
        │                             │
        └──────────────┬──────────────┘
                       ▼
                 FAISS Vector Index
                       │
        ┌──────────────┼──────────────┐
        │                             │
        ▼                             ▼
 Recommendation Engine         Natural Language
                                Assistant (LLM)
        │                             │
        └──────────────┬──────────────┘
                       ▼
               PySide6 Desktop App
```

---

# Folder Structure

```text
music-rec/

│
├── app/
│   │
│   ├── api/
│   │     FastAPI endpoints
│   │
│   ├── database/
│   │     SQLAlchemy models
│   │
│   ├── indexing/
│   │     Folder scanner
│   │     Metadata extraction
│   │     Feature extraction
│   │
│   ├── embeddings/
│   │     CLAP/OpenL3
│   │     Vector generation
│   │
│   ├── recommender/
│   │     Similarity search
│   │     Hybrid recommender
│   │     Playlist generation
│   │
│   ├── search/
│   │     FAISS index
│   │
│   ├── llm/
│   │     Prompt handling
│   │     Query parser
│   │
│   ├── player/
│   │     Audio playback
│   │     Queue
│   │
│   ├── ui/
│   │     PySide6 interface
│   │
│   ├── workers/
│   │     Background indexing
│   │
│   └── utils/
│
├── data/
│
├── models/
│
├── faiss/
│
├── tests/
│
├── scripts/
│
├── docs/
│
├── requirements.txt
│
└── README.md
```

---

# Project Pipeline

```text
Music Folder

↓

Find audio files

↓

Read metadata

↓

Extract audio features

↓

Generate embeddings

↓

Store in SQLite

↓

Insert vectors into FAISS

↓

Ready for searching
```

This pipeline only runs when new songs are added.

---

# Database Design

## Songs

Stores:

* title
* artist
* album
* genre
* duration
* path
* album art
* bitrate

---

## Audio Features

Stores:

* BPM
* key
* MFCC
* chroma
* RMS energy
* spectral centroid
* zero crossing rate
* spectral contrast

---

## Embeddings

Stores

* song_id
* embedding vector

---

## Listening History

Stores

* play count
* likes
* skips
* last played
* play duration

---

## Playlists

Stores

* playlist name
* generated manually or by AI
* song list

---

# Core Components

## 1. Music Scanner

Responsibilities

* Scan folders
* Detect new files
* Ignore duplicates
* Detect deleted songs

Output

```
List of audio files
```

---

## 2. Metadata Extractor

Uses

* mutagen

Extracts

* Artist
* Album
* Genre
* Track Number
* Year
* Duration
* Cover Art

---

## 3. Audio Feature Extractor

Uses

* librosa

Extracts

* Tempo
* Key
* MFCC
* Chroma
* Spectral Contrast
* RMS Energy

---

## 4. Genre Classification

Uses

MusicNN

Purpose

Predict genre without relying on metadata.

---

## 5. Embedding Generator

Uses

OpenL3 or CLAP

Produces

```
Song

↓

512-dimensional vector
```

Every song becomes a point in vector space.

---

## 6. Vector Search

Uses

FAISS

Purpose

```
Song

↓

Embedding

↓

Nearest neighbours

↓

Most similar songs
```

Expected search time

Less than 10 milliseconds.

---

## 7. Recommendation Engine

Contains several independent algorithms.

### Algorithm 1

Content-based recommendation

Uses

* embeddings
* cosine similarity

---

### Algorithm 2

k-Nearest Neighbours

Uses

Nearest vectors.

---

### Algorithm 3

Clustering

Uses

KMeans

Purpose

Automatically discover music groups.

---

### Algorithm 4

Hybrid

Combines

* embeddings
* listening history
* genre
* randomness

---

## 8. LLM Assistant

Runs using a lightweight local model.

Responsibilities

Translate

> "Play calm music"

into

```
energy < 0.3
tempo < 90
```

or

> "Songs like Hans Zimmer"

into

```
Find Hans Zimmer

↓

Retrieve embedding

↓

Search nearest neighbours
```

The LLM never recommends songs directly.

It only converts language into structured search.

---

## 9. Music Player

Responsibilities

* playback
* queue
* playlists
* shuffle
* repeat
* volume
* seek

---

## 10. User Interface

Framework

PySide6

Main Pages

### Home

Recent songs

---

### Library

Artists

Albums

Genres

Folders

---

### Search

Keyword search

Semantic search

---

### Recommendations

Generated playlists

---

### AI Assistant

Chat interface

---

### Settings

Music folders

Index status

Model settings

---

# Background Workers

Heavy operations never block the interface.

Workers

* Folder scan
* Feature extraction
* Embedding generation
* Database updates
* FAISS rebuild

---

# Development Roadmap

## Phase 1

Project setup

* Folder structure
* Database
* UI skeleton

Goal

Display songs.

---

## Phase 2

Metadata indexing

Goal

Build local music library.

---

## Phase 3

Feature extraction

Goal

Store BPM, MFCC, Chroma.

---

## Phase 4

Genre classification

Goal

Predict genres.

---

## Phase 5

Embedding generation

Goal

Generate semantic vectors.

---

## Phase 6

FAISS

Goal

Find similar songs.

---

## Phase 7

Recommendation engine

Goal

Recommend similar music.

---

## Phase 8

LLM integration

Goal

Natural language playlists.

---

## Phase 9

Listening history

Goal

Personalized recommendations.

---

## Phase 10

Polish

* Testing
* Packaging
* Documentation
* Performance improvements

---

# Future Enhancements

* Lyrics search
* Mood detection
* Duplicate song detection
* Crossfade playback
* Equalizer
* Smart playlists
* Podcast support
* Mobile remote control
* Music visualization
* Playlist sharing
* Web dashboard

---

# Technologies Used

Backend

* Python
* FastAPI
* SQLAlchemy

Database

* SQLite

Machine Learning

* PyTorch
* MusicNN
* OpenL3 or CLAP

Audio Processing

* librosa
* mutagen

Vector Search

* FAISS

Recommendation

* scikit-learn

Desktop UI

* PySide6

Testing

* pytest

---

# Skills Demonstrated

This project showcases:

* Software Architecture
* Backend Development
* Audio Signal Processing
* Machine Learning
* Information Retrieval
* Vector Databases
* Recommendation Systems
* Database Design
* Concurrency
* Desktop Application Development
* AI Integration
* Performance Optimization
* Modular Software Engineering

---

# Final Deliverable

A polished desktop application that:

* Indexes an entire local music library
* Understands music using machine learning
* Finds similar songs using vector embeddings
* Recommends playlists intelligently
* Accepts natural-language requests through an AI assistant
* Runs efficiently on a CPU-only laptop
* Demonstrates production-ready software engineering practices suitable for a strong software engineering or machine learning portfolio.

