# src/student_assessment.py (REVISED)
import time
import random
import json
import os
import re
from typing import Optional, Tuple, Dict, Any, Generator, List
from dotenv import load_dotenv
from openai import OpenAI
# Use absolute imports now that 'src' is a package
from .student_profiles import CurriculumManager # Relative import fix for use as a package

# --- LLM API Configuration ---
load_dotenv() 
LLM_MODEL = "gpt-4o-mini"
MAX_RETRIES = 5  # INCREASED RETRIES FOR CLOUD STABILITY
# Added base delay to wait between retries
BASE_RETRY_DELAY = 3 

# Initialize the OpenAI client globally (will pick up OPENAI_API_KEY from .env)
try:
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # Separate client for streaming might be overkill, but let's keep it consistent with main.py
    streaming_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) 
except Exception as e:
    print(f"Warning: OpenAI client could not be initialized. Error: {e}")
    openai_client = None
    streaming_client = None

def _try_parse_json(text: str) -> Optional[Dict]:
    """Tries to extract a JSON object from a string, even if it's embedded."""
    # Find the outermost curly braces
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None

# --- Versioned Prompt Templates ---
class PromptTemplates:
    """Central place to store LLM prompt templates."""
    
    # 1. Diagnostic / Final Quiz Generation Prompt
    QUIZ_SYSTEM = (
        "You are an expert AI assessment engine. Generate a diagnostic quiz for the concept "
        "provided. The quiz must contain exactly {num_mcq} Multiple Choice Questions (MCQ) "
        "and exactly {num_open} short, open-ended answer questions. "
        "The questions should cover concept and application. Return ONLY a single, valid JSON object."
    )
    QUIZ_USER = """
        Concept: "{concept_name}"

        JSON Format:
        {{
          "mcq": [
            {{
              "question": "MCQ question 1...",
              "options": ["A", "B", "C", "D"],
              "answer": "The correct option letter (e.g., B)"
            }},
            // ... up to {num_mcq} MCQs
          ],
          "open_questions": [
            "Short answer question 1...",
            // ... up to {num_open} open-ended questions
          ]
        }}
        """

    # 2. Open-Answer Grading Prompt
    GRADING_SYSTEM = (
        "You are a fast, precise, and fair AI grader. Grade the student's answer (0.0 to 1.0) "
        "and provide *brief*, constructive feedback (max 2 sentences). Respond ONLY with the JSON object."
    )
    GRADING_USER = """
        Concept: "{concept_name}"
        Question: "{question}"
        Student's Answer: "{user_answer}"
        
        Score (0.0=Incorrect, 1.0=Perfect).
        
        JSON Format:
        {{
          "score": 0.7,
          "feedback": "A short, concise critique."
        }}
        """
    
    # 3. Structured Content Generation Prompt (for fixed teaching flow)
    # The 'fixed_flow_step' is used to inject the specific stage (e.g., 'What it is', 'Why/Need')
    TEACHING_SYSTEM_FIXED = (
        "You are a friendly and expert AI tutor in 'Neural Networks and Transformers'. "
        "Explain the step '{fixed_flow_step}' of the concept '{hl_concept}' in clear, "
        "structured, student-friendly markdown, using simple analogies."
    )
    TEACHING_USER_FIXED = "Generate the explanation now."
    
    # 4. Standard Content Generation Prompt (for chat/general explanation)
    TEACHING_SYSTEM_GENERIC = (
        "You are a friendly and expert AI tutor in 'Neural Networks and Transformers'. "
        "Explain the concept or step: '{concept_name}' suitable for a university student, "
        "using simple analogies. The explanation must be clearly structured."
    )
    TEACHING_USER_GENERIC = "Provide an explanation of the topic: {concept_name}."


class AssessmentAgent:
    """
    Handles LLM-based content generation, quizzing, and grading.
    """
    def __init__(self):
        self.high_level_concepts = CurriculumManager.get_high_level_concepts()

    # NOTE: get_next_concept is deprecated in this new flow.
    # It remains here only if other legacy parts depend on it.

    def generate_diagnostic_quiz(self, concept_name: str, num_mcq: int, num_open: int) -> Dict[str, Any]:
        """
        Generates the combined diagnostic/final quiz (MCQ + Open-ended) in one call.
        """
        if not openai_client:
            return {"status": "error", "quiz": {"mcq": [], "open_questions": ["LLM client not initialized."]}}

        system_prompt = PromptTemplates.QUIZ_SYSTEM.format(num_mcq=num_mcq, num_open=num_open)
        user_query = PromptTemplates.QUIZ_USER.format(concept_name=concept_name, num_mcq=num_mcq, num_open=num_open)

        for attempt in range(MAX_RETRIES):
            try:
                response = openai_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7,
                )
                
                content = response.choices[0].message.content
                parsed_json = _try_parse_json(content)
                
                if parsed_json and "mcq" in parsed_json and "open_questions" in parsed_json:
                    # Return the two list types needed by the new flow
                    return {
                        "mcq": parsed_json["mcq"][:num_mcq],
                        "open_questions": parsed_json["open_questions"][:num_open]
                    } 
                else:
                    raise ValueError("Failed to parse the combined quiz JSON.")

            except Exception as e:
                print(f"OpenAI Quiz Generation Error on attempt {attempt + 1}: {e}")
                time.sleep(BASE_RETRY_DELAY * (2 ** attempt))

        return {"mcq": [], "open_questions": [f"LLM generation failed after {MAX_RETRIES} retries."]}


    def grade_answer(self, concept_name: str, question: str, user_answer: str) -> Dict[str, Any]:
        """
        Grades a student's open-ended answer using an LLM rubric (0.0 to 1.0).
        (This method is unchanged, now using the central prompt template)
        """
        if not openai_client:
            return {"score": 0.0, "feedback": "LLM client not initialized."}

        system_prompt = PromptTemplates.GRADING_SYSTEM
        user_query = PromptTemplates.GRADING_USER.format(
            concept_name=concept_name, question=question, user_answer=user_answer
        )

        for attempt in range(MAX_RETRIES):
            try:
                response = openai_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0, 
                )
                
                content = response.choices[0].message.content
                parsed_json = _try_parse_json(content)

                if parsed_json and "score" in parsed_json and "feedback" in parsed_json:
                    parsed_json["score"] = max(0.0, min(1.0, float(parsed_json["score"])))
                    return parsed_json
                else:
                    raise ValueError("Failed to parse grade from LLM.")

            except Exception as e:
                print(f"OpenAI Grading Error on attempt {attempt + 1}: {e}")
                time.sleep(BASE_RETRY_DELAY * (2 ** attempt))
        
        return {"score": 0.0, "feedback": "LLM grading failed after multiple retries."}

    def generate_streaming_content(self, hl_concept: str, concept_name: str, fixed_flow: Optional[List[Tuple[str, str]]] = None) -> Generator[str, None, None]:
        """
        Generates explanation content using the LLM and streams chunks back.
        Uses either the fixed teaching flow or a generic prompt.
        """
        if not streaming_client:
            yield json.dumps({"error": "LLM Streaming Client not initialized."})
            return

        # Determine System/User prompts based on fixed flow structure
        if fixed_flow:
            # Fixed flow: Generate content sequentially for each step in the flow
            for step_name, _ in fixed_flow:
                system_prompt = PromptTemplates.TEACHING_SYSTEM_FIXED.format(
                    fixed_flow_step=step_name, hl_concept=hl_concept
                )
                user_query = PromptTemplates.TEACHING_USER_FIXED
                
                # Yield a separator to indicate the start of the next section
                yield f"\n\n## 💡 {step_name} ({concept_name})\n\n"
                
                # Generate and yield content for this step
                stream = streaming_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    temperature=0.7,
                    stream=True
                )

                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        yield delta.content
        else:
            # Generic/Workflow Step: Generate content for the single step/concept name
            system_prompt = PromptTemplates.TEACHING_SYSTEM_GENERIC.format(concept_name=concept_name)
            user_query = PromptTemplates.TEACHING_USER_GENERIC.format(concept_name=concept_name)

            stream = streaming_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                temperature=0.7,
                stream=True
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content