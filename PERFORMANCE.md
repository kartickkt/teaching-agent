Teaching Agent: Performance Optimizations

This document logs the key performance optimizations implemented in the project. Each entry details the problem, the solution, and the measurable impact, demonstrating a focus on building scalable and efficient software.

1. Resolving N+1 Query Bottleneck in Assessment Agent

The Problem

The core logic for deciding the "next best concept" resides in AssessmentAgent.get_next_concept(). This function loops through all sub-concepts in the curriculum and, for each one, checks the student's current mastery and whether prerequisites are met.

The initial implementation caused the TempProfile proxy (in run_teaching_loop) and TempProfileProxy (in api/main.py) to call profile.get_mastery(concept_name) inside this loop. This resulted in hundreds of individual, sequential database queries to the Supabase Postgres instance just to decide which single concept to teach next.

This is a classic "N+1 Query Problem."

The Impact (Before Fix)

Local Test: The run_teaching_loop script would hang for 3-4 minutes on startup before teaching the first concept.

Production API: The /get_next_step endpoint, which uses the exact same logic, had an unusable API response time of ~3-4 minutes, which would have resulted in an immediate timeout in any production environment.

The Solution

We implemented a database-caching proxy pattern to pre-fetch all necessary data in a single call.

New DB Method: A new method, get_all_mastery(student_name), was added to the StudentProfile class in src/student_profiles.py. This method executes a single SQL query to fetch all mastery records for a given student and returns them as a dictionary (e.g., {"Self-Attention": 0.5, "RNNs": 0.2}).

Proxy Caching: The TempProfile (in the local test loop) and TempProfileProxy (in api/main.py) were both updated. Now, upon initialization, they call get_all_mastery once and store the resulting dictionary in an in-memory cache (self._mastery_cache).

Instant Lookups: The AssessmentAgent's get_next_concept function remains unchanged, but its calls to profile.get_mastery(concept_name) are now directed to the proxy's cache, resulting in instant dictionary lookups instead of database round-trips.

The Impact (After Fix)

Database Load: Reduced the number of database queries for the /get_next_step endpoint from ~70+ queries (one for each sub-concept) down to 1 query.

API Latency: Decreased the API response time for this critical endpoint from ~3-4 minutes to <1 second.

Scalability & Cost: Drastically reduced the load on the Postgres database, improving application scalability and lowering operational costs by minimizing database read operations.