# dashboard.py
"""
Streamlit dashboard for Sequential Gated Teaching Agent
- Guided Flow (diagnostic -> study -> final quiz)
- Practice MCQs (pick HL concept + difficulty -> 10 MCQs)
- Mastery Dashboard (per-lesson & sub-concept)
"""
import streamlit as st
import requests
import pandas as pd
import time
from typing import List, Dict, Any, Optional

# -------------------------
# Page config & helpers
# -------------------------
st.set_page_config(page_title="Adaptive Teaching Agent", page_icon="🤖", layout="wide")

def init_state(key, default):
    if key not in st.session_state:
        st.session_state[key] = default

# Initialize session state
init_state("student_name", "")
init_state("api_base_url", "https://teaching-agent-api-946597723332.asia-south1.run.app")
init_state("current_lesson_order", 1)
init_state("completed_lessons", [])
init_state("current_lesson_state", None)
init_state("current_quiz_data", None)  # holds diagnostic or final quiz (mcq + open_questions)
init_state("mcq_answers_storage", {})   # mapping question_id/text -> selected option index or option text
init_state("open_answers_storage", {})  # mapping open index -> text
init_state("is_streaming", False)
init_state("stream_placeholder", None)
init_state("current_explanation", "")
init_state("mastery_dashboard_data", None)
init_state("practice_quiz", None)      # holds practice quiz object
init_state("practice_answers", {})     # mapping qid -> selected index
init_state("practice_difficulty", "medium")
init_state("practice_concept", None)
init_state("api_timeout", 30)

# -------------------------
# API helpers
# -------------------------
def api_post(path: str, payload: Dict[str, Any], timeout: Optional[int] = None, stream: bool = False):
    url = st.session_state.api_base_url.rstrip("/") + "/" + path.lstrip("/")
    try:
        if stream:
            return requests.post(url, json=payload, stream=True, timeout=timeout or 300)
        return requests.post(url, json=payload, timeout=timeout or st.session_state.api_timeout)
    except requests.exceptions.RequestException as e:
        st.error(f"Network/API error calling {path}: {e}")
        return None

def api_get(path: str, timeout: Optional[int] = None):
    url = st.session_state.api_base_url.rstrip("/") + "/" + path.lstrip("/")
    try:
        return requests.get(url, timeout=timeout or st.session_state.api_timeout)
    except requests.exceptions.RequestException as e:
        st.error(f"Network/API error GET {path}: {e}")
        return None

# provide helper functions referenced in sidebar above (defined after they are used)
def get_program_status(lesson_order_override: Optional[int] = None):
    if not st.session_state.student_name:
        st.warning("Register a student first on the sidebar.")
        return
    payload = {"student_name": st.session_state.student_name}
    if lesson_order_override:
        payload["lesson_order"] = int(lesson_order_override)
    with st.spinner("Fetching program status..."):
        r = api_post("/program/start", payload, timeout=30)
        if not r:
            return
        try:
            r.raise_for_status()
            state = r.json()
            st.session_state.current_lesson_state = state
            st.session_state.current_lesson_order = state.get("lesson_order", st.session_state.current_lesson_order)
            st.session_state.completed_lessons = state.get("completed_lessons", [])
            # If diagnostic present, store quiz
            quiz = state.get("quiz")
            if quiz and isinstance(quiz, dict):
                # Normalize shape: ensure keys mcq/open_questions exist
                mcq = quiz.get("mcq") or quiz.get("mcqs") or quiz.get("questions") or []
                open_q = quiz.get("open_questions") or quiz.get("opens") or quiz.get("open_questions", []) or []
                st.session_state.current_quiz_data = {"mcq": mcq, "open_questions": open_q}
                # Reset answer storage
                st.session_state.mcq_answers_storage = {}
                st.session_state.open_answers_storage = {}
            else:
                st.session_state.current_quiz_data = None
            st.success("Program status loaded.")
        except Exception as e:
            st.error(f"Failed to parse program status response: {e}")

def load_mastery_dashboard():
    if not st.session_state.student_name:
        st.warning("Select a student to load mastery data.")
        return
    payload = {"student_name": st.session_state.student_name}
    r = api_post("/dashboard/mastery", payload, timeout=15)
    if not r:
        return
    try:
        r.raise_for_status()
        j = r.json()
        st.session_state.mastery_dashboard_data = j.get("dashboard_data") or j.get("data") or []
        st.success("Mastery dashboard loaded.")
    except Exception as e:
        st.error(f"Failed to load mastery: {e}")

# -------------------------
# Student registration
# -------------------------
with st.sidebar:
    st.title("🤖 Student & API")
    new_api = st.text_input("FastAPI URL", value=st.session_state.api_base_url, key="new_api_url")
    if st.button("Set API URL"):
        if new_api:
            st.session_state.api_base_url = new_api.strip()
            st.toast("API URL updated", icon="🔁")
        else:
            st.warning("Enter a valid URL")

    name_input = st.text_input("Student Name", key="student_name_input", placeholder="e.g., Kartick")
    if st.button("Register / Select Student"):
        name = name_input.strip()
        if not name:
            st.warning("Please enter a student name.")
        else:
            resp = api_post("/register_student", {"student_name": name}, timeout=10)
            if resp and resp.status_code == 200:
                st.session_state.student_name = name
                st.toast(f"Student selected: {name}", icon="✅")
                # refresh program status automatically
                get_program_status()
            else:
                st.error("Failed to register student. Check backend logs.")

    st.markdown("---")
    st.markdown("**Quick Controls**")
    if st.button("Refresh Program Status"):
        get_program_status()
    if st.button("Refresh Mastery Dashboard"):
        load_mastery_dashboard()
    st.write("API:", st.session_state.api_base_url)


# -------------------------
# Practice helpers
# -------------------------
def generate_practice_quiz(hl_concept: str, difficulty: str):
    if not st.session_state.student_name:
        st.warning("Register / select a student in the sidebar first.")
        return
    payload = {
        "student_name": st.session_state.student_name,
        "hl_concept_name": hl_concept,
        "difficulty": difficulty
    }
    with st.spinner("Generating practice quiz..."):
        r = api_post("/practice/generate_quiz", payload, timeout=30)
        if not r:
            return
        try:
            r.raise_for_status()
            q = r.json()
            # Expect { "concept_name":..., "questions":[{id,text,options,...}] }
            st.session_state.practice_quiz = q
            st.session_state.practice_answers = {}
            st.toast("Practice quiz ready", icon="📝")
        except Exception as e:
            st.error(f"Failed to generate practice quiz: {e}")

def submit_practice_quiz():
    quiz = st.session_state.practice_quiz
    if not quiz:
        st.warning("No practice quiz loaded.")
        return
    questions = quiz.get("questions", [])
    # compute score (simple compare with provided answer or assume answer_index)
    correct = 0
    for q in questions:
        qid = q.get("id") or q.get("question")[:40]
        selected = st.session_state.practice_answers.get(qid)
        # support different quiz shapes:
        # - q may have 'answer_index' or 'answer' (index or text)
        answer_index = q.get("answer_index")
        answer_value = q.get("answer")  # could be index or string
        options = q.get("options") or q.get("choices") or []
        # normalize selected: if selected is index or option text
        sel_index = None
        if isinstance(selected, int):
            sel_index = selected
        elif isinstance(selected, str) and options:
            try:
                sel_index = options.index(selected)
            except ValueError:
                sel_index = None
        # determine correct
        is_correct = False
        if isinstance(answer_index, int) and sel_index is not None:
            is_correct = (sel_index == int(answer_index))
        elif isinstance(answer_value, int) and sel_index is not None:
            is_correct = (sel_index == int(answer_value))
        elif isinstance(answer_value, str) and options and sel_index is not None:
            is_correct = (options[sel_index] == answer_value)
        # fallback: if answer stored as text and user chose same text
        if isinstance(answer_value, str) and isinstance(selected, str):
            is_correct = (answer_value.strip() == selected.strip())
        if is_correct:
            correct += 1

    score = correct / max(1, len(questions))
    # Optionally call backend to record practice score
    payload = {
        "student_name": st.session_state.student_name,
        "hl_concept_name": st.session_state.practice_quiz.get("concept_name"),
        "difficulty": st.session_state.practice_difficulty,
        "score": score
    }
    with st.spinner("Submitting practice score..."):
        r = api_post("/practice/submit_score", payload, timeout=15)
        # backend may accept payload with score in body even if signature expects query param
        if r:
            try:
                r.raise_for_status()
                st.success(f"Practice submitted — Score: {score:.2%} ({correct}/{len(questions)})")
                # Refresh mastery to show small bump
                load_mastery_dashboard()
                st.session_state.practice_quiz = None
            except Exception as e:
                # Even if server returns error, show local score
                st.warning(f"Practice score local: {score:.2%}. Backend submit error: {e}")
        else:
            st.warning(f"Practice score local: {score:.2%}")

# -------------------------
# Streaming helper
# -------------------------
def stream_teaching_step(lesson_order: int, concept_name: str):
    if st.session_state.is_streaming:
        st.warning("Already streaming. Wait for current stream to finish.")
        return
    if not st.session_state.student_name:
        st.warning("Select a student first.")
        return

    payload = {
        "student_name": st.session_state.student_name,
        "lesson_order": lesson_order,
        "concept_name": concept_name
    }

    placeholder = st.session_state.stream_placeholder or st.empty()
    st.session_state.stream_placeholder = placeholder
    st.session_state.is_streaming = True
    accumulated = ""
    try:
        r = api_post("/program/teach_step_stream", payload, stream=True, timeout=300)
        if not r:
            st.session_state.is_streaming = False
            return
        r.raise_for_status()
        placeholder.empty()
        for chunk in r.iter_lines(decode_unicode=True):
            if not chunk:
                continue
            accumulated += chunk
            # basic safety: stop if backend indicated error
            if accumulated.strip().lower().startswith("{") and "error" in accumulated.lower():
                placeholder.error(accumulated)
                break
            # render progressively
            placeholder.markdown(accumulated)
        st.session_state.current_explanation = accumulated
        st.success("Streaming finished.")
    except Exception as e:
        st.error(f"Streaming error: {e}")
    finally:
        st.session_state.is_streaming = False

# -------------------------
# UI: Page
# -------------------------
st.title("Adaptive Teaching Agent — Sequential Course")
st.markdown("Use the Guided Flow to pass lessons sequentially. Use Practice Mode to pick any topic and practice MCQs.")

if not st.session_state.student_name:
    st.info("Please register/select a student in the sidebar to proceed.")
    st.stop()

# Tabs
tab1, tab2, tab3 = st.tabs(["💡 Guided Flow (Sequential)", "📝 Practice MCQs", "📊 Mastery Dashboard"])

# -------------------------
# Tab 1: Guided Flow (Sequential)
# -------------------------
with tab1:
    st.header(f"Guided Flow — Lesson {st.session_state.current_lesson_order}")
    state = st.session_state.current_lesson_state

    if st.button("Load / Refresh Current Lesson"):
        get_program_status()

    st.divider()
    if not state:
        st.info("Click 'Load / Refresh' to start or resume the sequential program.")
    else:
        st.markdown(f"**Status:** {state.get('status', 'unknown')}")
        st.markdown(f"**Lesson:** {state.get('lesson_name') or state.get('high_level_name') } (Order {state.get('lesson_order')})")

        if state.get("status") in ["diagnostic_required", "passed_diagnostic"]:
            st.subheader("Diagnostic / Gate")
            quiz = st.session_state.current_quiz_data
            if not quiz:
                st.info("Diagnostic quiz not found. Click Load / Refresh.")
            else:
                # Render MCQs
                st.markdown("#### Multiple Choice (Part 1)")
                for i, q in enumerate(quiz.get("mcq", [])):
                    qid = q.get("id") or f"m{i+1}"
                    question_text = q.get("question") or q.get("text") or ""
                    options = q.get("options") or q.get("choices") or []
                    # pre-select if present
                    default_index = None
                    if st.session_state.mcq_answers_storage.get(qid) in options:
                        default_index = options.index(st.session_state.mcq_answers_storage.get(qid))
                    sel = st.radio(question_text, options, index=default_index or 0, key=f"diag_mcq_{qid}")
                    # save selection
                    st.session_state.mcq_answers_storage[qid] = sel

                st.markdown("#### Short Open Answers (Part 2)")
                for i, q in enumerate(quiz.get("open_questions", [])):
                    key = f"diag_open_{i}"
                    default_text = st.session_state.open_answers_storage.get(key, "")
                    txt = st.text_area(q, value=default_text, key=key, height=120)
                    st.session_state.open_answers_storage[key] = txt

                # Submit diagnostic
                if st.button("Submit Diagnostic & Grade"):
                    # assemble submission payload similar to backend expectation
                    mcq_answers = []
                    for q in quiz.get("mcq", []):
                        qid = q.get("id") or q.get("question")[:40]
                        mcq_answers.append({
                            "question": q.get("question"),
                            "options": q.get("options"),
                            "user_selection": st.session_state.mcq_answers_storage.get(qid),
                            "answer": q.get("answer") or q.get("answer_index")
                        })
                    open_subs = []
                    for i, q in enumerate(quiz.get("open_questions", [])):
                        open_subs.append({"question": q, "user_answer": st.session_state.open_answers_storage.get(f"diag_open_{i}", "")})
                    payload = {
                        "student_name": st.session_state.student_name,
                        "lesson_order": state.get("lesson_order"),
                        "submissions": {
                            "mcq_answers": mcq_answers,
                            "open_questions": open_subs
                        },
                        "skip_mode": False
                    }
                    r = api_post("/program/submit_diagnostic", payload, timeout=60)
                    if r:
                        try:
                            r.raise_for_status()
                            st.session_state.current_lesson_state = r.json()
                            # If passed and contains options, show them
                            st.success("Diagnostic graded. Check options on right column.")
                        except Exception as e:
                            st.error(f"Error submitting diagnostic: {e}")

        elif state.get("status") in ["start_teaching", "lesson_failed"]:
            st.subheader("Structured Teaching")
            sub_list = state.get("sub_concepts_list") or []
            idx = st.session_state.get("current_sub_concept_index", 0)
            st.markdown("**Sub-concepts**")
            for i, s in enumerate(sub_list):
                status = "✅" if i < idx else ("➡️" if i == idx else "⚪")
                st.markdown(f"- {status} {s}")

            if idx < len(sub_list):
                next_c = sub_list[idx]
                if st.button(f"Teach Next: {next_c}"):
                    # stream teaching step
                    stream_teaching_step(state.get("lesson_order"), next_c)
                    # after finishing streaming, increment index if explanation exists
                    if st.session_state.current_explanation:
                        st.session_state.current_sub_concept_index = min(len(sub_list), idx + 1)
            else:
                st.success("All sub-concepts covered. Start final lesson quiz when ready.")
                if st.button("Load Final Lesson Quiz"):
                    # reuse the original diagnostic as final if server provides quiz; otherwise call start to reload
                    get_program_status(state.get("lesson_order"))

        elif state.get("status") == "passed_diagnostic":
            # show pass options (skip or study)
            st.success(f"Passed diagnostic (score {state.get('score',0):.2%}).")
            if st.button("Skip to Next Lesson"):
                # call skip (submit with skip_mode True)
                payload = {
                    "student_name": st.session_state.student_name,
                    "lesson_order": state.get("lesson_order"),
                    "submissions": {"mcq_answers": [], "open_questions": []},
                    "skip_mode": True
                }
                r = api_post("/program/submit_diagnostic", payload, timeout=20)
                if r:
                    try:
                        r.raise_for_status()
                        res = r.json()
                        st.toast(res.get("message","Skipped"), icon="⏭️")
                        # reload new lesson status
                        time.sleep(0.5)
                        get_program_status()
                    except Exception as e:
                        st.error(f"Skip failed: {e}")
            if st.button("Study this Lesson Anyway"):
                # transition locally to start teaching state (server already returned options)
                # simplest approach: call submit_diagnostic with skip_mode False but no submissions to force teaching start
                payload = {"student_name": st.session_state.student_name, "lesson_order": state.get("lesson_order"), "submissions": {"mcq_answers": [], "open_questions": []}, "skip_mode": False}
                r = api_post("/program/submit_diagnostic", payload, timeout=20)
                if r:
                    try:
                        r.raise_for_status()
                        st.session_state.current_lesson_state = r.json()
                        st.toast("Entering study mode", icon="📚")
                    except Exception as e:
                        st.error(f"Failed to start study mode: {e}")

        # Right column: show explanation / pass options / grading details
        st.divider()
        st.subheader("Content / Explanation")
        placeholder = st.empty()
        st.session_state.stream_placeholder = placeholder
        if st.session_state.current_explanation:
            placeholder.markdown(st.session_state.current_explanation)
        else:
            placeholder.info("No explanation streamed yet. Use 'Teach Next' to stream content for current sub-concept.")

# -------------------------
# Tab 2: Practice MCQs
# -------------------------
with tab2:
    st.header("Practice MCQs — pick any topic")
    col1, col2 = st.columns([3, 1])

    with col1:
        st.markdown("Choose a high-level concept and difficulty, then generate a 10-question practice quiz.")
        hl = st.text_input("High-level concept name (exact match to curriculum)", key="practice_hl_input")
        diff = st.selectbox("Difficulty", ["easy", "medium", "hard"], index=["easy", "medium", "hard"].index(st.session_state.practice_difficulty))
        st.session_state.practice_difficulty = diff

        if st.button("Generate Practice Quiz"):
            if not hl.strip():
                st.warning("Enter a high-level concept name (e.g., 'Neural Networks and Transformers: Attention Mechanisms').")
            else:
                st.session_state.practice_concept = hl.strip()
                generate_practice_quiz(hl.strip(), st.session_state.practice_difficulty)

        # Render practice quiz
        quiz = st.session_state.practice_quiz
        if quiz:
            st.markdown(f"### Practice Quiz — {quiz.get('concept_name')}")
            questions = quiz.get("questions", [])
            for i, q in enumerate(questions):
                qid = q.get("id") or f"p{i+1}"
                qtext = q.get("question") or q.get("text") or ""
                options = q.get("options") or q.get("choices") or []
                st.markdown(f"**Q{i+1}. {qtext}**")
                default_index = 0
                # present as radio; store selection as index
                if options:
                    sel = st.radio(f"Select (Q{i+1})", options, index=0, key=f"practice_{qid}")
                    # update practice_answers as the option string - we'll map later
                    st.session_state.practice_answers[qid] = sel
                else:
                    st.text("Question options missing in this question data.")
            if st.button("Submit Practice Quiz"):
                submit_practice_quiz()

    with col2:
        st.markdown("Practice Controls")
        st.markdown("Current difficulty: " + st.session_state.practice_difficulty)
        if st.session_state.practice_quiz:
            st.button("Discard Practice Quiz", on_click=lambda: st.session_state.update({"practice_quiz": None, "practice_answers": {}}))

# -------------------------
# Tab 3: Mastery Dashboard
# -------------------------
with tab3:
    st.header("Mastery Dashboard")
    if not st.session_state.mastery_dashboard_data:
        if st.button("Load mastery dashboard"):
            load_mastery_dashboard()
        else:
            st.info("Click the button to load mastery and progress for the selected student.")
    else:
        data = st.session_state.mastery_dashboard_data
        # Summary table
        rows = []
        for lesson in data:
            rows.append({
                "Order": lesson.get("lesson_order"),
                "Lesson": lesson.get("high_level_concept"),
                "Mastery": lesson.get("mastery", 0.0),
                "Completed": lesson.get("completed", False)
            })
        df = pd.DataFrame(rows).sort_values("Order")
        st.dataframe(df, use_container_width=True)

        # Show detail for each lesson
        for lesson in data:
            st.markdown(f"### Lesson {lesson.get('lesson_order')}: {lesson.get('high_level_concept')}")
            st.progress(lesson.get("mastery", 0.0))
            with st.expander("Sub-concept mastery"):
                sub = lesson.get("sub_concepts", [])
                if not sub:
                    st.info("No recorded mastery for sub-concepts.")
                else:
                    subdf = pd.DataFrame(sub)
                    subdf = subdf.rename(columns={"concept": "Sub-concept", "mastery": "Mastery"})
                    st.dataframe(subdf, use_container_width=True)

# -------------------------
# Footer quick links
# -------------------------
st.markdown("---")
st.caption("If you run into backend 422/500 errors, check backend logs and ensure the API contract matches the front-end payloads.")
