# api/main.py
"""
Cleaned FastAPI for Adaptive Teaching Agent.
- Keeps the same public endpoints (no frontend changes required).
- Structured, robust streaming endpoint that yields token chunks.
- Clear logging and safer initialization.
"""
import os
import sys
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# OpenAI client (streaming)
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("teaching-agent-api")

# --- Initialize OpenAI streaming client from env ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found in environment. LLM calls will fail if not set.")
stream_client = OpenAI(api_key=OPENAI_API_KEY)

# --- Add 'src' to path so we can import project modules ---
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, "..", "src"))
if src_dir not in sys.path:
    sys.path.append(src_dir)

try:
    from student_profiles import StudentProfile, CurriculumManager
    from student_assessment import AssessmentAgent
    from student_teaching_loop import flatten_sub_concepts, load_concepts, WORKFLOWS_JSON
except Exception as e:
    logger.exception("Failed to import src modules. Ensure src/__init__.py exists and modules are correct.")
    raise

# --- FastAPI app ---
app = FastAPI(title="Adaptive Teaching Agent API", description="Deliver personalized lessons and streaming explanations")

# --- Initialize global agents and data structures ---
try:
    db_profile = StudentProfile()
    assessment_agent = AssessmentAgent()
    all_concepts_data = flatten_sub_concepts(load_concepts(WORKFLOWS_JSON))
    all_concept_names = [c["name"] for c in all_concepts_data]
    concept_lookup = {c["name"]: c for c in all_concepts_data}
    logger.info("Agents and curriculum loaded successfully.")
except Exception as e:
    logger.exception("Initialization failed: %s", e)
    # keep variables defined to avoid NameError elsewhere
    db_profile = None
    assessment_agent = None
    all_concepts_data = []
    all_concept_names = []
    concept_lookup = {}

# Difficulty weights
DIFFICULTY_WEIGHTS = {"easy": 0.8, "medium": 1.0, "hard": 1.2}


# --- Utilities & helper classes ---
class TempProfileProxy:
    """Cached mastery proxy to avoid N+1 DB access in the agent decision step."""
    def __init__(self, student_name: str):
        if db_profile is None:
            raise HTTPException(status_code=500, detail="Database profile not initialized")
        self._mastery_cache = db_profile.get_all_mastery(student_name)
        logger.info("Loaded %d mastery entries for %s", len(self._mastery_cache), student_name)

    def get_mastery(self, concept_name: str) -> float:
        return self._mastery_cache.get(concept_name, 0.0)


# --- Request/Response models (kept same as before for compatibility) ---
class StudentRequest(BaseModel):
    student_name: str = Field(..., example="Kartick_Test_Student")

class StepResponse(BaseModel):
    student_name: str
    concept_name: str
    is_structured_lesson: bool = False
    lesson_steps: Optional[List[str]] = None
    message: str

class ContentResponse(BaseModel):
    concept_name: str
    explanation: str

class MasteryProfile(BaseModel):
    student_name: str
    mastery_data: Dict[str, float]

class ConceptListResponse(BaseModel):
    all_concepts: List[str]

class QuizRequest(BaseModel):
    student_name: str
    concept_name: str
    difficulty: str = Field("medium", example="hard")

class QuizResponse(BaseModel):
    concept_name: str
    questions: List[str]

class AnswerRequest(BaseModel):
    student_name: str
    concept_name: str
    question: str
    user_answer: str
    difficulty: str = Field("medium", example="hard")

class GradingResponse(BaseModel):
    concept_name: str
    score: float
    feedback: str
    new_mastery: float


# --- Startup check ---
@app.on_event("startup")
async def startup_event():
    if db_profile is None or assessment_agent is None:
        logger.error("Server failed to initialize core components.")
        raise RuntimeError("Server components not initialized. Check logs.")
    try:
        db_profile.register_student("startup_test_user")
        logger.info("DB check OK.")
    except Exception as e:
        logger.exception("Database check failed on startup: %s", e)


# --- Endpoints (kept same signatures) ---
@app.post("/register_student", response_model=StudentRequest)
def register_student(request: StudentRequest):
    try:
        db_profile.register_student(request.student_name)
        return {"student_name": request.student_name}
    except Exception as e:
        logger.exception("register_student failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/get_next_step", response_model=StepResponse)
def get_next_step(request: StudentRequest):
    student_name = request.student_name
    proxy = TempProfileProxy(student_name)
    next_concept_name = assessment_agent.get_next_concept(proxy)
    if next_concept_name is None:
        return StepResponse(student_name=student_name, concept_name="N/A", message="Curriculum complete! No more concepts to teach.")
    concept_data = concept_lookup.get(next_concept_name)
    if not concept_data:
        raise HTTPException(status_code=404, detail=f"Concept '{next_concept_name}' not found.")
    return _create_step_response_from_concept_data(student_name, next_concept_name, concept_data)


def _create_step_response_from_concept_data(student_name: str, concept_name: str, concept_data: Dict[str, Any]) -> StepResponse:
    workflows = concept_data.get("workflows", [])
    if workflows and workflows[0].get("steps"):
        workflow = workflows[0]
        steps = sorted(workflow["steps"], key=lambda x: x.get("order", 0))
        step_names = [s.get("concept", "Unnamed Step") for s in steps]
        return StepResponse(student_name=student_name, concept_name=concept_name, is_structured_lesson=True, lesson_steps=step_names, message=f"Structured lesson: {workflow.get('workflow_id','N/A')}")
    return StepResponse(student_name=student_name, concept_name=concept_name, is_structured_lesson=False, lesson_steps=[concept_name], message="Fallback lesson: single explanation")


@app.post("/teach_step", response_model=ContentResponse)
def teach_step(request: QuizRequest):
    concept_name = request.concept_name
    explanation, _ = assessment_agent.generate_content_for_concept(concept_name)
    if "LLM generation failed" in explanation:
        raise HTTPException(status_code=503, detail=explanation)
    return ContentResponse(concept_name=concept_name, explanation=explanation)


@app.post("/get_mastery_profile", response_model=MasteryProfile)
def get_mastery_profile(request: StudentRequest):
    mastery_data = db_profile.get_all_mastery(request.student_name)
    return MasteryProfile(student_name=request.student_name, mastery_data=mastery_data)


@app.get("/get_all_concepts", response_model=ConceptListResponse)
def get_all_concepts():
    return ConceptListResponse(all_concepts=all_concept_names)


@app.post("/get_concept_structure", response_model=StepResponse)
def get_concept_structure(request: StudentRequest):
    concept_name = request.student_name
    concept_data = concept_lookup.get(concept_name)
    if not concept_data:
        raise HTTPException(status_code=404, detail=f"Concept '{concept_name}' not found.")
    return _create_step_response_from_concept_data("N/A", concept_name, concept_data)


@app.post("/start_assessment", response_model=QuizResponse)
def start_assessment(request: QuizRequest):
    logger.info("Start assessment: %s %s", request.concept_name, request.difficulty)
    quiz_data = assessment_agent.generate_quiz(request.concept_name, request.difficulty)
    if not quiz_data or "questions" not in quiz_data:
        raise HTTPException(status_code=503, detail="LLM failed to generate quiz.")
    return QuizResponse(concept_name=request.concept_name, questions=quiz_data["questions"])


@app.post("/submit_answer", response_model=GradingResponse)
def submit_answer(request: AnswerRequest):
    logger.info("Received answer for %s from %s", request.concept_name, request.student_name)
    grading_data = assessment_agent.grade_answer(request.concept_name, request.question, request.user_answer)
    llm_score = grading_data.get("score", 0.0)
    feedback = grading_data.get("feedback", "")
    if "failed" in feedback.lower():
        raise HTTPException(status_code=503, detail="LLM grading failed.")
    weight = DIFFICULTY_WEIGHTS.get(request.difficulty, 1.0)
    mastery_update_score = min(1.0, llm_score * weight)
    try:
        new_mastery = db_profile.update_mastery(request.student_name, request.concept_name, mastery_update_score)
        return GradingResponse(concept_name=request.concept_name, score=llm_score, feedback=feedback, new_mastery=new_mastery)
    except Exception as e:
        logger.exception("Failed to update mastery")
        raise HTTPException(status_code=500, detail=str(e))


# --- Streaming endpoint: yields incremental chunks from LLM ---
@app.post("/teach_step_stream")
async def teach_step_stream(request: QuizRequest):
    concept_name = request.concept_name

    def generate():
        """
        Generator that iterates the OpenAI streaming iterator and yields textual chunks.
        We instruct the LLM to produce short paragraphs / bullets to improve readability
        when streamed to the client.
        """
        # Prompt encourages short paragraphs and bullet points (helps readability)
        user_prompt = (
            f"Explain **{concept_name}** for a university student. "
            "Return the explanation in short paragraphs (1-3 sentences each), "
            "use bullets for lists, and include blank lines between paragraphs. "
            "Keep language simple and beginner-friendly. Do NOT return a single long paragraph."
        )

        try:
            stream = stream_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": user_prompt}],
                stream=True
            )
        except Exception as e:
            logger.exception("OpenAI streaming request failed: %s", e)
            yield f"Error: LLM streaming request failed: {e}"
            return

        # Iterate over stream chunks and yield incremental text
        try:
            for chunk in stream:
                # chunk.choices[0].delta may contain 'content' as incremental content
                # Safely extract text
                try:
                    delta = chunk.choices[0].delta
                    token = ""
                    # 'delta' may be dict-like depending on SDK; use .get if possible
                    if isinstance(delta, dict):
                        token = delta.get("content", "") or delta.get("text", "")
                    else:
                        # attempt attribute access
                        token = getattr(delta, "content", "") or getattr(delta, "text", "")
                except Exception:
                    token = ""

                if token:
                    yield token
        except Exception as e:
            logger.exception("Error while iterating LLM stream: %s", e)
            yield f"\n\n[STREAM ERROR] {e}\n"
            return

        # final marker (optional)
        yield "\n\n[END]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


# --- Local run ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting local server on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
