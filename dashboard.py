# dashboard.py
import streamlit as st
import requests
import pandas as pd

# --- Page Configuration ---
st.set_page_config(
    page_title="Adaptive Teaching Agent",
    page_icon="🤖",
    layout="wide",
)

# --- State Management ---
# Initialize session state variables
if "student_name" not in st.session_state:
    st.session_state.student_name = ""
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = "http://127.0.0.1:8000"
if "current_lesson" not in st.session_state:
    st.session_state.current_lesson = None # Stores the StepResponse
if "current_explanation" not in st.session_state:
    st.session_state.current_explanation = ""
if "current_step_index" not in st.session_state:
    st.session_state.current_step_index = 0
if "all_concepts" not in st.session_state:
    st.session_state.all_concepts = [] # Cache for Explore mode

# --- V3 State for Real Assessments & Tab Fix ---
if "current_quiz" not in st.session_state:
    st.session_state.current_quiz = None 
if "current_quiz_index" not in st.session_state:
    st.session_state.current_quiz_index = 0
if "last_grade" not in st.session_state:
    st.session_state.last_grade = None 
if "quiz_answer" not in st.session_state:
    st.session_state.quiz_answer = ""
if "quiz_difficulty" not in st.session_state:
    st.session_state.quiz_difficulty = "medium"
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Agentic Mode (Guided Path)" # New state for tab tracking


# --- API Helper Functions ---

def set_api_url(url: str):
    """Updates the API base URL in session state."""
    st.session_state.api_base_url = url

def register_student(student_name: str):
    """Registers a student and sets them as active."""
    api_url = st.session_state.api_base_url
    try:
        requests.post(f"{api_url}/register_student", json={"student_name": student_name}, timeout=10)
        st.session_state.student_name = student_name
        # Clear all old data
        st.session_state.current_lesson = None
        st.session_state.current_explanation = ""
        st.session_state.current_quiz = None
        st.session_state.last_grade = None
        st.toast(f"Student '{student_name}' selected!", icon="✅")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API at {api_url}: {e}")

def fetch_all_concepts():
    """Fetches the full list of concepts for the Explore dropdown."""
    api_url = st.session_state.api_base_url
    try:
        response = requests.get(f"{api_url}/get_all_concepts", timeout=10)
        if response.status_code == 200:
            st.session_state.all_concepts = ["-- Select a Topic --"] + response.json().get("all_concepts", [])
        else:
            st.warning("Could not load concept list from API.")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {e}")

def get_next_lesson_plan():
    """Calls the API to get the agent's recommended next lesson."""
    api_url = st.session_state.api_base_url
    student_name = st.session_state.student_name
    if not student_name:
        st.warning("Please register or select a student first.")
        return
    
    try:
        response = requests.post(f"{api_url}/get_next_step", json={"student_name": student_name}, timeout=30)
        if response.status_code == 200:
            st.session_state.current_lesson = response.json()
            st.session_state.current_step_index = 0
            st.session_state.current_explanation = ""
            st.session_state.current_quiz = None
            st.session_state.last_grade = None
            st.session_state.active_tab = "Agentic Mode (Guided Path)" # Set tab state
        else:
            st.error(f"Error fetching lesson: {response.json().get('detail')}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {e}")

def set_lesson_from_explore(concept_name: str):
    """Manually sets the lesson plan from the 'Explore' dropdown."""
    # FIX: Now calls the API to fetch the proper structured lesson plan
    fetch_selected_concept_structure(concept_name, st.session_state.student_name)


# --- FIX: New function to fetch structure for selected topic ---
def fetch_selected_concept_structure(concept_name: str, student_name: str):
    """
    Calls a new API endpoint to get the full step list for a user-selected concept.
    """
    api_url = st.session_state.api_base_url
    try:
        # We abuse the StudentRequest model since it has the one field we need (the concept name)
        response = requests.post(
            f"{api_url}/get_concept_structure", 
            json={"student_name": concept_name}, 
            timeout=10
        )
        if response.status_code == 200:
            lesson_data = response.json()
            st.session_state.current_lesson = lesson_data
            st.session_state.current_step_index = 0
            st.session_state.current_explanation = ""
            st.session_state.current_quiz = None
            st.session_state.last_grade = None
            st.toast(f"Structured lesson loaded: {concept_name}", icon="📚")
            st.session_state.active_tab = "User-Driven (Explore Curriculum)" # Set tab state
        else:
            st.error(f"Error loading concept structure: {response.json().get('detail')}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {e}")
# ---------------------------------------------------------------


def teach_next_lesson_step():
    """Fetches the explanation for the *current* step in the lesson plan."""
    lesson = st.session_state.current_lesson
    if not lesson:
        st.warning("Please get a lesson plan first.")
        return
        
    step_index = st.session_state.current_step_index
    if step_index >= len(lesson["lesson_steps"]):
        st.warning("Lesson complete! Please run an assessment.")
        return
        
    step_to_teach = lesson["lesson_steps"][step_index]
    api_url = st.session_state.api_base_url
    
    with st.spinner(f"Teaching: {step_to_teach}... (This may take a moment)"):
        try:
            # IMPORTANT: Increased timeout to 90s to prevent LLM generation errors
            response = requests.post(
                f"{api_url}/teach_step", 
                json={"student_name": lesson["student_name"], "concept_name": step_to_teach},
                timeout=90 
            )
            if response.status_code == 200:
                st.session_state.current_explanation = response.json().get("explanation")
                st.session_state.current_step_index += 1
            else:
                st.error(f"Error fetching explanation: {response.json().get('detail')}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to API (Timeout: 90s): {e}")

def handle_explore_select():
    """
    Called when the Explore dropdown changes.
    """
    selected_concept = st.session_state.explore_select
    if selected_concept != "-- Select a Topic --":
        set_lesson_from_explore(selected_concept)
        st.rerun() # Use st.rerun()

# --- V3 Assessment Functions ---

def start_quiz():
    """Calls the API to get quiz questions for the current concept."""
    lesson = st.session_state.current_lesson
    if not lesson:
        st.warning("No lesson active.")
        return

    concept_name = lesson["concept_name"]
    difficulty = st.session_state.quiz_difficulty # Use the selected difficulty
    api_url = st.session_state.api_base_url
    
    with st.spinner(f"Generating {difficulty} quiz for {concept_name}..."):
        try:
            response = requests.post(
                f"{api_url}/start_assessment",
                json={"student_name": st.session_state.student_name, "concept_name": concept_name, "difficulty": difficulty},
                timeout=45
            )
            if response.status_code == 200:
                quiz_data = response.json()
                st.session_state.current_quiz = quiz_data
                st.session_state.current_quiz_index = 0
                st.session_state.last_grade = None
                st.session_state.quiz_answer = "" # Clear old answer
            else:
                st.error(f"Error starting quiz: {response.json().get('detail')}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to API: {e}")

def submit_answer():
    """Submits the user's answer for grading."""
    quiz = st.session_state.current_quiz
    quiz_idx = st.session_state.current_quiz_index
    student_name = st.session_state.student_name
    answer = st.session_state.quiz_answer # Get answer from text_area
    
    if not (quiz and student_name and answer):
        st.warning("Please provide an answer.")
        return

    question = quiz["questions"][quiz_idx]
    concept_name = quiz["concept_name"]
    difficulty = st.session_state.quiz_difficulty # Pass difficulty to API for mastery weighting
    api_url = st.session_state.api_base_url

    with st.spinner("Grading your answer..."):
        try:
            response = requests.post(
                f"{api_url}/submit_answer",
                json={
                    "student_name": student_name,
                    "concept_name": concept_name,
                    "question": question,
                    "user_answer": answer,
                    "difficulty": difficulty # Send difficulty
                },
                timeout=60
            )
            if response.status_code == 200:
                st.session_state.last_grade = response.json()
            else:
                st.error(f"Error grading answer: {response.json().get('detail')}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to API: {e}")

def next_question():
    """Moves to the next question or finishes the quiz."""
    quiz_idx = st.session_state.current_quiz_index
    quiz_len = len(st.session_state.current_quiz["questions"])

    if quiz_idx + 1 < quiz_len:
        # Move to next question
        st.session_state.current_quiz_index += 1
        st.session_state.last_grade = None
        st.session_state.quiz_answer = "" # Clear text_area
        st.rerun() 
    else:
        # Quiz is over
        st.success(f"Quiz complete! Your mastery for {st.session_state.current_quiz['concept_name']} has been updated.")
        st.balloons()
        # Reset state for next lesson
        st.session_state.current_lesson = None
        st.session_state.current_explanation = ""
        st.session_state.current_quiz = None
        st.session_state.last_grade = None
        st.rerun()

# --- Sidebar UI ---
with st.sidebar:
    st.title("🤖 Student Setup")
    
    st.text_input(
        "FastAPI URL",
        value=st.session_state.api_base_url,
        on_change=lambda: set_api_url(st.session_state.new_api_url),
        key="new_api_url"
    )
    
    st.text_input(
        "Enter Student Name",
        key="student_name_input",
        placeholder="e.g., Kartick_Streamlit_Test"
    )
    
    if st.button("Register or Select Student"):
        if st.session_state.student_name_input:
            register_student(st.session_state.student_name_input)
        else:
            st.warning("Please enter a student name.")
            
    st.divider()

    # Load concepts on first render if list is empty
    if not st.session_state.all_concepts:
        fetch_all_concepts()

# --- Main Page UI ---
st.title("Adaptive Teaching Agent Dashboard")
st.markdown("A demonstration of personalized learning using **FastAPI** and **OpenAI/Supabase**.")

if not st.session_state.student_name:
    st.info("Please register or select a student in the sidebar to begin.")
else:
    st.header(f"Teaching Plan for: `{st.session_state.student_name}`")

    # --- Tab Selection (FIX: Stable tab selection) ---
    tab_titles = ["💡 Agentic Mode (Guided Path)", "📚 User-Driven (Explore Curriculum)"]
    
    # The fix for the TypeError is achieved by allowing the tabs to manage their own internal state.
    tab1_container, tab2_container = st.tabs(tab_titles)
    
    # --- Logic to handle content display based on which tab is clicked/active ---
    
    with tab1_container: # Agentic Mode Content
        st.subheader("Agentic Mode: Start Guided Path")
        st.markdown(
            "The **Agent** selects the most relevant concept for you based on prerequisites and your current mastery."
        )
        if st.button("Get Next Lesson Plan", type="primary"):
            get_next_lesson_plan()
        
    with tab2_container: # User-Driven Content
        st.subheader("User-Driven Mode: Select a Topic")
        st.markdown("Choose any topic to learn or revise, bypassing the agent's logic.")
        
        # --- Explore Curriculum Dropdown ---
        selected_concept = st.selectbox(
            "Choose a topic to learn:",
            options=st.session_state.all_concepts,
            key="explore_select",
            on_change=handle_explore_select
        )
        
    st.divider()

    # --- Consolidated UI Layout ---

    # Master Lesson Progress and Explanation in two main columns
    col1, col2 = st.columns([1, 2]) # Ratio 1:2 to give Explanation more space

    with col1:
        st.subheader("Lesson Progress")
        
        # Display the current lesson plan
        lesson = st.session_state.current_lesson
        if lesson and not st.session_state.current_quiz:
            st.info(f"**Concept:** {lesson['concept_name']}")
            
            # Simplified Step List Display
            if lesson["is_structured_lesson"]:
                st.markdown("**Steps:**")
                steps = lesson["lesson_steps"]
                current_step = st.session_state.current_step_index
                for i, step in enumerate(steps):
                    if i < current_step:
                        st.markdown(f"  - ~{step}~ (Completed)")
                    elif i == current_step:
                        st.markdown(f"  - **{step}** 👈")
                    else:
                        st.markdown(f"  - {step}")
            else:
                st.markdown("**Status:**")
                status = "In Progress" if st.session_state.current_step_index == 0 else "Complete"
                st.markdown(f"  - {lesson['lesson_steps'][0]} ({status})")

            # Lesson Action Buttons
            if st.session_state.current_step_index < len(lesson["lesson_steps"]):
                st.button("Teach Next Step", on_click=teach_next_lesson_step, type="secondary")
            else:
                st.success("Lesson Complete! Ready for your quiz.")
                
                # --- QUIZ DIFFICULTY (FIXED LOCATION) ---
                st.markdown("**Quiz Settings**")
                st.selectbox(
                    "Difficulty:",
                    options=["medium", "easy", "hard"],
                    key="quiz_difficulty"
                )
                st.button(f"Start Quiz ({st.session_state.quiz_difficulty.title()})", on_click=start_quiz, type="primary")
        
    with col2:
        st.subheader("Explanation / Quiz")
        if st.session_state.current_explanation and not st.session_state.current_quiz:
            # Explanation in a container to save space
            with st.container(height=400):
                st.markdown(st.session_state.current_explanation)
        elif st.session_state.current_quiz:
            # Quiz UI
            quiz = st.session_state.current_quiz
            quiz_idx = st.session_state.current_quiz_index
            question = quiz["questions"][quiz_idx]
            
            st.markdown(f"**Question {quiz_idx + 1} of {len(quiz['questions'])}**")
            st.info(question)
            
            st.text_area("Your Answer:", key="quiz_answer", height=150)
            
            # Grade/Feedback Display
            if st.session_state.last_grade:
                grade = st.session_state.last_grade
                # Display the raw LLM score
                if grade['score'] > 0.6:
                    st.success(f"**Score: {grade['score']:.2f}** | **Feedback:** {grade['feedback']}")
                else:
                    st.warning(f"**Score: {grade['score']:.2f}** | **Feedback:** {grade['feedback']}")
                
                # Show "Next Question" or "Finish Quiz"
                if quiz_idx + 1 < len(quiz['questions']):
                    st.button("Next Question", on_click=next_question)
                else:
                    st.button("Finish Quiz", on_click=next_question, type="primary")
            else:
                st.button("Submit Answer", on_click=submit_answer, type="secondary")
                
        else:
            st.info("Start a lesson to see the explanation here.")


    # --- Mastery Profile (Consolidated and Reworked) ---
    st.divider()
    
    with st.expander("📊 Student Mastery Profile & Progress"):
        
        # FIX: Refresh button inside the expander
        if st.button("Refresh Progress"):
            api_url = st.session_state.api_base_url
            try:
                response = requests.post(f"{api_url}/get_mastery_profile", json={"student_name": st.session_state.student_name}, timeout=10)
                if response.status_code == 200:
                    profile = response.json().get("mastery_data", {})
                    if profile:
                        st.markdown("### Mastery Score per Concept")
                        
                        # --- NEW Horizontal Bar Visualization ---
                        df = pd.DataFrame(profile.items(), columns=['Concept', 'Mastery'])
                        
                        # Sort by mastery score (optional, but good UX)
                        df = df.sort_values(by='Mastery', ascending=False)
                        
                        for _, row in df.iterrows():
                            concept = row['Concept'].split(': ')[-1]
                            mastery = row['Mastery']
                            
                            # Display Concept Name and Score
                            st.markdown(f"**{concept}** ({mastery:.2f})")
                            
                            # Display Horizontal Progress Bar (using a metric that scales 0 to 1)
                            st.progress(mastery)
                            
                        st.markdown("---")
                        st.markdown("**Raw Data:**")
                        st.json(profile)
                    else:
                        st.info("No mastery data found yet. Complete a lesson to see progress.")
                else:
                    st.error(f"Error fetching profile: {response.json().get('detail')}")
            except requests.exceptions.RequestException as e:
                st.error(f"Error connecting to API: {e}")
        else:
            st.info("Click Refresh Progress to load your current status across the curriculum.")