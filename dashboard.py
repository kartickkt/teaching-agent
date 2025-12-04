# dashboard.py (Corrected Version)
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
init_state("current_quiz_data", None)
init_state("mcq_answers_storage", {})
init_state("open_answers_storage", {})
init_state("is_streaming", False)
init_state("stream_placeholder", None)
init_state("current_explanation", "")
init_state("mastery_dashboard_data", None)
init_state("practice_quiz", None)
init_state("practice_answers", {})
init_state("practice_difficulty", "medium")
init_state("practice_concept", None)
init_state("api_timeout", 30)
init_state("current_sub_concept_index", 0)
init_state("hl_concepts_cache", None)

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

# -------------------------
# Helpers
# -------------------------
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
            quiz = state.get("quiz")

            def normalize_quiz(q):
                if not isinstance(q, dict):
                    return {"mcq": [], "open_questions": []}
                mcq = q.get("mcq") or q.get("mcqs") or q.get("questions") or []
                open_q = q.get("open_questions") or q.get("opens") or []
                if not isinstance(mcq, list):
                    mcq = []
                if not isinstance(open_q, list):
                    open_q = []
                return {"mcq": mcq, "open_questions": open_q}

            if quiz:
                st.session_state.current_quiz_data = normalize_quiz(quiz)
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

# Curriculum helper for practice dropdown
def load_hl_concepts():
    if st.session_state.hl_concepts_cache is not None:
        return st.session_state.hl_concepts_cache
    r = api_get("/curriculum/high_level", timeout=10)
    if not r:
        st.session_state.hl_concepts_cache = []
        return []
    try:
        r.raise_for_status()
        j = r.json()
        vals = j.get("high_level_concepts", []) or []
        st.session_state.hl_concepts_cache = vals
        return vals
    except Exception:
        st.session_state.hl_concepts_cache = []
        return []

# -------------------------
# Sidebar
# -------------------------
with st.sidebar:
    st.title("🤖 Student & API")
    new_api = st.text_input("FastAPI URL", value=st.session_state.api_base_url, key="new_api_url")
    if st.button("Set API URL"):
        if new_api:
            st.session_state.api_base_url = new_api.strip()
            st.toast("API URL updated", icon="🔁")
            st.session_state.hl_concepts_cache = None
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
                st.session_state.practice_quiz = None
                st.session_state.practice_answers = {}
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
    correct = 0
    for q in questions:
        qid = q.get("id") or q.get("question")[:40]
        selected = st.session_state.practice_answers.get(qid)
        answer_index = q.get("answer_index")
        answer_value = q.get("answer")
        options = q.get("options") or q.get("choices") or []
        sel_index = None
        if isinstance(selected, int):
            sel_index = selected
        elif isinstance(selected, str) and options:
            try:
                sel_index = options.index(selected)
            except ValueError:
                sel_index = None
        is_correct = False
        if isinstance(answer_index, int) and sel_index is not None:
            is_correct = (sel_index == int(answer_index))
        elif isinstance(answer_value, int) and sel_index is not None:
            is_correct = (sel_index == int(answer_value))
        elif isinstance(answer_value, str) and options and sel_index is not None:
            is_correct = (options[sel_index] == answer_value)
        if isinstance(answer_value, str) and isinstance(selected, str):
            is_correct = (answer_value.strip() == selected.strip())
        if is_correct:
            correct += 1

    score = correct / max(1, len(questions))
    payload = {
        "student_name": st.session_state.student_name,
        "hl_concept_name": st.session_state.practice_quiz.get("concept_name"),
        "difficulty": st.session_state.practice_difficulty,
        "score": score
    }
    with st.spinner("Submitting practice score..."):
        r = api_post("/practice/submit_score", payload, timeout=30)
        if r:
            try:
                r.raise_for_status()
                st.success(f"Practice submitted — Score: {score:.2%} ({correct}/{len(questions)})")
                load_mastery_dashboard()
                st.session_state.practice_quiz = None
            except Exception as e:
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
            accumulated += chunk + "\n"
            if accumulated.strip().lower().startswith("{") and "error" in accumulated.lower():
                placeholder.error(accumulated)
                break
            try:
                placeholder.markdown(accumulated)
            except Exception:
                placeholder.text(accumulated)
        st.session_state.current_explanation = accumulated
        st.success("Streaming finished.")
    except Exception as e:
        st.error(f"Streaming error: {e}")
    finally:
        st.session_state.is_streaming = False

# -------------------------
# UI
# -------------------------
st.title("Adaptive Teaching Agent — Sequential Course")
st.markdown("Use the Guided Flow to pass lessons sequentially. Use Practice Mode to pick any topic and practice MCQs.")

if not st.session_state.student_name:
    st.info("Please register/select a student in the sidebar to proceed.")
    st.stop()

tab1, tab2, tab3 = st.tabs(["💡 Guided Flow (Sequential)", "📝 Practice MCQs", "📊 Mastery Dashboard"])

# -------------------------
# Tab 1: Guided Flow
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

        # DIAGNOSTIC
        quiz = st.session_state.current_quiz_data
        if state.get("status") == "diagnostic_required" or quiz:
            st.subheader("Diagnostic / Gate")
            if not quiz:
                st.info("Diagnostic quiz not found. Click Load / Refresh.")
            else:
                st.markdown("#### Multiple Choice (Part 1)")
                for i, q in enumerate(quiz.get("mcq", [])):
                    qid = q.get("id") or q.get("question")[:40] or f"m{i+1}"
                    question_text = q.get("question") or q.get("text") or ""
                    options = q.get("options") or q.get("choices") or []
                    default_index = None
                    if isinstance(st.session_state.mcq_answers_storage.get(qid), str) and options:
                        try:
                            default_index = options.index(st.session_state.mcq_answers_storage.get(qid))
                        except ValueError:
                            default_index = None
                    index_to_use = default_index if default_index is not None else 0
                    sel = st.radio(question_text, options, index=index_to_use, key=f"diag_mcq_{qid}")
                    st.session_state.mcq_answers_storage[qid] = sel

                st.markdown("#### Short Open Answers (Part 2)")
                for i, q in enumerate(quiz.get("open_questions", [])):
                    qtext = q.get("question") if isinstance(q, dict) else str(q)
                    key = f"diag_open_{i}"
                    default_text = st.session_state.open_answers_storage.get(key, "")
                    txt = st.text_area(qtext, value=default_text, key=key, height=120)
                    st.session_state.open_answers_storage[key] = txt

                if st.button("Submit Diagnostic & Grade"):
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
                        qtext = q.get("question") if isinstance(q, dict) else str(q)
                        open_subs.append({
                            "question": qtext,
                            "user_answer": st.session_state.open_answers_storage.get(f"diag_open_{i}", "")
                        })
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
                            st.session_state.current_quiz_data = None
                            st.session_state.mcq_answers_storage = {}
                            st.session_state.open_answers_storage = {}
                            st.success("Diagnostic graded. Check options / teaching flow below.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error submitting diagnostic: {e}")

        # STRUCTURED TEACHING
        if state.get("status") in ["start_teaching", "lesson_failed"]:
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
                    stream_teaching_step(state.get("lesson_order"), next_c)
                    if st.session_state.current_explanation:
                        st.session_state.current_sub_concept_index = min(len(sub_list), idx + 1)
                        st.rerun()
            else:
                st.success("All sub-concepts covered. Load or submit the final lesson quiz when ready.")
                if st.button("Load Final Lesson Quiz"):
                    with st.spinner("Loading final quiz..."):
                        payload = {
                            "student_name": st.session_state.student_name,
                            "lesson_order": state.get("lesson_order")
                        }
                        r = api_post("/program/start", payload, timeout=30)
                        if r and r.status_code == 200:
                            quiz_json = r.json()
                            quiz_data = quiz_json.get("quiz")
                            if quiz_data and isinstance(quiz_data, dict):
                                st.session_state.current_quiz_data = quiz_data
                                st.session_state.mcq_answers_storage = {}
                                st.session_state.open_answers_storage = {}
                                st.toast("Final quiz loaded. Fill it out above.", icon="🧪")
                                st.rerun()
                            else:
                                st.error(f"Failed to get valid quiz data from backend. Response: {quiz_json}")
                        else:
                            st.error(f"API error loading final quiz. Status: {r.status_code if r else 'N/A'}")

                final_quiz = st.session_state.current_quiz_data
                if final_quiz:
                    st.markdown("You have a final quiz loaded. Review it above and press the button below to submit as final.")
                    if st.button("Submit Final Quiz & Grade"):
                        mcq_answers = []
                        for q in final_quiz.get("mcq", []):
                            qid = q.get("id") or q.get("question")[:40]
                            mcq_answers.append({
                                "question": q.get("question"),
                                "options": q.get("options"),
                                "user_selection": st.session_state.mcq_answers_storage.get(qid),
                                "answer": q.get("answer") or q.get("answer_index")
                            })
                        open_subs = []
                        for i, q in enumerate(final_quiz.get("open_questions", [])):
                            qtext = q.get("question") if isinstance(q, dict) else str(q)
                            open_subs.append({
                                "question": qtext,
                                "user_answer": st.session_state.open_answers_storage.get(f"diag_open_{i}", "")
                            })
                        payload = {
                            "student_name": st.session_state.student_name,
                            "lesson_order": state.get("lesson_order"),
                            "submissions": {
                                "mcq_answers": mcq_answers,
                                "open_questions": open_subs
                            }
                        }
                        r = api_post("/program/finish_quiz", payload, timeout=60)
                        if r:
                            try:
                                r.raise_for_status()
                                st.session_state.current_lesson_state = r.json()
                                st.success("Final quiz graded. Progress and mastery updated.")
                                st.session_state.current_sub_concept_index = 0
                                get_program_status()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error submitting final quiz: {e}")

        # PASSED DIAGNOSTIC — OPTIONS
        if state.get("status") == "passed_diagnostic":
            st.success(f"Passed diagnostic (score {state.get('score',0):.2%}).")

            # ----------------------
            # ✔ FIXED SKIP BUTTON
            # ----------------------
            if st.button("Skip to Next Lesson"):
                payload = {
                    "student_name": st.session_state.student_name,
                    "lesson_order": state.get("lesson_order"),
                    "submissions": {"mcq_answers": [], "open_questions": []},
                    "skip_mode": True
                }

                r = api_post("/program/submit_diagnostic", payload, timeout=10)

                if r:
                    try:
                        r.raise_for_status()
                        res = r.json()

                        st.session_state.current_explanation = ""
                        st.session_state.current_sub_concept_index = 0

                        st.success("Lesson skipped → Loading next lesson...")
                        get_program_status()
                        st.rerun()

                    except Exception as e:
                        st.error(f"Skip failed: {e}")

            # STUDY ANYWAY
            if st.button("Study this Lesson Anyway"):
                payload = {
                    "student_name": st.session_state.student_name,
                    "lesson_order": state.get("lesson_order"),
                    "submissions": {"mcq_answers": [], "open_questions": []},
                    "skip_mode": False
                }
                r = api_post("/program/submit_diagnostic", payload, timeout=20)
                if r:
                    try:
                        r.raise_for_status()
                        st.session_state.current_lesson_state = r.json()
                        st.session_state.current_quiz_data = None
                        st.session_state.mcq_answers_storage = {}
                        st.session_state.open_answers_storage = {}
                        st.toast("Entering study mode", icon="📚")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to start study mode: {e}")

        st.divider()
        st.subheader("Content / Explanation")
        placeholder = st.empty()
        st.session_state.stream_placeholder = placeholder
        if st.session_state.current_explanation:
            placeholder.markdown(st.session_state.current_explanation)
        else:
            placeholder.info("No explanation streamed yet. Use 'Teach Next'.")

# -------------------------
# Tab 2: Practice MCQs
# -------------------------
with tab2:
    st.header("Practice MCQs — pick any topic")
    col1, col2 = st.columns([3, 1])

    with col1:
        st.markdown("Choose a high-level concept and difficulty, then generate a practice quiz.")
        hl_concepts = load_hl_concepts()
        if not hl_concepts:
            st.warning("Unable to load curriculum list from backend. You can enter a concept manually.")
            hl = st.text_input("High-level concept name (manual)")
        else:
            hl = st.selectbox("High-Level Concept", hl_concepts)

        diff = st.selectbox("Difficulty", ["easy", "medium", "hard"],
                            index=["easy", "medium", "hard"].index(st.session_state.practice_difficulty))
        st.session_state.practice_difficulty = diff

        if st.button("Generate Practice Quiz"):
            if not hl or not str(hl).strip():
                st.warning("Enter or select a high-level concept name.")
            else:
                st.session_state.practice_concept = str(hl).strip()
                generate_practice_quiz(st.session_state.practice_concept, st.session_state.practice_difficulty)

        quiz = st.session_state.practice_quiz
        if quiz:
            st.markdown(f"### Practice Quiz — {quiz.get('concept_name')}")
            questions = quiz.get("questions", [])
            for i, q in enumerate(questions):
                qid = q.get("id") or f"p{i+1}"
                qtext = q.get("question") or q.get("text") or ""
                options = q.get("options") or q.get("choices") or []
                st.markdown(f"**Q{i+1}. {qtext}**")
                if options:
                    sel = st.radio(f"Select (Q{i+1})", options, index=0, key=f"practice_{qid}")
                    st.session_state.practice_answers[qid] = sel
                else:
                    st.text("Question options missing.")
            if st.button("Submit Practice Quiz"):
                submit_practice_quiz()

    with col2:
        st.markdown("Practice Controls")
        st.markdown("Current difficulty: " + st.session_state.practice_difficulty)
        if st.session_state.practice_quiz:
            st.button("Discard Practice Quiz",
                      on_click=lambda: st.session_state.update({"practice_quiz": None, "practice_answers": {}}))

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

st.markdown("---")
st.caption("If you run into backend 422/500 errors, check backend logs and ensure API contract matches the frontend payloads.")
