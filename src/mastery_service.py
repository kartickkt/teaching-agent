# src/mastery_service.py (FINAL CORRECT VERSION)
from typing import Dict, Any, Optional, List
from .student_profiles import StudentProfile, CurriculumManager
from .student_assessment import grade_answer

# --- Constants ---
DIFFICULTY_ALPHAS = {
    "diagnostic": 0.3,
    "final": 0.4,
    "practice": 0.1
}

class MasteryService:
    """
    Handles:
    - MCQ + open-answer grading
    - Composite score calculation
    - EMA mastery updates inside student_profiles.mastery JSON
    """

    def __init__(self, profile: StudentProfile):
        self.profile = profile

    # --------------------------------------------------------
    # COMPOSITE SCORING
    # --------------------------------------------------------
    def grade_composite_quiz(self, concept_name: str, quiz_submissions: Dict[str, Any], quiz_type: str):
        
        mcq_answers = quiz_submissions.get("mcq_answers", [])
        open_questions = quiz_submissions.get("open_questions", [])

        # --- MCQ grading (client sends correct answer temporarily)
        mcq_correct = 0
        for ans in mcq_answers:
            if ans.get("user_selection") == ans.get("answer"):
                mcq_correct += 1

        mcq_score_raw = mcq_correct  # out of 5

        # --- Open answers (LLM-based scoring)
        open_score_sum = 0.0
        graded_open = []

        for submission in open_questions:
            question = submission.get("question")
            user_answer = submission.get("user_answer")

            # LLM call
            result = grade_answer(concept_name, question, user_answer)
            open_score_sum += result.get("score", 0.0)

            graded_open.append({
                "question": question,
                "user_answer": user_answer,
                "score": result.get("score", 0.0),
                "feedback": result.get("feedback", "")
            })

        total_raw = mcq_score_raw + open_score_sum      # max = 8
        composite = total_raw / 8.0

        return {
            "mcq_correct": mcq_correct,
            "open_score_sum": open_score_sum,
            "total_score_raw": total_raw,
            "composite_score": composite,
            "graded_open_answers": graded_open
        }

    # --------------------------------------------------------
    # MASTERY UPDATES
    # --------------------------------------------------------
    def update_lesson_mastery(self, student_name: str, lesson_data: Dict[str, Any], final_score: float, quiz_type="final"):

        hl_name = lesson_data["high_level_concept"]
        sub_concepts = lesson_data.get("sub_concepts", [])

        alpha_sub = DIFFICULTY_ALPHAS.get(quiz_type, 0.4)
        alpha_hl  = 0.1

        # --------------------------------------------
        # Update sub-concepts with EMA
        # --------------------------------------------
        for sub in sub_concepts:
            name = sub["concept"]
            self.profile.update_mastery(
                student_name,
                name,
                final_score,
                alpha=alpha_sub
            )

        # --------------------------------------------
        # Update high-level mastery = avg(sub concept mastery)
        # --------------------------------------------
        if sub_concepts:
            mastery_map = self.profile.get_all_mastery(student_name)

            sub_scores = [
                mastery_map.get(sub["concept"], 0.0)
                for sub in sub_concepts
            ]

            if sub_scores:
                avg_sub_mastery = sum(sub_scores) / len(sub_scores)
                self.profile.update_mastery(
                    student_name,
                    hl_name,
                    avg_sub_mastery,
                    alpha=alpha_hl
                )

        # Return latest HL mastery
        mastery_map = self.profile.get_all_mastery(student_name)
        return mastery_map.get(hl_name, 0.0)
