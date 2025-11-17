# src/student_teaching_loop.py (REVISED)
import json
from typing import List, Dict, Any, Generator, Optional, Tuple

# Use absolute imports now that 'src' is a package
from .student_profiles import StudentProfile, CurriculumManager
from .student_assessment import AssessmentAgent
from .mastery_service import MasteryService 
from pathlib import Path
import os

# --- Constants & Initialization ---
PASS_THRESHOLD = 0.75
PROJECT_ROOT = Path(__file__).parent.parent 
WORKFLOWS_JSON = PROJECT_ROOT / "data" / "curriculum.json"

# Curriculum loading utilities (kept in this file as per original structure)
def load_concepts(json_path: Path) -> List[Dict[str, Any]]:
    # ... (Unchanged load_concepts implementation) ...
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
    # ... (Unchanged flatten_sub_concepts implementation) ...
    flat_list = []
    for parent_concept in sorted(concepts, key=lambda x: x.get('order', 0)):
        high_level_name = parent_concept.get('high_level_concept')
        if not high_level_name: continue
        
        parent_workflows = parent_concept.get('workflows', [])
        sub_concepts = parent_concept.get('sub_concepts', [])
        if not sub_concepts: continue

        for sub_concept in sorted(sub_concepts, key=lambda x: x.get('order', 0)):
            sub_concept_name = sub_concept.get('concept')
            if not sub_concept_name: continue

            all_workflows: Dict[str, Dict[str, Any]] = {}

            # 1. Add parent (high-level) workflows first
            for wf in parent_workflows:
                if wf.get('workflow_id'): all_workflows[wf['workflow_id']] = wf
            # 2. Add/overwrite with primary sub-concept workflows
            for wf in sub_concept.get('workflows', []):
                if wf.get('workflow_id'): all_workflows[wf['workflow_id']] = wf
            # 3. Add/overwrite with secondary sub-concept workflows
            for wf in sub_concept.get('secondary_workflows', []):
                if wf.get('workflow_id'): all_workflows[wf['workflow_id']] = wf

            flat_entry = {
                'high_level': high_level_name,
                'name': sub_concept_name,
                'workflows': list(all_workflows.values())
            }
            flat_list.append(flat_entry)
            
    return flat_list


class TeachingLoopService:
    """
    Implements the core sequential, gated teaching flow logic.
    """
    def __init__(self, student_name: str):
        self.student_name = student_name
        self.profile = StudentProfile()
        self.agent = AssessmentAgent()
        self.mastery_service = MasteryService(self.profile)
        self.high_level_concepts_map = CurriculumManager.get_high_level_concepts()
        self.profile.register_student(student_name)
        
        # Load the 9 lessons list globally for easy sequential lookup
        self.lessons_by_order = sorted(self.high_level_concepts_map.values(), key=lambda x: x.get('order', 99))
        self.max_order = self.lessons_by_order[-1]['order'] if self.lessons_by_order else 1


    def start_program(self, lesson_order_override: Optional[int] = None) -> Dict[str, Any]:
        """
        Action 1: Identify the current lesson and run the diagnostic.
        """
        # 1. Load persistent progress or use override
        progress = self.profile.get_progress(self.student_name)
        current_order = lesson_order_override if lesson_order_override else progress.get("current_lesson_order", 1)

        if current_order > self.max_order:
            return {"status": "complete", "message": "All lessons finished."}

        current_lesson_data = CurriculumManager.get_high_level_by_order(current_order)
        
        if not current_lesson_data:
             # Should only happen if curriculum is incomplete/misordered
            return {"status": "error", "message": f"Lesson Order {current_order} not found in curriculum."}

        hl_concept_name = current_lesson_data["high_level_concept"]
        
        # 2. Generate Diagnostic Quiz (5 MCQ + 3 Open-ended)
        diagnostic_quiz = self.agent.generate_diagnostic_quiz(hl_concept_name, num_mcq=5, num_open=3)

        return {
            "status": "diagnostic_required",
            "lesson_order": current_order,
            "lesson_name": hl_concept_name,
            "quiz": diagnostic_quiz,
            "completed_lessons": progress.get("completed_lessons", [])
        }


    def submit_diagnostic(self, lesson_order: int, quiz_submissions: Dict[str, Any], skip_mode: bool = False) -> Dict[str, Any]:
        """
        Action 2: Grade the diagnostic and determine the next step (Skip/Study).
        Used for both:
        1. Submitting the initial diagnostic.
        2. Accepting the 'Move to next lesson' option after passing (skip_mode=True).
        """
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson_data:
            return {"status": "error", "message": "Lesson not found."}

        hl_concept_name = lesson_data["high_level_concept"]

        if skip_mode:
            # Student chose to skip after passing. Mark current as complete and move ahead.
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)
            return {
                "status": "lesson_skipped",
                "next_lesson_order": next_order,
                "message": f"Lesson '{hl_concept_name}' skipped. Starting diagnostic for Lesson {next_order}."
            }
        
        # 1. Grade the quiz
        grading_result = self.mastery_service.grade_composite_quiz(
            concept_name=hl_concept_name,
            quiz_submissions=quiz_submissions, 
            quiz_type="diagnostic"
        )
        
        composite_score = grading_result["composite_score"]
        
        # 2. Update Mastery (Record the attempt in mastery for sub-concepts, low alpha)
        self.mastery_service.update_lesson_mastery(self.student_name, lesson_data, composite_score, quiz_type="diagnostic")

        if composite_score >= PASS_THRESHOLD:
            # Score >= Threshold: Offer to skip or study
            return {
                "status": "passed_diagnostic",
                "lesson_order": lesson_order,
                "score": composite_score,
                "threshold": PASS_THRESHOLD,
                "grading_details": grading_result,
                "options": ["Move to next lesson", "Study this lesson anyway"]
            }
        else:
            # Score < Threshold: Start structured teaching
            return self._start_structured_teaching(lesson_order, hl_concept_name)


    def _start_structured_teaching(self, lesson_order: int, hl_concept_name: str) -> Dict[str, Any]:
        """Initiates the structured teaching loop."""
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        sub_concepts = sorted(lesson_data.get('sub_concepts', []), key=lambda x: x.get('order', 0))
        
        if not sub_concepts:
            return {"status": "error", "message": "Lesson has no sub-concepts to teach."}

        # The teaching flow is based entirely on the sub-concept list
        first_sub_concept = sub_concepts[0]["concept"]
        
        return {
            "status": "start_teaching",
            "lesson_order": lesson_order,
            "high_level_name": hl_concept_name,
            "sub_concepts_list": [s['concept'] for s in sub_concepts],
            "next_concept_to_teach": first_sub_concept,
            "message": f"You scored below {PASS_THRESHOLD*100:.0f}%. Starting structured lesson."
        }


    def teach_step_stream(self, lesson_order: int, concept_name: str) -> StreamingResponse:
        """
        Generates content for a single sub-concept (or workflow step) and streams it out.
        Handles checking for custom workflows or falling back to the fixed template.
        """
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson_data:
            def error_gen(): yield json.dumps({"error": "Lesson not found"})
            return StreamingResponse(error_gen(), media_type="text/plain")
            
        hl_concept_name = lesson_data["high_level_concept"]
        sub_concept_data = next((s for s in lesson_data.get('sub_concepts', []) if s['concept'] == concept_name), None)
        
        if not sub_concept_data:
            # This is likely a specific step within a workflow, or the concept name is slightly off
            # We fall back to generic explanation
            return StreamingResponse(self.agent.generate_streaming_content(hl_concept_name, concept_name), media_type="text/plain")

        # Check for user-defined teaching workflows
        workflows = sub_concept_data.get('workflows', []) or sub_concept_data.get('secondary_workflows', [])
        
        if workflows and workflows[0].get('steps'):
            # The client should manage the sequence of steps, so we just return content for the input concept_name
            # If the concept_name IS a step, the initial non-matching sub_concept_data block handles it.
            # If the concept_name is the main sub-concept, we let the teaching loop decide the next step, 
            # or for simplicity, just stream the first step's content.
            first_step_concept = workflows[0]["steps"][0]["concept"]
            return StreamingResponse(self.agent.generate_streaming_content(hl_concept_name, first_step_concept), media_type="text/plain")
            
        else:
            # Fixed Teaching Template (what -> why -> how -> challenges -> example)
            teaching_flow = [
                ("What it is", "definition"), 
                ("Why/Need", "motivation"), 
                ("How/Process", "mechanism"), 
                ("Challenges/Limitations", "limitations"), 
                ("Example", "application")
            ]
            
            # The agent will generate content for each step in the flow sequentially
            return StreamingResponse(self.agent.generate_streaming_content(hl_concept_name, concept_name, fixed_flow=teaching_flow), media_type="text/plain")


    def finish_lesson_quiz(self, lesson_order: int, quiz_submissions: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action 4: Grades the final lesson quiz and updates mastery/progress.
        """
        lesson_data = CurriculumManager.get_high_level_by_order(lesson_order)
        if not lesson_data:
            return {"status": "error", "message": "Lesson not found."}

        hl_concept_name = lesson_data["high_level_concept"]

        # 1. Grade the final quiz
        grading_result = self.mastery_service.grade_composite_quiz(
            concept_name=hl_concept_name,
            quiz_submissions=quiz_submissions,
            quiz_type="final"
        )
        
        composite_score = grading_result["composite_score"]
        
        # 2. Update Mastery 
        self.mastery_service.update_lesson_mastery(self.student_name, lesson_data, composite_score, quiz_type="final")

        if composite_score >= PASS_THRESHOLD:
            # Pass: Move cursor to the next lesson and mark current as completed
            next_order = lesson_order + 1
            self.profile.update_progress(self.student_name, next_order, lesson_order)
            
            return {
                "status": "lesson_passed",
                "score": composite_score,
                "next_lesson_order": next_order,
                "grading_details": grading_result,
                "message": f"Congratulations! You passed the lesson and unlocked Lesson {next_order}."
            }
        else:
            # Fail: Offer to repeat the lesson (stay at current lesson order)
            self.profile.update_progress(self.student_name, lesson_order, completed_lesson_order=None)
            
            return {
                "status": "lesson_failed",
                "score": composite_score,
                "next_lesson_order": lesson_order,
                "grading_details": grading_result,
                "message": f"Your score was below {PASS_THRESHOLD*100:.0f}%. Please review the materials and try again."
            }

    def get_mastery_dashboard_data(self) -> Dict[str, Any]:
        """Gathers all high-level and sub-concept mastery data for the dashboard."""
        all_mastery = self.profile.get_all_mastery(self.student_name)
        dashboard_data = []

        for lesson in self.lessons_by_order:
            hl_name = lesson["high_level_concept"]
            lesson_order = lesson.get('order', 99)
            
            is_completed = lesson_order in self.profile.get_progress(self.student_name).get("completed_lessons", [])
            
            hl_mastery = all_mastery.get(hl_name, 0.0)

            sub_mastery_list = []
            for sub in lesson.get("sub_concepts", []):
                sub_name = sub["concept"]
                sub_mastery_list.append({
                    "concept": sub_name,
                    "mastery": all_mastery.get(sub_name, 0.0)
                })
            
            dashboard_data.append({
                "lesson_order": lesson_order,
                "high_level_concept": hl_name,
                "mastery": hl_mastery,
                "completed": is_completed,
                "sub_concepts": sub_mastery_list
            })
            
        return {"student_name": self.student_name, "dashboard_data": dashboard_data}


    def generate_practice_quiz(self, hl_concept_name: str, difficulty: str) -> Dict[str, Any]:
        """Generates a 10-MCQ practice quiz (no grading/state change)."""
        # We repurpose the diagnostic generator for MCQs only (5 MCQs twice for 10)
        practice_quiz_data = self.agent.generate_diagnostic_quiz(
            hl_concept_name, 
            num_mcq=10, # Request 10 MCQs
            num_open=0  # Request 0 open questions
        )
        
        # NOTE: If we wanted difficulty tuning, we'd add it to the LLM prompt.
        return {
            "concept_name": hl_concept_name,
            "questions": practice_quiz_data.get("mcq", [])
        }


    def submit_practice_quiz_score(self, hl_concept_name: str, score: float, difficulty: str) -> Dict[str, Any]:
        """
        Records the practice quiz score to slightly bump mastery (low alpha).
        This is an optional, lightweight mastery update for engagement.
        """
        lesson_data = next((c for c in self.lessons_by_order if c["high_level_concept"] == hl_concept_name), None)
        if not lesson_data:
             return {"message": "Concept not found, no mastery updated."}
             
        # Use the score from the practice attempt
        self.mastery_service.update_lesson_mastery(
            self.student_name, 
            lesson_data, 
            score, # Score is expected to be 0.0 to 1.0 from UI
            quiz_type="practice" # Uses a very low alpha (0.1)
        )
        
        return {
            "message": f"Practice quiz score recorded. Mastery for {hl_concept_name} subtly updated."
        }