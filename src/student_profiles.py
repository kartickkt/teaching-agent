# src/student_profiles.py
"""
Unified student profile storage using a SINGLE Supabase/Postgres table:
- student_name (PK)
- current_lesson_order (INT)
- completed_lessons (JSONB)
- mastery (JSONB: concept_name → mastery_score)
"""

import os
import json
import psycopg2
from dotenv import load_dotenv
from typing import Dict, Any, Optional, List
from datetime import datetime

load_dotenv()

# ----------------------------
# DB Connection
# ----------------------------

def get_db_connection():
    """Connects to Supabase Postgres."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            sslmode="require",
            connect_timeout=10
        )
        return conn
    except Exception as e:
        print(f"❌ DB CONNECTION FAILED: {e}")
        raise


# ----------------------------
# Curriculum Manager (unchanged)
# ----------------------------

import json
import os
CURRICULUM_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "curriculum.json")

class CurriculumManager:
    _data = None
    _flat = None

    @classmethod
    def load(cls):
        if cls._data is None:
            try:
                with open(CURRICULUM_FILE, "r") as f:
                    cls._data = json.load(f)
            except:
                cls._data = {"concepts": []}
        return cls._data

    @classmethod
    def get_high_level_concepts(cls):
        data = cls.load()
        return {c["high_level_concept"]: c for c in data.get("concepts", [])}

    @classmethod
    def get_high_level_by_order(cls, order: int):
        for c in cls.load().get("concepts", []):
            if c.get("order") == order:
                return c
        return None


# ----------------------------
# Student Profile (NEW CLEAN VERSION)
# ----------------------------

class StudentProfile:
    """
    Stores ALL student state inside ONE table:
    - current_lesson_order
    - completed_lessons
    - mastery (mapping each concept → mastery score)
    """

    TABLE = "student_profiles"

    def _exec(self, query: str, params: tuple = (), fetch=False):
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(query, params)
            if fetch:
                rows = cur.fetchall()
                cur.close()
                return rows
            conn.commit()
            cur.close()
        except Exception as e:
            if conn:
                conn.rollback()
            print("SQL ERROR:", e)
            return None
        finally:
            if conn:
                conn.close()

    # ----------------------------
    # Registration
    # ----------------------------

    def register_student(self, name: str):
        """Creates a profile row if missing."""
        exists = self._exec(
            f"SELECT student_name FROM {self.TABLE} WHERE student_name = %s",
            (name,),
            fetch=True,
        )
        if exists:
            return

        self._exec(
            f"""
            INSERT INTO {self.TABLE} 
            (student_name, current_lesson_order, completed_lessons, mastery)
            VALUES (%s, %s, %s, %s)
            """,
            (name, 1, json.dumps([]), json.dumps({})),
        )
        print(f"✅ Registered new student: {name}")

    # ----------------------------
    # Progress
    # ----------------------------

    def get_progress(self, name: str) -> Dict[str, Any]:
        self.register_student(name)

        rows = self._exec(
            f"""
            SELECT current_lesson_order, completed_lessons
            FROM {self.TABLE}
            WHERE student_name = %s
            """,
            (name,),
            fetch=True,
        )

        if not rows:
            return {"current_lesson_order": 1, "completed_lessons": []}

        current_order, completed_json = rows[0]

        if isinstance(completed_json, str):
            try:
                completed = json.loads(completed_json)
            except:
                completed = []
        else:
            completed = completed_json or []

        return {
            "current_lesson_order": current_order,
            "completed_lessons": completed,
        }

    def update_progress(self, name: str, new_order: int, completed: Optional[int]):
        self.register_student(name)
        prog = self.get_progress(name)

        completed_set = set(prog["completed_lessons"])
        if completed:
            completed_set.add(completed)

        completed_json = json.dumps(sorted(list(completed_set)))

        self._exec(
            f"""
            UPDATE {self.TABLE}
            SET current_lesson_order = %s,
                completed_lessons = %s
            WHERE student_name = %s
            """,
            (new_order, completed_json, name),
        )

    # ----------------------------
    # Mastery
    # ----------------------------

    def get_all_mastery(self, name: str) -> Dict[str, float]:
        self.register_student(name)

        rows = self._exec(
            f"SELECT mastery FROM {self.TABLE} WHERE student_name = %s",
            (name,),
            fetch=True,
        )

        if not rows:
            return {}

        mastery_json = rows[0][0]

        if isinstance(mastery_json, str):
            try:
                return json.loads(mastery_json)
            except:
                return {}

        return mastery_json or {}

    def update_mastery(self, name: str, concept: str, score: float, alpha: float = 0.3):
        """EMA update inside the mastery JSON."""
        mastery = self.get_all_mastery(name)
        prev = mastery.get(concept, 0.0)

        new = (1 - alpha) * prev + alpha * score
        mastery[concept] = round(new, 4)

        self._exec(
            f"UPDATE {self.TABLE} SET mastery = %s WHERE student_name = %s",
            (json.dumps(mastery), name),
        )

        return new
