# dashboard.py
import streamlit as st
import requests
import pandas as pd
import time

# --- Page Config ---
st.set_page_config(
    page_title="Adaptive Teaching Agent",
    page_icon="🤖",
    layout="wide",
)

# --- Session State Initialization ---
def init_state(key, default):
    if key not in st.session_state:
        st.session_state[key] = default

init_state("student_name", "")
init_state("api_base_url", "https://teaching-agent-api-946597723332.asia-south1.run.app")
init_state("current_lesson", None)
init_state("current_explanation", "")
init_state("current_step_index", 0)
init_state("all_concepts", [])
init_state("current_quiz", None)
init_state("current_quiz_index", 0)
init_state("last_grade", None)
init_state("quiz_answer", "")
init_state("quiz_difficulty", "medium")
init_state("is_streaming", False)
init_state("stream_placeholder", None)

# --- API Helpers ---
def set_api_url(url: str):
    st.session_state.api_base_url = url

def register_student(student_name: str):
    api = st.session_state.api_base_url
    try:
        requests.post(f"{api}/register_student", json={"student_name": student_name}, timeout=10)
        st.session_state.student_name = student_name
        st.session_state.current_lesson = None
        st.session_state.current_explanation = ""
        st.session_state.current_quiz = None
        st.session_state.last_grade = None
        st.toast(f"Student '{student_name}' selected!", icon="✅")
    except Exception as e:
        st.error(f"API Error: {e}")

def fetch_all_concepts():
    api = st.session_state.api_base_url
    try:
        r = requests.get(f"{api}/get_all_concepts", timeout=10)
        if r.status_code == 200:
            st.session_state.all_concepts = ["-- Select a Topic --"] + r.json()["all_concepts"]
        else:
            st.warning("Could not load concept list.")
    except Exception as e:
        st.error(f"API Error: {e}")

def get_next_lesson_plan():
    api = st.session_state.api_base_url
    student = st.session_state.student_name

    if not student:
        st.warning("Please register a student.")
        return

    try:
        r = requests.post(f"{api}/get_next_step", json={"student_name": student}, timeout=30)
        if r.status_code == 200:
            lesson = r.json()
            st.session_state.current_lesson = lesson
            st.session_state.current_step_index = 0
            st.session_state.current_explanation = ""
            st.session_state.current_quiz = None
            st.session_state.last_grade = None
        else:
            st.error(f"Lesson error: {r.json().get('detail')}")
    except Exception as e:
        st.error(f"API Error: {e}")

def fetch_selected_concept_structure(concept_name: str):
    api = st.session_state.api_base_url
    try:
        r = requests.post(f"{api}/get_concept_structure", json={"student_name": concept_name}, timeout=10)
        if r.status_code == 200:
            lesson = r.json()
            st.session_state.current_lesson = lesson
            st.session_state.current_step_index = 0
            st.session_state.current_explanation = ""
            st.session_state.current_quiz = None
            st.session_state.last_grade = None
            st.toast(f"Loaded: {concept_name}", icon="📚")
        else:
            st.error(f"Error loading concept: {r.json().get('detail')}")
    except Exception as e:
        st.error(f"API Error: {e}")

# --- Streaming Function ---
def teach_next_lesson_step_streaming():
    if st.session_state.is_streaming:
        st.warning("Still streaming…")
        return

    lesson = st.session_state.current_lesson
    if not lesson:
        st.warning("Get a lesson plan first.")
        return

    idx = st.session_state.current_step_index
    if idx >= len(lesson["lesson_steps"]):
        st.warning("Lesson Complete!")
        return

    concept = lesson["lesson_steps"][idx]
    api = st.session_state.api_base_url

    placeholder = st.session_state.stream_placeholder or st.empty()
    st.session_state.stream_placeholder = placeholder

    st.session_state.is_streaming = True
    accumulated = ""

    try:
        with requests.post(
            f"{api}/teach_step_stream",
            json={"student_name": lesson["student_name"], "concept_name": concept},
            stream=True,
            timeout=300
        ) as r:
            r.raise_for_status()

            for chunk in r.iter_lines(decode_unicode=True):
                if not chunk:
                    continue

                accumulated += chunk

                # Styled scrollable card
                placeholder.markdown(
                    f"""
                    <div style="
                        padding:1rem;
                        border-radius:10px;
                        background-color:#0f172a;
                        color:#ffffff;
                        height:350px;
                        overflow-y:auto;
                        font-size:1.05rem;
                        line-height:1.65;
                    ">{accumulated}</div>
                    """,
                    unsafe_allow_html=True
                )

        st.session_state.current_explanation = accumulated
        st.session_state.current_step_index += 1

    except Exception as e:
        st.error(f"Streaming Error: {e}")

    finally:
        st.session_state.is_streaming = False

# --- Quiz Functions ---
def start_quiz():
    lesson = st.session_state.current_lesson
    if not lesson:
        st.warning("No lesson active.")
        return

    api = st.session_state.api_base_url
    difficulty = st.session_state.quiz_difficulty
    student = st.session_state.student_name
    concept = lesson["concept_name"]

    with st.spinner("Generating quiz…"):
        try:
            r = requests.post(
                f"{api}/start_assessment",
                json={"student_name": student, "concept_name": concept, "difficulty": difficulty},
                timeout=45
            )
            if r.status_code == 200:
                st.session_state.current_quiz = r.json()
                st.session_state.current_quiz_index = 0
                st.session_state.last_grade = None
                st.session_state.quiz_answer = ""
            else:
                st.error(r.json().get("detail"))
        except Exception as e:
            st.error(f"API Error: {e}")

def submit_answer():
    quiz = st.session_state.current_quiz
    idx = st.session_state.current_quiz_index
    answer = st.session_state.quiz_answer
    student = st.session_state.student_name

    if not answer:
        st.warning("Please provide an answer.")
        return

    api = st.session_state.api_base_url
    q = quiz["questions"][idx]
    concept = quiz["concept_name"]

    with st.spinner("Grading…"):
        try:
            r = requests.post(
                f"{api}/submit_answer",
                json={
                    "student_name": student,
                    "concept_name": concept,
                    "question": q,
                    "user_answer": answer,
                    "difficulty": st.session_state.quiz_difficulty
                },
                timeout=60
            )
            if r.status_code == 200:
                st.session_state.last_grade = r.json()
            else:
                st.error(r.json().get("detail"))
        except Exception as e:
            st.error(f"API Error: {e}")

def next_question():
    idx = st.session_state.current_quiz_index
    total = len(st.session_state.current_quiz["questions"])

    if idx + 1 < total:
        st.session_state.current_quiz_index += 1
        st.session_state.last_grade = None
        st.session_state.quiz_answer = ""
        st.rerun()
    else:
        st.success("Quiz Finished! 🎉")
        st.balloons()
        st.session_state.current_lesson = None
        st.session_state.current_explanation = ""
        st.session_state.current_quiz = None
        st.rerun()

# --- UI: Sidebar ---
with st.sidebar:
    st.title("🤖 Student Setup")

    st.text_input(
        "FastAPI URL",
        value=st.session_state.api_base_url,
        key="new_api_url",
        on_change=lambda: set_api_url(st.session_state.new_api_url)
    )

    st.text_input("Enter Student Name", key="student_name_input")

    if st.button("Register or Select Student"):
        if st.session_state.student_name_input.strip():
            register_student(st.session_state.student_name_input.strip())
        else:
            st.warning("Enter a name.")

    st.divider()

    if not st.session_state.all_concepts:
        fetch_all_concepts()

# --- Main UI ---
st.title("Adaptive Teaching Agent Dashboard")
st.markdown("Built with **FastAPI**, **Streamlit**, **OpenAI**, and **Supabase**.")

if not st.session_state.student_name:
    st.info("Please register a student to start.")
    st.stop()

st.header(f"Teaching Plan for `{st.session_state.student_name}`")

# Tabs
tab1, tab2 = st.tabs(["💡 Agentic Mode", "📚 Explore Curriculum"])

with tab1:
    st.subheader("Guided Path")
    if st.button("Get Next Lesson Plan", type="primary"):
        get_next_lesson_plan()

with tab2:
    st.subheader("Select a Topic")
    selected = st.selectbox("Topic:", st.session_state.all_concepts)
    if selected not in ["", "-- Select a Topic --"] and st.button("Load Topic"):
        fetch_selected_concept_structure(selected)

st.divider()

# Two-column main layout
col1, col2 = st.columns([1, 2])

# --- Left Column: Lesson Steps ---
with col1:
    st.subheader("Lesson Progress")
    lesson = st.session_state.current_lesson

    if lesson and not st.session_state.current_quiz:
        st.info(f"**Concept:** {lesson['concept_name']}")

        steps = lesson["lesson_steps"]
        idx = st.session_state.current_step_index

        st.markdown("**Steps:**")
        for i, step in enumerate(steps):
            if i < idx:
                st.markdown(f"- ~{step}~ (Completed)")
            elif i == idx:
                st.markdown(f"- **{step}** 👈 (Now)")
            else:
                st.markdown(f"- {step}")

        if idx < len(steps):
            st.button("Teach Next Step", on_click=teach_next_lesson_step_streaming, type="primary")
        else:
            st.success("Lesson Complete! Begin your quiz.")
            st.selectbox("Difficulty:", ["medium", "easy", "hard"], key="quiz_difficulty")
            st.button(f"Start Quiz ({st.session_state.quiz_difficulty.title()})", on_click=start_quiz, type="primary")

# --- Right Column: Explanation / Quiz ---
with col2:
    st.subheader("Explanation / Quiz")

    placeholder = st.empty()
    st.session_state.stream_placeholder = placeholder

    if st.session_state.is_streaming:
        placeholder.info("Streaming… tokens arriving...")
    elif st.session_state.current_quiz:
        quiz = st.session_state.current_quiz
        idx = st.session_state.current_quiz_index
        q = quiz["questions"][idx]

        st.markdown(f"**Question {idx + 1} of {len(quiz['questions'])}**")
        st.info(q)
        st.text_area("Your Answer:", key="quiz_answer", height=150)

        if st.session_state.last_grade:
            grade = st.session_state.last_grade
            if grade["score"] > 0.6:
                st.success(f"Score: {grade['score']:.2f} | {grade['feedback']}")
            else:
                st.warning(f"Score: {grade['score']:.2f} | {grade['feedback']}")

            if idx + 1 < len(quiz["questions"]):
                st.button("Next Question", on_click=next_question)
            else:
                st.button("Finish Quiz", on_click=next_question, type="primary")
        else:
            st.button("Submit Answer", on_click=submit_answer, type="secondary")

    elif st.session_state.current_explanation:
        placeholder.markdown(
            f"""
            <div style="
                padding:1rem;
                border-radius:10px;
                background-color:#0f172a;
                color:white;
                height:350px;
                overflow-y:auto;
                font-size:1.05rem;
                line-height:1.65;
            ">{st.session_state.current_explanation}</div>
            """,
            unsafe_allow_html=True
        )
    else:
        placeholder.info("Start a lesson to see the explanation.")

# --- Mastery Profile ---
st.divider()
with st.expander("📊 Mastery Profile"):
    if st.button("Refresh Progress"):
        api = st.session_state.api_base_url
        try:
            r = requests.post(f"{api}/get_mastery_profile", json={"student_name": st.session_state.student_name}, timeout=10)
            if r.status_code == 200:
                profile = r.json()["mastery_data"]
                if profile:
                    df = pd.DataFrame(profile.items(), columns=["Concept", "Mastery"]).sort_values("Mastery", ascending=False)

                    st.markdown("### Mastery Scores")
                    for _, row in df.iterrows():
                        st.markdown(f"**{row['Concept'].split(': ')[-1]}** ({row['Mastery']:.2f})")
                        st.progress(row["Mastery"])
                    st.json(profile)
                else:
                    st.info("No mastery data yet.")
            else:
                st.error(r.json().get("detail"))
        except Exception as e:
            st.error(f"API Error: {e}")
    else:
        st.info("Click to load progress.")
