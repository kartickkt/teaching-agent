# src/student_assessment.py
import time
import random
import json
import os
import re
from typing import Optional, Tuple, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI
# Use absolute imports now that 'src' is a package
from student_profiles import CurriculumManager

# --- LLM API Configuration ---
load_dotenv() 
LLM_MODEL = "gpt-4o-mini"
MAX_RETRIES = 3

# Initialize the OpenAI client globally (will pick up OPENAI_API_KEY from .env)
try:
    openai_client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY")
    )
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY not found in .env file.")
except Exception as e:
    print(f"Warning: OpenAI client could not be initialized. API calls will fail. Error: {e}")
    openai_client = None

def _try_parse_json(text: str) -> Optional[Dict]:
    """Tries to extract a JSON object from a string, even if it's embedded."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None

class AssessmentAgent:
    """
    Determines the next best concept to teach based on the student's profile 
    and generates learning materials.
    """
    def __init__(self):
        # Assessment agent relies on the CurriculumManager for data structure
        # This is a fixed, in-memory copy of the curriculum high-level structure
        self.high_level_concepts = CurriculumManager.get_high_level_concepts()
        self.epsilon = 0.01  # Small value to prevent division by zero

    def get_next_concept(self, profile: object) -> Optional[str]:
        """
        Calculates the most valuable concept to teach next.
        Prioritizes unmastered concepts where prerequisites are met, and uses 
        curriculum priority/order as tie-breakers.
        
        Note: 'profile' is expected to be a proxy object (TempProfile) 
        that implements get_mastery(concept_name).
        """
        best_candidate: Optional[str] = None
        highest_score = -1.0

        if not self.high_level_concepts:
            print("Error in AssessmentAgent: No high-level concepts were loaded.")
            return None

        # Iterate over all high-level concepts and their sub-concepts
        for hl_concept_name, hl_data in self.high_level_concepts.items():
            
            # 1. Prerequisite Check
            prereq_met = True
            for prereq_name in hl_data.get('prerequisites', []):
                # We check if the prerequisite high-level concept has been engaged at all
                if not self._check_high_level_mastery(profile, prereq_name, threshold=0.1):
                    prereq_met = False
                    break
            
            if not prereq_met:
                continue

            # 2. Score Calculation for Sub-concepts
            for sub_concept_data in hl_data.get('sub_concepts', []):
                sub_concept_name = sub_concept_data.get('concept')
                if not sub_concept_name:
                    continue

                # IMPORTANT: Call get_mastery on the proxy profile object
                current_mastery = profile.get_mastery(sub_concept_name)
                
                if current_mastery >= 1.0:
                    continue  # Skip concepts considered fully mastered

                # Scoring Formula: Priority * (1 / (Current_Mastery + epsilon))
                priority = hl_data.get('priority', 1)
                
                # Relevance score rewards low mastery and high priority
                relevance_score = priority / (current_mastery + self.epsilon)
                
                # Use order as a tie-breaker. Lower order numbers should have higher priority.
                # We use a large number minus the order to make smaller orders more valuable.
                order_score = (1000 - hl_data.get('order', 0) * 10) + (10 - sub_concept_data.get('order', 0))
                
                combined_score = relevance_score + order_score

                if combined_score > highest_score:
                    highest_score = combined_score
                    best_candidate = sub_concept_name

        return best_candidate

    def _check_high_level_mastery(self, profile: object, hl_name: str, threshold: float) -> bool:
        """
        Utility to check if a high-level concept has met a basic engagement threshold.
        Relies on the provided 'profile' object's get_mastery method.
        """
        hl_data = self.high_level_concepts.get(hl_name)
        if not hl_data:
            return True # If prereq is unknown, assume met for robustness
        
        # Check if *any* sub-concept within the high-level prereq has a mastery >= threshold
        sub_concepts = hl_data.get('sub_concepts', [])
        if not sub_concepts:
            return False # No sub-concepts to be mastered
            
        for sub_concept_data in sub_concepts:
            concept_name = sub_concept_data.get('concept')
            if concept_name and profile.get_mastery(concept_name) >= threshold:
                return True
        return False

    def generate_content_for_concept(self, concept_name: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Uses the LLM API (OpenAI) to generate a targeted explanation for a step or a concept.
        """
        if not openai_client:
            return "LLM generation failed: Client not initialized (check API Key).", None

        # The 'concept_name' here can be a full concept OR a structured step concept
        system_prompt = f"You are a friendly and expert AI tutor in 'Neural Networks and Transformers'. Your task is to provide a concise, engaging explanation of the concept or step: '{concept_name}' suitable for a university student, using simple analogies. The explanation must be clearly structured."
        user_query = f"Provide an explanation of the topic: {concept_name}."

        print(f"\n--- Generating content for '{concept_name}' using {LLM_MODEL}... ---")
        
        for attempt in range(MAX_RETRIES):
            try:
                response = openai_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    temperature=0.7,
                    max_tokens=1024 # Increased token limit to prevent cut-offs
                )
                
                text = response.choices[0].message.content
                return text, None

            except Exception as e:
                print(f"OpenAI API Error on attempt {attempt + 1}: {e}")

            time.sleep(2 ** attempt)

        return "LLM generation failed after multiple retries.", None

    def generate_quiz(self, concept_name: str, difficulty: str = "medium") -> Dict[str, Any]:
        """
        NEW: Generates a short, open-ended quiz for a concept using the LLM.
        """
        if not openai_client:
            return {"questions": ["LLM client not initialized."]}

        # Adjust prompt based on difficulty
        if difficulty == "easy":
            difficulty_prompt = "Generate 3 straightforward, conceptual questions."
            temp = 0.3
        elif difficulty == "hard":
            difficulty_prompt = "Generate 3 complex, problem-solving, application-based questions."
            temp = 0.8
        else: # medium
            difficulty_prompt = "Generate 3 open-ended questions balancing concept and application."
            temp = 0.5

        system_prompt = f"You are an expert AI educator. {difficulty_prompt} for the given concept. Return ONLY a valid JSON object."
        user_query = f"""
        Concept: "{concept_name}"

        Format:
        {{
          "questions": [
            "Your first open-ended question here...",
            "Your second open-ended question here...",
            "Your third open-ended question here..."
          ]
        }}
        """
        print(f"\n--- Generating {difficulty} quiz for '{concept_name}'... ---")
        
        for attempt in range(MAX_RETRIES):
            try:
                response = openai_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    response_format={"type": "json_object"},
                    temperature=temp,
                )
                
                content = response.choices[0].message.content
                parsed_json = _try_parse_json(content)
                
                if parsed_json and "questions" in parsed_json:
                    # We enforce exactly 3 questions here for consistent UI flow
                    return {"questions": parsed_json["questions"][:3]} 
                else:
                    raise ValueError("Failed to parse quiz questions.")

            except Exception as e:
                print(f"OpenAI Quiz Generation Error on attempt {attempt + 1}: {e}")
                time.sleep(2 ** attempt)

        return {"questions": [f"LLM generation failed after {MAX_RETRIES} retries."]}


    def grade_answer(self, concept_name: str, question: str, user_answer: str) -> Dict[str, Any]:
        """
        NEW: Grades a student's open-ended answer using an LLM rubric.
        Optimized prompt for faster response.
        """
        if not openai_client:
            return {"score": 0.0, "feedback": "LLM client not initialized."}

        # Simplified prompt structure to minimize LLM thinking time and token usage
        system_prompt = "You are a fast, precise, and fair AI grader. Grade the student's answer (0.0 to 1.0) and provide *brief*, constructive feedback. Respond ONLY with the JSON object."
        user_query = f"""
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
        print(f"\n--- Grading answer for '{concept_name}'... ---")

        for attempt in range(MAX_RETRIES):
            try:
                response = openai_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0, # Zero temperature for consistent grading
                )
                
                content = response.choices[0].message.content
                parsed_json = _try_parse_json(content)

                if parsed_json and "score" in parsed_json and "feedback" in parsed_json:
                    # Ensure score is a float between 0 and 1
                    parsed_json["score"] = max(0.0, min(1.0, float(parsed_json["score"])))
                    return parsed_json
                else:
                    raise ValueError("Failed to parse grade from LLM.")

            except Exception as e:
                print(f"OpenAI Grading Error on attempt {attempt + 1}: {e}")
                time.sleep(2 ** attempt)
        
        return {"score": 0.0, "feedback": "LLM grading failed after multiple retries."}