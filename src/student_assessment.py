# src/student_assessment.py
import os
import time
import json
import re
from typing import Optional, Dict, Any, Generator, List
from dotenv import load_dotenv

load_dotenv()

# Configuration
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
MAX_RETRIES = int(os.getenv("ASSESSMENT_MAX_RETRIES", "4"))
BASE_RETRY_DELAY = float(os.getenv("ASSESSMENT_BASE_RETRY_DELAY", "1.0"))

# ------------------------------
# Clients (Sync & Async)
# ------------------------------
_openai_client = None
_async_client = None

def get_openai_client():
    global _openai_client
    if _openai_client: return _openai_client
    if not OPENAI_KEY: return None
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_KEY)
        return _openai_client
    except: return None

def get_async_client():
    global _async_client
    if _async_client: return _async_client
    if not OPENAI_KEY: return None
    try:
        from openai import AsyncOpenAI
        _async_client = AsyncOpenAI(api_key=OPENAI_KEY)
        return _async_client
    except: return None

# ------------------------------
# JSON Parsers (Unchanged)
# ------------------------------
def _try_parse_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text or not isinstance(text, str): return None
    match = re.search(r"\{(?:.|\n)*\}", text)
    if not match: return None
    candidate = match.group(0)
    try: return json.loads(candidate)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*}", "}", candidate)
        cleaned = re.sub(r",\s*\]", "]", cleaned)
        try: return json.loads(cleaned)
        except: return None

# ------------------------------
# Prompts
# ------------------------------
DIAGNOSTIC_PROMPT = """You are an assessment generator. Produce EXACT JSON with these keys:
{{
  "mcq": [ {{ "id": "m1", "question": "text", "options": ["A","B","C","D"], "answer_index": 0 }} ],
  "open_questions": [ {{ "id": "o1", "question": "text" }} ]
}}
Generate {num_mcq} MCQs and {num_open} open questions for: "{concept_name}".
"""

GRADING_PROMPT = """You are a concise grader. Given:
Concept: "{concept_name}"
Question: "{question}"
Student answer: "{student_answer}"

Return ONLY valid JSON:
{{ "score": 0.0, "feedback": "short, constructive feedback" }}
Score must be between 0.0 and 1.0
"""

TEACHING_PROMPT_SYSTEM = "You are a friendly expert tutor. Provide clear, well-structured markdown explanations."

# ------------------------------
# Helpers
# ------------------------------
def _ensure_quiz_shape(parsed: Any, concept_name: str, num_mcq: int, num_open: int) -> Dict[str, Any]:
    if not isinstance(parsed, dict): return _fallback_quiz_static(concept_name, num_mcq, num_open)
    mcq = parsed.get("mcq") or parsed.get("mcqs") or []
    open_q = parsed.get("open_questions") or parsed.get("opens") or []
    
    # Normalize MCQs
    normalized_mcq = []
    for i, m in enumerate(mcq if isinstance(mcq, list) else []):
        if not isinstance(m, dict): continue
        opts = m.get("options") or ["A","B","C","D"]
        normalized_mcq.append({
            "id": m.get("id", f"m{i}"),
            "question": m.get("question", "Question?"),
            "options": opts,
            "answer_index": m.get("answer_index", 0),
            "answer": m.get("answer", opts[0])
        })
    return {"mcq": normalized_mcq, "open_questions": open_q if isinstance(open_q, list) else []}

def _fallback_quiz_static(concept_name: str, num_mcq: int, num_open: int) -> Dict[str, Any]:
    return {
        "mcq": [{"id": f"m{i}", "question": f"Fallback Q{i} about {concept_name}", "options": ["A","B"], "answer_index":0, "answer":"A"} for i in range(num_mcq)],
        "open_questions": [{"id": f"o{i}", "question": f"Explain {concept_name} part {i}"} for i in range(num_open)]
    }

# ------------------------------
# Agent Class
# ------------------------------
class AssessmentAgent:
    def __init__(self):
        self.model = LLM_MODEL

    # Sync Quiz Generation (Kept sync as it is 1 call)
    def generate_diagnostic_quiz(self, concept_name: str, num_mcq=5, num_open=3) -> Dict[str, Any]:
        client = get_openai_client()
        if not client: return _fallback_quiz_static(concept_name, num_mcq, num_open)
        
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": DIAGNOSTIC_PROMPT.format(num_mcq=num_mcq, num_open=num_open, concept_name=concept_name)}],
                temperature=0.3,
                max_tokens=800
            )
            parsed = _try_parse_json(resp.choices[0].message.content)
            return _ensure_quiz_shape(parsed, concept_name, num_mcq, num_open)
        except Exception as e:
            print(f"Quiz Gen Error: {e}")
            return _fallback_quiz_static(concept_name, num_mcq, num_open)

    # NEW: Async Grading
    async def grade_answer_async(self, concept_name: str, question: str, student_answer: str) -> Dict[str, Any]:
        client = get_async_client()
        # Fallback if no key or client failure
        if not client:
            return {"score": 0.5, "feedback": "Fallback (No API Key)"}

        prompt = GRADING_PROMPT.format(concept_name=concept_name, question=question, student_answer=student_answer)
        try:
            resp = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=200
            )
            parsed = _try_parse_json(resp.choices[0].message.content)
            if parsed and "score" in parsed:
                return {"score": float(parsed["score"]), "feedback": parsed.get("feedback", "")}
        except Exception as e:
            print(f"Async Grading Error: {e}")
        
        return {"score": 0.0, "feedback": "Grading failed."}

    # Streaming (Sync generator)
    def generate_streaming_content(self, high_level: str, concept_name: str, fixed_flow=None) -> Generator[str, None, None]:
        client = get_openai_client()
        if not client:
            yield f"## {concept_name}\n\n(Fallback) No API Key."
            return

        user_msg = f"Explain {concept_name} (context: {high_level}) in clear markdown."
        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": TEACHING_PROMPT_SYSTEM}, {"role": "user", "content": user_msg}],
                temperature=0.6,
                stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"Stream Error: {e}"

# Functional Wrappers
def generate_diagnostic_quiz(concept_name, num_mcq=5, num_open=3):
    return AssessmentAgent().generate_diagnostic_quiz(concept_name, num_mcq, num_open)

def generate_streaming_content(high_level, concept_name, fixed_flow=None):
    return AssessmentAgent().generate_streaming_content(high_level, concept_name, fixed_flow)

# Export async wrapper
async def grade_answer_async(concept_name, question, student_answer):
    return await AssessmentAgent().grade_answer_async(concept_name, question, student_answer)