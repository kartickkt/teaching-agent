# src/mastery_service.py
import asyncio
from typing import Dict, Any, List
from .student_profiles import StudentProfile
from .student_assessment import grade_answer_async 

DIFFICULTY_ALPHAS = {"diagnostic": 0.3, "final": 0.4, "practice": 0.1}

class MasteryService:
    def __init__(self, profile: StudentProfile):
        self.profile = profile

    # --------------------------------------------------------
    # ASYNC COMPOSITE SCORING (PARALLEL)
    # --------------------------------------------------------
    async def grade_composite_quiz_async(self, concept_name: str, quiz_submissions: Dict[str, Any], quiz_type: str):
        mcq_answers = quiz_submissions.get("mcq_answers", [])
        open_questions = quiz_submissions.get("open_questions", [])

        # 1. MCQ Grading (Instant)
        mcq_correct = 0
        for ans in mcq_answers:
            # Flexible checking for dict or object
            sel = ans.get("user_selection")
            corr = ans.get("answer")
            if sel == corr:
                mcq_correct += 1
        
        mcq_score_raw = mcq_correct

        # 2. Open Answers (Parallel Async LLM calls)
        tasks = []
        for submission in open_questions:
            q = submission.get("question", "")
            u_ans = submission.get("user_answer", "")
            # Schedule the coroutine
            tasks.append(grade_answer_async(concept_name, q, u_ans))
        
        # Execute all LLM calls concurrently
        results = await asyncio.gather(*tasks)

        open_score_sum = sum(r.get("score", 0.0) for r in results)
        
        # Reconstruct feedback list
        graded_open = []
        for i, submission in enumerate(open_questions):
            graded_open.append({
                "question": submission.get("question"),
                "user_answer": submission.get("user_answer"),
                "score": results[i].get("score", 0.0),
                "feedback": results[i].get("feedback", "")
            })

        # Final Calc
        # Denominator: 5 MCQs + 3 Open = 8 usually. Or dynamic.
        total_items = max(1, len(mcq_answers) + len(open_questions))
        total_raw = mcq_score_raw + open_score_sum
        composite = total_raw / float(total_items)

        return {
            "mcq_correct": mcq_correct,
            "open_score_sum": open_score_sum,
            "total_score_raw": total_raw,
            "composite_score": composite,
            "graded_open_answers": graded_open
        }

    # --------------------------------------------------------
    # MASTERY UPDATES (Sync is fine here)
    # --------------------------------------------------------
    def update_lesson_mastery(self, student_name: str, lesson_data: Dict[str, Any], final_score: float, quiz_type="final"):
        hl_name = lesson_data["high_level_concept"]
        sub_concepts = lesson_data.get("sub_concepts", [])
        alpha_sub = DIFFICULTY_ALPHAS.get(quiz_type, 0.4)
        
        # Update subs
        for sub in sub_concepts:
            self.profile.update_mastery(student_name, sub["concept"], final_score, alpha=alpha_sub)

        # Update HL
        if sub_concepts:
            mastery_map = self.profile.get_all_mastery(student_name)
            sub_scores = [mastery_map.get(s["concept"], 0.0) for s in sub_concepts]
            if sub_scores:
                avg = sum(sub_scores) / len(sub_scores)
                self.profile.update_mastery(student_name, hl_name, avg, alpha=0.1)