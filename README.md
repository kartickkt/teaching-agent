# 🤖 Adaptive Teaching Agent (V3)

This is a full-stack MLOps project demonstrating a personalized learning application built around the Neural Network/Transformer curriculum. The agent dynamically generates lessons and grades open-ended quizzes using an LLM, adapting to the student's mastery level in real time.

---

## ✨ Key Architectural Achievements

| **Achievement** | **Description** | **Resume Value** |
|-----------------|------------------|------------------|
| **Adaptive Core (EDA)** | Agent selects the next concept based on a calculated priority score, factoring in prerequisites, mastery gaps, and concept priority (`get_next_concept`). | Adaptive Algorithm Design |
| **LLM-Driven Assessment** | Uses OpenAI (GPT-4o-mini) to dynamically generate and grade unique, open-ended quiz questions, replacing static MCQs. | Dynamic RAG / GenAI Integration |
| **Weighted Mastery** | Quiz scores are scaled by difficulty (**1.2× Hard**, **0.8× Easy**) before updating the student's persistent mastery score. | Custom Logic / Score Weighting |
| **N+1 Performance Fix** | Solved a severe PostgreSQL N+1 query bottleneck by implementing a centralized caching proxy, dramatically reducing API latency. | Backend Performance Optimization |
| **Structured Learning** | Enforces sequential, step-by-step teaching using `curriculum.json` workflows, preventing the LLM from generating long, generic explanations. | Content Structuring / Prompt Engineering |

---

## 🏗️ Technology Stack

| **Layer** | **Technologies** | **Role** |
|----------|------------------|----------|
| **Backend** | FastAPI (ASGI), Uvicorn | High-performance API serving all business logic |
| **Frontend/Demo** | Streamlit | Responsive dashboard for user–agent interaction |
| **Data Persistence** | PostgreSQL (via Supabase) | Secure external store for student profiles & mastery logs |
| **AI** | OpenAI (GPT-4o-mini) | Generates explanations, quiz questions, and grading |
| **Deployment** | Docker, Google Cloud Run | Containerization and scalable microservice hosting |

---

## 🚀 Getting Started

### Install dependencies
```bash
pip install -r requirements.txt
```

### Start Backend (Terminal 1)
```bash
uvicorn api.main:app --reload --port 8000
```

### Start Frontend (Terminal 2)
```bash
streamlit run dashboard.py
```

> **Note:**  
> Secrets are handled via local `.env` and secured using `.gitignore` and `.gcloudignore` for cloud deployment.
