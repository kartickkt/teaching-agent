# src/student_assessment.py
"""
LLM generation and streaming helpers for the teaching agent.
Safe, lazy initialization of OpenAI client and robust JSON parsing.
"""

import os
import time
import json
import re
from typing import Optional, Dict, Any, Generator, List
from dotenv import load_dotenv

load_dotenv()

# Default model can be overridden via env var
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# Lazy client holder
_openai_client = None

def get_openai_client():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    try:
        from openai import OpenAI
    except Exception as e:
        print("OpenAI SDK not available:", e)
        _openai_client = None
        return None
    if not OPENAI_KEY:
        print("Warning: OPENAI_API_KEY not set.")
        _openai_client = None
        return None
    try:
        _openai_client = OpenAI(api_key=OPENAI_KEY)
    except Exception as e:
        print("Failed to initialize OpenAI client:", e)
        _openai_client = None
    return _openai_client

# Simple JSON extractor (robust)
def _try_parse_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    # look for outermost braces
    m = re.search(r"\{(?:.|\n)*\}", text)
    if not m:
        return None
    s = m.group(0)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # fallback: try to fix common problems (remove trailing commas)
        s2 = re.sub(r",\s*}", "}", s)
        s2 = re.sub(r",\s*\]", "]", s2)
        try:
            return json.loads(s2)
        except Exception:
            return None

# Prompts (no JS comments, deterministic JSON spec)
DIAGNOSTIC_PROMPT_TEMPLATE = """You are an expert assessment generator.
Produce a JSON object exactly matching this schema:

{{
  "mcq": [
    {{
      "id": "m1",
      "question": "Question text",
      "options": ["A", "B", "C", "D"],
      "answer_index": 1
    }}
  ],
  "open_questions": [
    {{
      "id": "o1",
      "question": "Short open-ended question text"
    }}
  ]
}}

Generate {num_mcq} MCQs and {num_open} open questions for the topic: "{concept_name}".
Return ONLY the JSON object, with keys 'mcq' and 'open_questions'.
"""

GRADING_PROMPT_TEMPLATE = """You are a concise grader. Given the concept: "{concept_name}", question: "{question}",
and student's answer: "{student_answer}", return a JSON object with keys: score (0.0-1.0) and feedback (short).
Example:
{{ "score": 0.75, "feedback": "Concise actionable feedback." }}
Return ONLY valid JSON.
"""

TEACHING_SYSTEM_PROMPT = "You are an expert tutor. Provide a clear, short, structured Markdown explanation."

# ------- Public API -------

def generate_diagnostic_quiz(concept_name: str, num_mcq: int = 5, num_open: int = 3, max_retries: int = 3) -> Dict[str, Any]:
    """
    Ask LLM to generate mcq + open questions in strict JSON. If LLM fails to give JSON, fallback deterministic placeholders.
    """
    client = get_openai_client()
    prompt = DIAGNOSTIC_PROMPT_TEMPLATE.format(num_mcq=num_mcq, num_open=num_open, concept_name=concept_name)

    if client is None:
        # fallback deterministic
        mcqs = []
        for i in range(num_mcq):
            mcqs.append({
                "id": f"m{i+1}",
                "question": f"(Placeholder) What is an important fact about {concept_name}? ({i+1})",
                "options": ["A", "B", "C", "D"],
                "answer_index": 0
            })
        open_qs = [{"id": f"o{i+1}", "question": f"(Placeholder) Briefly explain: {concept_name} (open {i+1})"} for i in range(num_open)]
        return {"mcq": mcqs, "open_questions": open_qs}

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role":"system","content":"You are a strict JSON outputter."},
                          {"role":"user","content":prompt}],
                max_tokens=800,
                temperature=0.2
            )
            text = ""
            try:
                text = resp.choices[0].message.content
            except Exception:
                text = getattr(resp.choices[0], "text", "")
            parsed = _try_parse_json(text)
            if parsed and "mcq" in parsed and "open_questions" in parsed:
                # normalize fields: ensure options and answer_index types exist
                return parsed
        except Exception as e:
            print("Diagnostic generation error:", e)
        time.sleep(1 + attempt)
    # fallback deterministic
    mcqs = []
    for i in range(num_mcq):
        mcqs.append({
            "id": f"m{i+1}",
            "question": f"(Fallback) What is an important fact about {concept_name}? ({i+1})",
            "options": ["A", "B", "C", "D"],
            "answer_index": 0
        })
    open_qs = [{"id": f"o{i+1}", "question": f"(Fallback) Briefly explain: {concept_name} (open {i+1})"} for i in range(num_open)]
    return {"mcq": mcqs, "open_questions": open_qs}


def grade_answer(concept_name: str, question: str, student_answer: str, max_retries: int = 3) -> Dict[str, Any]:
    """
    Grades a single short answer returning {"score": float, "feedback": str}.
    Uses LLM when available, otherwise fallback heuristics.
    """
    client = get_openai_client()
    prompt = GRADING_PROMPT_TEMPLATE.format(concept_name=concept_name, question=question, student_answer=student_answer)

    if client is None:
        # fallback heuristic (short answers -> low, longer answers -> medium)
        score = 0.6 if len(student_answer) > 30 else 0.2
        return {"score": score, "feedback": "Auto-graded fallback."}

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role":"system","content":"You are a concise grader."},
                          {"role":"user","content":prompt}],
                temperature=0.0,
                max_tokens=200
            )
            text = ""
            try:
                text = resp.choices[0].message.content
            except Exception:
                text = getattr(resp.choices[0], "text", "")
            parsed = _try_parse_json(text)
            if parsed and "score" in parsed:
                parsed["score"] = max(0.0, min(1.0, float(parsed.get("score", 0.0))))
                parsed["feedback"] = parsed.get("feedback", "") or ""
                return parsed
        except Exception as e:
            print("Grading error:", e)
        time.sleep(1 + attempt)
    return {"score": 0.0, "feedback": "Grading failed (fallback)."}


def generate_streaming_content(high_level: str, concept_name: str, fixed_flow: Optional[List] = None) -> Generator[str, None, None]:
    """
    Streaming generator yielding string chunks (normalized across SDK differences).
    If OpenAI streaming client not available, yield a single explanation string.
    """
    client = get_openai_client()
    base_messages = [{"role":"system","content":TEACHING_SYSTEM_PROMPT},
                     {"role":"user","content":f"Explain {concept_name} (high level: {high_level}) in short Markdown."}]
    if client is None:
        # fallback single message
        yield f"**{concept_name}**\n\n(Offline fallback) Short explanation of {concept_name}."
        yield "\n\n[END]"
        return

    try:
        stream = client.chat.completions.create(model=LLM_MODEL, messages=base_messages, stream=True, temperature=0.6)
    except Exception as e:
        # streaming not available; do single-shot
        try:
            resp = client.chat.completions.create(model=LLM_MODEL, messages=base_messages, temperature=0.6)
            text = ""
            try:
                text = resp.choices[0].message.content
            except Exception:
                text = getattr(resp.choices[0], "text", "")
            yield text
            yield "\n\n[END]"
            return
        except Exception as e2:
            yield f"[STREAM ERROR] {e2}"
            yield "\n\n[END]"
            return

    # Normalize streaming chunks
    try:
        for chunk in stream:
            # modern SDK: chunk.choices[0].delta.content
            try:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content
                    continue
            except Exception:
                pass
            # older shape
            try:
                text = chunk.choices[0].text
                if text:
                    yield text
            except Exception:
                # ignore keep-alive or irregular chunks
                continue
    except GeneratorExit:
        return
    except Exception as e:
        yield f"\n\n[STREAM ERROR] {e}\n\n"
    finally:
        yield "\n\n[END]"
