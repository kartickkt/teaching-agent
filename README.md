# Adaptive Teaching Agent

A production-grade **Adaptive Orchestration Engine** that dynamically evaluates students, generates targeted explanations, and enforces pedagogical prerequisites in real-time.
Powered by **FastAPI (Async)**, **Supabase (PostgreSQL)**, **OpenAI GPT-4o-mini**, and a **Streamlit** UI.

This project demonstrates **high-concurrency backend engineering**, **LLM inference optimization**, and **hybrid schema design** deployed on Google Cloud Run.

---

## Live Demo
Try the interactive teaching agent:
**[Launch Adaptive Agent](https://teaching-agent-6savqkhboahfztm83w9wtj.streamlit.app)**

---

# Core Engineering Highlights

| Feature | Engineering Implementation | Impact |
|--------|----------------------------|--------|
| **High-Concurrency Grading** | **Asyncio** pipeline (`asyncio.gather`) to parallelize LLM grading requests. | **70% Latency Reduction** (15s → ~3.5s) |
| **Low-Latency UX** | **Lazy Loading** pattern decouples inference from UI rendering; **Connection Pooling** (`psycopg2.pool`) for DB throughput. | **FCP < 500ms** (down from 25s) |
| **Hybrid Schema Design** | **PostgreSQL** with Relational columns for identity + **JSONB** for flexible mastery state. | Schema evolution without migrations |
| **Adaptive Orchestration** | Centralized **State Engine** routes users between Diagnostic, Teaching, and Evaluation modes. | Stateful, personalized curriculum |
| **Bias Mitigation** | Deterministic **Response Shuffling** algorithms applied to LLM-generated MCQs. | Mitigates "Option A Bias" |

---

# System Architecture

           ┌─────────────────────────┐
           │      Streamlit UI       │
           │   (Client-Side Rendering)│
           └─────────────▲───────────┘
                         │ REST / JSON (Lazy Loaded)
                         │
           ┌─────────────┴────────────┐
           │     FastAPI Backend      │
           │ (Async Orchestration Engine)│
           └─────────▲───────▲────────┘
       Parallel      │       │ Persistent
       Async calls   │       │ Connection Pool
           ┌─────────┴───┐   ┌──┴────────────┐
           │ OpenAI API  │   │ Supabase DB   │
           │ (Inference) │   │ (Postgres)    │
           └─────────────┘   └───────────────┘

---

# Performance Engineering

This project is optimized for **Throughput** and **Latency** using the following techniques:

### 1. Async Pipeline (The "70% Speedup")
* **Problem:** Grading 5 open-ended questions sequentially took ~15 seconds (Blocking I/O).
* **Solution:** Implemented `asyncio.gather` to fire all LLM inference requests in parallel.
* **Result:** Latency dropped to the duration of the single slowest request (~3.5s).

### 2. Connection Pooling & FCP Optimization
* **Problem:** Establishing a new DB connection per request added ~200ms overhead; eager loading LLM content blocked the UI for 25s.
* **Solution:** * Implemented `psycopg2.pool.ThreadedConnectionPool` to reuse active TCP sockets.
    * Refactored to a **Lazy Loading** architecture: API returns lightweight skeleton JSON immediately (<200ms), triggering a secondary async fetch for content.
* **Result:** **First Contentful Paint (FCP)** dropped to <500ms.

---

# Technology Stack

| Layer | Technology | Key Patterns Used |
|-------|------------|-------------------|
| **Backend** | Python, FastAPI, Uvicorn | **Asyncio**, Pydantic Validation, Dependency Injection |
| **Orchestration** | Custom Engine | State Management, Error Handling, Retry Logic |
| **Database** | Supabase (PostgreSQL) | **Connection Pooling**, **JSONB**, Hybrid Schema |
| **AI / LLM** | OpenAI GPT-4o-mini | Prompt Engineering, **Parallel Inference**, Token Streaming |
| **Deployment** | Docker, Google Cloud Run | Containerization, Environment Secret Management |

---

# Project Structure

# 📂 Project Structure

```bash
├── api/
│   └── main.py              # FastAPI entrypoint (Async Endpoints + Lazy Loading)
├── src/
│   ├── student_assessment.py # Async LLM Client + Parallel Grading Logic
│   ├── student_teaching_loop.py # Orchestration Engine (State Logic)
│   ├── student_profiles.py   # DB Layer (Connection Pool + JSONB Handling)
│   └── mastery_service.py    # Scoring Algorithms & Composite Logic
├── data/
│   └── curriculum.json       # Hierarchical Curriculum Definition
├── dashboard.py              # Streamlit Frontend
├── Dockerfile                # Cloud Run Configuration
├── requirements.txt
└── README.md

# Local Development

### 1) Install dependencies
```bash
pip install -r requirements.txt

### 2) Start Backend (FastAPI)

uvicorn api.main:app --port 8000 --reload

### 3) Start Frontend (Streamlit)

streamlit run dashboard.py

# Deployment

Backend (Google Cloud Run)
Fully containerized using Docker.

Stateless scaling with gunicorn + uvicorn workers.

Secrets (OPENAI_API_KEY, DB_URL) managed via Cloud Run Environment Variables.

Database (Supabase)
Hybrid Schema: Uses student_profiles table with jsonb columns for scalable mastery tracking.

Pooling: Application manages a persistent ThreadedConnectionPool.