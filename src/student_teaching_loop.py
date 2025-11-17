# src/student_teaching_loop.py
import json
from typing import List, Dict, Any, Generator, Optional
from pathlib import Path
import os

# streaming response import (was missing)
from fastapi.responses import StreamingResponse

# Use absolute imports now that 'src' is a package
from .student_profiles import StudentProfile, CurriculumManager
from .student_assessment import generate_diagnostic_quiz, generate_streaming_content, grade_answer
from .mastery_service import MasteryService

# --- Constants & Initialization ---
PASS_THRESHOLD = 0.75
PROJECT_ROOT = Path(__file__).parent.parent
WORKFLOWS_JSON = PROJECT_ROOT / "data" / "curriculum.json"

def load_concepts(json_path: Path) -> List[Dict[str, Any]]:
    if not json_path.exists():
        return []
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'concepts' in data:
        return data['concepts']
    elif isinstance(data, list):
        return data
    return []

def flatten_sub_concepts(concepts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat_list = []
    for parent_concept in sorted(concepts, key=lambda x: x.get('order', 0)):
        high_level_name = parent_concept.get('high_level_concept')
        if not high_level_name:
            continue
        parent_workflows = parent_concept.get('workflows', [])
        sub_concepts = parent_concept.get('sub_concepts', [])
        if not sub_concepts:
            continue
        for sub_concept in sorted(sub_concepts, key=lambda x: x.get('order', 0)):
            sub_concept_name = sub_concept.get('concept')
            if not sub_concept_name:
                continue
            all_workflows = {}
            for wf in parent_workflows:
                if wf.get('workflow_id'):
                    all_workflows[wf['workflow_id']] = wf
            for wf in sub_concept.get('workflows', []):
                if wf.get('workflow_id'):
                    all_workflows[wf['workflow_id']] = wf
            for wf in sub_concept.get('secondary_workflows', []):
                if wf.get('workflow_id'):
                    all_workflows[wf['workflow_id']] = wf
            flat_entry = {
                'high_level': high_level_name,
                'name': sub_concept_name,
                'workflows': list(all_workflows.values())
            }
            flat_list.append(flat_entry)
    return flat_list

class TeachingLoopService:
    def __init__(self, student_name: str):
        self.student_name = student_name
        self.profile = StudentProfile()
        self.mastery_service = MasteryService(self.profile)
        # IMPORTANT: avoid creating multiple AssessmentAgent instances here;
        # Use functions from student_assessment which manage lazy client
        self.high_level_concepts_map = CurriculumManager.get_high_level_concepts()
        self.profile.register_student(student_name)
        self.lessons_by_order = sorted(self.high_level_concepts_map.values(), key=lambda x: x.get('order', 99)) if self.high_level_concepts_map else []
        self.max_order = self.lessons_by_order[-1]['order'] if self.lessons_by_order else 1

    def start_program(self, lesson_order_override: Optional[int] = None) -> Dict[str, Any]:
        progress = self.profile.get_progress(self.student_name)
        current_order = lesson_order_override if lesson_order_override else progress.get("current_lesson_order", 1)
        if current_order > self.max_order:
            return {"status": "complete", "message": "All lessons finished."}
        current_lesson = CurriculumManager.get_high_level_by_order(current_order)
        if not current_lesson:
            return {"status": "error", "message": f"Lesson Order {current_order} not found."}
        hl_name = current_lesson["high_level_concept"]
        # generate diagnostic (safe)
        diag = generate_diagnostic_quiz(hl_name, num_mcq=5, num_open=3)
        return {
            "status": "diagnostic_required",
            "lesson_order": current_order,
            "lesson_name": hl_name,
            "quiz": diag,
            "completed_lessons": progress.get("completed_lessons", [])
        }

    def submit_diagnostic(self, lesson_order: int, quiz_submissions: Dict[str, Any], skip_mode: bool = False) -> Dict[str, Any]:
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson_data:
            return {"status": "error", "message": "Lesson not found."}
        hl_name = lesson_data["high_level_concept"]
        if skip_mode:
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)
            return {"status": "lesson_skipped", "next_lesson_order": next_order, "message": f"Skipped {hl_name}"}
        # grade composite using mastery_service
        grading_result = self.mastery_service.grade_composite_quiz(hl_name, quiz_submissions, quiz_type="diagnostic")
        composite_score = grading_result.get("composite_score", 0.0)
        self.mastery_service.update_lesson_mastery(self.student_name, lesson_data, composite_score, quiz_type="diagnostic")
        if composite_score >= PASS_THRESHOLD:
            return {"status": "passed_diagnostic", "lesson_order": lesson_order, "score": composite_score, "options": ["Move to next lesson", "Study this lesson anyway"], "grading_details": grading_result}
        else:
            return self._start_structured_teaching(lesson_order, hl_name)

    def _start_structured_teaching(self, lesson_order: int, hl_concept_name: str) -> Dict[str, Any]:
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        sub_concepts = sorted(lesson_data.get('sub_concepts', []), key=lambda x: x.get('order', 0))
        if not sub_concepts:
            return {"status": "error", "message": "No sub-concepts."}
        first_sub = sub_concepts[0]["concept"]
        return {"status": "start_teaching", "lesson_order": lesson_order, "high_level_name": hl_concept_name, "sub_concepts_list": [s['concept'] for s in sub_concepts], "next_concept_to_teach": first_sub}

    def teach_step_stream(self, lesson_order: int, concept_name: str):
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson_data:
            def err(): 
                yield json.dumps({"error":"lesson not found"})
            return StreamingResponse(err(), media_type="text/plain")
        hl = lesson_data["high_level_concept"]
        # if sub-concept exists and has workflows, pick first step; else generic streaming
        sub = next((s for s in lesson_data.get('sub_concepts', []) if s['concept'] == concept_name), None)
        if sub and (sub.get('workflows') or sub.get('secondary_workflows')):
            wf = (sub.get('workflows') or sub.get('secondary_workflows'))[0]
            first_step = wf.get('steps', [{}])[0].get('concept', concept_name)
            gen = generate_streaming_content(hl, first_step)
            return StreamingResponse(gen, media_type="text/plain")
        else:
            gen = generate_streaming_content(hl, concept_name)
            return StreamingResponse(gen, media_type="text/plain")

    def finish_lesson_quiz(self, lesson_order: int, quiz_submissions: Dict[str, Any]) -> Dict[str, Any]:
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson_data:
            return {"status":"error","message":"Lesson not found."}
        hl = lesson_data["high_level_concept"]
        grading_result = self.mastery_service.grade_composite_quiz(hl, quiz_submissions, quiz_type="final")
        composite_score = grading_result.get("composite_score", 0.0)
        self.mastery_service.update_lesson_mastery(self.student_name, lesson_data, composite_score, quiz_type="final")
        if composite_score >= PASS_THRESHOLD:
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)
            return {"status":"lesson_passed","score":composite_score,"next_lesson_order":next_order,"grading_details":grading_result}
        else:
            self.profile.update_progress(self.student_name, lesson_order, None)
            return {"status":"lesson_failed","score":composite_score,"next_lesson_order":lesson_order,"grading_details":grading_result}

    def get_mastery_dashboard_data(self):
        all_mastery = self.profile.get_all_mastery(self.student_name)
        dashboard = []
        for lesson in self.lessons_by_order:
            hl = lesson["high_level_concept"]
            order = lesson.get("order", 99)
            completed = order in self.profile.get_progress(self.student_name).get("completed_lessons", [])
            hl_mastery = all_mastery.get(hl, 0.0)
            sub_list = [{"concept": s["concept"], "mastery": all_mastery.get(s["concept"], 0.0)} for s in lesson.get("sub_concepts",[])]
            dashboard.append({"lesson_order": order, "high_level_concept": hl, "mastery": hl_mastery, "completed": completed, "sub_concepts": sub_list})
        return {"student_name": self.student_name, "dashboard_data": dashboard}

    def generate_practice_quiz(self, hl_concept_name: str, difficulty: str):
        quiz = generate_diagnostic_quiz(hl_concept_name, num_mcq=10, num_open=0)
        return {"concept_name": hl_concept_name, "questions": quiz.get("mcq", [])}

    def submit_practice_quiz_score(self, hl_concept_name: str, score: float, difficulty: str):
        lesson = next((c for c in self.lessons_by_order if c["high_level_concept"]==hl_concept_name), None)
        if not lesson:
            return {"message":"Concept not found."}
        self.mastery_service.update_lesson_mastery(self.student_name, lesson, score, quiz_type="practice")
        return {"message":"Practice score recorded."}
