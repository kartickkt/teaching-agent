User Flow: The Top-Tier Teaching Agent

This document defines the ideal user journey, from a new student's first click to a returning student's mastery. This flow is designed to be generic and work with any curriculum.json.

Phase 1: The Onboarding (First 5 Minutes)

The goal is to personalize the experience immediately and demonstrate value.

1. Welcome & Choice:
A new student ("Student_New") registers. The agent sees their mastery profile is empty.

UI: Shows a welcome screen.

The Choice: The user is given three distinct paths:

"Start 5-Min Placement Quiz" (Recommended): This triggers the Initial Assessment (Roadmap Item #1). The agent picks 5-7 key concepts from the curriculum, generates questions, and builds a baseline mastery profile.

"I'm a Beginner, Start from Scratch": The user skips the quiz. The agent finds the first concept with no prerequisites and prepares it as the first lesson.

"I'll Explore the Curriculum Myself": This drops the user directly into the "Exploration Path" (Roadmap Item #2).

Why this is better: It gives the user agency and makes the first lesson feel personalized, not just "item #1 on a list."

Phase 2: The Dashboard (The "Home Base")

This is the central hub for a returning student. It's not just a set of buttons, but a snapshot of their progress.

UI: The student sees:

"Your Next Lesson" (Primary): This is the Adaptive Path (Roadmap Item #2). The UI proactively shows the single concept the agent recommends (e.g., "Recommended for you: Self-Attention"). This is the main "call to action."

"Explore Curriculum" (Secondary): A "Browse All Topics" link or sidebar. This is the User-Driven Path where they can override the agent.

"My Progress": A high-level visual (like a spider chart or progress bars) showing their mastery of the high-level concepts (e.g., "Attention: 80%", "Architecture: 30%").

Why this is better: It's an intelligent dashboard, not a blank page. It tells the user what's next and why, reinforcing the "adaptive" value.

Phase 3: The Learning Loop (The "Real Assessment")

This is the core "Teach -> Assess -> Review" loop. This replaces our "simulation" with the Real Assessment (Roadmap Item #3).

1. Teach:

User clicks "Start Lesson: Self-Attention".

The API's /get_next_step endpoint has already determined if this is a Structured Lesson (with steps) or a Fallback Lesson (one explanation).

UI (Lesson Mode): The user reads the explanation(s), clicking "Next Step" until the content is finished. The final button is "I'm ready for the quiz."

2. Assess:

UI (Quiz Mode): The app immediately transitions to a quiz.

The backend (a new /get_quiz_for_concept endpoint) generates 2-3 questions based on the content just taught.

The user submits their answers (e.g., in a text box).

3. Review & Update:

The answers are sent to the new POST /submit_real_assessment endpoint.

Backend: The LLM acts as a "grader," scores the user's answers, and calculates a final mastery score (e.g., 0.85). StudentProfile is updated.

UI (Feedback): The user gets immediate feedback: "Great job! You scored 2/3. Your mastery of 'Self-Attention' is now 75%."

Loop Complete: The user is sent back to the Dashboard, which now shows a new "Your Next Lesson" card.

Why this is better: This is a tight, professional loop. It directly connects learning with assessment, provides immediate feedback, and clearly demonstrates the user's progress.