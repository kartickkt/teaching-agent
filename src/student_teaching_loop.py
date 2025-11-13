# src/student_teaching_loop.py
import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any

# Use absolute imports now that 'src' is a package
from student_profiles import StudentProfile, CurriculumManager
from student_assessment import AssessmentAgent

# --- Constants ---
# Correct the path to point to 'data/curriculum.json' from the project root
# We assume the script is run from the root as `python -m src.student_teaching_loop`
PROJECT_ROOT = Path(__file__).parent.parent 
WORKFLOWS_JSON = PROJECT_ROOT / "data" / "curriculum.json"

# --- Curriculum Loading & Flattening ---

def load_concepts(json_path: Path) -> List[Dict[str, Any]]:
    """Loads the curriculum concepts from the JSON file."""
    if not json_path.exists():
        print(f"Error: curriculum.json not found at {json_path}")
        return []
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'concepts' in data:
        return data['concepts']
    elif isinstance(data, list):
        return data
    raise ValueError("Invalid curriculum.json format: Must be a list or a dict with a 'concepts' key.")

def flatten_sub_concepts(concepts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Flattens the curriculum into a single list of teachable units.
    It intelligently aggregates 'workflows' from parents, self, and 'secondary_workflows'.
    """
    flat_list = []
    
    # Sort high-level concepts by their order
    for parent_concept in sorted(concepts, key=lambda x: x.get('order', 0)):
        high_level_name = parent_concept.get('high_level_concept')
        if not high_level_name:
            continue
            
        # Get workflows defined at the high-level (parent)
        parent_workflows = parent_concept.get('workflows', [])
        
        sub_concepts = parent_concept.get('sub_concepts', [])
        if not sub_concepts:
            continue

        # Sort sub-concepts by their order
        for sub_concept in sorted(sub_concepts, key=lambda x: x.get('order', 0)):
            sub_concept_name = sub_concept.get('concept')
            if not sub_concept_name:
                continue

            # --- Workflow Aggregation ---
            # Use a dictionary to de-duplicate workflows based on workflow_id
            all_workflows: Dict[str, Dict[str, Any]] = {}

            # 1. Add parent (high-level) workflows first
            for wf in parent_workflows:
                if wf.get('workflow_id'):
                    all_workflows[wf['workflow_id']] = wf

            # 2. Add/overwrite with primary sub-concept workflows
            primary_workflows = sub_concept.get('workflows', [])
            for wf in primary_workflows:
                if wf.get('workflow_id'):
                    all_workflows[wf['workflow_id']] = wf
            
            # 3. Add/overwrite with secondary sub-concept workflows
            secondary_workflows = sub_concept.get('secondary_workflows', [])
            for wf in secondary_workflows:
                if wf.get('workflow_id'):
                    all_workflows[wf['workflow_id']] = wf

            # Create the final flat entry
            flat_entry = {
                'high_level': high_level_name,
                'name': sub_concept_name,
                'prerequisites': parent_concept.get('prerequisites', []),
                'priority': parent_concept.get('priority', 3), # Default priority
                'order_hl': parent_concept.get('order', 0),
                'order_sub': sub_concept.get('order', 0),
                'workflows': list(all_workflows.values()) # Convert dict values back to a list
            }
            flat_list.append(flat_entry)
            
    return flat_list


# --- Local Test Runner ---

def run_teaching_loop(student_name: str, max_iterations: int = 5):
    """
    A local "smoke test" to run the full backend loop.
    This function is NOT used by the FastAPI server.
    """
    print("--- Teaching Agent Initialized ---")
    
    # 1. Initialize Agents
    try:
        profile = StudentProfile()
        agent = AssessmentAgent()
        # Load and flatten curriculum data for the local test
        all_concepts_data = flatten_sub_concepts(load_concepts(WORKFLOWS_JSON))
        if not all_concepts_data:
            print("Error: No concepts were loaded, ending simulation.")
            return
    except Exception as e:
        print(f"Error during initialization: {e}")
        return

    # 2. Register Student (or ensure they exist)
    profile.register_student(student_name)
    print(f"Student: {student_name}")
    print("------------------------------")

    for i in range(max_iterations):
        print(f"\n[Iteration {i+1}/{max_iterations}]")
        
        # 3. Create the TempProfileProxy to pre-fetch mastery data
        # This is the fix for the N+1 query problem
        class TempProfile:
            def __init__(self, s_name: str, prof: StudentProfile):
                self._cache = prof.get_all_mastery(s_name)
                print(f"  (Loaded {len(self._cache)} mastery records for agent)")
            
            def get_mastery(self, concept_name: str) -> float:
                return self._cache.get(concept_name, 0.0)

        # 4. Get Agent's Decision
        temp_profile_proxy = TempProfile(student_name, profile)
        next_concept_name = agent.get_next_concept(temp_profile_proxy)

        if next_concept_name is None:
            print("🎉 Curriculum complete! No more concepts to teach.")
            break
        
        current_mastery = temp_profile_proxy.get_mastery(next_concept_name)
        print(f"Decision: Targeting concept: '{next_concept_name}' (Mastery: {current_mastery:.2f})")
        
        # 5. Find the concept data to check for workflows
        concept_data = next((c for c in all_concepts_data if c['name'] == next_concept_name), None)
        if not concept_data:
            print(f"Error: Could not find concept data for '{next_concept_name}'. Skipping.")
            continue

        # 6. Teach (Structured Workflow OR Fallback)
        workflows = concept_data.get("workflows", [])
        if workflows and workflows[0].get("steps"):
            # --- Structured Teaching Path ---
            print("📘 Starting Structured Teaching (Workflow Steps)")
            workflow = workflows[0]
            steps = sorted(workflow["steps"], key=lambda x: x.get("order", 0))
            
            for step in steps:
                step_concept = step.get("concept", "Unnamed Step")
                print(f"\n  --- Teaching Step: {step_concept} ---")
                
                # Use a more contextual prompt for steps
                step_prompt = f"the specific step '{step_concept}' within the larger concept of '{next_concept_name}'"
                explanation, _ = agent.generate_content_for_concept(step_prompt)
                
                if "LLM generation failed" in explanation:
                    print(f"    Error: {explanation}")
                else:
                    # Print a snippet to keep the console clean
                    print(f"    {explanation[:500].strip()}...")
                
                profile.log_teaching_step(student_name, next_concept_name, step_concept, explanation)
                time.sleep(1) # Simulate time between steps
        
        else:
            # --- Fallback Teaching Path ---
            print("📘 Starting Fallback Teaching (Single LLM Explanation)")
            explanation, _ = agent.generate_content_for_concept(next_concept_name)
            
            if "LLM generation failed" in explanation:
                print(f"  Error: {explanation}")
            else:
                print(f"  {explanation[:500].strip()}...")
            
            profile.log_teaching_step(student_name, next_concept_name, next_concept_name, explanation)

        print("\n--- LLM Generated Explanation Complete ---")

        # 7. Simulate Student Engagement / Assessment
        time.sleep(1) 
        # Re-create the proxy to get the *absolute latest* mastery data for the simulation
        sim_profile_proxy = TempProfile(student_name, profile)
        simulated_score = agent.simulate_assessment(sim_profile_proxy, next_concept_name)
        
        # 8. Update Student Profile in DB
        new_mastery = profile.update_mastery(student_name, next_concept_name, simulated_score)
        
        print(f"-> Mastery for '{next_concept_name}' updated to {new_mastery:.2f} (from {current_mastery:.2f})")
        print(f"\n✅ Lesson Complete: Score {simulated_score:.2f} | New Mastery: {new_mastery:.2f}")

    print("\n--- Local Teaching Simulation Complete ---")


if __name__ == "__main__":
    # This block runs when you execute `python -m src.student_teaching_loop`
    test_student_name = "Kartick_Workflow_Test"
    run_teaching_loop(test_student_name, max_iterations=5)