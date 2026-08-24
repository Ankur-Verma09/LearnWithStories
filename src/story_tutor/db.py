from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .hierarchy import clean_name, normalized_name, stable_node_id
from .progression import misconception_key, progression_update


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS learner_profiles (
  id INTEGER PRIMARY KEY,
  display_name TEXT NOT NULL,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO learner_profiles(id,display_name,is_default) VALUES (1,'Default learner',1);

CREATE TABLE IF NOT EXISTS source_chunks (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  publisher TEXT NOT NULL,
  authority_tier TEXT NOT NULL,
  license_note TEXT NOT NULL,
  edition TEXT NOT NULL,
  effective_date TEXT NOT NULL,
  subject TEXT NOT NULL,
  concept TEXT NOT NULL,
  section TEXT NOT NULL,
  text TEXT NOT NULL,
  UNIQUE(source_id, section, text)
);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '',
  concept TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  salience REAL NOT NULL DEFAULT 0.5,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT,
  superseded_by INTEGER REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS lessons (
  id INTEGER PRIMARY KEY,
  cache_key TEXT NOT NULL UNIQUE,
  subject TEXT NOT NULL,
  concept TEXT NOT NULL,
  question TEXT NOT NULL DEFAULT '',
  understanding_level INTEGER NOT NULL,
  learner_age INTEGER NOT NULL DEFAULT 18,
  knowledge_level TEXT NOT NULL DEFAULT 'beginner',
  learning_profile TEXT NOT NULL DEFAULT 'young_adult',
  story_style TEXT NOT NULL DEFAULT 'realistic_funny',
  difficulty TEXT NOT NULL DEFAULT 'standard',
  language TEXT NOT NULL,
  model_provider TEXT NOT NULL DEFAULT 'ollama',
  model_name TEXT NOT NULL,
  generation_ms INTEGER NOT NULL DEFAULT 0,
  evidence_json TEXT NOT NULL,
  context_json TEXT NOT NULL,
  lesson_json TEXT NOT NULL,
  verification_json TEXT NOT NULL,
  status TEXT NOT NULL,
  learner_id INTEGER NOT NULL DEFAULT 1 REFERENCES learner_profiles(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comprehension_attempts (
  id INTEGER PRIMARY KEY,
  lesson_id INTEGER NOT NULL REFERENCES lessons(id),
  score INTEGER NOT NULL,
  total INTEGER NOT NULL,
  difficulty_feedback TEXT NOT NULL DEFAULT 'right',
  answers_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mastery (
  subject TEXT NOT NULL,
  concept TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_reviewed TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(subject, concept)
);

CREATE TABLE IF NOT EXISTS learner_topic_progress (
  learner_id INTEGER NOT NULL REFERENCES learner_profiles(id),
  subject TEXT NOT NULL,
  concept TEXT NOT NULL,
  mastery_score REAL NOT NULL DEFAULT 0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  success_streak INTEGER NOT NULL DEFAULT 0,
  incorrect_streak INTEGER NOT NULL DEFAULT 0,
  progression_stage TEXT NOT NULL DEFAULT 'foundation',
  recommended_knowledge_level TEXT NOT NULL DEFAULT 'beginner',
  last_reviewed_at TEXT,
  next_review_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(learner_id, subject, concept)
);

CREATE TABLE IF NOT EXISTS learning_attempts (
  id INTEGER PRIMARY KEY,
  learner_id INTEGER NOT NULL REFERENCES learner_profiles(id),
  lesson_id INTEGER REFERENCES lessons(id),
  source_attempt_id INTEGER UNIQUE,
  attempt_type TEXT NOT NULL,
  score INTEGER NOT NULL,
  total INTEGER NOT NULL,
  difficulty_feedback TEXT NOT NULL DEFAULT 'right',
  response_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS misconceptions (
  id INTEGER PRIMARY KEY,
  learner_id INTEGER NOT NULL REFERENCES learner_profiles(id),
  subject TEXT NOT NULL,
  concept TEXT NOT NULL,
  misconception_key TEXT NOT NULL,
  description TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'recall_check',
  occurrence_count INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'OPEN',
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT,
  UNIQUE(learner_id, subject, concept, misconception_key)
);

CREATE TABLE IF NOT EXISTS review_schedule (
  learner_id INTEGER NOT NULL REFERENCES learner_profiles(id),
  subject TEXT NOT NULL,
  concept TEXT NOT NULL,
  due_at TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'SCHEDULED',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(learner_id, subject, concept)
);

CREATE TABLE IF NOT EXISTS lesson_conversations (
  id INTEGER PRIMARY KEY,
  learner_id INTEGER NOT NULL REFERENCES learner_profiles(id),
  lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(learner_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id INTEGER PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES lesson_conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL,
  sources_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_learning_attempts_learner ON learning_attempts(learner_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_schedule_due ON review_schedule(learner_id,status,due_at);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_order ON conversation_messages(conversation_id,id);

CREATE TABLE IF NOT EXISTS source_documents (
  id INTEGER PRIMARY KEY,
  file_name TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  jsonl_path TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL,
  source_id TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL,
  title TEXT NOT NULL,
  publisher TEXT NOT NULL DEFAULT '',
  edition TEXT NOT NULL DEFAULT '',
  file_type TEXT NOT NULL,
  status TEXT NOT NULL,
  records INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topic_nodes (
  id TEXT PRIMARY KEY,
  document_id INTEGER NOT NULL DEFAULT 0,
  source_id TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  parent_id TEXT NOT NULL DEFAULT '',
  node_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  name_origin TEXT NOT NULL DEFAULT 'extracted',
  approval_status TEXT NOT NULL DEFAULT 'PENDING',
  name_locked INTEGER NOT NULL DEFAULT 0,
  page_start INTEGER NOT NULL DEFAULT 0,
  page_end INTEGER NOT NULL DEFAULT 0,
  UNIQUE(document_id,parent_id,node_type,normalized_name)
);
CREATE INDEX IF NOT EXISTS idx_topic_nodes_lookup ON topic_nodes(document_id,parent_id,node_type,normalized_name);

CREATE TABLE IF NOT EXISTS exams (
  id INTEGER PRIMARY KEY,
  exam_name TEXT NOT NULL,
  exam_type TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  topic TEXT NOT NULL DEFAULT '',
  total_questions INTEGER NOT NULL,
  total_time_minutes INTEGER NOT NULL,
  model_name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'READY',
  current_position INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  question_started_at TEXT,
  submitted_at TEXT,
  time_taken_seconds INTEGER NOT NULL DEFAULT 0,
  correct_count INTEGER NOT NULL DEFAULT 0,
  incorrect_count INTEGER NOT NULL DEFAULT 0,
  unanswered_count INTEGER NOT NULL DEFAULT 0,
  marks REAL NOT NULL DEFAULT 0,
  percentage REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exam_subjects (
  exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  subject TEXT NOT NULL,
  question_count INTEGER NOT NULL,
  time_seconds INTEGER NOT NULL,
  PRIMARY KEY(exam_id, subject),
  UNIQUE(exam_id, position)
);

CREATE TABLE IF NOT EXISTS exam_questions (
  id INTEGER PRIMARY KEY,
  exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  subject TEXT NOT NULL,
  topic TEXT NOT NULL DEFAULT '',
  question_text TEXT NOT NULL,
  question_hash TEXT NOT NULL,
  options_json TEXT NOT NULL,
  correct_index INTEGER NOT NULL CHECK(correct_index BETWEEN 0 AND 3),
  explanation TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  source_title TEXT NOT NULL DEFAULT '',
  source_page_start INTEGER NOT NULL DEFAULT 0,
  source_page_end INTEGER NOT NULL DEFAULT 0,
  allotted_seconds INTEGER NOT NULL,
  UNIQUE(exam_id, position),
  UNIQUE(exam_id, question_hash)
);

CREATE TABLE IF NOT EXISTS exam_answers (
  id INTEGER PRIMARY KEY,
  exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES exam_questions(id) ON DELETE CASCADE,
  selected_index INTEGER CHECK(selected_index BETWEEN 0 AND 3),
  answer_status TEXT NOT NULL,
  elapsed_seconds INTEGER NOT NULL DEFAULT 0,
  is_correct INTEGER NOT NULL DEFAULT 0,
  submission_key TEXT NOT NULL,
  submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(exam_id, question_id),
  UNIQUE(exam_id, submission_key)
);
CREATE INDEX IF NOT EXISTS idx_exams_history ON exams(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exam_questions_order ON exam_questions(exam_id,position);
"""


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back like sqlite3.Connection, then release the file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO learner_profiles(id,display_name,is_default) VALUES (1,'Default learner',1)"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_documents)")}
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='source_documents'"
            ).fetchone()["sql"]
            if "sha256 TEXT NOT NULL UNIQUE" in table_sql or not {"source_id", "publisher", "edition"} <= columns:
                connection.executescript("""
                    ALTER TABLE source_documents RENAME TO source_documents_legacy;
                    CREATE TABLE source_documents (
                      id INTEGER PRIMARY KEY, file_name TEXT NOT NULL, stored_path TEXT NOT NULL,
                      jsonl_path TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL,
                      source_id TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL, title TEXT NOT NULL,
                      publisher TEXT NOT NULL DEFAULT '', edition TEXT NOT NULL DEFAULT '',
                      file_type TEXT NOT NULL, status TEXT NOT NULL, records INTEGER NOT NULL DEFAULT 0,
                      error_message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO source_documents
                      (id,file_name,stored_path,jsonl_path,sha256,source_id,subject,title,publisher,edition,file_type,status,records,error_message,created_at)
                    SELECT id,file_name,stored_path,jsonl_path,sha256,'upload-' || substr(sha256,1,16),subject,title,
                           COALESCE((SELECT publisher FROM source_chunks WHERE source_id='upload-' || substr(source_documents_legacy.sha256,1,16) LIMIT 1),''),
                           COALESCE((SELECT edition FROM source_chunks WHERE source_id='upload-' || substr(source_documents_legacy.sha256,1,16) LIMIT 1),''),
                           file_type,status,records,error_message,created_at
                    FROM source_documents_legacy;
                    DROP TABLE source_documents_legacy;
                """)
            chunk_columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_chunks)")}
            additions = {
                "document_id": "INTEGER NOT NULL DEFAULT 0", "section_name": "TEXT NOT NULL DEFAULT ''",
                "chapter": "TEXT NOT NULL DEFAULT ''", "topic_id": "TEXT NOT NULL DEFAULT ''",
                "topic": "TEXT NOT NULL DEFAULT ''", "subtopic_id": "TEXT NOT NULL DEFAULT ''",
                "subtopic": "TEXT NOT NULL DEFAULT ''", "page_start": "INTEGER NOT NULL DEFAULT 0",
                "page_end": "INTEGER NOT NULL DEFAULT 0", "name_origin": "TEXT NOT NULL DEFAULT 'legacy'",
                "approval_status": "TEXT NOT NULL DEFAULT 'APPROVED'", "name_locked": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in chunk_columns:
                    connection.execute(f"ALTER TABLE source_chunks ADD COLUMN {name} {definition}")
            connection.execute("UPDATE source_chunks SET topic=concept WHERE topic='' ")
            connection.execute("UPDATE source_chunks SET chapter=section WHERE chapter='' ")
            node_columns = {row["name"] for row in connection.execute("PRAGMA table_info(topic_nodes)")}
            if "subject" not in node_columns:
                connection.execute("ALTER TABLE topic_nodes ADD COLUMN subject TEXT NOT NULL DEFAULT ''")
            lesson_columns = {row["name"] for row in connection.execute("PRAGMA table_info(lessons)")}
            if "question" not in lesson_columns:
                connection.execute("ALTER TABLE lessons ADD COLUMN question TEXT NOT NULL DEFAULT ''")
            lesson_additions = {
                "learner_age": "INTEGER NOT NULL DEFAULT 18",
                "knowledge_level": "TEXT NOT NULL DEFAULT 'beginner'",
                "learning_profile": "TEXT NOT NULL DEFAULT 'young_adult'",
                "story_style": "TEXT NOT NULL DEFAULT 'realistic_funny'",
                "difficulty": "TEXT NOT NULL DEFAULT 'standard'",
                "model_provider": "TEXT NOT NULL DEFAULT 'ollama'",
                "generation_ms": "INTEGER NOT NULL DEFAULT 0",
                "learner_id": "INTEGER NOT NULL DEFAULT 1",
            }
            age_added = "learner_age" not in lesson_columns
            for name, definition in lesson_additions.items():
                if name not in lesson_columns:
                    connection.execute(f"ALTER TABLE lessons ADD COLUMN {name} {definition}")
            if age_added:
                connection.execute("UPDATE lessons SET learner_age=understanding_level")
            connection.execute("""INSERT OR IGNORE INTO learner_topic_progress
              (learner_id,subject,concept,mastery_score,attempt_count,progression_stage,
               recommended_knowledge_level,last_reviewed_at,next_review_at)
              SELECT 1,subject,concept,score,attempts,
                CASE WHEN score>=0.85 AND attempts>=4 THEN 'mastered'
                     WHEN score>=0.65 AND attempts>=2 THEN 'proficient'
                     WHEN score>=0.35 THEN 'developing' ELSE 'foundation' END,
                CASE WHEN score>=0.85 AND attempts>=4 THEN 'advanced'
                     WHEN score>=0.65 AND attempts>=2 THEN 'intermediate' ELSE 'beginner' END,
                last_reviewed,datetime(last_reviewed,'+3 days')
              FROM mastery""")
            connection.execute("""INSERT OR IGNORE INTO learning_attempts
              (learner_id,lesson_id,source_attempt_id,attempt_type,score,total,difficulty_feedback,response_json,created_at)
              SELECT 1,lesson_id,id,'recall_check',score,total,difficulty_feedback,answers_json,created_at
              FROM comprehension_attempts""")
            connection.execute("""INSERT OR IGNORE INTO review_schedule
              (learner_id,subject,concept,due_at,reason,status)
              SELECT learner_id,subject,concept,COALESCE(next_review_at,CURRENT_TIMESTAMP),'Migrated mastery review','SCHEDULED'
              FROM learner_topic_progress""")

    def ingest(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        inserted = skipped = 0
        sql = """INSERT OR IGNORE INTO source_chunks
            (source_id,title,publisher,authority_tier,license_note,edition,effective_date,subject,concept,section,text,
             document_id,section_name,chapter,topic_id,topic,subtopic_id,subtopic,page_start,page_end,name_origin,approval_status,name_locked)
            VALUES (:source_id,:title,:publisher,:authority_tier,:license_note,:edition,:effective_date,:subject,:concept,:section,:text,
             :document_id,:section_name,:chapter,:topic_id,:topic,:subtopic_id,:subtopic,:page_start,:page_end,:name_origin,:approval_status,:name_locked)"""
        with self.connect() as connection:
            for record in records:
                record = dict(record)
                defaults = {"document_id": 0, "section_name": "", "chapter": record.get("section", ""),
                    "topic_id": "", "topic": record.get("concept", ""), "subtopic_id": "", "subtopic": "",
                    "page_start": 0, "page_end": 0, "name_origin": "legacy", "approval_status": "APPROVED", "name_locked": 0}
                defaults.update(record)
                record = defaults
                before = connection.total_changes
                connection.execute(sql, record)
                was_inserted = connection.total_changes > before
                self._upsert_nodes(connection, record)
                if was_inserted:
                    inserted += 1
                else:
                    skipped += 1
                    connection.execute("""UPDATE source_chunks SET
                      document_id=:document_id,section_name=:section_name,chapter=:chapter,
                      topic_id=:topic_id,topic=:topic,subtopic_id=:subtopic_id,subtopic=:subtopic,
                      page_start=:page_start,page_end=:page_end,name_origin=:name_origin,
                      concept=CASE WHEN :subtopic<>'' THEN :subtopic ELSE :topic END
                      WHERE source_id=:source_id AND section=:section AND text=:text AND name_locked=0""", record)
        return inserted, skipped

    def _upsert_nodes(self, connection: sqlite3.Connection, record: dict[str, Any]) -> None:
        parent = ""
        for node_type, field, id_field in (("section", "section_name", ""), ("chapter", "chapter", ""), ("topic", "topic", "topic_id"), ("subtopic", "subtopic", "subtopic_id")):
            name = clean_name(str(record.get(field, "")))
            if not name:
                continue
            node_id = str(record.get(id_field, "")) if id_field else ""
            node_id = node_id or stable_node_id(str(record["source_id"]), node_type, parent, name)
            connection.execute("""INSERT INTO topic_nodes
              (id,document_id,source_id,subject,parent_id,node_type,display_name,normalized_name,name_origin,approval_status,name_locked,page_start,page_end)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(document_id,parent_id,node_type,normalized_name) DO UPDATE SET
                page_start=CASE WHEN topic_nodes.page_start=0 THEN excluded.page_start ELSE MIN(topic_nodes.page_start,excluded.page_start) END,
                page_end=MAX(topic_nodes.page_end,excluded.page_end)""",
              (node_id,int(record.get("document_id",0)),record["source_id"],record.get("subject",""),parent,node_type,name,normalized_name(name),
               record.get("name_origin","extracted"),record.get("approval_status","PENDING"),int(record.get("name_locked",0)),
               int(record.get("page_start",0)),int(record.get("page_end",0))))
            found = connection.execute("SELECT id FROM topic_nodes WHERE document_id=? AND parent_id=? AND node_type=? AND normalized_name=?",
              (int(record.get("document_id",0)),parent,node_type,normalized_name(name))).fetchone()
            parent = found["id"]

    def create_manual_topic(self, subject: str, name: str, document_id: int = 0, parent_id: str = "") -> dict[str, Any]:
        subject, name = clean_name(subject), clean_name(name)
        if not subject or not name:
            raise ValueError("Subject and topic name are required")
        source_id = f"manual:{normalized_name(subject)}"
        node_id = stable_node_id(source_id, "topic", parent_id, name)
        with self.connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO topic_nodes
              (id,document_id,source_id,subject,parent_id,node_type,display_name,normalized_name,name_origin,approval_status,name_locked)
              VALUES (?,?,?,?,?,?,?,?,?,?,1)""", (node_id,document_id,source_id,subject,parent_id,"topic",name,normalized_name(name),"manual","APPROVED"))
            row = connection.execute("SELECT * FROM topic_nodes WHERE document_id=? AND parent_id=? AND node_type='topic' AND normalized_name=?",
              (document_id,parent_id,normalized_name(name))).fetchone()
            return dict(row)

    def update_topic(self, topic_id: str, action: str, values: dict[str, Any]) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM topic_nodes WHERE id=?", (topic_id,)).fetchone()
            if row is None: return None
            if action == "rename":
                name = clean_name(str(values.get("display_name", "")))
                if not name: raise ValueError("Enter a topic name")
                connection.execute("UPDATE topic_nodes SET display_name=?,normalized_name=?,name_origin='admin_corrected',name_locked=1 WHERE id=?", (name,normalized_name(name),topic_id))
                field = "subtopic" if row["node_type"] == "subtopic" else "topic"
                connection.execute(f"UPDATE source_chunks SET {field}=?,name_origin='admin_corrected',name_locked=1 WHERE {field}_id=?", (name,topic_id))
            elif action in {"approve", "reject"}:
                status = "APPROVED" if action == "approve" else "REJECTED"
                connection.execute("UPDATE topic_nodes SET approval_status=? WHERE id=?", (status,topic_id))
                connection.execute("UPDATE source_chunks SET approval_status=? WHERE topic_id=? OR subtopic_id=?", (status,topic_id,topic_id))
            elif action == "move":
                connection.execute("UPDATE topic_nodes SET parent_id=?,name_origin='admin_corrected',name_locked=1 WHERE id=?", (str(values.get("parent_id", "")),topic_id))
            elif action == "merge":
                target = str(values.get("target_id", ""))
                target_row = connection.execute("SELECT * FROM topic_nodes WHERE id=?", (target,)).fetchone()
                if target_row is None or target == topic_id: raise ValueError("Choose a valid merge target")
                field = "subtopic" if row["node_type"] == "subtopic" else "topic"
                connection.execute(f"UPDATE source_chunks SET {field}_id=?,{field}=? WHERE {field}_id=?", (target,target_row["display_name"],topic_id))
                connection.execute("UPDATE topic_nodes SET parent_id=? WHERE parent_id=?", (target,topic_id))
                connection.execute("DELETE FROM topic_nodes WHERE id=?", (topic_id,))
                return dict(target_row)
            else: raise ValueError("Unsupported review action")
            return dict(connection.execute("SELECT * FROM topic_nodes WHERE id=?", (topic_id,)).fetchone())

    def library_hierarchy(self, search: str = "", subject: str = "", document_id: int = 0) -> dict[str, Any]:
        with self.connect() as connection:
            params: list[Any] = []
            where = []
            if subject: where.append("lower(COALESCE(NULLIF(d.subject,''),n.subject))=lower(?)"); params.append(subject)
            if document_id: where.append("n.document_id=?"); params.append(document_id)
            if search: where.append("n.normalized_name LIKE ?"); params.append(f"%{normalized_name(search)}%")
            clause = " WHERE " + " AND ".join(where) if where else ""
            rows = [dict(r) for r in connection.execute(f"""SELECT n.*,COALESCE(NULLIF(d.subject,''),n.subject) AS subject,d.title AS book,
              (SELECT COUNT(*) FROM topic_nodes c WHERE c.parent_id=n.id) AS child_count,
              (SELECT COUNT(*) FROM source_chunks s WHERE s.topic_id=n.id OR s.subtopic_id=n.id) AS concept_count
              FROM topic_nodes n LEFT JOIN source_documents d ON d.id=n.document_id{clause}
              ORDER BY d.subject COLLATE NOCASE,d.title COLLATE NOCASE,n.page_start,n.display_name COLLATE NOCASE""", params)]
            docs = [dict(r) for r in connection.execute("SELECT id,subject,title,status,records FROM source_documents ORDER BY subject,title")]
        return {"mode": "matches" if search else "tree", "nodes": rows, "documents": docs}

    def chunks(self, subject: str = "") -> list[sqlite3.Row]:
        with self.connect() as connection:
            if subject:
                return connection.execute(
                    "SELECT * FROM source_chunks WHERE lower(subject)=lower(?)", (subject,)
                ).fetchall()
            return connection.execute("SELECT * FROM source_chunks").fetchall()

    def memories(self, subject: str, concept: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM memories
                   WHERE superseded_by IS NULL
                     AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                     AND (subject='' OR lower(subject)=lower(?))
                     AND (concept='' OR lower(concept)=lower(?))
                   ORDER BY salience DESC, created_at DESC LIMIT 20""",
                (subject, concept),
            ).fetchall()

    def add_memory(self, kind: str, content: str, subject: str = "", concept: str = "", salience: float = 0.5) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO memories(kind,subject,concept,content,salience) VALUES (?,?,?,?,?)",
                (kind, subject, concept, content, salience),
            )
            return int(cursor.lastrowid)

    def add_memory_if_absent(self, kind: str, content: str, subject: str = "", concept: str = "", salience: float = 0.5) -> int:
        with self.connect() as connection:
            existing = connection.execute("""SELECT id FROM memories WHERE superseded_by IS NULL AND kind=?
              AND lower(subject)=lower(?) AND lower(concept)=lower(?) AND lower(trim(content))=lower(trim(?))""",
              (kind, subject, concept, content)).fetchone()
            if existing:
                return int(existing["id"])
            cursor = connection.execute("INSERT INTO memories(kind,subject,concept,content,salience) VALUES (?,?,?,?,?)",
              (kind, subject, concept, content, salience))
            return int(cursor.lastrowid)

    def delete_memory(self, memory_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            return cursor.rowcount > 0

    def cached_lesson(self, cache_key: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM lessons WHERE cache_key=? AND status='PASS'", (cache_key,)
            ).fetchone()

    def save_lesson(self, values: dict[str, Any]) -> int:
        values = {"learner_id": 1, **values}
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO lessons
                (cache_key,subject,concept,question,understanding_level,learner_age,knowledge_level,learning_profile,
                 story_style,difficulty,language,model_provider,model_name,generation_ms,
                 evidence_json,context_json,lesson_json,verification_json,status,learner_id)
                VALUES (:cache_key,:subject,:concept,:question,:understanding_level,:learner_age,:knowledge_level,:learning_profile,
                 :story_style,:difficulty,:language,:model_provider,:model_name,:generation_ms,
                 :evidence_json,:context_json,:lesson_json,:verification_json,:status,:learner_id)
                ON CONFLICT(cache_key) DO UPDATE SET
                  subject=excluded.subject,concept=excluded.concept,question=excluded.question,
                  understanding_level=excluded.understanding_level,learner_age=excluded.learner_age,
                  knowledge_level=excluded.knowledge_level,learning_profile=excluded.learning_profile,
                  story_style=excluded.story_style,difficulty=excluded.difficulty,language=excluded.language,
                  model_provider=excluded.model_provider,model_name=excluded.model_name,generation_ms=excluded.generation_ms,
                  evidence_json=excluded.evidence_json,context_json=excluded.context_json,lesson_json=excluded.lesson_json,
                  verification_json=excluded.verification_json,status=excluded.status,learner_id=excluded.learner_id""",
                values,
            )
            return int(connection.execute("SELECT id FROM lessons WHERE cache_key=?", (values["cache_key"],)).fetchone()["id"])

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO events(event_type,payload_json) VALUES (?,?)",
                (event_type, json.dumps(payload, ensure_ascii=False)),
            )

    def lesson_history(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT id,subject,concept,question,understanding_level,learner_age,knowledge_level,
                          learning_profile,story_style,difficulty,language,status,created_at
                   FROM lessons ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()

    def lesson_detail(self, lesson_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()

    def conversation_for_lesson(self, lesson_id: int, learner_id: int = 1) -> dict[str, Any] | None:
        with self.connect() as connection:
            lesson = connection.execute("SELECT id FROM lessons WHERE id=? AND status='PASS'", (lesson_id,)).fetchone()
            if lesson is None:
                return None
            conversation = connection.execute("""SELECT id,status,summary,created_at,updated_at
              FROM lesson_conversations WHERE learner_id=? AND lesson_id=?""", (learner_id, lesson_id)).fetchone()
            if conversation is None:
                return {"conversation_id": None, "lesson_id": lesson_id, "status": "EMPTY", "summary": "", "messages": []}
            messages = []
            for row in connection.execute("""SELECT id,role,content,sources_json,created_at FROM conversation_messages
              WHERE conversation_id=? ORDER BY id""", (conversation["id"],)).fetchall():
                item = dict(row)
                item["sources"] = json.loads(item.pop("sources_json"))
                messages.append(item)
            return {"conversation_id": int(conversation["id"]), "lesson_id": lesson_id,
                    "status": conversation["status"], "summary": conversation["summary"], "messages": messages}

    def get_or_create_conversation(self, lesson_id: int, conversation_id: int | None = None,
                                   learner_id: int = 1) -> int:
        with self.connect() as connection:
            lesson = connection.execute("SELECT id FROM lessons WHERE id=? AND status='PASS'", (lesson_id,)).fetchone()
            if lesson is None:
                raise ValueError("Verified lesson not found")
            if conversation_id:
                row = connection.execute("""SELECT id FROM lesson_conversations
                  WHERE id=? AND lesson_id=? AND learner_id=?""", (conversation_id, lesson_id, learner_id)).fetchone()
                if row is None:
                    raise ValueError("This follow-up conversation does not belong to the selected lesson")
                return int(row["id"])
            connection.execute("""INSERT OR IGNORE INTO lesson_conversations(learner_id,lesson_id)
              VALUES (?,?)""", (learner_id, lesson_id))
            row = connection.execute("SELECT id FROM lesson_conversations WHERE learner_id=? AND lesson_id=?",
                                     (learner_id, lesson_id)).fetchone()
            return int(row["id"])

    def conversation_context(self, conversation_id: int, max_messages: int = 6) -> dict[str, Any]:
        max_messages = max(1, min(int(max_messages), 12))
        with self.connect() as connection:
            conversation = connection.execute("SELECT summary FROM lesson_conversations WHERE id=?", (conversation_id,)).fetchone()
            if conversation is None:
                raise ValueError("Follow-up conversation not found")
            rows = connection.execute("""SELECT role,content FROM (
              SELECT id,role,content FROM conversation_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?
            ) ORDER BY id""", (conversation_id, max_messages)).fetchall()
            return {"summary": conversation["summary"], "recent_messages": [dict(row) for row in rows]}

    def save_followup_exchange(
        self, conversation_id: int, question: str, answer: str, sources: list[dict[str, Any]],
        summary: str = "", possible_misconception: str = "", learner_id: int = 1,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            conversation = connection.execute("""SELECT c.lesson_id,l.subject,l.concept FROM lesson_conversations c
              JOIN lessons l ON l.id=c.lesson_id WHERE c.id=? AND c.learner_id=?""",
              (conversation_id, learner_id)).fetchone()
            if conversation is None:
                raise ValueError("Follow-up conversation not found")
            connection.execute("INSERT INTO conversation_messages(conversation_id,role,content) VALUES (?,'user',?)",
                               (conversation_id, question))
            cursor = connection.execute("""INSERT INTO conversation_messages(conversation_id,role,content,sources_json)
              VALUES (?,'assistant',?,?)""", (conversation_id, answer, json.dumps(sources, ensure_ascii=False)))
            summary = " ".join(summary.split())[:800]
            connection.execute("""UPDATE lesson_conversations SET summary=?,status='ACTIVE',updated_at=CURRENT_TIMESTAMP
              WHERE id=?""", (summary, conversation_id))
            signal = " ".join(possible_misconception.split())[:300]
            if signal:
                key = misconception_key(signal)
                connection.execute("""INSERT INTO misconceptions
                  (learner_id,subject,concept,misconception_key,description,source,status)
                  VALUES (?,?,?,?,?,'followup_signal','POSSIBLE')
                  ON CONFLICT(learner_id,subject,concept,misconception_key) DO UPDATE SET
                    occurrence_count=misconceptions.occurrence_count+1,last_seen_at=CURRENT_TIMESTAMP""",
                  (learner_id, conversation["subject"], conversation["concept"], key, signal))
            return {"conversation_id": conversation_id, "message_id": int(cursor.lastrowid),
                    "answer": answer, "sources": sources}

    def clear_conversation(self, lesson_id: int, learner_id: int = 1) -> bool:
        with self.connect() as connection:
            conversation = connection.execute("SELECT id FROM lesson_conversations WHERE learner_id=? AND lesson_id=?",
                                              (learner_id, lesson_id)).fetchone()
            if conversation is None:
                return False
            connection.execute("DELETE FROM conversation_messages WHERE conversation_id=?", (conversation["id"],))
            connection.execute("""UPDATE lesson_conversations SET summary='',status='CLEARED',updated_at=CURRENT_TIMESTAMP
              WHERE id=?""", (conversation["id"],))
            return True

    def progression_context(self, subject: str, concept: str, learner_id: int = 1) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("""SELECT mastery_score,attempt_count,success_streak,incorrect_streak,
              progression_stage,recommended_knowledge_level,last_reviewed_at,next_review_at
              FROM learner_topic_progress WHERE learner_id=? AND lower(subject)=lower(?) AND lower(concept)=lower(?)""",
              (learner_id, subject, concept)).fetchone()
            open_misconceptions = [item["description"] for item in connection.execute("""SELECT description FROM misconceptions
              WHERE learner_id=? AND lower(subject)=lower(?) AND lower(concept)=lower(?) AND status='OPEN'
              ORDER BY last_seen_at DESC LIMIT 5""", (learner_id, subject, concept)).fetchall()]
        if row is None:
            return {"stage": "not_started", "mastery_score": 0.0, "attempt_count": 0,
                    "recommended_knowledge_level": "beginner", "open_misconceptions": open_misconceptions}
        return {"stage": row["progression_stage"], "mastery_score": round(float(row["mastery_score"]), 3),
                "attempt_count": int(row["attempt_count"]), "success_streak": int(row["success_streak"]),
                "incorrect_streak": int(row["incorrect_streak"]),
                "recommended_knowledge_level": row["recommended_knowledge_level"],
                "last_reviewed_at": row["last_reviewed_at"], "next_review_at": row["next_review_at"],
                "open_misconceptions": open_misconceptions}

    def save_comprehension(
        self, lesson_id: int, score: int, total: int, answers: list[int], difficulty: str,
        questions: list[dict[str, Any]] | None = None, learner_id: int = 1,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            lesson = connection.execute("SELECT subject,concept FROM lessons WHERE id=? AND status='PASS'", (lesson_id,)).fetchone()
            if lesson is None:
                raise ValueError("Verified lesson not found")
            cursor = connection.execute(
                "INSERT INTO comprehension_attempts(lesson_id,score,total,difficulty_feedback,answers_json) VALUES (?,?,?,?,?)",
                (lesson_id, score, total, difficulty, json.dumps(answers)),
            )
            progress = connection.execute("""SELECT mastery_score,attempt_count,success_streak,incorrect_streak
              FROM learner_topic_progress WHERE learner_id=? AND lower(subject)=lower(?) AND lower(concept)=lower(?)""",
              (learner_id, lesson["subject"], lesson["concept"])).fetchone()
            decision = progression_update(
                current_score=float(progress["mastery_score"]) if progress else 0.0,
                attempt_count=int(progress["attempt_count"]) if progress else 0,
                success_streak=int(progress["success_streak"]) if progress else 0,
                incorrect_streak=int(progress["incorrect_streak"]) if progress else 0,
                score=score, total=total, difficulty_feedback=difficulty,
            )
            connection.execute(
                """INSERT INTO mastery(subject,concept,score,attempts,last_reviewed) VALUES (?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(subject,concept) DO UPDATE SET score=excluded.score,attempts=excluded.attempts,last_reviewed=CURRENT_TIMESTAMP""",
                (lesson["subject"], lesson["concept"], decision.mastery_score, decision.attempt_count),
            )
            connection.execute("""INSERT INTO learner_topic_progress
              (learner_id,subject,concept,mastery_score,attempt_count,success_streak,incorrect_streak,
               progression_stage,recommended_knowledge_level,last_reviewed_at,next_review_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?,CURRENT_TIMESTAMP)
              ON CONFLICT(learner_id,subject,concept) DO UPDATE SET
                mastery_score=excluded.mastery_score,attempt_count=excluded.attempt_count,
                success_streak=excluded.success_streak,incorrect_streak=excluded.incorrect_streak,
                progression_stage=excluded.progression_stage,
                recommended_knowledge_level=excluded.recommended_knowledge_level,
                last_reviewed_at=CURRENT_TIMESTAMP,next_review_at=excluded.next_review_at,updated_at=CURRENT_TIMESTAMP""",
              (learner_id, lesson["subject"], lesson["concept"], decision.mastery_score,
               decision.attempt_count, decision.success_streak, decision.incorrect_streak,
               decision.progression_stage, decision.recommended_knowledge_level, decision.next_review_at))
            response = {"answers": answers, "questions": questions or []}
            connection.execute("""INSERT INTO learning_attempts
              (learner_id,lesson_id,source_attempt_id,attempt_type,score,total,difficulty_feedback,response_json)
              VALUES (?,?,?,'recall_check',?,?,?,?)""",
              (learner_id, lesson_id, int(cursor.lastrowid), score, total, difficulty, json.dumps(response, ensure_ascii=False)))
            connection.execute("""INSERT INTO review_schedule(learner_id,subject,concept,due_at,reason,status,updated_at)
              VALUES (?,?,?,?,?,'SCHEDULED',CURRENT_TIMESTAMP)
              ON CONFLICT(learner_id,subject,concept) DO UPDATE SET due_at=excluded.due_at,reason=excluded.reason,
                status='SCHEDULED',updated_at=CURRENT_TIMESTAMP""",
              (learner_id, lesson["subject"], lesson["concept"], decision.next_review_at,
               f"Recall mastery {round(decision.mastery_score * 100)}%"))
            for index, item in enumerate(questions or []):
                description = " ".join(str(item.get("question", "")).split())[:300]
                if not description:
                    continue
                key = misconception_key(description)
                correct = index < len(answers) and answers[index] == item.get("correct_index")
                if correct:
                    connection.execute("""UPDATE misconceptions SET status='RESOLVED',resolved_at=CURRENT_TIMESTAMP
                      WHERE learner_id=? AND lower(subject)=lower(?) AND lower(concept)=lower(?) AND misconception_key=?""",
                      (learner_id, lesson["subject"], lesson["concept"], key))
                else:
                    connection.execute("""INSERT INTO misconceptions
                      (learner_id,subject,concept,misconception_key,description,source)
                      VALUES (?,?,?,?,?,'recall_check')
                      ON CONFLICT(learner_id,subject,concept,misconception_key) DO UPDATE SET
                        occurrence_count=misconceptions.occurrence_count+1,status='OPEN',last_seen_at=CURRENT_TIMESTAMP,resolved_at=NULL""",
                      (learner_id, lesson["subject"], lesson["concept"], key, f"Review: {description}"))
            return {"subject": lesson["subject"], "concept": lesson["concept"],
                    "mastery": decision.mastery_score, "attempts": decision.attempt_count,
                    "stage": decision.progression_stage,
                    "recommended_knowledge_level": decision.recommended_knowledge_level,
                    "success_streak": decision.success_streak, "next_review_at": decision.next_review_at}

    def progress(self) -> dict[str, Any]:
        with self.connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) AS lessons,
                          SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) AS verified,
                          COUNT(DISTINCT CASE WHEN status='PASS' THEN lower(subject)||':'||lower(concept) END) AS concepts
                   FROM lessons"""
            ).fetchone()
            checks = connection.execute("SELECT COUNT(*) AS attempts, COALESCE(SUM(score),0) AS correct, COALESCE(SUM(total),0) AS total FROM comprehension_attempts").fetchone()
            mastery = [dict(row) for row in connection.execute("""SELECT subject,concept,mastery_score AS score,
              attempt_count AS attempts,success_streak,incorrect_streak,progression_stage,
              recommended_knowledge_level,last_reviewed_at AS last_reviewed,next_review_at
              FROM learner_topic_progress WHERE learner_id=1 ORDER BY mastery_score ASC,last_reviewed_at DESC""").fetchall()]
            due_reviews = connection.execute("""SELECT COUNT(*) AS count FROM review_schedule
              WHERE learner_id=1 AND status='SCHEDULED' AND datetime(due_at)<=CURRENT_TIMESTAMP""").fetchone()["count"]
            open_misconceptions = connection.execute("""SELECT COUNT(*) AS count FROM misconceptions
              WHERE learner_id=1 AND status='OPEN'""").fetchone()["count"]
            learner = connection.execute("SELECT id,display_name FROM learner_profiles WHERE id=1").fetchone()
            return {
                "lessons": int(totals["lessons"] or 0), "verified_lessons": int(totals["verified"] or 0),
                "concepts_studied": int(totals["concepts"] or 0), "check_attempts": int(checks["attempts"] or 0),
                "check_accuracy": round(float(checks["correct"]) / float(checks["total"]), 3) if checks["total"] else 0,
                "mastery": mastery, "due_reviews": int(due_reviews or 0),
                "open_misconceptions": int(open_misconceptions or 0),
                "learner": dict(learner) if learner else {"id": 1, "display_name": "Default learner"},
            }

    def content_inventory(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT subject,concept,COUNT(*) AS chunks,COUNT(DISTINCT source_id) AS sources,
                          GROUP_CONCAT(DISTINCT authority_tier) AS authority_tiers
                   FROM source_chunks GROUP BY subject,concept ORDER BY subject,concept"""
            ).fetchall()]

    def catalog(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT subject, CASE WHEN subtopic<>'' THEN subtopic WHEN topic<>'' THEN topic ELSE concept END AS concept,
                          COUNT(*) AS chunks, COUNT(DISTINCT source_id) AS sources
                   FROM source_chunks GROUP BY lower(subject),lower(trim(CASE WHEN subtopic<>'' THEN subtopic WHEN topic<>'' THEN topic ELSE concept END))
                   ORDER BY subject COLLATE NOCASE, concept COLLATE NOCASE"""
            ).fetchall()
        subjects: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = subjects.setdefault(row["subject"], {"subject": row["subject"], "topics": [], "chunks": 0, "sources": 0})
            item["topics"].append(row["concept"])
            item["chunks"] += int(row["chunks"])
            item["sources"] += int(row["sources"])
        return list(subjects.values())

    def register_document(self, values: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO source_documents
                   (file_name,stored_path,jsonl_path,sha256,source_id,subject,title,publisher,edition,file_type,status,records,error_message)
                   VALUES (:file_name,:stored_path,:jsonl_path,:sha256,:source_id,:subject,:title,:publisher,:edition,:file_type,:status,:records,:error_message)""",
                values,
            )
            return int(cursor.lastrowid)

    def update_document(self, document_id: int, *, status: str, jsonl_path: str = "", records: int = 0, error_message: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE source_documents SET status=?,jsonl_path=?,records=?,error_message=? WHERE id=?",
                (status, jsonl_path, records, error_message, document_id),
            )

    def prepare_reprocess(self, document_id: int) -> None:
        """Remove only replaceable extracted names; approvals and locked corrections remain."""
        with self.connect() as connection:
            connection.execute("DELETE FROM topic_nodes WHERE document_id=? AND name_locked=0", (document_id,))
            connection.execute("""UPDATE source_chunks SET section_name='',chapter='',topic_id='',topic='',
              subtopic_id='',subtopic='',page_start=0,page_end=0,name_origin='legacy'
              WHERE document_id=? AND name_locked=0""", (document_id,))

    def documents(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            documents = [dict(row) for row in connection.execute(
                """SELECT id,file_name,stored_path,source_id,subject,title,publisher,edition,file_type,status,
                          records,error_message,created_at,jsonl_path
                   FROM source_documents ORDER BY id DESC"""
            ).fetchall()]
            for document in documents:
                document["topics"] = [row["concept"] for row in connection.execute(
                    "SELECT DISTINCT concept FROM source_chunks WHERE source_id=? ORDER BY concept COLLATE NOCASE",
                    (document["source_id"],),
                ).fetchall()] if document["source_id"] else []
            return documents

    def document(self, document_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM source_documents WHERE id=?", (document_id,)).fetchone()
            return dict(row) if row else None

    def delete_document(self, document_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM source_documents WHERE id=?", (document_id,)).fetchone()
            if row is None:
                return None
            document = dict(row)
            if document["source_id"]:
                connection.execute("DELETE FROM source_chunks WHERE source_id=?", (document["source_id"],))
            connection.execute("DELETE FROM source_documents WHERE id=?", (document_id,))
            return document

    def delete_document_topic(self, document_id: int, concept: str) -> int | None:
        with self.connect() as connection:
            document = connection.execute("SELECT source_id FROM source_documents WHERE id=?", (document_id,)).fetchone()
            if document is None:
                return None
            cursor = connection.execute(
                "DELETE FROM source_chunks WHERE source_id=? AND lower(concept)=lower(?)",
                (document["source_id"], concept),
            )
            remaining = connection.execute(
                "SELECT COUNT(*) AS count FROM source_chunks WHERE source_id=?", (document["source_id"],)
            ).fetchone()["count"]
            connection.execute("UPDATE source_documents SET records=? WHERE id=?", (remaining, document_id))
            return int(cursor.rowcount)

    def memory_inventory(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id,kind,subject,concept,content,salience,created_at FROM memories WHERE superseded_by IS NULL ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()]

    def create_exam(self, values: dict[str, Any], allocations: list[dict[str, Any]], questions: list[dict[str, Any]]) -> int:
        if len(questions) != int(values["total_questions"]):
            raise ValueError("Generated question count does not match the exam configuration")
        with self.connect() as connection:
            cursor = connection.execute("""INSERT INTO exams
              (exam_name,exam_type,difficulty,topic,total_questions,total_time_minutes,model_name,config_json,status)
              VALUES (:exam_name,:exam_type,:difficulty,:topic,:total_questions,:total_time_minutes,:model_name,:config_json,'READY')""", values)
            exam_id = int(cursor.lastrowid)
            for position, item in enumerate(allocations, 1):
                connection.execute("INSERT INTO exam_subjects(exam_id,position,subject,question_count,time_seconds) VALUES (?,?,?,?,?)",
                                   (exam_id, position, item["subject"], item["question_count"], item["time_seconds"]))
            for position, item in enumerate(questions, 1):
                connection.execute("""INSERT INTO exam_questions
                  (exam_id,position,subject,topic,question_text,question_hash,options_json,correct_index,explanation,
                   evidence_id,source_title,source_page_start,source_page_end,allotted_seconds)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (exam_id, position, item["subject"], item.get("topic", ""), item["question"], item["question_hash"],
                   json.dumps(item["options"], ensure_ascii=False), item["correct_index"], item["explanation"],
                   item["evidence_id"], item.get("source_title", ""), int(item.get("source_page_start", 0)),
                   int(item.get("source_page_end", 0)), int(item["allotted_seconds"])))
            self._record_event(connection, "exam_generated", {"exam_id": exam_id, "questions": len(questions)})
            return exam_id

    @staticmethod
    def _record_event(connection: sqlite3.Connection, event_type: str, payload: dict[str, Any]) -> None:
        connection.execute("INSERT INTO events(event_type,payload_json) VALUES (?,?)",
                           (event_type, json.dumps(payload, ensure_ascii=False)))

    def exam_history(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("""SELECT e.id,e.exam_name,e.exam_type,e.difficulty,e.topic,
              e.total_questions,e.total_time_minutes,e.status,e.correct_count,e.incorrect_count,e.unanswered_count,
              e.marks,e.percentage,e.time_taken_seconds,e.created_at,e.submitted_at,
              GROUP_CONCAT(s.subject, ' · ') AS subjects
              FROM exams e LEFT JOIN exam_subjects s ON s.exam_id=e.id GROUP BY e.id ORDER BY e.id DESC LIMIT ?""", (limit,))]

    @staticmethod
    def _elapsed_seconds(connection: sqlite3.Connection, timestamp: str | None) -> int:
        if not timestamp:
            return 0
        row = connection.execute("SELECT MAX(0,CAST((julianday('now')-julianday(?))*86400 AS INTEGER)) AS seconds", (timestamp,)).fetchone()
        return int(row["seconds"] or 0)

    def _exam_payload(self, connection: sqlite3.Connection, exam_id: int, reveal_answers: bool) -> dict[str, Any] | None:
        exam = connection.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
        if exam is None:
            return None
        result = dict(exam)
        result["subjects"] = [dict(row) for row in connection.execute(
            "SELECT subject,question_count,time_seconds FROM exam_subjects WHERE exam_id=? ORDER BY position", (exam_id,))]
        total_seconds = int(exam["total_time_minutes"]) * 60
        elapsed = self._elapsed_seconds(connection, exam["started_at"])
        result["remaining_seconds"] = max(0, total_seconds - elapsed) if exam["started_at"] and exam["status"] != "COMPLETED" else 0
        result.pop("config_json", None)
        if exam["status"] == "COMPLETED" or reveal_answers:
            rows = connection.execute("""SELECT q.id,q.position,q.subject,q.topic,q.question_text,q.options_json,q.correct_index,
              q.explanation,q.evidence_id,q.source_title,q.source_page_start,q.source_page_end,q.allotted_seconds,
              a.selected_index,a.answer_status,a.elapsed_seconds,a.is_correct
              FROM exam_questions q LEFT JOIN exam_answers a ON a.exam_id=q.exam_id AND a.question_id=q.id
              WHERE q.exam_id=? ORDER BY q.position""", (exam_id,)).fetchall()
            result["analysis"] = [{**dict(row), "options": json.loads(row["options_json"])} for row in rows]
            for item in result["analysis"]:
                item.pop("options_json", None)
        elif exam["status"] == "IN_PROGRESS":
            row = connection.execute("SELECT id,position,subject,topic,question_text,options_json,allotted_seconds FROM exam_questions WHERE exam_id=? AND position=?",
                                     (exam_id, exam["current_position"])).fetchone()
            if row:
                question = dict(row); question["options"] = json.loads(question.pop("options_json"))
                question["remaining_seconds"] = max(0, int(row["allotted_seconds"]) - self._elapsed_seconds(connection, exam["question_started_at"]))
                result["current_question"] = question
        return result

    def exam_detail(self, exam_id: int, reveal_answers: bool = False) -> dict[str, Any] | None:
        with self.connect() as connection:
            exam = connection.execute("SELECT status,started_at,total_time_minutes FROM exams WHERE id=?", (exam_id,)).fetchone()
            if exam and exam["status"] == "IN_PROGRESS" and self._elapsed_seconds(connection, exam["started_at"]) >= int(exam["total_time_minutes"]) * 60:
                return self._finish_exam(connection, exam_id)
            return self._exam_payload(connection, exam_id, reveal_answers)

    def start_exam(self, exam_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            exam = connection.execute("SELECT status FROM exams WHERE id=?", (exam_id,)).fetchone()
            if exam is None:
                return None
            if exam["status"] == "READY":
                connection.execute("UPDATE exams SET status='IN_PROGRESS',current_position=1,started_at=CURRENT_TIMESTAMP,question_started_at=CURRENT_TIMESTAMP WHERE id=?", (exam_id,))
                self._record_event(connection, "exam_started", {"exam_id": exam_id})
            return self._exam_payload(connection, exam_id, False)

    def _finish_exam(self, connection: sqlite3.Connection, exam_id: int) -> dict[str, Any]:
        exam = connection.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
        if exam is None:
            raise ValueError("Exam not found")
        if exam["status"] == "COMPLETED":
            return self._exam_payload(connection, exam_id, True) or {}
        answered_ids = {row["question_id"] for row in connection.execute("SELECT question_id FROM exam_answers WHERE exam_id=?", (exam_id,))}
        for row in connection.execute("SELECT id FROM exam_questions WHERE exam_id=?", (exam_id,)):
            if row["id"] not in answered_ids:
                connection.execute("""INSERT INTO exam_answers
                  (exam_id,question_id,selected_index,answer_status,elapsed_seconds,is_correct,submission_key)
                  VALUES (?,?,NULL,'UNANSWERED',0,0,?)""", (exam_id, row["id"], f"finish-{exam_id}-{row['id']}"))
        counts = connection.execute("""SELECT
          SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct,
          SUM(CASE WHEN answer_status='ANSWERED' AND is_correct=0 THEN 1 ELSE 0 END) AS incorrect,
          SUM(CASE WHEN answer_status IN ('UNANSWERED','TIMED_OUT') THEN 1 ELSE 0 END) AS unanswered
          FROM exam_answers WHERE exam_id=?""", (exam_id,)).fetchone()
        correct = int(counts["correct"] or 0); incorrect = int(counts["incorrect"] or 0); unanswered = int(counts["unanswered"] or 0)
        total = int(exam["total_questions"]); elapsed = min(int(exam["total_time_minutes"]) * 60, self._elapsed_seconds(connection, exam["started_at"]))
        percentage = round((correct / total) * 100, 2) if total else 0
        connection.execute("""UPDATE exams SET status='COMPLETED',submitted_at=CURRENT_TIMESTAMP,time_taken_seconds=?,
          correct_count=?,incorrect_count=?,unanswered_count=?,marks=?,percentage=? WHERE id=?""",
          (elapsed, correct, incorrect, unanswered, float(correct), percentage, exam_id))
        self._record_event(connection, "exam_completed", {"exam_id": exam_id, "correct": correct, "total": total})
        return self._exam_payload(connection, exam_id, True) or {}

    def submit_exam_answer(self, exam_id: int, question_id: int, selected_index: int | None, submission_key: str,
                           force_timeout: bool = False) -> dict[str, Any] | None:
        submission_key = " ".join(str(submission_key or "").split())[:100]
        if not submission_key:
            raise ValueError("A submission key is required")
        if selected_index is not None and (isinstance(selected_index, bool) or not isinstance(selected_index, int) or not 0 <= selected_index <= 3):
            raise ValueError("Selected option must be between 0 and 3")
        with self.connect() as connection:
            exam = connection.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
            if exam is None:
                return None
            if exam["status"] == "COMPLETED":
                return self._exam_payload(connection, exam_id, True)
            if exam["status"] != "IN_PROGRESS":
                raise ValueError("Start the exam before answering")
            total_elapsed = self._elapsed_seconds(connection, exam["started_at"])
            if total_elapsed >= int(exam["total_time_minutes"]) * 60:
                return self._finish_exam(connection, exam_id)
            question = connection.execute("SELECT * FROM exam_questions WHERE exam_id=? AND id=?", (exam_id, question_id)).fetchone()
            if question is None or int(question["position"]) != int(exam["current_position"]):
                raise ValueError("This question is not currently open")
            existing = connection.execute("SELECT id FROM exam_answers WHERE exam_id=? AND question_id=?", (exam_id, question_id)).fetchone()
            if existing:
                return self._exam_payload(connection, exam_id, False)
            reused_key = connection.execute("SELECT question_id FROM exam_answers WHERE exam_id=? AND submission_key=?", (exam_id, submission_key)).fetchone()
            if reused_key:
                raise ValueError("This submission key was already used for another question")
            question_elapsed = self._elapsed_seconds(connection, exam["question_started_at"])
            timed_out = force_timeout or question_elapsed >= int(question["allotted_seconds"])
            if timed_out:
                selected_index = None
            status = "TIMED_OUT" if timed_out else ("ANSWERED" if selected_index is not None else "UNANSWERED")
            is_correct = int(selected_index is not None and selected_index == int(question["correct_index"]))
            connection.execute("""INSERT INTO exam_answers
              (exam_id,question_id,selected_index,answer_status,elapsed_seconds,is_correct,submission_key)
              VALUES (?,?,?,?,?,?,?)""", (exam_id, question_id, selected_index, status,
                                            min(question_elapsed, int(question["allotted_seconds"])), is_correct, submission_key))
            next_position = int(exam["current_position"]) + 1
            if next_position > int(exam["total_questions"]):
                return self._finish_exam(connection, exam_id)
            connection.execute("UPDATE exams SET current_position=?,question_started_at=CURRENT_TIMESTAMP WHERE id=?", (next_position, exam_id))
            return self._exam_payload(connection, exam_id, False)

    def finish_exam(self, exam_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            if connection.execute("SELECT id FROM exams WHERE id=?", (exam_id,)).fetchone() is None:
                return None
            return self._finish_exam(connection, exam_id)
