# api/main.py (REVISED)
"""
FastAPI application to serve the teaching agent logic with the new 
Sequential Gated Flow (9 Ordered Lessons, Diagnostic Gates).
"""
import os
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from fastapi.responses import StreamingResponse
from openai import OpenAI # Kept for chat functionality if needed, though replaced in other files

# --- Add src to Python Path ---
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, '..', 'src'))
if src_dir not in sys.path:
    sys.path.append(src_dir)
# -------------------------------

try:
    # --- New Imports ---
    from student_profiles import StudentProfile, CurriculumManager
    from student_assessment import AssessmentAgent, LLM_MODEL
    from student_teaching_loop import TeachingLoopService, flatten_sub_concepts, load_concepts, WORKFLOWS_JSON
    # -------------------
except ImportError as e:
    print(f"Error: Failed to import src modules: {e}")
    sys.exit(1)

# --- FastAPI App & Global Agents ---
app = FastAPI(
    title="Sequential Gated Teaching Agent API",
    description="Implements the 9-lesson sequential, diagnostic-gated learning flow.",
)

# Initialize global, singleton instances
try:
    # We still need StudentProfile and CurriculumManager for context outside the loop
    db_profile = StudentProfile() 
    assessment_agent = AssessmentAgent() 
    
    # Load and flatten the curriculum once on startup
    all_concepts_data = flatten_sub_concepts(load_concepts(WORKFLOWS_JSON))
    
    print("✅ FastAPI server startup complete. Agents and curriculum loaded.")
except Exception as e:
    print(f"❌ FastAPI server startup failed: {e}")
    db_profile = None
    assessment_agent = None
    all_concepts_data = []

# --- API Request/Response Models ---

# Standard Request/Response Models (Simplified)
class StudentRequest(BaseModel):
    student_name: str = Field(..., example="Kartick_Test_Student")

class LessonOrderRequest(StudentRequest):
    lesson_order: Optional[int] = Field(None, description="Optional override to jump to a specific lesson.")

class QuizSubmission(BaseModel):
    # This composite model represents the client's submission for the 8 questions
    mcq_answers: List[Dict[str, Any]] = Field(..., description="List of submitted MCQ answers with question/answer keys.")
    open_questions: List[Dict[str, Any]] = Field(..., description="List of submitted open answers with question/answer text.")

class SubmitDiagnosticRequest(StudentRequest):
    lesson_order: int
    submissions: QuizSubmission
    skip_mode: bool = False # Flag for when student opts to skip after passing

# Teaching Flow Models
class DiagnosticResponse(BaseModel):
    status: str = Field(..., description="E.g., 'diagnostic_required', 'passed_diagnostic', 'start_teaching', 'error'")
    lesson_order: int
    lesson_name: Optional[str] = None
    quiz: Optional[Dict[str, Any]] = None # Contains 'mcq' and 'open_questions' lists
    options: Optional[List[str]] = None
    message: Optional[str] = None
    completed_lessons: Optional[List[int]] = None # For dashboard display

class FinalQuizRequest(SubmitDiagnosticRequest):
    pass # Reuses structure: lesson_order + submissions

class FinalQuizResponse(BaseModel):
    status: str
    score: float
    next_lesson_order: int
    message: str
    grading_details: Optional[Dict[str, Any]] = None

class TeachingStepRequest(StudentRequest):
    lesson_order: int
    concept_name: str # The sub_concept currently being taught

class MasteryDashboardResponse(BaseModel):
    student_name: str
    dashboard_data: List[Dict[str, Any]]
    
class PracticeQuizRequest(StudentRequest):
    hl_concept_name: str
    difficulty: str = "medium"

# --- API Endpoints ---

@app.post("/register_student", response_model=StudentRequest)
def register_student_endpoint(request: StudentRequest):
    """Registers a new student and initializes their progress (Lesson 1)."""
    try:
        db_profile.register_student(request.student_name)
        return {"student_name": request.student_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register student: {e}")

# --- NEW SEQUENTIAL FLOW ENDPOINTS ---

@app.post("/program/start", response_model=DiagnosticResponse)
def start_program_endpoint(request: LessonOrderRequest):
    """
    1. Loads student progress.
    2. Identifies the current lesson.
    3. Runs the diagnostic quiz for that lesson.
    """
    service = TeachingLoopService(request.student_name)
    try:
        result = service.start_program(request.lesson_order)
        return DiagnosticResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting program: {e}")


@app.post("/program/submit_diagnostic", response_model=DiagnosticResponse)
def submit_diagnostic_endpoint(request: SubmitDiagnosticRequest):
    """
    2. Grades diagnostic (MCQ + Open).
    3. If pass (>= 0.75): Returns options (Skip/Study).
    4. If fail (< 0.75): Returns status to begin structured teaching.
    """
    service = TeachingLoopService(request.student_name)
    try:
        result = service.submit_diagnostic(
            lesson_order=request.lesson_order,
            quiz_submissions=request.submissions.model_dump(),
            skip_mode=request.skip_mode
        )
        return DiagnosticResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting diagnostic: {e}")

# NOTE: This endpoint is called repeatedly by the client for each sub_concept/step
@app.post("/program/teach_step_stream")
def teach_step_stream_endpoint(request: TeachingStepRequest):
    """
    Streams the educational content for a sub_concept using the fixed template/workflow.
    (Replaces the old /teach_step_stream)
    """
    service = TeachingLoopService(request.student_name)
    try:
        # The service handles checking the curriculum structure and choosing the correct prompt
        return service.teach_step_stream(request.lesson_order, request.concept_name)
    except Exception as e:
        def error_gen(): yield json.dumps({"error": f"LLM teaching failed: {e}"})
        return StreamingResponse(error_gen(), media_type="text/plain")


@app.post("/program/finish_quiz", response_model=FinalQuizResponse)
def finish_lesson_quiz_endpoint(request: FinalQuizRequest):
    """
    4. Grades the final quiz after studying.
    5. If pass (>= 0.75): Updates mastery, marks lesson complete, moves to next lesson.
    6. If fail (< 0.75): Updates mastery (low alpha), keeps student at current lesson.
    """
    service = TeachingLoopService(request.student_name)
    try:
        result = service.finish_lesson_quiz(
            lesson_order=request.lesson_order,
            quiz_submissions=request.submissions.model_dump()
        )
        return FinalQuizResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error finishing lesson quiz: {e}")

# --- DASHBOARD & PRACTICE MODE ENDPOINTS ---

@app.post("/dashboard/mastery", response_model=MasteryDashboardResponse)
def get_mastery_dashboard(request: StudentRequest):
    """Retrieves mastery data organized by high-level concept for the dashboard view."""
    service = TeachingLoopService(request.student_name)
    try:
        data = service.get_mastery_dashboard_data()
        return MasteryDashboardResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving dashboard data: {e}")

@app.post("/practice/generate_quiz")
def generate_practice_quiz_endpoint(request: PracticeQuizRequest):
    """Generates a 10-MCQ practice quiz (no state change)."""
    service = TeachingLoopService(request.student_name)
    try:
        quiz_data = service.generate_practice_quiz(request.hl_concept_name, request.difficulty)
        return quiz_data # Returns JSON containing the list of 10 MCQs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating practice quiz: {e}")

@app.post("/practice/submit_score")
def submit_practice_quiz_score_endpoint(request: PracticeQuizRequest, score: float):
    """Updates mastery slightly after a practice attempt (low alpha)."""
    service = TeachingLoopService(request.student_name)
    try:
        result = service.submit_practice_quiz_score(request.hl_concept_name, score, request.difficulty)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting practice score: {e}")

# The critical code block you needed to add:
if __name__ == "__main__":
    import uvicorn
    import os
    
    # This reads the environment variable set by Cloud Run!
    port = int(os.getenv("PORT", 8000)) 
    
    # When executed directly, it starts the server on the REQUIRED host/port
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)


# --- DEPRECATED ENDPOINTS (Kept for reference if client needs backward compatibility) ---

# @app.post("/get_next_step", ...) - DEPRECATED in favor of /program/start
# @app.post("/submit_answer", ...) - DEPRECATED (individual open-answer grading replaced by composite grading in /program/submit_diagnostic)
# @app.post("/start_assessment", ...) - DEPRECATED (replaced by composite quiz generation in /program/start)

# ... (End of main.py) ...