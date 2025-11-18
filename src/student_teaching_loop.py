# src/student_teaching_loop.py

import json
from typing import List, Dict, Any, Optional
from pathlib import Path
import os

from fastapi.responses import StreamingResponse

from .student_profiles import StudentProfile, CurriculumManager
from .student_assessment import AssessmentAgent, _ensure_quiz_shape  # reuse helper
from .mastery_service import MasteryService

# -----------------------------
# Constants
# -----------------------------
PASS_THRESHOLD = 0.75
PROJECT_ROOT = Path(__file__).parent.parent
WORKFLOWS_JSON = PROJECT_ROOT / "data" / "curriculum.json"


# -----------------------------
# Teaching Loop Service
# -----------------------------
class TeachingLoopService:
    def __init__(self, student_name: str):
        self.student_name = student_name

        # DB + master modules
        self.profile = StudentProfile()
        self.mastery_service = MasteryService(self.profile)

        # LLM agent
        self.agent = AssessmentAgent()

        # Curriculum
        self.high_level_concepts_map = CurriculumManager.get_high_level_concepts()

        # Ensure student exists in DB
        self.profile.register_student(student_name)

        # Sequential lesson map
        self.lessons_by_order = sorted(
            self.high_level_concepts_map.values(),
            key=lambda x: x.get("order", 99)
        ) if self.high_level_concepts_map else []

        self.max_order = (
            self.lessons_by_order[-1]["order"]
            if self.lessons_by_order else 1
        )

    # -----------------------------
    # Program Start (Diagnostic)
    # -----------------------------
    def start_program(self, lesson_order_override: Optional[int] = None) -> Dict[str, Any]:

        progress = self.profile.get_progress(self.student_name)
        current_order = lesson_order_override or progress.get("current_lesson_order", 1)

        if current_order > self.max_order:
            return {"status": "complete", "message": "All lessons completed."}

        lesson = CurriculumManager.get_high_level_by_order(current_order)
        if not lesson:
            return {"status": "error", "message": f"Lesson {current_order} missing."}

        hl_name = lesson["high_level_concept"]

        # Generate diagnostic quiz
        quiz = self.agent.generate_diagnostic_quiz(
            concept_name=hl_name,
            num_mcq=5,
            num_open=3
        )

        # Defensive normalization: ensure canonical shape before returning to API layer
        try:
            quiz = _ensure_quiz_shape(quiz, hl_name, 5, 3)
        except Exception:
            # final fallback
            quiz = {"mcq": [], "open_questions": []}

        # Return structured program start state
        return {
            "status": "diagnostic_required",
            "lesson_order": current_order,
            "lesson_name": hl_name,
            "quiz": quiz,
            "completed_lessons": progress.get("completed_lessons", [])
        }

    # -----------------------------
    # Submit Diagnostic
    # -----------------------------
    def submit_diagnostic(self, lesson_order: int, quiz_submissions: Dict[str, Any], skip_mode: bool = False):

        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson:
            return {"status": "error", "message": "Lesson not found."}

        hl_name = lesson["high_level_concept"]

        # Skip mode (user explicitly wants to skip lesson)
        if skip_mode:
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)

            return {
                "status": "lesson_skipped",
                "next_lesson_order": next_order,
                "message": f"Skipped {hl_name}"
            }

        # Grade diagnostic quiz
        grading_result = self.mastery_service.grade_composite_quiz(
            concept_name=hl_name,
            quiz_submissions=quiz_submissions,
            quiz_type="diagnostic"
        )

        composite_score = grading_result["composite_score"]

        # Update mastery
        self.mastery_service.update_lesson_mastery(
            self.student_name,
            lesson,
            composite_score,
            quiz_type="diagnostic"
        )

        # Pass case
        if composite_score >= PASS_THRESHOLD:
            return {
                "status": "passed_diagnostic",
                "lesson_order": lesson_order,
                "score": composite_score,
                "options": [
                    "Move to next lesson",
                    "Study this lesson anyway"
                ],
                "grading_details": grading_result
            }

        # Otherwise → start structured teaching
        return self._start_structured_teaching(lesson_order, hl_name)

    # -----------------------------
    # Start structured teaching
    # -----------------------------
    def _start_structured_teaching(self, lesson_order: int, hl_name: str):

        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        subs = sorted(lesson.get("sub_concepts", []), key=lambda x: x.get("order", 0))

        if not subs:
            return {
                "status": "error",
                "message": "No sub-concepts found for lesson."
            }

        first_sub = subs[0]["concept"]

        return {
            "status": "start_teaching",
            "lesson_order": lesson_order,
            "high_level_name": hl_name,
            "sub_concepts_list": [s["concept"] for s in subs],
            "next_concept_to_teach": first_sub
        }

    # -----------------------------
    # Streaming teaching
    # -----------------------------
    def teach_step_stream(self, lesson_order: int, concept_name: str):

        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson:
            def err():
                yield json.dumps({"error": "Lesson not found"})
            return StreamingResponse(err(), media_type="text/plain")

        hl = lesson["high_level_concept"]

        # Find sub-concept
        sub = next((s for s in lesson.get("sub_concepts", [])
                    if s["concept"] == concept_name), None)

        # Use workflow if available
        if sub and (sub.get("workflows") or sub.get("secondary_workflows")):
            wf = (sub.get("workflows") or sub.get("secondary_workflows"))[0]
            first_step = wf.get("steps", [{}])[0].get("concept", concept_name)
            generator = self.agent.generate_streaming_content(hl, first_step)
            return StreamingResponse(generator, media_type="text/plain")

        # Default: explain the concept directly
        generator = self.agent.generate_streaming_content(hl, concept_name)
        return StreamingResponse(generator, media_type="text/plain")

    # -----------------------------
    # Final lesson quiz
    # -----------------------------
    def finish_lesson_quiz(self, lesson_order: int, quiz_submissions: Dict[str, Any]):

        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson:
            return {"status": "error", "message": "Lesson not found."}

        hl = lesson["high_level_concept"]

        grading_result = self.mastery_service.grade_composite_quiz(
            concept_name=hl,
            quiz_submissions=quiz_submissions,
            quiz_type="final"
        )

        composite_score = grading_result["composite_score"]

        # Update mastery
        self.mastery_service.update_lesson_mastery(
            self.student_name,
            lesson,
            composite_score,
            quiz_type="final"
        )

        # Pass
        if composite_score >= PASS_THRESHOLD:
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)

            return {
                "status": "lesson_passed",
                "score": composite_score,
                "next_lesson_order": next_order,
                "grading_details": grading_result
            }

        # Fail
        self.profile.update_progress(self.student_name, lesson_order, None)

        return {
            "status": "lesson_failed",
            "score": composite_score,
            "next_lesson_order": lesson_order,
            "grading_details": grading_result
        }

    # -----------------------------
    # Mastery Dashboard
    # -----------------------------
    def get_mastery_dashboard_data(self):

        all_mastery = self.profile.get_all_mastery(self.student_name)
        dashboard = []

        for lesson in self.lessons_by_order:

            hl = lesson["high_level_concept"]
            order = lesson.get("order", 99)

            progress = self.profile.get_progress(self.student_name)
            completed = order in progress.get("completed_lessons", [])

            hl_mastery = all_mastery.get(hl, 0.0)

            subs = [
                {
                    "concept": s["concept"],
                    "mastery": all_mastery.get(s["concept"], 0.0)
                }
                for s in lesson.get("sub_concepts", [])
            ]

            dashboard.append({
                "lesson_order": order,
                "high_level_concept": hl,
                "mastery": hl_mastery,
                "completed": completed,
                "sub_concepts": subs
            })

        return {
            "student_name": self.student_name,
            "dashboard_data": dashboard
        }

    # -----------------------------
    # Practice Mode
    # -----------------------------
    def generate_practice_quiz(self, hl_concept_name: str, difficulty: str):

        quiz = self.agent.generate_diagnostic_quiz(
            concept_name=hl_concept_name,
            num_mcq=10,
            num_open=0
        )

        quiz = _ensure_quiz_shape(quiz, hl_concept_name, 10, 0)
        return {
            "concept_name": hl_concept_name,
            "questions": quiz.get("mcq", [])
        }

    def submit_practice_quiz_score(self, hl_concept_name: str, score: float, difficulty: str):

        lesson = next(
            (c for c in self.lessons_by_order if c["high_level_concept"] == hl_concept_name),
            None
        )

        if not lesson:
            return {"message": "Concept not found."}

        self.mastery_service.update_lesson_mastery(
            self.student_name,
            lesson,
            score,
            quiz_type="practice"
        )

        return {"message": "Practice score recorded."}
