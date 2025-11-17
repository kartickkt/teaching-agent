# dashboard.py (REVISED FOR SEQUENTIAL GATED FLOW)
import streamlit as st
import requests
import pandas as pd
import time
from typing import List, Dict, Any

# --- Page Config ---
st.set_page_config(
    page_title="Sequential Gated Teaching Agent",
    page_icon="🤖",
    layout="wide",
)

# --- Session State Initialization ---
def init_state(key, default):
    if key not in st.session_state:
        st.session_state[key] = default

init_state("student_name", "")
init_state("api_base_url", "https://teaching-agent-api-946597723332.asia-south1.run.app")
init_state("current_lesson_order", 1) # Track the current lesson number (1-9)
init_state("completed_lessons", [])   # List of completed lesson orders
init_state("current_lesson_state", None) # Stores response from /program/start (diagnostic, teaching, etc.)
init_state("current_explanation", "")
init_state("current_sub_concept_index", 0) # For teaching sub-concepts sequentially
init_state("all_concepts", [])
init_state("current_quiz_data", None) # Stores the 5 MCQ + 3 Open quiz data
init_state("mcq_answers_storage", {}) # Storage for MCQ selections before submission
init_state("quiz_difficulty", "medium")
init_state("is_streaming", False)
init_state("stream_placeholder", None)
init_state("feedback_details", None) # Stores grading results (scores, feedback)
init_state("mastery_dashboard_data", None) # Stores structured mastery data for the dashboard

# --- API Helpers ---
def set_api_url(url: str):
    st.session_state.api_base_url = url

def register_student(student_name: str):
    api = st.session_state.api_base_url
    try:
        requests.post(f"{api}/register_student", json={"student_name": student_name}, timeout=10)
        st.session_state.student_name = student_name
        # Fetch initial progress state on successful registration/selection
        get_current_program_status() 
        st.toast(f"Student '{student_name}' selected!", icon="✅")
    except Exception as e:
        st.error(f"API Error: {e}")

def fetch_all_concepts():
    # This remains for the "Explore Curriculum" tab
    api = st.session_state.api_base_url
    try:
        # NOTE: This endpoint might not exist anymore, or it might need to be created 
        # based on the new curriculum structure.
        # For simplicity, let's keep the old endpoint call for now, assuming it returns sub-concepts.
        r = requests.get(f"{api}/get_all_concepts", timeout=10) 
        if r.status_code == 200:
            st.session_state.all_concepts = ["-- Select a Topic --"] + r.json()["all_concepts"]
        else:
            st.warning("Could not load concept list.")
    except Exception as e:
        # In the new API, we might need a dedicated endpoint to list all high-level concepts
        st.error(f"API Error fetching all concepts: {e}")


def get_current_program_status(lesson_order_override: Optional[int] = None):
    """Calls the new /program/start endpoint to get the current state (Diagnostic/Complete)."""
    api = st.session_state.api_base_url
    student = st.session_state.student_name
    
    if not student:
        st.warning("Please register a student.")
        return

    payload = {"student_name": student}
    if lesson_order_override is not None:
        payload["lesson_order"] = lesson_order_override

    with st.spinner(f"Loading Lesson {lesson_order_override if lesson_order_override else 'Current'}..."):
        try:
            # New Endpoint: /program/start
            r = requests.post(f"{api}/program/start", json=payload, timeout=30)
            if r.status_code == 200:
                lesson_state = r.json()
                st.session_state.current_lesson_state = lesson_state
                st.session_state.current_lesson_order = lesson_state.get("lesson_order", 1)
                st.session_state.completed_lessons = lesson_state.get("completed_lessons", [])
                st.session_state.current_explanation = ""
                st.session_state.current_sub_concept_index = 0
                st.session_state.feedback_details = None
                st.session_state.mcq_answers_storage = {}
                
                if lesson_state.get("status") == "diagnostic_required":
                    st.session_state.current_quiz_data = lesson_state["quiz"]
                    st.toast(f"Diagnostic for Lesson {lesson_state['lesson_order']} loaded!", icon="📝")
                else:
                    st.session_state.current_quiz_data = None
                    st.toast(lesson_state.get("message", "Program status updated."), icon="ℹ️")

            else:
                st.error(f"Program status error: {r.json().get('detail')}")
        except Exception as e:
            st.error(f"API Error: {e}")

def submit_composite_quiz(quiz_type: str):
    """Submits the full composite quiz (MCQ + Open) to the corresponding endpoint."""
    
    lesson_order = st.session_state.current_lesson_order
    quiz_data = st.session_state.current_quiz_data
    
    # 1. Gather all answers into the correct structure
    mcq_submissions = []
    for q_data in quiz_data["mcq"]:
        # Get the selected answer from the session state storage
        selection = st.session_state.mcq_answers_storage.get(q_data["question"])
        mcq_submissions.append({
            "question": q_data["question"],
            "options": q_data["options"],
            "user_selection": selection,
            "answer": q_data["answer"], # We send the answer key back for easy grading on the backend
        })

    open_submissions = []
    for i, q_text in enumerate(quiz_data["open_questions"]):
        # The key for the text area input is generated in render_full_quiz_form
        answer = st.session_state.get(f"open_answer_{i}", "") 
        open_submissions.append({
            "question": q_text,
            "user_answer": answer
        })

    submissions_payload = {
        "mcq_answers": mcq_submissions,
        "open_questions": open_submissions
    }
    
    # 2. Determine Endpoint and Payload
    api = st.session_state.api_base_url
    student = st.session_state.student_name
    
    endpoint = f"{api}/program/submit_diagnostic" if quiz_type == "diagnostic" else f"{api}/program/finish_quiz"
    
    payload = {
        "student_name": student,
        "lesson_order": lesson_order,
        "submissions": submissions_payload
    }

    with st.spinner("Grading composite quiz..."):
        try:
            r = requests.post(endpoint, json=payload, timeout=90)
            if r.status_code == 200:
                result = r.json()
                st.session_state.current_lesson_state = result
                st.session_state.feedback_details = result.get("grading_details")
                st.session_state.current_quiz_data = None # Clear quiz after submission
                
                # Re-fetch the status to update completed lessons/current order
                get_current_program_status(result.get("next_lesson_order")) 
                st.rerun()

            else:
                st.error(f"Submission error: {r.json().get('detail')}")
        except Exception as e:
            st.error(f"API Error during submission: {e}")

def skip_to_next_lesson():
    """Handles the 'Move to next lesson' option after passing the diagnostic."""
    api = st.session_state.api_base_url
    student = st.session_state.student_name
    lesson_order = st.session_state.current_lesson_order
    
    # Call submit_diagnostic with skip_mode=True (quiz_submissions is empty/ignored)
    payload = {
        "student_name": student,
        "lesson_order": lesson_order,
        "submissions": {"mcq_answers": [], "open_questions": []},
        "skip_mode": True
    }
    
    with st.spinner("Skipping lesson..."):
        try:
            r = requests.post(f"{api}/program/submit_diagnostic", json=payload, timeout=30)
            if r.status_code == 200:
                result = r.json()
                st.toast(result.get("message", "Skipped!"), icon="⏭️")
                # Immediately fetch the diagnostic for the next lesson
                get_current_program_status(result.get("next_lesson_order"))
                st.rerun()
            else:
                st.error(f"Skip error: {r.json().get('detail')}")
        except Exception as e:
            st.error(f"API Error: {e}")


# --- Streaming Function ---
def teach_next_sub_concept_streaming(lesson_order: int, concept_name: str):
    """Streams content for a single sub-concept or structured teaching step."""
    if st.session_state.is_streaming:
        st.warning("Still streaming...")
        return

    api = st.session_state.api_base_url
    placeholder = st.session_state.stream_placeholder or st.empty()
    st.session_state.stream_placeholder = placeholder

    st.session_state.is_streaming = True
    accumulated = ""
    st.session_state.current_explanation = "" # Reset explanation at start

    try:
        # New Endpoint: /program/teach_step_stream
        with requests.post(
            f"{api}/program/teach_step_stream",
            json={
                "student_name": st.session_state.student_name, 
                "lesson_order": lesson_order,
                "concept_name": concept_name
            },
            stream=True,
            timeout=300
        ) as r:
            r.raise_for_status()

            # Clear placeholder before streaming
            placeholder.empty()

            for chunk in r.iter_lines(decode_unicode=True):
                if not chunk: continue
                
                # Simple markdown rendering, updated dynamically
                accumulated += chunk
                
                # Check for explicit errors from the backend generator
                if 'error' in accumulated.lower() and len(accumulated) < 500:
                    st.error(f"Backend streaming error: {accumulated}")
                    break

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
        
        # Advance the teaching index after successful completion
        state = st.session_state.current_lesson_state
        sub_concepts = state["sub_concepts_list"]
        idx = st.session_state.current_sub_concept_index
        
        if idx + 1 < len(sub_concepts):
            st.session_state.current_sub_concept_index += 1
            st.toast(f"Completed '{concept_name}'. Ready for the next sub-concept.", icon="➡️")
        else:
            st.toast("Structured Lesson Complete! Time for the final quiz.", icon="✅")

    except Exception as e:
        st.error(f"Streaming Error: {e}")

    finally:
        st.session_state.is_streaming = False


# --- UI Components ---

def render_full_quiz_form(quiz_type: str):
    """Renders the combined 5 MCQ + 3 Open-Answer submission form."""
    
    quiz = st.session_state.current_quiz_data
    if not quiz:
        st.info("Quiz data is loading or missing.")
        return
    
    st.header(f"Quiz: {quiz_type.title()}")
    st.markdown("---")

    # --- Part 1: Multiple Choice Questions (5 Questions) ---
    st.subheader("Part 1: Multiple Choice Questions (MCQ)")
    
    for i, q_data in enumerate(quiz["mcq"]):
        st.markdown(f"**{i+1}. {q_data['question']}**")
        
        options = q_data["options"]
        
        # Use a Streamlit radio button and link its value to the session state storage
        selected = st.radio(
            f"Select the answer for Q{i+1}:",
            options=options,
            index=options.index(st.session_state.mcq_answers_storage.get(q_data["question"])) if st.session_state.mcq_answers_storage.get(q_data["question"]) else None,
            key=f"mcq_{i}",
            on_change=lambda q=q_data["question"], key=f"mcq_{i}": st.session_state.mcq_answers_storage.update({q: st.session_state[key]})
        )
    
    st.markdown("---")

    # --- Part 2: Open-Ended Questions (3 Questions) ---
    st.subheader("Part 2: Short Open Answers")
    
    for i, q_text in enumerate(quiz["open_questions"]):
        st.markdown(f"**{i+6}. {q_text}**") # Q6, Q7, Q8
        st.text_area(
            f"Your short answer for Q{i+6}:", 
            key=f"open_answer_{i}", 
            height=100
        )
        
    st.markdown("---")

    st.button(f"Submit All and Grade ({quiz_type.title()})", 
              on_click=lambda: submit_composite_quiz(quiz_type), 
              type="primary")


def render_mastery_dashboard():
    """Renders the structured mastery dashboard based on the new API endpoint."""
    
    api = st.session_state.api_base_url
    student = st.session_state.student_name

    @st.cache_data(ttl=60)
    def fetch_dashboard_data(student_name: str, api_url: str):
        try:
            r = requests.post(f"{api_url}/dashboard/mastery", json={"student_name": student_name}, timeout=10)
            r.raise_for_status()
            return r.json()["dashboard_data"]
        except Exception as e:
            st.error(f"Error fetching dashboard data: {e}")
            return []

    if st.button("Refresh Mastery Dashboard"):
        st.session_state.mastery_dashboard_data = fetch_dashboard_data(student, api)

    if not st.session_state.mastery_dashboard_data:
        st.info("Click the button to load your current mastery and lesson progress.")
        return

    # Use a dictionary to track overall summary
    summary_data = []

    for lesson in st.session_state.mastery_dashboard_data:
        hl_name = lesson['high_level_concept']
        hl_mastery = lesson['mastery']
        is_completed = lesson['completed']
        lesson_order = lesson['lesson_order']
        
        summary_data.append({
            "Order": lesson_order,
            "Lesson": hl_name,
            "Completed": "✅" if is_completed else "➡️" if lesson_order == st.session_state.current_lesson_order else "❌",
            "Mastery Score": f"{hl_mastery:.2f}",
        })
        
        # Display the high-level mastery and progress bar
        st.markdown(f"### Lesson {lesson_order}: {hl_name} {'(Completed)' if is_completed else ''}")
        st.progress(hl_mastery, text=f"Overall Mastery: {hl_mastery:.1%}")

        # Display sub-concept mastery data in an expander
        with st.expander("Sub-Concept Breakdown"):
            sub_df = pd.DataFrame(lesson['sub_concepts'])
            sub_df.columns = ["Sub-Concept", "Mastery"]
            sub_df = sub_df[sub_df["Mastery"] > 0.0] # Filter out unstarted concepts
            
            if not sub_df.empty:
                st.dataframe(sub_df.sort_values('Mastery', ascending=False), 
                             hide_index=True, 
                             use_container_width=True)
            else:
                 st.info("No recorded mastery for sub-concepts yet.")
    
    st.markdown("---")
    st.subheader("Program Summary")
    st.dataframe(pd.DataFrame(summary_data).set_index("Order"), hide_index=False, use_container_width=True)


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

    st.markdown(f"**Current Lesson:** **{st.session_state.current_lesson_order}**")
    if st.session_state.current_lesson_state and st.session_state.current_lesson_state.get("lesson_name"):
        st.markdown(f"*{st.session_state.current_lesson_state['lesson_name']}*")

    st.markdown("**Completed Lessons:**")
    st.code(", ".join(map(str, sorted(st.session_state.completed_lessons))))

# --- Main UI ---
st.title("Sequential Gated Teaching Agent Dashboard")
st.markdown("Built with **FastAPI**, **Streamlit**, **OpenAI**, and **Postgres**.")

if not st.session_state.student_name:
    st.info("Please register a student to start.")
    st.stop()

st.header(f"Teaching Flow for `{st.session_state.student_name}`")

# Tabs
tab1, tab2, tab3 = st.tabs(["💡 Guided Flow (Sequential)", "📚 Explore Curriculum (TODO)", "📊 Mastery Dashboard"])

with tab1:
    state = st.session_state.current_lesson_state
    
    if st.button("Load/Advance Program Status", type="primary"):
        get_current_program_status()

    st.divider()

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Lesson Progress")
        
        if not state:
            st.info("Click 'Load/Advance Program Status' to start Lesson 1.")
        elif state["status"] == "complete":
            st.success("🎉 Curriculum Complete! Great job.")
        elif state["status"] == "diagnostic_required" or state["status"] == "passed_diagnostic":
            lesson_name = state.get("lesson_name", f"Lesson {state['lesson_order']}")
            st.warning(f"**Gate Check:** Diagnostic for **{lesson_name}** is required.")
        elif state["status"] in ["start_teaching", "lesson_failed"]:
            st.info(f"**Structured Study:** {state['high_level_name']}")
            
            # Sub-concept list rendering
            sub_concepts = state["sub_concepts_list"]
            idx = st.session_state.current_sub_concept_index

            st.markdown("**Sub-Concepts:**")
            for i, concept in enumerate(sub_concepts):
                status_icon = "🟢" if i < idx else ("🟡" if i == idx else "⚪")
                st.markdown(f"- {status_icon} **{concept}**")

            if idx < len(sub_concepts):
                next_concept = sub_concepts[idx]
                st.button(f"Teach Next: **{next_concept}**", 
                          on_click=lambda: teach_next_sub_concept_streaming(state['lesson_order'], next_concept), 
                          type="primary")
            else:
                st.success("All concepts covered! Time for the final lesson quiz.")
                # Final Quiz button triggers the diagnostic render
                st.button("Start Final Lesson Quiz", on_click=lambda: st.session_state.current_quiz_data.update(st.session_state.current_lesson_state.get("quiz", {})), type="primary") # Re-load quiz data if needed
                
    with col2:
        st.subheader("Content & Assessment")
        
        placeholder = st.empty()
        st.session_state.stream_placeholder = placeholder

        # --- Render Logic based on State ---

        if state and state["status"] == "passed_diagnostic":
            # State: Diagnostic passed, offer choice to skip or study
            st.success(f"Score: **{state['score']:.1%}** (Pass!)")
            st.info(f"You passed the diagnostic for Lesson {state['lesson_order']}. What would you like to do?")
            
            if st.button("Move to Next Lesson (Skip)", type="primary"):
                skip_to_next_lesson()
            
            if st.button("Study this Lesson Anyway"):
                # Transition to teaching state without re-grading the quiz
                service = TeachingLoopService(st.session_state.student_name)
                teaching_state = service._start_structured_teaching(state['lesson_order'], state['lesson_name'])
                st.session_state.current_lesson_state = teaching_state
                st.rerun()

        elif st.session_state.current_quiz_data:
            # State: Diagnostic or Final Quiz is active
            quiz_type = "diagnostic" if state and state["status"] == "diagnostic_required" else "final"
            render_full_quiz_form(quiz_type)
        
        elif st.session_state.current_explanation:
            # State: Explanation streaming finished
            if st.session_state.feedback_details:
                st.info(f"Composite Score: {st.session_state.feedback_details.get('composite_score', 0.0):.1%}")
                with st.expander("Detailed Grading Feedback"):
                    for grade in st.session_state.feedback_details.get('graded_open_answers', []):
                         st.markdown(f"**Q:** {grade['question']}")
                         st.markdown(f"**Score:** {grade['score']:.2f}")
                         st.markdown(f"**Feedback:** *{grade['feedback']}*")
                    st.markdown(f"**MCQ Correct:** {st.session_state.feedback_details.get('mcq_correct', 0)}/5")
            
            # Show the streamed explanation in the placeholder (handled by streaming function itself)
            # The static version is needed if the user navigates away and back
            if st.session_state.stream_placeholder:
                st.session_state.stream_placeholder.markdown(
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
            placeholder.info("Start the program flow to begin Lesson 1.")

with tab2:
    st.subheader("Explore Curriculum (Not part of the main sequential flow)")
    st.warning("This tab uses the old API calls. Integration with the new sequential structure requires a dedicated design.")
    # You can re-implement the old 'Explore' logic here if you need it.

with tab3:
    render_mastery_dashboard()