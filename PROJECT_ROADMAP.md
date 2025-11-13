# Project Roadmap – Teaching Agent (V3)

This roadmap outlines the planned enhancements for the next version of the Adaptive Teaching Agent. The focus is on improving onboarding, expanding learning pathways, and implementing fully integrated real assessments.

---

## 1. Initial Assessment (Baseline Mastery)

### Objective
Establish an accurate baseline mastery profile for new students instead of defaulting to zero mastery.

### Features
- **New UI State:** For new students, display a “Start Placement Quiz” prompt instead of “Get Next Lesson Plan.”
- **Milestone Concept Selection:** Automatically select 5–7 foundational concepts from `curriculum.json` across high-level categories.
- **Assessment Generation:** Use the LLM to generate one diagnostic question per milestone concept.
- **Backend Endpoints:**
  - `POST /initial_assessment`
  - `POST /submit_initial_assessment`
- **Mastery Initialization:** Grade each response using LLM evaluation and store baseline mastery values in `StudentProfile`.

### Expected Outcome
Adaptive sequencing starts with a meaningful profile instead of an artificial zero state, resulting in more accurate first-lesson recommendations.

---

## 2. Dual Learning Paths (Adaptive vs. Exploration)

### Objective
Give learners control while maintaining adaptive guidance.

### Features
- **Adaptive Path:** Existing flow (“What should I learn next?”).
- **Exploration Path:** User-driven concept selection.
  - UI component (sidebar or dropdown) listing all concepts from `curriculum.json`.
  - Selecting a concept triggers a learning session for that topic.
- **Backend Reuse:** No new endpoints required—existing `/teach_step` logic supports arbitrary concept teaching.

### Expected Outcome
Learners can either follow AI-guided progression or explore topics independently without bypassing the system’s core logic.

---

## 3. Real Assessment Pipeline (Replacing Simulation)

### Objective
Transition from placeholder assessments to fully integrated concept-level quizzes.

### Features
- **Quiz Generation:** When `/get_next_step` selects a concept, generate 2–3 concept-specific quiz questions.
- **Lesson → Quiz Flow:** After completing teaching steps, users enter quiz mode automatically.
- **New Endpoint:**  
  - `POST /submit_real_assessment`
- **LLM Grader:** Evaluate free-text answers using a standardized grading prompt (score 0.0–1.0).
- **Mastery Update:** Apply weighted scoring and persist results to `StudentProfile`.

### Expected Outcome
A closed-loop teaching cycle: Teach → Assess → Update → Recommend, producing a measurable and continuous mastery profile.
