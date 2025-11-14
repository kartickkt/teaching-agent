# api/main.py
"""
FastAPI application to serve the teaching agent logic.
Handles student state, calculates next steps, and generates content via LLM.
"""
import os
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from fastapi.responses import StreamingResponse
from openai import OpenAI

# Initialize streaming OpenAI client
stream_client = OpenAI()


# --- Add src to Python Path ---
# This allows us to import modules from the 'src' directory
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, '..', 'src'))
if src_dir not in sys.path:
    sys.path.append(src_dir)
# -------------------------------

try:
    # Now we can import from 'src'
    from student_profiles import StudentProfile, CurriculumManager
    from student_assessment import AssessmentAgent
    from student_teaching_loop import flatten_sub_concepts, load_concepts, WORKFLOWS_JSON
except ImportError as e:
    print(f"Error: Failed to import src modules: {e}")
    print("Please ensure __init__.py exists in src/ and all dependencies are installed.")
    sys.exit(1)

# --- FastAPI App & Global Agents ---
app = FastAPI(
    title="Adaptive Teaching Agent API",
    description="Manages student mastery and delivers personalized learning paths.",
)

# Initialize global, singleton instances
# These are thread-safe and persist for the life of the server
try:
    db_profile = StudentProfile()
    assessment_agent = AssessmentAgent()
    # Load and flatten the curriculum once on startup
    all_concepts_data = flatten_sub_concepts(load_concepts(WORKFLOWS_JSON))
    all_concept_names = [c['name'] for c in all_concepts_data]
    
    # Store concept lookup dictionary for easy structure access (V4)
    concept_lookup = {c['name']: c for c in all_concepts_data}
    
    print("✅ FastAPI server startup complete. Agents and curriculum loaded.")
except Exception as e:
    print(f"❌ FastAPI server startup failed: {e}")
    db_profile = None
    assessment_agent = None
    all_concepts_data = []
    all_concept_names = []
    concept_lookup = {}

# --- Difficulty Multipliers for Mastery Update ---
DIFFICULTY_WEIGHTS = {
    "easy": 0.8,
    "medium": 1.0,
    "hard": 1.2
}
# -------------------------------------------------

# --- Helper Class: Mastery Cache Proxy ---
class TempProfileProxy:
    """
    A temporary, cached proxy of the student's profile for the AssessmentAgent.
    This solves the N+1 query problem by pre-fetching all mastery data.
    """
    def __init__(self, student_name: str):
        if not db_profile:
             raise HTTPException(status_code=500, detail="Database profile not initialized")
        # 1. Fetch all mastery data ONCE from the DB
        self._mastery_cache = db_profile.get_all_mastery(student_name)
        print(f"  (Loaded {len(self._mastery_cache)} mastery records for agent proxy)")

    def get_mastery(self, concept_name: str) -> float:
        # 2. Agent reads from the fast, in-memory cache
        return self._mastery_cache.get(concept_name, 0.0)

# --- API Request/Response Models ---
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

# --- NEW Models for V3 Real Assessment ---
class QuizRequest(BaseModel):
    student_name: str
    concept_name: str
    difficulty: str = Field("medium", example="hard") # NEW FIELD

class QuizResponse(BaseModel):
    concept_name: str
    questions: List[str]

class AnswerRequest(BaseModel):
    student_name: str
    concept_name: str
    question: str
    user_answer: str
    difficulty: str = Field("medium", example="hard") # NEW FIELD

class GradingResponse(BaseModel):
    concept_name: str
    score: float
    feedback: str
    new_mastery: float # Return the updated mastery

# --- API Endpoints ---

@app.on_event("startup")
async def startup_event():
    if db_profile is None or assessment_agent is None:
        raise RuntimeError("Server failed to initialize agents. Check DB connection and curriculum file.")
    print("Application startup... checking DB connection.")
    try:
        # Perform a simple check to ensure DB is reachable
        db_profile.register_student("startup_test_user")
        print("Database connection verified.")
    except Exception as e:
        print(f"FATAL: Database connection check failed on startup: {e}")
        # In a real-world scenario, you might want the app to fail fast
        # or enter a degraded state.

@app.post("/register_student", response_model=StudentRequest)
def register_student(request: StudentRequest):
    """Registers a new student in the database."""
    try:
        db_profile.register_student(request.student_name)
        return {"student_name": request.student_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register student: {e}")

@app.post("/get_next_step", response_model=StepResponse)
def get_next_step(request: StudentRequest):
    """
    The core "adaptive" endpoint.
    Calculates the next best concept for the student to learn.
    """
    student_name = request.student_name
    
    # 1. Create the fast, cached proxy for the agent
    profile_proxy = TempProfileProxy(student_name)
    
    # 2. Get the agent's decision
    next_concept_name = assessment_agent.get_next_concept(profile_proxy)
    
    if next_concept_name is None:
        return StepResponse(
            student_name=student_name,
            concept_name="N/A",
            message="Curriculum complete! No more concepts to teach."
        )

    # 3. Find the full data (including workflows) for this concept
    concept_data = concept_lookup.get(next_concept_name)
    
    if not concept_data:
        raise HTTPException(status_code=404, detail=f"Concept data for '{next_concept_name}' not found.")

    # 4. Check if we have a structured, step-by-step lesson plan
    
    # Use the structure helper endpoint (logic is consolidated there now)
    return _create_step_response_from_concept_data(student_name, next_concept_name, concept_data)


# --- NEW: Helper function to generate structured response ---
def _create_step_response_from_concept_data(student_name: str, concept_name: str, concept_data: Dict[str, Any]) -> StepResponse:
    """Helper to process concept data and determine if it has steps."""
    workflows = concept_data.get("workflows", [])
    if workflows and workflows[0].get("steps"):
        workflow = workflows[0]
        # Sort steps by order for safe teaching sequence
        steps = sorted(workflow["steps"], key=lambda x: x.get("order", 0))
        step_names = [s.get("concept", "Unnamed Step") for s in steps]
        
        return StepResponse(
            student_name=student_name,
            concept_name=concept_name,
            is_structured_lesson=True,
            lesson_steps=step_names,
            message=f"Structured lesson found: {workflow.get('workflow_id', 'N/A')}"
        )
    else:
        # Fallback lesson
        return StepResponse(
            student_name=student_name,
            concept_name=concept_name,
            is_structured_lesson=False,
            lesson_steps=[concept_name],
            message="Fallback lesson: A single explanation will be generated."
        )


@app.post("/teach_step", response_model=ContentResponse)
def teach_step(request: QuizRequest): # Using QuizRequest as it has the fields we need
    """
    Generates the LLM explanation for a *single* concept or step.
    """
    concept_name = request.concept_name
    
    # The agent handles both full concepts and specific steps
    explanation, _ = assessment_agent.generate_content_for_concept(concept_name)
    
    if "LLM generation failed" in explanation:
        raise HTTPException(status_code=503, detail=explanation)
        
    return ContentResponse(concept_name=concept_name, explanation=explanation)

@app.post("/get_mastery_profile", response_model=MasteryProfile)
def get_mastery_profile(request: StudentRequest):
    """Retrieves the full mastery profile for a student."""
    mastery_data = db_profile.get_all_mastery(request.student_name)
    return MasteryProfile(
        student_name=request.student_name,
        mastery_data=mastery_data
    )

@app.get("/get_all_concepts", response_model=ConceptListResponse)
def get_all_concepts():
    """
    New endpoint for the "Explore Curriculum" feature.
    Returns a flat list of all teachable concept names.
    """
    return ConceptListResponse(all_concepts=all_concept_names)

# --- NEW V4 Endpoint: Fetch detailed structure for User-Driven Mode ---
@app.post("/get_concept_structure", response_model=StepResponse)
def get_concept_structure(request: StudentRequest):
    """
    Fetches the full structure (steps) for a user-selected concept.
    """
    concept_name = request.student_name # Abuse the student_name field to pass the concept name
    
    concept_data = concept_lookup.get(concept_name)
    
    if not concept_data:
        raise HTTPException(status_code=404, detail=f"Concept data for '{concept_name}' not found.")

    # Return the full structure, assuming a generic student for structure purposes
    return _create_step_response_from_concept_data("N/A", concept_name, concept_data)

# --- NEW V3 ASSESSMENT ENDPOINTS ---

@app.post("/start_assessment", response_model=QuizResponse)
def start_assessment(request: QuizRequest):
    """
    NEW: Generates a quiz for the given concept and difficulty.
    """
    print(f"API: Received request to start {request.difficulty} assessment for {request.concept_name}")
    # Pass the difficulty parameter to the agent
    quiz_data = assessment_agent.generate_quiz(request.concept_name, request.difficulty)
    if "Failed" in quiz_data["questions"][0]:
        raise HTTPException(status_code=503, detail="LLM failed to generate quiz.")
    
    return QuizResponse(
        concept_name=request.concept_name,
        questions=quiz_data["questions"]
    )

@app.post("/submit_answer", response_model=GradingResponse)
def submit_answer(request: AnswerRequest):
    """
    NEW: Grades a single answer and updates mastery, applying a weight based on difficulty.
    """
    print(f"API: Received answer for {request.concept_name} from {request.student_name}")
    
    # 1. Grade the answer using the LLM
    grading_data = assessment_agent.grade_answer(
        request.concept_name, request.question, request.user_answer
    )
    llm_score = grading_data["score"]
    feedback = grading_data["feedback"]
    
    if "failed" in feedback.lower():
        raise HTTPException(status_code=503, detail="LLM failed to grade answer.")

    # 2. Apply Difficulty Weight to the Score
    weight = DIFFICULTY_WEIGHTS.get(request.difficulty, 1.0)
    
    # The score that will be used in the EMA formula (capped at 1.0)
    mastery_update_score = min(1.0, llm_score * weight) 
    
    # 3. Update the mastery in the database
    try:
        new_mastery = db_profile.update_mastery(
            request.student_name, request.concept_name, mastery_update_score
        )
        print(f"API: Mastery updated for {request.student_name} on {request.concept_name}. New: {new_mastery:.2f}")
        
        return GradingResponse(
            concept_name=request.concept_name,
            # We return the raw LLM score (not the weighted score) for display purposes
            score=llm_score, 
            feedback=feedback,
            new_mastery=new_mastery
        )
    except Exception as e:
        print(f"API Error: Failed to update mastery: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update mastery: {e}")

@app.post("/teach_step_stream")
async def teach_step_stream(request: QuizRequest):
    concept_name = request.concept_name

    def generate():
        stream = stream_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"Explain the concept: {concept_name}"}
            ],
            stream=True
        )
        for chunk in stream:
            token = chunk.choices[0].delta.get("content", "")
            if token:
                yield token
        yield "[END]"

    return StreamingResponse(generate(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI server locally on port 8000...")
    uvicorn.run(app, host="127.0.0.1", port=8000)