# Teaching Agent Engine

This project is the core logic for an adaptive AI tutor.

It uses a structured curriculum to test a student, estimate their mastery, teach weak concepts, and decide what they should learn next.

---

## What It Does

**Input:**
- A student name
- A curriculum file (`curriculum.json`)
- Student answers to quizzes

**Output:**
- Mastery scores per concept
- Teaching actions (teach, retest, or advance)
- Updated student progress

The system runs in a loop:
**test → measure → teach → retest → advance**

---

## How It Works

1. Loads a structured curriculum (topics, sub-topics, order, prerequisites)
2. Generates a diagnostic quiz for the current lesson
3. Grades answers (MCQs locally, open answers via LLM)
4. Updates numeric mastery scores using a moving average
5. If the student passes, moves to the next lesson
6. If not, teaches sub-concepts and retries

---

## Core Components

- `student_teaching_loop.py` — Main policy engine (decides what happens next)  
- `mastery_service.py` — Scoring and mastery update logic  
- `student_assessment.py` — Quiz generation and LLM grading  
- `student_profiles.py` — Student state and persistence layer  
- `data/curriculum.json` — Structured learning plan  

---

## Design Goal

This repo focuses on the **teaching policy**, not the web or deployment layer.

A separate service can wrap this engine with:
- APIs
- UI
- Deployment and scaling
