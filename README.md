# LifePilot AI

A FastAPI + HTML/CSS/JavaScript student productivity assistant prototype for the Alexa+ simulated-experience hackathon track.

## Features
- Chat UI with a transparent intent router and real tools
- Add/list/complete/delete tasks
- Priority-based study planning
- SQLite persistence for tasks and conversation history
- FastAPI health endpoint and interactive API docs

## Run on Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000 and API docs at http://127.0.0.1:8000/docs.

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again. Alternatively use Command Prompt:
```bat
.venv\Scripts\activate.bat
```

## Try these prompts
- `Add task to finish my FastAPI project with high priority`
- `Show my tasks`
- `Make a study plan`

## Architecture
Browser UI -> FastAPI routes -> intent router/agent tools -> SQLite database.

This first version uses deterministic intent routing and does not call an external LLM. Before a hackathon submission, document this honestly and consider adding a real model/tool-calling integration if time and credentials permit.
