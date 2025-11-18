# api/main.py (FINAL PRODUCTION VERSION)
"""
FastAPI application to serve the teaching agent logic with the new 
Sequential Gated Flow (9 Ordered Lessons, Diagnostic Gates).
"""

import os
import sys
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# ----------------------------------------------------
# Logging (Cloud Run reads from stderr automatically)
# ----------------------------------------------------
logger = logging.getLogger("uvicorn.error")

# ----------------------------------------------------
# Add src/ to PYTHONPATH (safe for Cloud Run)
# ----------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, '..', 'src'))
if src_dir not in sys.path:
    sys.path.append(src_dir)

# ----------------------------------------------------
# Import core modules with safe error handling
# ----------------------------------------------------
try:
    from src.student_profiles import StudentProfile, CurriculumManager
    from src.student_assessment import AssessmentAgent, LLM_MODEL
    from src.student_teaching_loop import TeachingLoopService, WORKFLOWS_JSON
except Exception as e:
    logger.error(f"❌ Failed to import backend modules: {e}")
    raise

# ----------------------------------------------------
# Environment Checks (non-fatal but logged)
# ----------------------------------------------------
if not os.getenv("OPENAI_API_KEY"):
    logger.warning("⚠️ OPENAI_API_KEY not found. LLM features will run in fallback mode.")

if not WORKFLOWS_JSON.exists():
    logger.warning(f"⚠️ curriculum.json not found at: {WORKFLOWS_JSON}")

# ----------------------------------------------------
# Create FastAPI App
# ----------------------------------------------------
app = FastAPI(
    title="Sequential Gated Teaching Agent API",
    description="Implements the 9-lesson sequential, diagnostic-gated learning flow.",
)

# ----------------------------------------------------
# Initialize global, singleton instances safely
# ----------------------------------------------------
try:
    db_profile = StudentProfile()
    assessment_agent = AssessmentAgent()

    logger.info("✅ FastAPI server startup complete. Agents and curriculum loaded.")
except Exception as e:
    logger.error(f"❌ Startup initialization failed: {e}")
    db_profile = None
    assessment_agent = None


# ----------------------------------------------------
# Pydantic Models
# ----------------------------------------------------
class StudentRequest(BaseModel):
    student_name: str = Field(..., example="Kartick_Test_Student")


class LessonOrderRequest(StudentRequest):
    lesson_order: Optional[int] = Field(None, description="Optional override to jump to a specific lesson.")


class QuizSubmission(BaseModel):
    mcq_answers: List[Dict[str, Any]]
    open_questions: List[Dict[str, Any]]


class SubmitDiagnosticRequest(StudentRequest):
    lesson_order: int
    submissions: QuizSubmission
    skip_mode: bool = False


class DiagnosticResponse(BaseModel):
    status: str
    lesson_order: int
    lesson_name: Optional[str] = None
    quiz: Optional[Dict[str, Any]] = None
    options: Optional[List[str]] = None
    message: Optional[str] = None
    completed_lessons: Optional[List[int]] = None


class FinalQuizRequest(SubmitDiagnosticRequest):
    pass


class FinalQuizResponse(BaseModel):
    status: str
    score: float
    next_lesson_order: int
    message: Optional[str] = None
    grading_details: Optional[Dict[str, Any]] = None


class TeachingStepRequest(StudentRequest):
    lesson_order: int
    concept_name: str


class MasteryDashboardResponse(BaseModel):
    student_name: str
    dashboard_data: List[Dict[str, Any]]


class PracticeQuizRequest(StudentRequest):
    hl_concept_name: str
    difficulty: str = "medium"


# FIXED: proper full request model for practice submit
class PracticeSubmitRequest(PracticeQuizRequest):
    score: float


# ----------------------------------------------------
# API Endpoints
# ----------------------------------------------------
@app.post("/register_student", response_model=StudentRequest)
def register_student_endpoint(request: StudentRequest):
    try:
        db_profile.register_student(request.student_name)
        return {"student_name": request.student_name}
    except Exception as e:
        raise HTTPException(500, f"Failed to register student: {e}")


@app.post("/program/start", response_model=DiagnosticResponse)
def start_program_endpoint(request: LessonOrderRequest):
    service = TeachingLoopService(request.student_name)
    try:
        result = service.start_program(request.lesson_order)
        # DEBUG: log raw result so we can see malformed quiz shapes in logs
        logger.info("DEBUG start_program raw result: %s", result)

        # Try to coerce into pydantic model but if validation fails, return raw JSON with helpful message
        try:
            return DiagnosticResponse(**result)
        except ValidationError as ve:
            # Log the validation error and the raw payload
            logger.error("ValidationError building DiagnosticResponse: %s", ve)
            logger.error("Raw payload causing validation error: %s", result)
            # Return raw JSON (status 200) so frontend can inspect; include warning
            payload = {
                "status": result.get("status", "error"),
                "lesson_order": result.get("lesson_order", request.lesson_order or 1),
                "lesson_name": result.get("lesson_name"),
                "quiz": result.get("quiz"),
                "completed_lessons": result.get("completed_lessons", []),
                "warning": "Response shape did not match DiagnosticResponse - returned raw payload; check backend logs."
            }
            return JSONResponse(status_code=200, content=payload)
    except Exception as e:
        logger.error(f"start_program error: {e}", exc_info=True)
        raise HTTPException(500, f"Error starting program: {e}")


@app.post("/program/submit_diagnostic", response_model=DiagnosticResponse)
def submit_diagnostic_endpoint(request: SubmitDiagnosticRequest):
    service = TeachingLoopService(request.student_name)
    try:
        result = service.submit_diagnostic(
            lesson_order=request.lesson_order,
            quiz_submissions=request.submissions.model_dump(),
            skip_mode=request.skip_mode
        )
        return DiagnosticResponse(**result)
    except Exception as e:
        logger.error(f"submit_diagnostic error: {e}")
        raise HTTPException(500, f"Error submitting diagnostic: {e}")


@app.post("/program/teach_step_stream")
def teach_step_stream_endpoint(request: TeachingStepRequest):
    service = TeachingLoopService(request.student_name)
    try:
        return service.teach_step_stream(request.lesson_order, request.concept_name)
    except Exception as e:
        logger.error(f"teach_step_stream error: {e}")

        def error_gen():
            yield f"{{'error': '{e}'}}"

        return StreamingResponse(error_gen(), media_type="text/plain")


@app.post("/program/finish_quiz", response_model=FinalQuizResponse)
def finish_lesson_quiz_endpoint(request: FinalQuizRequest):
    service = TeachingLoopService(request.student_name)
    try:
        result = service.finish_lesson_quiz(
            lesson_order=request.lesson_order,
            quiz_submissions=request.submissions.model_dump()
        )
        return FinalQuizResponse(**result)
    except Exception as e:
        logger.error(f"finish_quiz error: {e}")
        raise HTTPException(500, f"Error finishing lesson quiz: {e}")


@app.post("/dashboard/mastery", response_model=MasteryDashboardResponse)
def get_mastery_dashboard(request: StudentRequest):
    service = TeachingLoopService(request.student_name)
    try:
        data = service.get_mastery_dashboard_data()
        return MasteryDashboardResponse(**data)
    except Exception as e:
        logger.error(f"dashboard error: {e}")
        raise HTTPException(500, f"Error retrieving dashboard: {e}")


@app.post("/practice/generate_quiz")
def generate_practice_quiz_endpoint(request: PracticeQuizRequest):
    service = TeachingLoopService(request.student_name)
    try:
        return service.generate_practice_quiz(request.hl_concept_name, request.difficulty)
    except Exception as e:
        logger.error(f"practice/generate_quiz error: {e}")
        raise HTTPException(500, f"Error generating practice quiz: {e}")


# FIXED: clean practice submit endpoint
@app.post("/practice/submit_score")
def submit_practice_quiz_score_endpoint(request: PracticeSubmitRequest):
    service = TeachingLoopService(request.student_name)
    try:
        return service.submit_practice_quiz_score(
            request.hl_concept_name,
            request.score,
            request.difficulty
        )
    except Exception as e:
        logger.error(f"practice/submit_score error: {e}")
        raise HTTPException(500, f"Error submitting practice score: {e}")


# ----------------------------------------------------
# Local Dev Entry Point (Cloud Run uses entrypoint CMD)
# ----------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
