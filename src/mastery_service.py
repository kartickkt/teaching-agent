# src/mastery_service.py (NEW FILE)
from typing import Dict, Any, Optional
from .student_profiles import StudentProfile, CurriculumManager
from .student_assessment import AssessmentAgent

# --- Constants ---
DIFFICULTY_ALPHAS = {
    "diagnostic": 0.3, # Medium impact for diagnostic
    "final": 0.4,      # Higher impact for passing the final test
    "practice": 0.1    # Low impact for practice mode
}

class MasteryService:
    """Handles grading, composite score calculation, and EMA updates."""

    def __init__(self, profile: StudentProfile):
        self.profile = profile
        self.agent = AssessmentAgent()

    def grade_composite_quiz(self, concept_name: str, quiz_submissions: Dict[str, Any], quiz_type: str) -> Dict[str, Any]:
        """
        Calculates the composite score based on MCQ (out of 5) and open answers (out of 3).
        Total Max Score = 8 points.
        """
        
        mcq_answers = quiz_submissions.get('mcq_answers', [])
        open_questions = quiz_submissions.get('open_questions', [])
        
        # 1. MCQ Grading (Assuming the client provides the correct answer key for quick local grading)
        # NOTE: For security, the backend should ideally store and grade against the true answer key.
        # Assuming for now 'mcq_answers' contains the generated question, user_answer, and the correct 'answer' key.
        mcq_correct = 0
        for ans in mcq_answers:
             # Basic check: if the user's selected option matches the correct answer key from the quiz generation
             if ans.get('user_selection') == ans.get('answer'): 
                 mcq_correct += 1
        mcq_score_raw = mcq_correct # Score out of 5
        
        # 2. Open-Answer Grading (LLM Call - auto-graded, short answers)
        open_score_sum = 0.0
        graded_open_answers = []
        
        # Open answers structure should be: [{"question": Q1, "answer": A1}, ...]
        for submission in open_questions: 
            question = submission.get('question', 'N/A')
            answer = submission.get('user_answer', '')
            
            grade_result = self.agent.grade_answer(concept_name, question, answer)
            open_score_sum += grade_result.get('score', 0.0) # Sum of 0.0 to 1.0 scores
            graded_open_answers.append({**submission, **grade_result})

        # 3. Composite Score Calculation
        # Total score is (MCQ count) + (Sum of LLM scores from 0-3)
        # Max Score = 5 (MCQ) + 3 (Open) = 8
        total_score_raw = mcq_score_raw + open_score_sum
        composite_score = total_score_raw / 8.0 

        return {
            "mcq_correct": mcq_correct,
            "open_score_sum": open_score_sum,
            "total_score_raw": total_score_raw,
            "composite_score": composite_score,
            "graded_open_answers": graded_open_answers
        }

    def update_lesson_mastery(self, student_name: str, lesson_data: Dict[str, Any], final_score: float, quiz_type: str = "final"):
        """
        Updates EMA mastery for all sub-concepts and the high-level concept.
        """
        hl_concept_name = lesson_data["high_level_concept"]
        sub_concepts = lesson_data.get('sub_concepts', [])
        
        # Alpha tune based on quiz type (as requested)
        sub_concept_alpha = DIFFICULTY_ALPHAS.get(quiz_type, 0.4) 
        hl_concept_alpha = 0.1 # Keep high-level mastery more stable
        
        # 1. Update Sub-Concept Mastery (Propagate final score to all sub-concepts)
        for sub in sub_concepts:
            sub_name = sub["concept"]
            self.profile.update_mastery(student_name, sub_name, final_score, alpha=sub_concept_alpha)
            
        # 2. Calculate and Update High-Level Mastery
        if sub_concepts:
            # Calculate the average mastery across all sub-concepts after the update
            new_sub_masteries = [self.profile.get_mastery(student_name, sub["concept"]) for sub in sub_concepts]
            weighted_average_mastery = sum(new_sub_masteries) / len(sub_concepts)
            
            # Update the high-level concept mastery using the calculated average
            self.profile.update_mastery(student_name, hl_concept_name, weighted_average_mastery, alpha=hl_concept_alpha)
            
        return self.profile.get_mastery(student_name, hl_concept_name)