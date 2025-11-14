# dashboard.py
import streamlit as st
import requests
import pandas as pd
import time

# --- Page Configuration ---
st.set_page_config(
    page_title="Adaptive Teaching Agent",
    page_icon="🤖",
    layout="wide",
)

# --- State Management ---
if "student_name" not in st.session_state:
    st.session_state.student_name = ""
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = "https://teaching-agent-api-946597723332.asia-south1.run.app"
if "current_lesson" not in st.session_state:
    st.session_state.current_lesson = None
if "current_explanation" not in st.session_state:
    st.session_state.current_explanation = ""
if "current_step_index" not in st.session_state:
    st.session_state.current_step_index = 0
if "all_concepts" not in st.session_state:
    st.session_state.all_concepts = []

# V3 state
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

# streaming flags & placeholders
if "is_streaming" not in st.session_state:
    st.session_state.is_streaming = False
# we'll create stream_placeholder in the UI render and store it each run
if "stream_placeholder" not in st.session_state:
    st.session_state.stream_placeholder = None

# --- API Helpers ---
def set_api_url(url: str):
    st.session_state.api_base_url = url

def register_student(student_name: str):
    api_url = st.session_state.api_base_url
    try:
        requests.post(f"{api_url}/register_student", json={"student_name": student_name}, timeout=10)
        st.session_state.student_name = student_name
        st.session_state.current_lesson = None
        st.session_state.current_explanation = ""
        st.session_state.current_quiz = None
        st.session_state.last_grade = None
        st.toast(f"Student '{student_name}' selected!", icon="✅")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API at {api_url}: {e}")

def fetch_all_concepts():
    api_url = st.session_state.api_base_url
    try:
        r = requests.get(f"{api_url}/get_all_concepts", timeout=10)
        if r.status_code == 200:
            st.session_state.all_concepts = ["-- Select a Topic --"] + r.json().get("all_concepts", [])
        else:
            st.warning("Could not load concept list from API.")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {e}")

def get_next_lesson_plan():
    api_url = st.session_state.api_base_url
    student_name = st.session_state.student_name
    if not student_name:
        st.warning("Please register or select a student first.")
        return

    try:
        r = requests.post(f"{api_url}/get_next_step", json={"student_name": student_name}, timeout=30)
        if r.status_code == 200:
            st.session_state.current_lesson = r.json()
            st.session_state.current_step_index = 0
            st.session_state.current_explanation = ""
            st.session_state.current_quiz = None
            st.session_state.last_grade = None
        else:
            st.error(f"Error fetching lesson: {r.json().get('detail')}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {e}")

def fetch_selected_concept_structure(concept_name: str):
    api_url = st.session_state.api_base_url
    try:
        r = requests.post(f"{api_url}/get_concept_structure", json={"student_name": concept_name}, timeout=10)
        if r.status_code == 200:
            st.session_state.current_lesson = r.json()
            st.session_state.current_step_index = 0
            st.session_state.current_explanation = ""
            st.session_state.current_quiz = None
            st.session_state.last_grade = None
            st.toast(f"Structured lesson loaded: {concept_name}", icon="📚")
        else:
            st.error(f"Error loading concept structure: {r.json().get('detail')}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to API: {e}")

# --- Teaching / Streaming functions ---
def teach_next_lesson_step():
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
            r = requests.post(
                f"{api_url}/teach_step",
                json={"student_name": lesson["student_name"], "concept_name": step_to_teach},
                timeout=90
            )
            if r.status_code == 200:
                st.session_state.current_explanation = r.json().get("explanation", "")
                st.session_state.current_step_index += 1
            else:
                st.error(f"Error fetching explanation: {r.json().get('detail')}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to API (Timeout: 90s): {e}")

def teach_next_lesson_step_streaming():
    # Guard against re-entrancy
    if st.session_state.get("is_streaming", False):
        st.warning("Already streaming. Please wait for current stream to finish.")
        return

    lesson = st.session_state.current_lesson
    if not lesson:
        st.warning("Please get a lesson plan first.")
        return

    step_index = st.session_state.current_step_index
    if step_index >= len(lesson["lesson_steps"]):
        st.warning("Lesson complete!")
        return

    concept = lesson["lesson_steps"][step_index]
    api_url = st.session_state.api_base_url

    # if no placeholder available (shouldn't happen normally), create a local one
    placeholder = st.session_state.get("stream_placeholder")
    if placeholder is None:
        placeholder = st.empty()

    st.session_state.is_streaming = True
    accumulated = ""

    try:
        # stream=True enables incremental chunks from server
        with requests.post(
            f"{api_url}/teach_step_stream",
            json={"student_name": lesson["student_name"], "concept_name": concept},
            stream=True,
            timeout=300
        ) as r:
            try:
                r.raise_for_status()
            except Exception as e:
                st.error(f"Stream request failed: {e}")
                return

            # Iterate over lines/chunks as they arrive.
            # This will allow a token-by-token or chunked display depending on the server.
            for chunk in r.iter_lines(decode_unicode=True):
                # chunk may be '' or whitespace if server sends keep-alives; ignore.
                if not chunk:
                    continue
                # append chunk and update placeholder immediately
                accumulated += chunk
                # update placeholder in-place to give a progressive feel.
                placeholder.markdown(accumulated)
                # small sleep can help UI refresh on some hosting environments (optional)
                # time.sleep(0.01)

        # After streaming finishes successfully, store the explanation and advance step
        st.session_state.current_explanation = accumulated
        st.session_state.current_step_index += 1

    except requests.exceptions.RequestException as e:
        st.error(f"Error streaming: {e}")
    except Exception as e:
        st.error(f"Unexpected streaming error: {e}")
    finally:
        st.session_state.is_streaming = False

# --- Quiz & Assessment functions (unchanged) ---
def start_quiz():
    lesson = st.session_state.current_lesson
    if not lesson:
        st.warning("No lesson active.")
        return
    concept_name = lesson["concept_name"]
    difficulty = st.session_state.quiz_difficulty
    api_url = st.session_state.api_base_url
    with st.spinner(f"Generating {difficulty} quiz for {concept_name}..."):
        try:
            r = requests.post(
                f"{api_url}/start_assessment",
                json={"student_name": st.session_state.student_name, "concept_name": concept_name, "difficulty": difficulty},
                timeout=45
            )
            if r.status_code == 200:
                quiz_data = r.json()
                st.session_state.current_quiz = quiz_data
                st.session_state.current_quiz_index = 0
                st.session_state.last_grade = None
                st.session_state.quiz_answer = ""
            else:
                st.error(f"Error starting quiz: {r.json().get('detail')}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to API: {e}")

def submit_answer():
    quiz = st.session_state.current_quiz
    quiz_idx = st.session_state.current_quiz_index
    student_name = st.session_state.student_name
    answer = st.session_state.quiz_answer
    if not (quiz and student_name and answer):
        st.warning("Please provide an answer.")
        return
    question = quiz["questions"][quiz_idx]
    concept_name = quiz["concept_name"]
    difficulty = st.session_state.quiz_difficulty
    api_url = st.session_state.api_base_url

    with st.spinner("Grading your answer..."):
        try:
            r = requests.post(
                f"{api_url}/submit_answer",
                json={
                    "student_name": student_name,
                    "concept_name": concept_name,
                    "question": question,
                    "user_answer": answer,
                    "difficulty": difficulty
                },
                timeout=60
            )
            if r.status_code == 200:
                st.session_state.last_grade = r.json()
            else:
                st.error(f"Error grading answer: {r.json().get('detail')}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to API: {e}")

def next_question():
    quiz_idx = st.session_state.current_quiz_index
    quiz_len = len(st.session_state.current_quiz["questions"])
    if quiz_idx + 1 < quiz_len:
        st.session_state.current_quiz_index += 1
        st.session_state.last_grade = None
        st.session_state.quiz_answer = ""
        st.rerun()
    else:
        st.success(f"Quiz complete! Your mastery for {st.session_state.current_quiz['concept_name']} has been updated.")
        st.balloons()
        st.session_state.current_lesson = None
        st.session_state.current_explanation = ""
        st.session_state.current_quiz = None
        st.session_state.last_grade = None
        st.rerun()

# --- UI: Sidebar ---
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
    if not st.session_state.all_concepts:
        fetch_all_concepts()

# --- UI: Main ---
st.title("Adaptive Teaching Agent Dashboard")
st.markdown("A demonstration of personalized learning using **FastAPI** and **OpenAI/Supabase**.")

if not st.session_state.student_name:
    st.info("Please register or select a student in the sidebar to begin.")
else:
    st.header(f"Teaching Plan for: `{st.session_state.student_name}`")

    tab_titles = ["💡 Agentic Mode (Guided Path)", "📚 User-Driven (Explore Curriculum)"]
    tab1_container, tab2_container = st.tabs(tab_titles)

    with tab1_container:
        st.subheader("Agentic Mode: Start Guided Path")
        st.markdown("The **Agent** selects the most relevant concept for you based on prerequisites and your current mastery.")
        if st.button("Get Next Lesson Plan", type="primary"):
            get_next_lesson_plan()

    with tab2_container:
        st.subheader("User-Driven Mode: Select a Topic")
        st.markdown("Choose any topic to learn or revise, bypassing the agent's logic.")
        selected_concept = st.selectbox(
            "Choose a topic to learn:",
            options=st.session_state.all_concepts,
            key="explore_select"
        )
        if st.button("Load Selected Topic") and selected_concept and selected_concept != "-- Select a Topic --":
            fetch_selected_concept_structure(selected_concept)

    st.divider()

    # --- Layout ---
    col1, col2 = st.columns([1, 2])

    # Left column: lesson progress and controls
    with col1:
        st.subheader("Lesson Progress")
        lesson = st.session_state.current_lesson
        if lesson and not st.session_state.current_quiz:
            st.info(f"**Concept:** {lesson['concept_name']}")
            if lesson.get("is_structured_lesson"):
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

            if st.session_state.current_step_index < len(lesson["lesson_steps"]):
                st.button("Teach Next Step", on_click=teach_next_lesson_step, type="secondary")
                st.button("Teach Next Step (Stream)", on_click=teach_next_lesson_step_streaming, type="primary")
            else:
                st.success("Lesson Complete! Ready for your quiz.")
                st.markdown("**Quiz Settings**")
                st.selectbox("Difficulty:", options=["medium", "easy", "hard"], key="quiz_difficulty")
                st.button(f"Start Quiz ({st.session_state.quiz_difficulty.title()})", on_click=start_quiz, type="primary")

    # Right column: explanation / quiz area
    with col2:
        st.subheader("Explanation / Quiz")
        # ensure a placeholder is present on every render and available to functions
        placeholder = st.empty()
        st.session_state.stream_placeholder = placeholder

        # If streaming is in progress, show the placeholder only (it will be updated by streaming function)
        if st.session_state.get("is_streaming", False):
            placeholder.markdown("Streaming explanation... (tokens arriving)")
        else:
            # not streaming
            # prefer static explanation if it exists AND no quiz is active
            if st.session_state.current_explanation and st.session_state.current_quiz is None:
                # Display static explanation in the placeholder (keeps layout stable)
                placeholder.markdown(st.session_state.current_explanation)
            elif st.session_state.current_quiz:
                # Quiz UI (we don't use stream_placeholder here)
                quiz = st.session_state.current_quiz
                quiz_idx = st.session_state.current_quiz_index
                question = quiz["questions"][quiz_idx]

                st.markdown(f"**Question {quiz_idx + 1} of {len(quiz['questions'])}**")
                st.info(question)
                st.text_area("Your Answer:", key="quiz_answer", height=150)

                if st.session_state.last_grade:
                    grade = st.session_state.last_grade
                    if grade['score'] > 0.6:
                        st.success(f"**Score: {grade['score']:.2f}** | **Feedback:** {grade['feedback']}")
                    else:
                        st.warning(f"**Score: {grade['score']:.2f}** | **Feedback:** {grade['feedback']}")
                    if quiz_idx + 1 < len(quiz['questions']):
                        st.button("Next Question", on_click=next_question)
                    else:
                        st.button("Finish Quiz", on_click=next_question, type="primary")
                else:
                    st.button("Submit Answer", on_click=submit_answer, type="secondary")
            else:
                placeholder.info("Start a lesson to see the explanation here.")

    # --- Mastery profile ---
    st.divider()
    with st.expander("📊 Student Mastery Profile & Progress"):
        if st.button("Refresh Progress"):
            api_url = st.session_state.api_base_url
            try:
                r = requests.post(f"{api_url}/get_mastery_profile", json={"student_name": st.session_state.student_name}, timeout=10)
                if r.status_code == 200:
                    profile = r.json().get("mastery_data", {})
                    if profile:
                        st.markdown("### Mastery Score per Concept")
                        df = pd.DataFrame(profile.items(), columns=['Concept', 'Mastery'])
                        df = df.sort_values(by='Mastery', ascending=False)
                        for _, row in df.iterrows():
                            concept = row['Concept'].split(': ')[-1]
                            mastery = row['Mastery']
                            st.markdown(f"**{concept}** ({mastery:.2f})")
                            st.progress(mastery)
                        st.markdown("---")
                        st.markdown("**Raw Data:**")
                        st.json(profile)
                    else:
                        st.info("No mastery data found yet. Complete a lesson to see progress.")
                else:
                    st.error(f"Error fetching profile: {r.json().get('detail')}")
            except requests.exceptions.RequestException as e:
                st.error(f"Error connecting to API: {e}")
        else:
            st.info("Click Refresh Progress to load your current status across the curriculum.")
