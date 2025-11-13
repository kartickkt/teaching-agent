# User Flow – Adaptive Teaching Agent

This document describes the end-to-end user experience for the Adaptive Teaching Agent. The flow is designed to support any curriculum defined in `curriculum.json`.

---

## 1. Onboarding Flow (First Session)

### Objective
Provide a personalized starting point for new learners.

### Flow
1. **Profile Check:** The system detects that the student has no mastery records.
2. **Welcome Screen:** Present three entry paths:
   - **Placement Quiz (Recommended):**  
     Runs the initial assessment to build baseline mastery.
   - **Start from Scratch:**  
     Begins with the earliest concept that has no prerequisites.
   - **Explore Curriculum:**  
     Opens the user-driven exploration mode.
3. **Assessment Mode (if selected):**
   - Present 5–7 diagnostic questions generated for milestone concepts.
   - User submits answers.
   - System evaluates responses and initializes mastery.

### Outcome
The dashboard and recommendations are tailored from the first session.

---

## 2. Dashboard Flow (Returning Sessions)

### Purpose
Provide a clear overview of progress and next steps.

### Elements
- **Next Recommended Lesson (Primary CTA):**  
  The system calculates the optimal next concept based on mastery and prerequisites.
- **Explore Curriculum (Secondary CTA):**  
  User can manually select any concept to study.
- **Progress Overview:**  
  Displays mastery across high-level categories (e.g., Attention, Transformers, Optimization).

### Outcome
The dashboard functions as a central navigation point and helps the learner understand their current standing.

---

## 3. Learning Loop (Teach → Assess → Review)

### 3.1 Teach Phase
- User begins a lesson for the recommended or manually selected concept.
- `/get_next_step` determines if the concept:
  - Has structured steps (multi-step lesson), or
  - Requires a fallback single-step explanation.
- User proceeds through each teaching step until the lesson is complete.
- Final step transitions to quiz mode: “I’m ready for the quiz.”

### 3.2 Assessment Phase
- The system generates 2–3 concept-specific quiz questions.
- UI displays each question with response inputs.
- User submits answers.

### 3.3 Review & Mastery Update
- Answers are sent to `POST /submit_real_assessment`.
- The LLM evaluates each answer with a numeric score (0.0–1.0).
- Difficulty weighting is applied (e.g., 1.2× for Hard).
- StudentProfile is updated with the new mastery value.
- User receives immediate performance feedback.

### Outcome
The user returns to the dashboard with updated mastery and an updated recommendation, completing the adaptive learning loop.

---

## Summary

This user flow establishes a structured and scalable experience:  
- Personalized onboarding  
- Dual learning modes  
- A consistent teaching–assessment cycle  
- Real-time mastery tracking  

It supports extensibility for future features and integrates cleanly with the existing backend architecture.
