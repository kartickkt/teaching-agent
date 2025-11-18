# Adaptive Teaching Agent

A production-grade **adaptive learning system** that evaluates students, generates targeted explanations, personalizes practice, and updates mastery in real time.  
Powered by **FastAPI**, **Supabase PostgreSQL**, **OpenAI GPT-4o-mini**, and a smooth **Streamlit** UI.

This project demonstrates backend engineering, LLM orchestration, mastery modeling, and real-world deployment on Google Cloud Run.

---

## Live Demo
Try the interactive teaching agent:

**https://teaching-agent-6savqkhboahfztm83w9wtj.streamlit.app**

---

# Core Highlights

| Feature | What It Does | Engineering Focus |
|--------|---------------|------------------|
| **Sequential Gated Learning** | Enforces a strict 9-lesson progression with diagnostic gates, sub-concept teaching, and final quizzes. | Workflow Design • State Machines |
| **LLM-Driven Assessments** | Generates MCQs, open questions, and structured teaching explanations using GPT-4o-mini. | Prompt Engineering • LLM Integration |
| **Real-Time Mastery Modeling** | Difficulty-weighted scoring and granular mastery updates per lesson + sub-concept. | Scoring Algorithms • User Modeling |
| **Optimized Backend** | Eliminated N+1 queries using a simple caching layer and optimized DB access patterns. | Performance Optimization |
| **Cloud-Native Deployment** | Dockerized FastAPI backend deployed on Cloud Run; Streamlit frontend decoupled. | Docker • Cloud Architecture |

---

# System Architecture

           ┌─────────────────────────┐
           │       Streamlit UI       │
           └─────────────▲───────────┘
                         │ REST API
                         │
           ┌─────────────┴────────────┐
           │       FastAPI Backend     │
           │  (Sequencer + Evaluator)  │
           └─────────────▲────────────┘
                         │ LLM Calls
           ┌─────────────┴────────────┐
           │     OpenAI GPT-4o-mini    │
           └─────────────▲────────────┘
                         │ Database I/O
           ┌─────────────┴────────────┐
           │    Supabase PostgreSQL    │
           └───────────────────────────┘


---

# How Learning Works

### 1) Diagnostic Gate  
Each lesson starts with an LLM-generated diagnostic quiz (MCQ + open-ended).  
- **If passed** → student skips directly to next lesson  
- **If failed** → enters structured teaching

### 2️) Structured Teaching (Streaming)  
LLM explains each sub-concept one by one, streamed token-by-token for better UX.

### 3) Final Lesson Quiz  
A second quiz evaluates understanding before progression and updates mastery.

### 4) Practice Mode  
Student chooses a **high-level concept + difficulty**, backend returns a **10-question MCQ quiz**.

---

# 🧩 Technology Stack

| Layer | Tools | Role |
|-------|-------|------|
| **Backend** | FastAPI, Uvicorn | Adaptive engine, sequencing, routing |
| **Frontend** | Streamlit | UI, state management, token streaming |
| **Database** | Supabase PostgreSQL | Persistent student + mastery storage |
| **AI** | OpenAI GPT-4o-mini | Quiz generation, grading, teaching content |
| **Deployment** | Docker, Google Cloud Run | Scalable backend container hosting |

---

# Project Structure

├── api/
│ └── main.py # FastAPI entrypoint
├── src/
│ ├── student_assessment.py # LLM-based quiz generation + grading
│ ├── student_teaching_loop.py# Sequential teaching engine
│ └── student_profiles.py # DB layer + caching + mastery updates
├── data/
│ └── curriculum.json # Ordered lessons + sub-concepts
├── dashboard.py # Streamlit frontend
├── Dockerfile # Backend container
├── requirements.txt
└── README.md


---

# 🛠️ Local Development

### 1️) Install dependencies

pip install -r requirements.txt

### 2) Start Backend (FastAPI)
uvicorn api.main:app --port 8000 --reload

### 4) Start Frontend (Streamlit)
streamlit run dashboard.py

### Frontend appears at:
http://localhost:8501

## Deployment

### **Backend**
- Fully containerized using **Docker**
- Deployed on **Google Cloud Run**
- API URL injected into Streamlit as an environment variable
- Secrets managed securely using Cloud Run environment variables:  
  - `OPENAI_API_KEY`  
  - `SUPABASE_URL`  
  - `SUPABASE_KEY`

### **Frontend**
- Hosted on **Streamlit Cloud**
- Communicates with the FastAPI backend over HTTPS

### **Database**
- External **Supabase PostgreSQL** instance
- Persistent across deployments
- Stores:
  - Student profiles  
  - Lesson order  
  - Mastery scores (per lesson + sub-concept)  
  - Practice quiz history  

---

## Summary

This repository contains a fully working **adaptive teaching system** featuring:

- **Real-time mastery dashboard**
- **Automatic diagnostic gates**
- **LLM-generated quizzes, explanations, and grading**
- **Structured teaching with streaming explanations**
- **Practice MCQs with difficulty control**
- **Cloud-native backend deployed on GCP**
- **Clean separation across backend, frontend, and database**

### **Engineering Expertise Demonstrated**
- Backend architecture & API design  
- LLM systems engineering (prompting, streaming, evaluation)  
- State management + adaptive sequencing logic  
- Cloud Run cont
