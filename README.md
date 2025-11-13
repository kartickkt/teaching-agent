# Adaptive Teaching Agent

A production-grade adaptive learning system that generates personalized lessons, evaluates open-ended responses using an LLM, and updates student mastery in real time. Built as a full-stack microservice architecture with FastAPI, Supabase PostgreSQL, OpenAI GPT-4o-mini, and Streamlit.

This project demonstrates backend engineering, state management, database optimization, and practical GenAI integration in a clean, scalable design.

## 🚀 Live Demo
Try the interactive version here:  
👉 https://teaching-agent-6savqkhboahfztm83w9wtj.streamlit.app/

---

## Key Architectural Achievements

| Achievement | Description | Technical Focus |
|------------|-------------|-----------------|
| **Adaptive Core Sequencer** | Selects the next concept using a custom priority function derived from prerequisites, mastery gaps, and curriculum ordering. | Adaptive Algorithm Design |
| **LLM-Driven Assessment** | Dynamically generates and grades open-ended quiz questions using GPT-4o-mini, replacing static MCQs. | LLM Integration / Evaluation Pipeline |
| **Weighted Mastery Update** | Applies difficulty-based multipliers (1.2× Hard, 0.8× Easy) before updating persistent mastery scores. | Scoring Algorithms / Custom Logic |
| **N+1 Query Elimination** | Replaced repeated DB lookups with a lightweight caching layer, solving a PostgreSQL N+1 bottleneck and reducing latency. | Backend Performance Optimization |
| **Structured Learning Enforcement** | Uses curriculum.json workflows to enforce step-by-step teaching, ensuring the LLM produces concise, targeted outputs. | Prompt Engineering / Content Structuring |

---

## System Architecture

```
                   ┌──────────────────────┐
                   │     Streamlit UI     │
                   └───────────▲──────────┘
                               │
                               │ REST API
                               │
                   ┌───────────┴──────────┐
                   │      FastAPI API      │
                   │  (Business Logic Layer)│
                   └───────────▲───────────┘
                               │
                     LLM Calls │
                               │
                   ┌───────────┴───────────┐
                   │     GPT-4o-mini        │
                   └───────────▲───────────┘
                               │
                     DB Reads  │  DB Writes
                               │
                   ┌───────────┴──────────┐
                   │  Supabase PostgreSQL  │
                   └───────────────────────┘
```

---

## Technology Stack

| Layer | Stack | Purpose |
|-------|--------|----------|
| Backend | FastAPI (ASGI), Uvicorn | Core adaptive logic, routing, orchestration |
| Frontend | Streamlit | Interactive student/agent interface |
| Database | Supabase PostgreSQL | Persistent mastery profiles & logs |
| AI | OpenAI GPT-4o-mini | Lesson creation, quiz generation, grading |
| Deployment | Docker, Google Cloud Run | Containerization & scalable backend hosting |

---

## Project Structure

```
├── api/
│   └── main.py                 # FastAPI entrypoint (HTTP routes)
├── src/
│   ├── student_assessment.py   # Adaptive sequencing + LLM logic
│   └── student_profiles.py     # DB access layer + caching
├── data/
│   └── curriculum.json         # Concepts, prerequisites, steps
├── dashboard.py                # Streamlit frontend
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Getting Started (Local)

### Install dependencies
```bash
pip install -r requirements.txt
```

### Start Backend
```bash
uvicorn api.main:app --reload --port 8000
```

### Start Frontend
```bash
streamlit run dashboard.py
```

The UI will be available at:
```
http://localhost:8501
```

---

## Deployment Notes

- Backend is deployed on **Google Cloud Run** using Docker.
- Frontend is deployed via **Streamlit Cloud**.
- Secrets are handled using:
  - `.env` locally (ignored via `.gitignore` and `.gcloudignore`)
  - Cloud environment variables in production
- Supabase PostgreSQL acts as the external managed database.

---

## Summary

This project implements a scalable, adaptive teaching system using modern backend practices and practical GenAI workflows. It demonstrates real-time mastery modeling, structured LLM prompting, database optimization, and containerized deployment.

