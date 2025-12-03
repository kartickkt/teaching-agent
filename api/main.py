# api/main.py

import os
import sys
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from fastapi.responses import StreamingResponse

# Setup Path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, '..', 'src'))
if src_dir not in sys.path: sys.path.append(src_dir)

from src.student_profiles import StudentProfile, init_db_pool # <--- Import init_db_pool
from src.student_teaching_loop import TeachingLoopService
from src.student_profiles import CurriculumManager # for helper endpoint

logger = logging.getLogger("uvicorn")
app = FastAPI(title="Async Teaching Agent API")

# ----------------------------------------
# Startup Event: Initialize DB Pool
# ----------------------------------------
@app.on_event("startup")
def startup_event():
    init_db_pool() # <--- Crucial for performance

# ----------------------------------------
# Models (Simplified for copy-paste)
# ----------------------------------------
class StudentRequest(BaseModel):
    student_name: str

class LessonOrderRequest(StudentRequest):
    lesson_order: Optional[int] = None

class SubmitDiagnosticRequest(StudentRequest):
    lesson_order: int
    submissions: Dict[str, Any]
    skip_mode: bool = False

class FinalQuizRequest(StudentRequest):
    lesson_order: int
    submissions: Dict[str, Any]

class TeachingStepRequest(StudentRequest):
    lesson_order: int
    concept_name: str

class PracticeQuizRequest(StudentRequest):
    hl_concept_name: str
    difficulty: str = "medium"

class PracticeSubmitRequest(PracticeQuizRequest):
    score: float

# ----------------------------------------
# Endpoints
# ----------------------------------------
@app.get("/healthz")
def healthz(): return {"status": "ok"}

@app.post("/register_student")
def register_student(req: StudentRequest):
    StudentProfile().register_student(req.student_name)
    return {"status": "registered"}

@app.get("/curriculum/high_level")
def list_hl():
    return {"high_level_concepts": list(CurriculumManager.get_high_level_concepts().keys())}

# Sync Endpoint (Program Start)
@app.post("/program/start")
def start_program(req: LessonOrderRequest):
    service = TeachingLoopService(req.student_name)
    return service.start_program(req.lesson_order)

# ASYNC Endpoint (Grading)
@app.post("/program/submit_diagnostic")
async def submit_diagnostic(req: SubmitDiagnosticRequest):
    service = TeachingLoopService(req.student_name)
    # AWAIT the async method
    return await service.submit_diagnostic_async(req.lesson_order, req.submissions, req.skip_mode)

# ASYNC Endpoint (Final Grading)
@app.post("/program/finish_quiz")
async def finish_quiz(req: FinalQuizRequest):
    service = TeachingLoopService(req.student_name)
    # AWAIT the async method
    return await service.finish_lesson_quiz_async(req.lesson_order, req.submissions)

@app.post("/program/teach_step_stream")
def teach_stream(req: TeachingStepRequest):
    service = TeachingLoopService(req.student_name)
    return service.teach_step_stream(req.lesson_order, req.concept_name)

@app.post("/dashboard/mastery")
def get_dashboard(req: StudentRequest):
    service = TeachingLoopService(req.student_name)
    return service.get_mastery_dashboard_data()

@app.post("/practice/generate_quiz")
def practice_gen(req: PracticeQuizRequest):
    service = TeachingLoopService(req.student_name)
    return service.generate_practice_quiz(req.hl_concept_name, req.difficulty)

@app.post("/practice/submit_score")
def practice_sub(req: PracticeSubmitRequest):
    service = TeachingLoopService(req.student_name)
    service.submit_practice_quiz_score(req.hl_concept_name, req.score, req.difficulty)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)