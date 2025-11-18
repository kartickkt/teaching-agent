# src/student_assessment.py
"""
LLM-based quiz generation, grading, and teaching content streaming.

Features:
- Lazy OpenAI client initialization using `openai.OpenAI`
- Robust JSON extraction from LLM outputs with fallbacks
- Deterministic fallback content when the LLM or API key is unavailable
- Defensive normalization so generate_diagnostic_quiz ALWAYS returns
  {"mcq": [...], "open_questions": [...]}
"""

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

# Lazy client holder
_openai_client = None

def _init_openai_client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not OPENAI_KEY:
        print("Warning: OPENAI_API_KEY not set; falling back to deterministic responses.")
        _openai_client = None
        return None
    try:
        from openai import OpenAI
    except Exception as e:
        print("OpenAI SDK not available:", e)
        _openai_client = None
        return None
    try:
        _openai_client = OpenAI(api_key=OPENAI_KEY)
        return _openai_client
    except Exception as e:
        print("Failed to initialize OpenAI client:", e)
        _openai_client = None
        return None

def get_openai_client():
    return _init_openai_client()

# ------------------------------
# Robust JSON extraction
# ------------------------------
def _try_parse_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Extract the outermost JSON object from text. Returns dict or None."""
    if not text or not isinstance(text, str):
        return None
    # Find the largest {...} block (greedy)
    match = re.search(r"\{(?:.|\n)*\}", text)
    if not match:
        return None
    candidate = match.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # attempt to clean trailing commas etc.
        cleaned = re.sub(r",\s*}", "}", candidate)
        cleaned = re.sub(r",\s*\]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None

# ------------------------------
# Prompt templates (escaped braces)
# ------------------------------
DIAGNOSTIC_PROMPT = """You are an assessment generator. Produce EXACT JSON with these keys:
{{
  "mcq": [
    {{
      "id": "m1",
      "question": "text",
      "options": ["A","B","C","D"],
      "answer_index": 0
    }}
    ...
  ],
  "open_questions": [
    {{
      "id": "o1",
      "question": "text"
    }}
    ...
  ]
}}
Generate {num_mcq} MCQs and {num_open} open questions for: "{concept_name}".
Return ONLY the JSON object.
"""

GRADING_PROMPT = """You are a concise grader. Given:
Concept: "{concept_name}"
Question: "{question}"
Student answer: "{student_answer}"

Return ONLY valid JSON:
{{ "score": 0.0, "feedback": "short, constructive feedback" }}
Score must be between 0.0 and 1.0
"""

TEACHING_PROMPT_USER = "Explain the concept '{concept_name}' (high level: {high_level}) in short structured Markdown."
TEACHING_PROMPT_SYSTEM = "You are a friendly expert tutor. Provide clear, well-structured markdown explanations."

# ------------------------------
# Helpers
# ------------------------------
def _ensure_quiz_shape(parsed: Any, concept_name: str, num_mcq: int, num_open: int) -> Dict[str, Any]:
    """
    Ensure the quiz dict has canonical shape:
      {"mcq": [...], "open_questions": [...]}
    If shape is invalid, return fallback quiz.
    """
    if not isinstance(parsed, dict):
        return _fallback_quiz_static(concept_name, num_mcq, num_open)
    mcq = parsed.get("mcq") or parsed.get("mcqs") or parsed.get("questions") or []
    open_q = parsed.get("open_questions") or parsed.get("opens") or []
    if not isinstance(mcq, list):
        mcq = []
    if not isinstance(open_q, list):
        open_q = []
    # Ensure each mcq is dict and has minimal fields
    normalized = []
    for i, m in enumerate(mcq):
        if not isinstance(m, dict):
            normalized.append({
                "id": f"m{i+1}",
                "question": str(m),
                "options": ["A","B","C","D"],
                "answer_index": 0,
                "answer": "A"
            })
            continue
        opts = m.get("options") or m.get("choices") or ["A","B","C","D"]
        if not isinstance(opts, list):
            opts = ["A","B","C","D"]
        ans_idx = m.get("answer_index")
        ans_text = m.get("answer")
        if isinstance(ans_idx, int) and 0 <= ans_idx < len(opts):
            ans_text = opts[ans_idx]
        elif isinstance(ans_text, int) and 0 <= int(ans_text) < len(opts):
            ans_idx = int(ans_text)
            ans_text = opts[ans_idx]
        normalized.append({
            "id": m.get("id", f"m{i+1}"),
            "question": m.get("question", m.get("text", "")),
            "options": opts,
            "answer_index": ans_idx if isinstance(ans_idx, int) else 0,
            "answer": ans_text if isinstance(ans_text, str) else (opts[0] if opts else "A")
        })
    return {"mcq": normalized, "open_questions": open_q}

def _fallback_quiz_static(concept_name: str, num_mcq: int, num_open: int) -> Dict[str, Any]:
    mcq = []
    for i in range(num_mcq):
        mcq.append({
            "id": f"m{i+1}",
            "question": f"(Fallback) What is important about {concept_name}? ({i+1})",
            "options": ["A", "B", "C", "D"],
            "answer_index": 0,
            "answer": "A"
        })
    open_q = []
    for i in range(num_open):
        open_q.append({
            "id": f"o{i+1}",
            "question": f"(Fallback) Briefly explain: {concept_name} ({i+1})"
        })
    return {"mcq": mcq, "open_questions": open_q}

# ------------------------------
# AssessmentAgent class (legacy / OO)
# ------------------------------
class AssessmentAgent:
    def __init__(self):
        # don't create client here; use get_openai_client lazily
        self.model = LLM_MODEL

    # Diagnostic quiz generation (returns dict with keys 'mcq' and 'open_questions')
    def generate_diagnostic_quiz(self, concept_name: str, num_mcq: int = 5, num_open: int = 3, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
        client = get_openai_client()
        prompt = DIAGNOSTIC_PROMPT.format(num_mcq=num_mcq, num_open=num_open, concept_name=concept_name)

        if client is None:
            return _fallback_quiz_static(concept_name, num_mcq, num_open)

        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Return only JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=800,
                )
                # SDK shape: resp.choices[0].message.content or resp.choices[0].text
                raw = ""
                try:
                    raw = resp.choices[0].message.content
                except Exception:
                    raw = getattr(resp.choices[0], "text", "")
                parsed = _try_parse_json(raw)
                if parsed:
                    parsed = _ensure_quiz_shape(parsed, concept_name, num_mcq, num_open)
                    return parsed
            except Exception as e:
                print(f"Diagnostic generation attempt {attempt+1} error:", e)
            time.sleep(BASE_RETRY_DELAY * (2 ** attempt))
        return _fallback_quiz_static(concept_name, num_mcq, num_open)

    def _fallback_quiz(self, concept_name: str, num_mcq: int, num_open: int) -> Dict[str, Any]:
        return _fallback_quiz_static(concept_name, num_mcq, num_open)

    # Grade a single open answer (returns dict {score: float, feedback: str})
    def grade_answer(self, concept_name: str, question: str, student_answer: str, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
        client = get_openai_client()
        prompt = GRADING_PROMPT.format(concept_name=concept_name, question=question, student_answer=student_answer)

        if client is None:
            # simple heuristic fallback
            score = 0.6 if len(student_answer or "") > 30 else 0.2
            return {"score": float(score), "feedback": "Fallback grading heuristic."}

        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Return only JSON with keys score and feedback."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=200
                )
                raw = ""
                try:
                    raw = resp.choices[0].message.content
                except Exception:
                    raw = getattr(resp.choices[0], "text", "")
                parsed = _try_parse_json(raw)
                if parsed and "score" in parsed:
                    # sanitize
                    parsed_score = parsed.get("score", 0.0)
                    try:
                        parsed_score = float(parsed_score)
                    except Exception:
                        parsed_score = 0.0
                    parsed_score = max(0.0, min(1.0, parsed_score))
                    feedback = parsed.get("feedback", "") or ""
                    return {"score": parsed_score, "feedback": feedback}
            except Exception as e:
                print(f"Grading attempt {attempt+1} error:", e)
            time.sleep(BASE_RETRY_DELAY * (2 ** attempt))

        return {"score": 0.0, "feedback": "LLM grading failed after retries."}

    # Streaming content generation: yields text chunks (string)
    def generate_streaming_content(self, high_level: str, concept_name: str, fixed_flow: Optional[List] = None) -> Generator[str, None, None]:
        client = get_openai_client()

        # If fixed_flow provided, iterate steps and stream each
        if fixed_flow and isinstance(fixed_flow, list):
            for step in fixed_flow:
                step_name = step[0] if isinstance(step, (list, tuple)) and len(step) > 0 else str(step)
                system_msg = TEACHING_PROMPT_SYSTEM
                user_msg = f"Step: {step_name}. Explain {concept_name} (high level: {high_level}) in clear, student-friendly markdown."
                if client is None:
                    yield f"## {step_name} — {concept_name}\n\n(Fallback) Explanation not available.\n\n"
                    continue

                try:
                    stream = client.chat.completions.create(
                        model=self.model,
                        messages=[{"role":"system","content":system_msg},{"role":"user","content":user_msg}],
                        temperature=0.6,
                        stream=True
                    )
                except Exception:
                    # try single-shot
                    try:
                        resp = client.chat.completions.create(
                            model=self.model,
                            messages=[{"role":"system","content":system_msg},{"role":"user","content":user_msg}],
                            temperature=0.6
                        )
                        txt = ""
                        try:
                            txt = resp.choices[0].message.content
                        except Exception:
                            txt = getattr(resp.choices[0], "text", "")
                        yield txt
                        continue
                    except Exception as e:
                        yield f"[STREAM ERROR] {e}"
                        continue

                # stream chunks
                try:
                    for chunk in stream:
                        try:
                            delta = chunk.choices[0].delta
                            if hasattr(delta, "content") and delta.content:
                                yield delta.content
                                continue
                        except Exception:
                            pass
                        try:
                            text = chunk.choices[0].text
                            if text:
                                yield text
                                continue
                        except Exception:
                            continue
                except GeneratorExit:
                    return
                except Exception as e:
                    yield f"\n[STREAM ERROR] {e}\n"
            return

        # Generic single-step streaming
        system_msg = TEACHING_PROMPT_SYSTEM
        user_msg = TEACHING_PROMPT_USER.format(concept_name=concept_name, high_level=high_level)

        if client is None:
            yield f"## {concept_name}\n\n(Fallback) Explanation unavailable (no LLM client).\n"
            return

        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=[{"role":"system","content":system_msg},{"role":"user","content":user_msg}],
                stream=True,
                temperature=0.6
            )
        except Exception:
            # single-shot fallback
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role":"system","content":system_msg},{"role":"user","content":user_msg}],
                    temperature=0.6
                )
                txt = ""
                try:
                    txt = resp.choices[0].message.content
                except Exception:
                    txt = getattr(resp.choices[0], "text", "")
                yield txt
                return
            except Exception as e:
                yield f"[STREAM ERROR] {e}"
                return

        try:
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        yield delta.content
                        continue
                except Exception:
                    pass
                try:
                    txt = chunk.choices[0].text
                    if txt:
                        yield txt
                except Exception:
                    continue
        except GeneratorExit:
            return
        except Exception as e:
            yield f"\n[STREAM ERROR] {e}\n"

# ------------------------------
# Module-level wrappers (functional API)
# ------------------------------
def generate_diagnostic_quiz(concept_name: str, num_mcq: int = 5, num_open: int = 3, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
    agent = AssessmentAgent()
    return agent.generate_diagnostic_quiz(concept_name, num_mcq=num_mcq, num_open=num_open, max_retries=max_retries)

def grade_answer(concept_name: str, question: str, student_answer: str, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
    agent = AssessmentAgent()
    return agent.grade_answer(concept_name, question, student_answer, max_retries=max_retries)

def generate_streaming_content(high_level: str, concept_name: str, fixed_flow: Optional[List] = None) -> Generator[str, None, None]:
    agent = AssessmentAgent()
    return agent.generate_streaming_content(high_level, concept_name, fixed_flow=fixed_flow)
