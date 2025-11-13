Project Roadmap: Teaching Agent V2

This document outlines the design decisions and feature backlog for the next version of the adaptive teaching agent.

1. The "New Student" Onboarding Flow

Problem: Right now, a new student (like "Kartick_Streamlit_Test") starts with 0 mastery. The agent just picks the first available concept.

Proposed Solution (Your Idea):
When a student logs in for the first time, we should perform an Initial Assessment to get a baseline mastery profile.

How it would work:

UI Change: When a student with no mastery logs in, the dashboard shows an "Start Initial Assessment" button instead of "Get Next Lesson Plan".

Backend Logic (New Endpoint): POST /initial_assessment

The agent scans curriculum.json and picks 5-7 key "milestone" concepts (e.g., one from each high_level_concept).

It calls the LLM to generate one question for each of these milestone concepts.

UI Change (Quiz Mode):

The Streamlit app displays these 5-7 questions one by one.

The user submits their answers.

Backend Logic (V3): POST /submit_real_assessment

A new endpoint takes the user's answers and uses the LLM to "grade" them (e.g., score: 0.8).

The StudentProfile is updated with these baseline scores.

Result: The agent now has a populated mastery profile and can make a truly adaptive decision for the first lesson.

2. Learning Path: Agent-Driven vs. User-Driven

Problem: The current flow is 100% "Agent-Driven." The user can only learn what the agent tells them to learn next.

Proposed Solution (Your Idea):
Offer two learning paths:

Adaptive Path (Agent-Driven): The button we have now: "What should I learn next?" This is the core "smart" feature.

Exploration Path (User-Driven): A new UI element (like a sidebar "Table of Contents") that lets the user choose any concept from the curriculum to learn immediately.

How it would work:

UI Change:

Add a st.selectbox or st.page_link in the sidebar populated with all concept names from curriculum.json.

Backend Logic (No Change Needed!):

We can just re-use our existing /teach_step endpoint! When the user selects "Self-Attention" from the list, the dashboard just calls /teach_step with that concept name. This is a very easy win.

3. V3 Feature: Replace "Simulation" with "Real Assessment"

Problem: The "Simulate Assessment" button is just a placeholder. It doesn't actually test the student.

Proposed Solution:
This is the final step to make the agent "real."

Backend Logic (/get_next_step):

When the agent decides to teach "Self-Attention," it should also generate 2-3 quiz questions related to it at the same time.

The API response for /get_next_step should include these questions.

UI Change:

After the user reads the explanation, the dashboard shows the questions and a st.text_area for the user's answer.

Backend Logic (New Endpoint): POST /submit_real_assessment

This endpoint receives the user's answers.

It uses a "grader" prompt to ask the LLM to evaluate the user's answer against the real answer (e.g., "Score this answer from 0.0 to 1.0...").

The resulting score is used to update_mastery. This completes the loop!