# src/student_profiles.py (REVISED)
"""
Manages persistent student profiles and mastery state using Supabase/Postgres.
Includes support for sequential lesson progress and Exponential Moving Average (EMA) mastery model.
"""
import os
import json
import psycopg2
from datetime import datetime
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Load environment variables for DB connection
load_dotenv() 

# ----------------------------
# Curriculum Management (In-Memory)
# ----------------------------
CURRICULUM_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'curriculum.json')

class CurriculumManager:
    """Manages loading and providing access to the curriculum structure."""
    _data: Optional[Dict[str, Any]] = None
    _high_level_map: Optional[Dict[str, Dict[str, Any]]] = None
    
    @classmethod
    def load_curriculum(cls) -> Dict[str, Any]:
        # ... (Unchanged load_curriculum implementation) ...
        if cls._data is None:
            try:
                with open(CURRICULUM_FILE, 'r') as f:
                    cls._data = json.load(f)
            except Exception as e:
                print(f"Error loading curriculum.json: {e}")
                cls._data = {"concepts": []}
        return cls._data

    @classmethod
    def get_all_sub_concepts(cls) -> List[str]:
        # ... (Unchanged get_all_sub_concepts implementation) ...
        data = cls.load_curriculum()
        concepts = []
        for high_level_concept in data.get("concepts", []):
            for sub_concept in high_level_concept.get("sub_concepts", []):
                concept_name = sub_concept.get("concept")
                if concept_name:
                    concepts.append(concept_name)
        return concepts

    @classmethod
    def get_high_level_concepts(cls) -> Dict[str, Any]:
        """Returns the high-level concept structure indexed by name."""
        if cls._high_level_map is None:
            data = cls.load_curriculum()
            cls._high_level_map = {c['high_level_concept']: c for c in data.get("concepts", [])}
        return cls._high_level_map

    @classmethod
    def get_high_level_by_order(cls, order: int) -> Optional[Dict[str, Any]]:
        """Retrieves a high-level concept by its sequential order number."""
        data = cls.load_curriculum()
        for concept in data.get("concepts", []):
            if concept.get('order') == order:
                return concept
        return None
# ----------------------------
# DB Connection and Persistence
# ----------------------------

def get_db_connection():
    # ... (Unchanged get_db_connection implementation) ...
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            connect_timeout=10,
            sslmode="require",
        )
        return conn
    except Exception as e:
        print(f"❌ DATABASE CONNECTION FAILED: {e}")
        raise RuntimeError("Failed to connect to the database.") from e


class StudentProfileDB:
    """Manages student profile, mastery, and sequencing using Postgres."""

    def __init__(self):
        pass # Connections are made per operation

    def _execute_query(self, query: str, params: tuple = ()) -> Optional[List[tuple]]:
        # ... (Unchanged _execute_query implementation) ...
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if query.strip().lower().startswith('select'):
                results = cursor.fetchall()
                cursor.close()
                return results
            else:
                conn.commit()
                cursor.close()
                return None
        except psycopg2.Error as e:
            print(f"Database Error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def _get_student_id(self, name: str) -> Optional[int]:
        # ... (Unchanged _get_student_id implementation) ...
        try:
            results = self._execute_query("SELECT id FROM students WHERE name = %s", (name,))
            return results[0][0] if results else None
        except Exception:
            return None

    def register_student(self, name: str, level: str = "beginner"):
        """Registers a student if they don't exist, initializing current_lesson_order."""
        student_id = self._get_student_id(name)
        if student_id is None:
            date = datetime.now().isoformat()
            try:
                # IMPORTANT: Added 'current_lesson_order' to the students table (default 1)
                self._execute_query(
                    "INSERT INTO students (name, level, registration_date, current_lesson_order) VALUES (%s, %s, %s, %s)",
                    (name, level, date, 1),
                )
                print(f"✅ Registered new student: {name}")
            except Exception as e:
                print(f"⚠️ Could not register student {name}: {e}")
        else:
            # We assume the 'students' table is modified to include current_lesson_order
            pass

# --- NEW PROGRESS TRACKING METHODS ---

    def get_progress(self, name: str) -> Dict[str, Any]:
        """Retrieves the student's sequential progress state (current lesson & completed lessons)."""
        student_id = self._get_student_id(name)
        if not student_id:
            return {"current_lesson_order": 1, "completed_lessons": []}
        
        # NOTE: This assumes 'students' table has 'current_lesson_order' (INT) and 
        # 'completed_lessons' (JSONB or TEXT array) columns.
        query = "SELECT current_lesson_order, completed_lessons FROM students WHERE id = %s"
        results = self._execute_query(query, (student_id,))

        if results:
            current_order, completed_lessons_json = results[0]
            
            # Assuming 'completed_lessons' is stored as a JSON string/JSONB array of lesson orders
            if isinstance(completed_lessons_json, str):
                try:
                    completed_lessons = json.loads(completed_lessons_json)
                except (json.JSONDecodeError, TypeError):
                    completed_lessons = []
            elif isinstance(completed_lessons_json, list):
                 completed_lessons = completed_lessons_json
            else:
                 completed_lessons = []


            # Ensure current_order is at least 1
            current_order = max(1, current_order if current_order is not None else 1)

            return {
                "current_lesson_order": current_order,
                "completed_lessons": [int(l) for l in completed_lessons] # Ensure orders are integers
            }
        
        return {"current_lesson_order": 1, "completed_lessons": []}

    def update_progress(self, name: str, new_lesson_order: int, completed_lesson_order: Optional[int] = None):
        """Updates the student's current lesson order and optionally marks a lesson as completed."""
        self.register_student(name)
        student_id = self._get_student_id(name)
        if not student_id:
            return

        # 1. Get existing data
        progress = self.get_progress(name)
        current_completed = set(progress.get("completed_lessons", []))
        
        # 2. Add completed lesson if provided
        if completed_lesson_order is not None:
            current_completed.add(completed_lesson_order)

        completed_lessons_list = sorted(list(current_completed))
        completed_lessons_json = json.dumps(completed_lessons_list)
        
        # 3. Update the database record
        update_query = """
        UPDATE students 
        SET current_lesson_order = %s, completed_lessons = %s 
        WHERE id = %s
        """
        self._execute_query(
            update_query,
            (new_lesson_order, completed_lessons_json, student_id)
        )
        print(f"🔄 Progress updated. Current Lesson: {new_lesson_order}. Completed: {completed_lessons_list}")

# --- EMA MASTERY METHODS (Unchanged/Refined) ---

    def get_mastery(self, name: str, concept: str) -> float:
        # ... (Unchanged get_mastery implementation) ...
        student_id = self._get_student_id(name)
        if not student_id:
            return 0.0

        # We now track mastery for both sub-concepts (detailed) AND high-level concepts (summary)
        results = self._execute_query(
            "SELECT mastery FROM mastery WHERE student_id = %s AND concept = %s",
            (student_id, concept)
        )
        return float(results[0][0]) if results else 0.0

    def get_all_mastery(self, name: str) -> Dict[str, float]:
        # ... (Unchanged get_all_mastery implementation) ...
        student_id = self._get_student_id(name)
        if not student_id:
            return {}

        results = self._execute_query(
            "SELECT concept, mastery FROM mastery WHERE student_id = %s",
            (student_id,)
        )
        return {concept: float(mastery) for concept, mastery in results} if results else {}

    def update_mastery(self, name: str, concept: str, score: float, alpha: float = 0.3) -> float:
        """Updates the mastery level using exponential moving average (EMA)."""
        self.register_student(name)
        student_id = self._get_student_id(name)
        if not student_id:
            return 0.0

        prev_mastery = self.get_mastery(name, concept)
        # EMA Formula: New_Mastery = (1 - alpha) * Prev_Mastery + alpha * Score
        new_mastery = (1 - alpha) * prev_mastery + alpha * score
        new_mastery = max(0.0, min(1.0, new_mastery)) # Clamp 0 to 1
        now = datetime.now().isoformat()
        
        upsert_query = """
        INSERT INTO mastery (student_id, concept, mastery, last_updated)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (student_id, concept)
        DO UPDATE SET
            mastery = EXCLUDED.mastery,
            last_updated = EXCLUDED.last_updated;
        """
        
        try:
            self._execute_query(
                upsert_query,
                (student_id, concept, new_mastery, now)
            )
        except Exception as e:
            print(f"Error during mastery UPSERT for {concept}: {e}")
            return 0.0
        
        return new_mastery

# Renaming the primary class to avoid confusion with the previous version
StudentProfile = StudentProfileDB

# --- IMPORTANT DATABASE ASSUMPTIONS ---
# The 'students' table must be modified to include:
# 1. current_lesson_order INT DEFAULT 1
# 2. completed_lessons JSONB (or TEXT) DEFAULT '[]'
#
# The 'mastery' table must continue to track mastery per named concept (sub-concept name or high-level concept name).