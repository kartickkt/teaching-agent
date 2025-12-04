# src/student_teaching_loop.py

import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from fastapi.responses import StreamingResponse

from .student_profiles import StudentProfile, CurriculumManager
from .student_assessment import AssessmentAgent, _ensure_quiz_shape
from .mastery_service import MasteryService

PASS_THRESHOLD = 0.75

class TeachingLoopService:
    def __init__(self, student_name: str):
        self.student_name = student_name
        self.profile = StudentProfile()
        self.mastery_service = MasteryService(self.profile)
        self.agent = AssessmentAgent()
        
        # Ensure student exists
        self.profile.register_student(student_name)
        
        # Curriculum
        self.high_level_concepts_map = CurriculumManager.get_high_level_concepts()
        self.lessons_by_order = sorted(
            self.high_level_concepts_map.values(),
            key=lambda x: x.get("order", 99)
        )
        self.max_order = self.lessons_by_order[-1]["order"] if self.lessons_by_order else 1

    # -----------------------------
    # Sync Methods
    # -----------------------------
    def start_program(self, lesson_order_override: Optional[int] = None, lazy: bool = False) -> Dict[str, Any]:
        """
        Determines the student's current state.
        If lazy=True, skips the expensive quiz generation step.
        """
        progress = self.profile.get_progress(self.student_name)
        current_order = lesson_order_override or progress.get("current_lesson_order", 1)

        if current_order > self.max_order:
            return {"status": "complete", "message": "All lessons completed."}

        lesson = CurriculumManager.get_high_level_by_order(current_order)
        hl_name = lesson["high_level_concept"]

        # --- LAZY LOADING LOGIC ---
        if lazy:
             return {
                "status": "diagnostic_required",
                "lesson_order": current_order,
                "lesson_name": hl_name,
                "quiz": None, # Frontend handles this by calling ensure_diagnostic_quiz
                "completed_lessons": progress.get("completed_lessons", [])
            }
        # --------------------------

        # Fallback: Synchronous generation (if lazy=False)
        quiz = self.agent.generate_diagnostic_quiz(hl_name, 5, 3)
        
        return {
            "status": "diagnostic_required",
            "lesson_order": current_order,
            "lesson_name": hl_name,
            "quiz": quiz,
            "completed_lessons": progress.get("completed_lessons", [])
        }

    def ensure_diagnostic_quiz(self, lesson_order: int):
        """
        On-demand generation for the 'Lazy Load' pattern.
        Called when the frontend sees 'quiz': None.
        """
        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson:
            return {"quiz": None}
            
        hl_name = lesson["high_level_concept"]
        # This is the slow LLM call (5-10s)
        quiz = self.agent.generate_diagnostic_quiz(hl_name, 5, 3)
        return {"quiz": quiz}

    def teach_step_stream(self, lesson_order: int, concept_name: str):
        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        hl = lesson["high_level_concept"] if lesson else "Unknown"
        generator = self.agent.generate_streaming_content(hl, concept_name)
        return StreamingResponse(generator, media_type="text/plain")
    
    def get_mastery_dashboard_data(self):
        all_mastery = self.profile.get_all_mastery(self.student_name)
        dashboard = []
        progress = self.profile.get_progress(self.student_name)
        
        for lesson in self.lessons_by_order:
            hl = lesson["high_level_concept"]
            order = lesson.get("order", 99)
            completed = order in progress.get("completed_lessons", [])
            subs = [{"concept": s["concept"], "mastery": all_mastery.get(s["concept"], 0.0)} for s in lesson.get("sub_concepts", [])]
            dashboard.append({
                "lesson_order": order,
                "high_level_concept": hl,
                "mastery": all_mastery.get(hl, 0.0),
                "completed": completed,
                "sub_concepts": subs
            })
        return {"student_name": self.student_name, "dashboard_data": dashboard}

    def generate_practice_quiz(self, hl_concept_name: str, difficulty: str):
        quiz = self.agent.generate_diagnostic_quiz(hl_concept_name, 10, 0)
        return {"concept_name": hl_concept_name, "questions": quiz.get("mcq", [])}

    def submit_practice_quiz_score(self, hl_concept_name: str, score: float, difficulty: str):
        lesson = next((c for c in self.lessons_by_order if c["high_level_concept"] == hl_concept_name), None)
        if lesson:
            self.mastery_service.update_lesson_mastery(self.student_name, lesson, score, quiz_type="practice")

    # -----------------------------
    # ASYNC Methods (For grading)
    # -----------------------------
    async def submit_diagnostic_async(self, lesson_order: int, quiz_submissions: Dict[str, Any], skip_mode: bool = False):
        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson: return {"status": "error", "message": "Lesson not found."}
        hl_name = lesson["high_level_concept"]

        if skip_mode:
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)
            return {"status": "lesson_skipped", "next_lesson_order": next_order}

        # ASYNC GRADING CALL
        grading_result = await self.mastery_service.grade_composite_quiz_async(
            concept_name=hl_name,
            quiz_submissions=quiz_submissions,
            quiz_type="diagnostic"
        )
        composite = grading_result["composite_score"]
        
        # Sync DB Update
        self.mastery_service.update_lesson_mastery(self.student_name, lesson, composite, "diagnostic")

        if composite >= PASS_THRESHOLD:
            return {
                "status": "passed_diagnostic",
                "lesson_order": lesson_order,
                "score": composite,
                "grading_details": grading_result
            }
        
        # Fail logic -> Start Teaching
        subs = sorted(lesson.get("sub_concepts", []), key=lambda x: x.get("order", 0))
        return {
            "status": "start_teaching",
            "lesson_order": lesson_order,
            "high_level_name": hl_name,
            "sub_concepts_list": [s["concept"] for s in subs],
            "next_concept_to_teach": subs[0]["concept"] if subs else ""
        }

    async def finish_lesson_quiz_async(self, lesson_order: int, quiz_submissions: Dict[str, Any]):
        lesson = CurriculumManager.get_high_level_by_order(lesson_order)
        hl = lesson["high_level_concept"]

        # ASYNC GRADING
        grading_result = await self.mastery_service.grade_composite_quiz_async(
            concept_name=hl,
            quiz_submissions=quiz_submissions,
            quiz_type="final"
        )
        composite = grading_result["composite_score"]

        # Sync DB Update
        self.mastery_service.update_lesson_mastery(self.student_name, lesson, composite, "final")

        if composite >= PASS_THRESHOLD:
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)
            return {"status": "lesson_passed", "score": composite, "next_lesson_order": next_order}
        
        self.profile.update_progress(self.student_name, lesson_order, None)
        return {"status": "lesson_failed", "score": composite, "next_lesson_order": lesson_order}