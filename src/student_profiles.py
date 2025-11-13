# src/student_profiles.py
"""
Manages persistent student profiles and mastery state using Supabase/Postgres.
Note: Requires a populated .env file and existing 'students' and 'mastery' tables 
in the target Supabase database.
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
    
    @classmethod
    def load_curriculum(cls) -> Dict[str, Any]:
        """Loads the curriculum JSON data."""
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
        """Extracts a flat list of all teachable sub-concept names."""
        data = cls.load_curriculum()
        concepts = []
        for high_level_concept in data.get("concepts", []):
            for sub_concept in high_level_concept.get("sub_concepts", []):
                # Using .get("concept") for robustness, matching curriculum structure
                concept_name = sub_concept.get("concept")
                if concept_name:
                    concepts.append(concept_name)
        return concepts

    @classmethod
    def get_high_level_concepts(cls) -> Dict[str, Any]:
        """Returns the high-level concept structure indexed by name."""
        data = cls.load_curriculum()
        return {c['high_level_concept']: c for c in data.get("concepts", [])}


# ----------------------------
# DB Connection and Persistence
# ----------------------------

def get_db_connection():
    """Establishes a connection to the Supabase Postgres database."""
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
        # In a production environment, you might re-raise or handle this error more gracefully.
        raise RuntimeError("Failed to connect to the database.") from e

class StudentProfileDB:
    """Manages student profile, mastery, and logging using Postgres."""

    def __init__(self):
        # We don't connect here; connections are made per operation for safety/threading
        pass

    def _execute_query(self, query: str, params: tuple = ()) -> Optional[List[tuple]]:
        """Handles PostgreSQL query execution and connection management."""
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
        """Helper to retrieve student ID by name."""
        try:
            results = self._execute_query("SELECT id FROM students WHERE name = %s", (name,))
            return results[0][0] if results else None
        except Exception:
            return None


    def register_student(self, name: str, level: str = "beginner"):
        """Registers a student if they don't exist."""
        if self._get_student_id(name) is None:
            date = datetime.now().isoformat()
            try:
                self._execute_query(
                    "INSERT INTO students (name, level, registration_date) VALUES (%s, %s, %s)",
                    (name, level, date),
                )
                print(f"✅ Registered new student: {name}")
            except Exception as e:
                # Handle race condition where student might be created simultaneously
                print(f"⚠️ Could not register student {name}: {e}")
        else:
            # print(f"Student '{name}' already registered.")
            pass


    def get_mastery(self, name: str, concept: str) -> float:
        """Retrieves the mastery level for a concept, defaulting to 0.0."""
        student_id = self._get_student_id(name)
        if not student_id:
            return 0.0

        results = self._execute_query(
            "SELECT mastery FROM mastery WHERE student_id = %s AND concept = %s",
            (student_id, concept)
        )
        return float(results[0][0]) if results else 0.0

    def get_all_mastery(self, name: str) -> Dict[str, float]:
        """Retrieves all mastery data for a student in a single query."""
        student_id = self._get_student_id(name)
        if not student_id:
            return {}

        results = self._execute_query(
            "SELECT concept, mastery FROM mastery WHERE student_id = %s",
            (student_id,)
        )
        return {concept: float(mastery) for concept, mastery in results} if results else {}


    def update_mastery(self, name: str, concept: str, score: float, alpha: float = 0.3) -> float:
        """Updates the mastery level using exponential moving average."""
        self.register_student(name) # Ensure student exists
        student_id = self._get_student_id(name)
        if not student_id:
            return 0.0 # Should not happen after register_student call

        prev_mastery = self.get_mastery(name, concept)
        new_mastery = (1 - alpha) * prev_mastery + alpha * score
        new_mastery = max(0.0, min(1.0, new_mastery)) # Clamp 0 to 1
        now = datetime.now().isoformat()
        
        # --- FIX: Replace flawed try/except with atomic UPSERT ---
        # This single query will INSERT a new row, or UPDATE an existing one
        # if the (student_id, concept) constraint is violated.
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
            print(f"Error during UPSERT: {e}")
            return 0.0 # Return 0 on failure
        # --- End of FIX ---

        print(f"-> Mastery for '{concept}' updated to {new_mastery:.2f} (from {prev_mastery:.2f})")
        return new_mastery

    # Note: Added for completeness, matching the previous in-memory model structure
    def get_student(self, name):
        """Returns student data (ID, name, level, reg_date) by name."""
        return self._execute_query("SELECT id, name, level, registration_date FROM students WHERE name = %s", (name,))

    def log_interaction(self, student_name: str, action: str, concept: str, result: str):
        # This function would require a new 'interactions' table in the DB.
        # Skipping implementation for simplicity, as the core functionality is covered by update_mastery.
        pass

# Renaming the primary class to avoid confusion with the previous version
StudentProfile = StudentProfileDB