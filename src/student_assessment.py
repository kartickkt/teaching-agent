# src/student_assessment.py
"""
LLM-based quiz generation, grading, and teaching content streaming.
Compatible with TeachingLoopService, MasteryService, and Cloud Run.
"""

import os
import time
import json
import re
from typing import Optional, Dict, Any, Generator, List
from dotenv import load_dotenv

load_dotenv()

# ------------------------------
# Model + API configuration
# ------------------------------
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

_openai_client = None    # lazy-loaded client


def get_openai_client():
    """Lazy initialization of OpenAI client."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    if not OPENAI_KEY:
        print("❌ OPENAI_API_KEY not set.")
        return None

    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_KEY)
    except Exception as e:
        print("❌ Failed to initialize OpenAI client:", e)
        _openai_client = None

    return _openai_client


# ------------------------------
# Helpers: JSON extraction
# ------------------------------
def _try_parse_json(text: str) -> Optional[Dict]:
    """Extract outermost JSON object, even if wrapped in text."""
    if not text:
        return None

    match = re.search(r"\{(?:.|\n)*\}", text)
    if not match:
        return None

    blob = match.group(0)

    # Try clean load
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Clean common trailing commas
        cleaned = re.sub(r",\s*}", "}", blob)
        cleaned = re.sub(r",\s*\]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None


# ------------------------------
# Prompt Templates
# ------------------------------
DIAGNOSTIC_PROMPT = """
You are an exam generator. Produce STRICT JSON with keys "mcq" and "open_questions".

Each MCQ:
{{
  "id": "m1",
  "question": "text",
  "options": ["A","B","C","D"],
  "answer_index": 0
}}

Each open question:
{{
  "id": "o1",
  "question": "text"
}}

Generate {num_mcq} MCQs and {num_open} open-ended questions for "{concept_name}".
Return ONLY the JSON object.
"""

GRADING_PROMPT = """
You are a strict short-answer grader.
Concept: "{concept_name}"
Question: "{question}"
Student Answer: "{student_answer}"

Return ONLY JSON:
{{ "score": 0.0-1.0, "feedback": "short feedback" }}
"""

TEACHING_SYSTEM_PROMPT = "You are an expert tutor. Provide clear structured Markdown."


# =====================================================
#             CORE CLASS FOR YOUR ENTIRE SYSTEM
# =====================================================

class AssessmentAgent:
    """
    Core class used by TeachingLoopService for:
      • Diagnostic quiz generation
      • Final quiz generation
      • Open-answer grading
      • Streaming structured explanations
    """

    # -------------------------------------------
    # 1. QUIZ GENERATION
    # -------------------------------------------
    def generate_diagnostic_quiz(self, concept_name: str,
                                 num_mcq: int = 5,
                                 num_open: int = 3,
                                 max_retries: int = 4) -> Dict[str, Any]:

        client = get_openai_client()

        # If LLM unavailable: deterministic fallback
        if client is None:
            return self._fallback_quiz(concept_name, num_mcq, num_open)

        prompt = DIAGNOSTIC_PROMPT.format(
            num_mcq=num_mcq,
            num_open=num_open,
            concept_name=concept_name
        )

        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Return only JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=800,
                )

                raw = resp.choices[0].message.content
                parsed = _try_parse_json(raw)

                if parsed and "mcq" in parsed and "open_questions" in parsed:
                    return parsed

            except Exception as e:
                print(f"[Diagnostic Retry {attempt+1}] Error:", e)

            time.sleep(1 + attempt)

        # fallback after max retries
        return self._fallback_quiz(concept_name, num_mcq, num_open)

    def _fallback_quiz(self, concept_name, num_mcq, num_open):
        mcq = [{
            "id": f"m{i+1}",
            "question": f"(Fallback) Fact about {concept_name} ({i+1})",
            "options": ["A", "B", "C", "D"],
            "answer_index": 0
        } for i in range(num_mcq)]

        open_q = [{
            "id": f"o{i+1}",
            "question": f"(Fallback) Explain {concept_name} ({i+1})"
        } for i in range(num_open)]

        return {"mcq": mcq, "open_questions": open_q}

    # -------------------------------------------
    # 2. OPEN-ANSWER GRADING
    # -------------------------------------------
    def grade_answer(self, concept_name: str, question: str,
                     student_answer: str, max_retries: int = 3) -> Dict[str, Any]:

        client = get_openai_client()

        # Fallback if OpenAI unavailable
        if client is None:
            score = 0.6 if len(student_answer) > 30 else 0.2
            return {"score": score, "feedback": "Fallback heuristic grade."}

        prompt = GRADING_PROMPT.format(
            concept_name=concept_name,
            question=question,
            student_answer=student_answer
        )

        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Return only JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                )

                raw = resp.choices[0].message.content
                parsed = _try_parse_json(raw)

                if parsed and "score" in parsed:
                    parsed["score"] = max(0, min(1, float(parsed["score"])))
                    parsed["feedback"] = parsed.get("feedback", "")
                    return parsed

            except Exception as e:
                print(f"[Grading Retry {attempt+1}] Error:", e)

            time.sleep(1 + attempt)

        # final fallback
        return {"score": 0.0, "feedback": "LLM grading failed."}

    # -------------------------------------------
    # 3. STREAM TEACHING CONTENT
    # -------------------------------------------
    def generate_streaming_content(self,
                                   high_level: str,
                                   concept_name: str,
                                   fixed_flow: Optional[List] = None
                                   ) -> Generator[str, None, None]:

        client = get_openai_client()

        base_messages = [
            {"role": "system", "content": TEACHING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Explain the concept '{concept_name}' under high-level topic '{high_level}' "
                    f"in clear structured Markdown."
                )
            }
        ]

        # fallback: no streaming
        if client is None:
            yield f"## {concept_name}\n\n(Fallback) Explanation unavailable.\n"
            yield "[END]"
            return

        try:
            stream = client.chat.completions.create(
                model=LLM_MODEL,
                messages=base_messages,
                stream=True,
                temperature=0.6
            )
        except Exception:
            # fallback to non-stream
            try:
                resp = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=base_messages,
                    temperature=0.6
                )
                text = resp.choices[0].message.content
                yield text
                yield "\n[END]"
                return
            except Exception as e:
                yield f"[STREAM ERROR] {e}"
                yield "[END]"
                return

        # stream tokens
        try:
            for chunk in stream:
                delta = None
                try:
                    delta = chunk.choices[0].delta.content
                except Exception:
                    pass

                if delta:
                    yield delta
                    continue

                # older format
                try:
                    txt = chunk.choices[0].text
                    if txt:
                        yield txt
                except Exception:
                    continue
        except Exception as e:
            yield f"\n[STREAM ERROR] {e}"

        yield "\n[END]"
