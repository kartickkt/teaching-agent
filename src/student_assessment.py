"""
LLM-based quiz generation, grading, and streaming explanations.

This version:
- Adds _ensure_quiz_shape() for guaranteed normalization
- Ensures diagnostic quiz always returns {"mcq": [...], "open_questions": [...]}
- Fixes malformed LLM JSON issues
- Cleans MCQ answer/option alignment
"""

import os
import time
import json
import re
from typing import Optional, Dict, Any, Generator, List
from dotenv import load_dotenv

load_dotenv()

# -----------------------
# Config
# -----------------------
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
MAX_RETRIES = int(os.getenv("ASSESSMENT_MAX_RETRIES", "4"))
BASE_RETRY_DELAY = float(os.getenv("ASSESSMENT_BASE_RETRY_DELAY", "1.0"))

_openai_client = None


# -----------------------
# OpenAI initialization
# -----------------------
def _init_openai_client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not OPENAI_KEY:
        print("Warning: No OPENAI_API_KEY; using fallback mode.")
        return None
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_KEY)
        return _openai_client
    except Exception as e:
        print("OpenAI init failed:", e)
        return None


def get_openai_client():
    return _init_openai_client()


# -----------------------
# JSON Extraction
# -----------------------
def _try_parse_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Extract outermost JSON block from text."""
    if not text or not isinstance(text, str):
        return None

    match = re.search(r"\{(?:.|\n)*\}", text)
    if not match:
        return None

    candidate = match.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*}", "}", candidate)
        cleaned = re.sub(r",\s*\]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None


# -----------------------
# Prompts
# -----------------------
DIAGNOSTIC_PROMPT = """You are an assessment generator. Produce ONLY this JSON:
{
  "mcq": [
    {
      "id": "m1",
      "question": "text",
      "options": ["A","B","C","D"],
      "answer_index": 0
    }
  ],
  "open_questions": [
    {
      "id": "o1",
      "question": "text"
    }
  ]
}
Generate exactly {num_mcq} MCQs and {num_open} open questions for: "{concept_name}".
Return only JSON. No extra text.
"""

GRADING_PROMPT = """You are a concise grader. Concept: "{concept_name}"
Question: "{question}"
Student answer: "{student_answer}"

Return ONLY:
{"score": <0-1 float>, "feedback": "short constructive feedback"}"""


TEACHING_PROMPT_SYSTEM = "You are a friendly expert tutor. Use clear markdown."
TEACHING_PROMPT_USER = "Explain '{concept_name}' (high level: {high_level}) clearly."


# -----------------------
# Normalization Helper
# -----------------------
def _ensure_quiz_shape(q: Any,
                       num_mcq_expected: int = 5,
                       num_open_expected: int = 3,
                       concept_name: str = "") -> Dict[str, Any]:

    """Guarantee quiz = {'mcq': [...], 'open_questions': [...]}"""

    # If nothing valid → fallback
    if not isinstance(q, dict):
        return AssessmentAgent()._fallback_quiz(concept_name,
                                                num_mcq_expected,
                                                num_open_expected)

    mcq = q.get("mcq") or q.get("mcqs") or q.get("questions") or []
    open_q = q.get("open_questions") or q.get("opens") or q.get("openQ") or []

    if not isinstance(mcq, list):
        mcq = []
    if not isinstance(open_q, list):
        open_q = []

    norm_mcq = []
    for i, m in enumerate(mcq):
        if not isinstance(m, dict):
            # wrap simple strings as fallback MCQs
            norm_mcq.append({
                "id": f"m{i+1}",
                "question": str(m),
                "options": ["A", "B", "C", "D"],
                "answer_index": 0,
                "answer": "A",
            })
            continue

        opts = m.get("options") or m.get("choices") or []
        if not isinstance(opts, list) or len(opts) == 0:
            opts = ["A", "B", "C", "D"]

        ans_idx = m.get("answer_index")
        ans = m.get("answer")

        # Normalize answer index/text
        if isinstance(ans_idx, int) and 0 <= ans_idx < len(opts):
            ans = opts[ans_idx]
        elif isinstance(ans, int) and 0 <= ans < len(opts):
            ans_idx = ans
            ans = opts[ans_idx]
        elif isinstance(ans, str) and ans in opts:
            ans_idx = opts.index(ans)
        else:
            ans_idx = 0
            ans = opts[0]

        norm_mcq.append({
            "id": m.get("id", f"m{i+1}"),
            "question": m.get("question", m.get("text", "")),
            "options": opts,
            "answer_index": ans_idx,
            "answer": ans,
        })

    return {
        "mcq": norm_mcq,
        "open_questions": open_q
    }


# -----------------------
# AssessmentAgent
# -----------------------
class AssessmentAgent:
    def __init__(self):
        self.model = LLM_MODEL

    # -----------------------
    # Diagnostic Quiz
    # -----------------------
    def generate_diagnostic_quiz(self,
                                 concept_name: str,
                                 num_mcq: int = 5,
                                 num_open: int = 3,
                                 max_retries: int = MAX_RETRIES) -> Dict[str, Any]:

        client = get_openai_client()

        prompt = DIAGNOSTIC_PROMPT.format(
            num_mcq=num_mcq,
            num_open=num_open,
            concept_name=concept_name
        )

        # If no OpenAI → fallback
        if client is None:
            return self._fallback_quiz(concept_name, num_mcq, num_open)

        # Try multiple times
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Return ONLY JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=600,
                )
                raw = ""
                try:
                    raw = resp.choices[0].message.content
                except Exception:
                    raw = getattr(resp.choices[0], "text", "")

                parsed = _try_parse_json(raw)
                if parsed:
                    normalized = _ensure_quiz_shape(parsed,
                                                    num_mcq,
                                                    num_open,
                                                    concept_name)
                    return normalized

            except Exception as e:
                print(f"Quiz attempt {attempt+1} failed:", e)

            time.sleep(BASE_RETRY_DELAY * (2 ** attempt))

        # All attempts failed → fallback
        return self._fallback_quiz(concept_name, num_mcq, num_open)

    # -----------------------
    # Fallback Quiz
    # -----------------------
    def _fallback_quiz(self, concept_name: str, num_mcq: int, num_open: int):
        mcq = [{
            "id": f"m{i+1}",
            "question": f"(Fallback) What is a key idea in {concept_name}? ({i+1})",
            "options": ["A", "B", "C", "D"],
            "answer_index": 0,
            "answer": "A",
        } for i in range(num_mcq)]

        open_q = [{
            "id": f"o{i+1}",
            "question": f"(Fallback) Briefly explain: {concept_name} ({i+1})"
        } for i in range(num_open)]

        return {"mcq": mcq, "open_questions": open_q}

    # -----------------------
    # Grade single open question
    # -----------------------
    def grade_answer(self, concept_name: str, question: str,
                     student_answer: str,
                     max_retries: int = MAX_RETRIES) -> Dict[str, Any]:

        client = get_openai_client()

        if client is None:
            score = 0.6 if len(student_answer) > 30 else 0.2
            return {"score": score, "feedback": "Fallback heuristic."}

        prompt = GRADING_PROMPT.format(
            concept_name=concept_name,
            question=question,
            student_answer=student_answer,
        )

        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Return JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=200,
                )

                raw = ""
                try:
                    raw = resp.choices[0].message.content
                except:
                    raw = getattr(resp.choices[0], "text", "")

                parsed = _try_parse_json(raw)
                if parsed and "score" in parsed:
                    score = float(parsed.get("score", 0.0))
                    score = max(0.0, min(1.0, score))
                    feedback = parsed.get("feedback", "")
                    return {"score": score, "feedback": feedback}

            except Exception as e:
                print(f"Grading attempt {attempt+1} error:", e)

            time.sleep(BASE_RETRY_DELAY * (2 ** attempt))

        return {"score": 0.0, "feedback": "LLM grading failed."}

    # -----------------------
    # Streaming explanation
    # -----------------------
    def generate_streaming_content(self,
                                  high_level: str,
                                  concept_name: str,
                                  fixed_flow: Optional[List] = None
                                  ) -> Generator[str, None, None]:

        client = get_openai_client()

        # If predefined workflow steps exist:
        if fixed_flow:
            for step in fixed_flow:
                step_name = step
                system_msg = TEACHING_PROMPT_SYSTEM
                user_msg = f"Step: {step_name}\nExplain {concept_name} (high level: {high_level})."

                if client is None:
                    yield f"## {step_name}\n(Fallback) Explanation unavailable.\n"
                    continue

                try:
                    stream = client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg},
                        ],
                        stream=True,
                        temperature=0.6,
                    )
                except Exception as e:
                    yield f"[STREAM ERROR] {e}"
                    continue

                for chunk in stream:
                    try:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            yield delta.content
                    except:
                        pass
            return

        # Normal single-concept explanation
        system_msg = TEACHING_PROMPT_SYSTEM
        user_msg = TEACHING_PROMPT_USER.format(
            concept_name=concept_name,
            high_level=high_level,
        )

        if client is None:
            yield f"### {concept_name}\n(Fallback) Explanation unavailable.\n"
            return

        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                stream=True,
                temperature=0.6,
            )
        except Exception as e:
            yield f"[STREAM ERROR] {e}"
            return

        for chunk in stream:
            try:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content
            except:
                pass


# -----------------------
# Module-level functional wrappers
# -----------------------
def generate_diagnostic_quiz(concept_name: str,
                             num_mcq: int = 5,
                             num_open: int = 3,
                             max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
    return AssessmentAgent().generate_diagnostic_quiz(
        concept_name,
        num_mcq=num_mcq,
        num_open=num_open,
        max_retries=max_retries
    )


def grade_answer(concept_name: str,
                 question: str,
                 student_answer: str,
                 max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
    return AssessmentAgent().grade_answer(
        concept_name,
        question,
        student_answer,
        max_retries=max_retries
    )


def generate_streaming_content(high_level: str,
                               concept_name: str,
                               fixed_flow: Optional[List] = None):
    return AssessmentAgent().generate_streaming_content(
        high_level,
        concept_name,
        fixed_flow=fixed_flow
    )
