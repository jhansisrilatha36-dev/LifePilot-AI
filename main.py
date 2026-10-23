
from contextlib import asynccontextmanager
from datetime import datetime, date
from pathlib import Path
import json
import re
import sqlite3
import os
from typing import Optional

from dotenv import load_dotenv
from google import genai
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# --------------------------------------------------
# 1. PROJECT CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lifepilot.db"
STATIC_DIR = BASE_DIR / "static"

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)
print("Gemini API key loaded:", bool(GEMINI_API_KEY))

# --------------------------------------------------
# 2. GEMINI AI
# --------------------------------------------------


def ask_gemini(message):
    """Answer general questions using recent conversation history."""
    if gemini_client is None:
        return (
            "Gemini is not configured. Please add your "
            "GEMINI_API_KEY to the .env file."
        )

    # Fetch the five most recent saved conversations.
    with get_db() as conn:
        
        rows = conn.execute(
            """
            SELECT user_message, assistant_message
            FROM conversations
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()


    # Display them in chronological order for Gemini.
    rows = list(reversed(rows))

    history = []
    for row in rows:
        history.append(f"User: {row['user_message']}")
        history.append(f"LifePilot AI: {row['assistant_message']}")

    conversation_context = "\n".join(history)

    prompt = f"""
You are LifePilot AI, a personal assistant with access to the saved history below.

Use the history to answer follow-up questions.
Do not claim you cannot remember previous messages when the relevant
messages are included in the history.
If the history does not contain the answer, say so honestly.

SAVED CONVERSATION HISTORY:
{conversation_context}

CURRENT USER MESSAGE:
{message}

Answer the current message directly and naturally.
"""

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    return response.text or "Gemini did not return a text response."


# --------------------------------------------------
# 3. DATABASE
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT,
                priority TEXT NOT NULL DEFAULT 'medium',
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# --------------------------------------------------
# 4. FASTAPI APPLICATION
# --------------------------------------------------

app = FastAPI(
    title="LifePilot AI",
    description=(
        "A student productivity assistant with task-management "
        "tools and Gemini AI."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)


# --------------------------------------------------
# 5. REQUEST MODELS
# --------------------------------------------------

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    due_date: Optional[str] = None
    priority: str = "medium"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------
# 6. TASK MANAGEMENT FUNCTIONS
# --------------------------------------------------

def row_to_task(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "due_date": row["due_date"],
        "priority": row["priority"],
        "completed": bool(row["completed"]),
        "created_at": row["created_at"],
    }


def list_tasks():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM tasks
            ORDER BY completed ASC,
              CASE priority
                  WHEN 'high' THEN 1
                  WHEN 'medium' THEN 2
                  ELSE 3
              END,
              CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
              due_date ASC,
              id DESC
        """).fetchall()

    return [row_to_task(row) for row in rows]


def create_task(title, due_date=None, priority="medium"):
    title = title.strip()

    if not title:
        raise ValueError("Task title cannot be empty.")

    if priority not in {"low", "medium", "high"}:
        priority = "medium"

    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError:
            raise ValueError("Due date must use YYYY-MM-DD.")

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks
            (title, due_date, priority, completed, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (
                title,
                due_date,
                priority,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

        task_id = cur.lastrowid

        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

    return row_to_task(row)


def update_task(task_id, completed=None, priority=None):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        new_completed = (
            row["completed"]
            if completed is None
            else int(completed)
        )

        new_priority = (
            row["priority"]
            if priority is None
            else priority
        )

        if new_priority not in {"low", "medium", "high"}:
            raise HTTPException(
                status_code=400,
                detail="Priority must be low, medium, or high",
            )

        conn.execute(
            """
            UPDATE tasks
            SET completed = ?, priority = ?
            WHERE id = ?
            """,
            (new_completed, new_priority, task_id),
        )

        updated = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

    return row_to_task(updated)


def delete_task(task_id):
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,),
        )

        if cur.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )


# --------------------------------------------------
# 7. STUDY PLANNER
# --------------------------------------------------

def make_study_plan(tasks):
    pending = [
        task for task in tasks
        if not task["completed"]
    ]

    if not pending:
        return (
            "Your task list is clear. Add a task "
            "and I can help organize it."
        )

    high = [
        task for task in pending
        if task["priority"] == "high"
    ]

    others = [
        task for task in pending
        if task["priority"] != "high"
    ]

    ordered = high + others

    lines = [
        "Here is a practical plan based on your saved tasks:"
    ]

    for i, task in enumerate(ordered[:5], 1):
        due = (
            f" (due {task['due_date']})"
            if task["due_date"]
            else ""
        )

        lines.append(
            f"{i}. Spend 25 minutes on "
            f"**{task['title']}**{due}, "
            "then take a 5-minute break."
        )

    if len(ordered) > 5:
        lines.append(
            f"You have {len(ordered) - 5} more tasks; "
            "keep them for the next planning block."
        )

    lines.append(
        "Start with the first task now. This is a suggested "
        "plan, so adjust it to your actual deadlines."
    )

    return "\n".join(lines)


# --------------------------------------------------
# 8. CHATBOT AGENT
# --------------------------------------------------

def run_agent(message):
    """
    Handle task-management commands first.
    Use Gemini for other questions.
    """

    msg = message.strip()
    lower = msg.lower()

    # Tool 1: Create a task
    create_patterns = [
        r"^(?:add|create|remember|schedule)\s+"
        r"(?:a\s+)?(?:task|todo|to-do)?\s*(?:to\s+)?(.+)$",
        r"^i need to\s+(.+)$",
        r"^remind me to\s+(.+)$",
    ]

    if any(
        phrase in lower
        for phrase in [
            "add task",
            "create task",
            "add a task",
            "remind me to",
            "i need to",
        ]
    ):
        title = msg

        for pattern in create_patterns:
            match = re.match(
                pattern,
                msg,
                flags=re.IGNORECASE,
            )

            if match:
                title = match.group(1).strip()
                break

        title = re.sub(
            r"\s+(with\s+)?(high|medium|low)\s+priority$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

        priority_match = re.search(
            r"\b(high|medium|low)\s+priority\b",
            lower,
        )

        priority = (
            priority_match.group(1)
            if priority_match
            else "medium"
        )

        title = re.sub(
            r"\b(high|medium|low)\s+priority\b",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip(" .,:-")

        title = re.sub(
            r"^(?:to|about)\s+",
            "",
            title,
            flags=re.IGNORECASE,
        )

        if title.lower() in {
            "task",
            "a task",
            "todo",
            "to-do",
        } or not title:
            return {
                "reply": (
                    "Tell me the task. For example: "
                    "'Add task to revise Python with high priority.'"
                ),
                "tool": "ask_for_task_details",
                "data": None,
            }

        try:
            task = create_task(
                title,
                priority=priority,
            )

        except ValueError as exc:
            return {
                "reply": str(exc),
                "tool": "create_task",
                "data": None,
            }

        return {
            "reply": (
                f"Added **{task['title']}** with "
                f"{task['priority']} priority. "
                "You can see it in your task list."
            ),
            "tool": "create_task",
            "data": task,
        }

    # Tool 2: List pending tasks
    if any(
        keyword in lower
        for keyword in [
            "show my tasks",
            "list tasks",
            "my tasks",
            "what do i need to do",
            "what are my tasks",
        ]
    ):
        tasks = list_tasks()

        pending = [
            task for task in tasks
            if not task["completed"]
        ]

        if not pending:
            reply = (
                "You have no pending tasks. "
                "Add one whenever you're ready."
            )
        else:
            reply = "Your pending tasks:\n" + "\n".join(
                f"- {task['title']} "
                f"[{task['priority']} priority]"
                + (
                    f", due {task['due_date']}"
                    if task["due_date"]
                    else ""
                )
                for task in pending
            )

        return {
            "reply": reply,
            "tool": "list_tasks",
            "data": pending,
        }

    # Tool 3: Mark a task complete
    complete_patterns = [
        r"^(?:please\s+)?mark\s+(.+?)\s+"
        r"(?:as\s+)?(?:complete|completed|done)$",
        r"^(?:please\s+)?(?:complete|finish)\s+"
        r"(?:the\s+)?(?:task\s+)?(.+)$",
        r"^(?:please\s+)?mark\s+(?:the\s+)?task\s+"
        r"(.+?)\s+as\s+(?:complete|completed|done)$",
    ]

    if (
        any(word in lower for word in ["mark ", "complete ", "finish "])
        and any(
            word in lower
            for word in ["complete", "completed", "done", "finish"]
        )
    ):
        task_title = None

        for pattern in complete_patterns:
            match = re.match(
                pattern,
                msg,
                flags=re.IGNORECASE,
            )

            if match:
                task_title = (
                    match.group(1)
                    .strip()
                    .strip("\"' .,:;")
                )
                break

        if task_title:
            tasks = list_tasks()

            candidates = [
                task for task in tasks
                if (
                    not task["completed"]
                    and task_title.lower() in task["title"].lower()
                )
            ]

            if len(candidates) == 1:
                task = update_task(
                    candidates[0]["id"],
                    completed=True,
                )

                return {
                    "reply": (
                        f"Marked **{task['title']}** "
                        "as complete."
                    ),
                    "tool": "update_task",
                    "data": task,
                }

            if len(candidates) > 1:
                options = "\n".join(
                    f"- {task['title']}"
                    for task in candidates
                )

                return {
                    "reply": (
                        "I found multiple matching tasks. "
                        "Please include more of the task title:\n"
                        + options
                    ),
                    "tool": "ask_which_task",
                    "data": candidates,
                }

            return {
                "reply": (
                    f"I couldn't find a pending task matching "
                    f"**{task_title}**. Say 'Show my tasks' "
                    "to see your pending tasks."
                ),
                "tool": "find_task",
                "data": None,
            }

    # Tool 4: Delete a task
    delete_patterns = [
        r"^(?:please\s+)?(?:delete|remove)\s+"
        r"(?:the\s+)?(?:task\s+)?(.+)$",
        r"^(?:please\s+)?delete\s+my\s+task\s+(.+)$",
    ]

    if re.match(
        r"^(?:please\s+)?(?:delete|remove)\b",
        lower,
    ):
        task_title = None

        for pattern in delete_patterns:
            match = re.match(
                pattern,
                msg,
                flags=re.IGNORECASE,
            )

            if match:
                task_title = (
                    match.group(1)
                    .strip()
                    .strip("\"' .,:;")
                )
                break

        if task_title and task_title.lower() not in {
            "task",
            "my task",
            "all tasks",
            "everything",
        }:
            tasks = list_tasks()

            candidates = [
                task for task in tasks
                if task_title.lower() in task["title"].lower()
            ]

            if len(candidates) == 1:
                task = candidates[0]
                delete_task(task["id"])

                return {
                    "reply": (
                        f"Deleted **{task['title']}** "
                        "from your tasks."
                    ),
                    "tool": "delete_task",
                    "data": {
                        "id": task["id"],
                        "title": task["title"],
                    },
                }

            if len(candidates) > 1:
                options = "\n".join(
                    f"- {task['title']}"
                    for task in candidates
                )

                return {
                    "reply": (
                        "I found multiple matching tasks. "
                        "Please specify which one to delete:\n"
                        + options
                    ),
                    "tool": "ask_which_task",
                    "data": candidates,
                }

            return {
                "reply": (
                    f"I couldn't find a task matching "
                    f"**{task_title}**. Say 'Show my tasks' "
                    "to see your tasks."
                ),
                "tool": "find_task",
                "data": None,
            }

        return {
            "reply": (
                "Tell me which task to delete. For example: "
                "'Delete my Practice Python task.'"
            ),
            "tool": "ask_for_task_details",
            "data": None,
        }

    # Tool 5: Study planner
    if any(
        keyword in lower
        for keyword in [
            "plan my day",
            "make a plan",
            "study plan",
            "organize my day",
            "plan my tasks",
        ]
    ):
        tasks = list_tasks()

        return {
            "reply": make_study_plan(tasks),
            "tool": "make_study_plan",
            "data": tasks,
        }

    # Tool 6: Gemini answers general questions
    try:
        reply = ask_gemini(msg)

        return {
            "reply": reply,
            "tool": "gemini",
            "data": None,
        }

    except Exception as exc:
        print(f"Gemini API error: {exc}")

        return {
            "reply": (
                "Sorry, I couldn't get a response from Gemini. "
                "Please check your API key, model name, internet "
                "connection, and the server terminal for details."
            ),
            "tool": "gemini_error",
            "data": None,
        }


# --------------------------------------------------
# 9. API ENDPOINTS
# --------------------------------------------------

@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "LifePilot AI",
        "version": app.version,
    }


@app.get("/api/tasks")
def get_tasks():
    return {"tasks": list_tasks()}


@app.post("/api/tasks")
def post_task(payload: TaskCreate):
    try:
        task = create_task(
            payload.title,
            payload.due_date,
            payload.priority,
        )

        return {"task": task}

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: int, payload: dict):
    return {
        "task": update_task(
            task_id,
            payload.get("completed"),
            payload.get("priority"),
        )
    }


@app.delete("/api/tasks/{task_id}")
def remove_task(task_id: int):
    delete_task(task_id)

    return {
        "deleted": True,
        "id": task_id,
    }


@app.post("/api/chat")
def chat(payload: ChatRequest):
    result = run_agent(payload.message)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO conversations
            (user_message, assistant_message, created_at)
            VALUES (?, ?, ?)
            """,
            (
                payload.message,
                result["reply"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    return result


@app.get("/api/conversations")
def get_conversations():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, user_message, assistant_message, created_at
            FROM conversations
            ORDER BY id DESC
            LIMIT 30
            """
        ).fetchall()

    return {
        "conversations": [
            dict(row) for row in rows
        ]
    }


# --------------------------------------------------
# 10. RUN THE APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
