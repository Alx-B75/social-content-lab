# Project Baseline

## Project Purpose

Social Content Lab is a standalone, local-first Streamlit MVP for planning AI-assisted social media content. It helps a director capture instructions, collect reference sources, answer clarifying questions, choose a production route, estimate rough cost bands, and export a structured pre-production content pack.

## Current Stack

- Python 3.12
- Streamlit
- Pydantic
- python-dotenv
- Pillow for basic image metadata
- Local filesystem storage
- No database
- No authentication
- No deployment setup

## Folder Map

```text
app.py                  Streamlit application entrypoint
src/config.py           Environment and path configuration
src/models/             Pydantic project, source, and planning models
src/services/           Project, source analysis, routing, costing, and pack-building services
src/ui/                 Streamlit UI panels for the app flow
templates/              Starter markdown and CSV templates copied into projects
content/.gitkeep        Placeholder for ignored local generated projects and media
docs/                   Project documentation
README.md               Setup, purpose, MVP scope, and roadmap
requirements.txt        Python dependencies
.env.example            Future API key names without real secrets
.gitignore              Local, generated, secret, cache, and media ignore rules
```

## Current MVP Capabilities

- Creates timestamped, slugified local project folders under `content/`.
- Creates starter project files: `brief.md`, `script.md`, `storyboard.md`, `prompts.md`, `captions.md`, `asset-log.csv`, `project.json`, `sources/`, and `sources/source-index.json`.
- Accepts image uploads, video uploads, URLs, pasted text, and manual descriptions.
- Saves uploaded files and pasted text under each project's `sources/` folder.
- Uses Pillow for basic image metadata: filename, MIME type, file size, width, height, and aspect ratio.
- Records video metadata and future extraction needs without parsing video content.
- Stores URL and manual-description source metadata without scraping.
- Summarises pasted text with a local preview, word count, and likely use-case heuristic.
- Presents grouped clarifying questions in the requested planning categories.
- Recommends a workflow route, provider type, rough cost band, rationale, warnings, and next step.
- Generates and saves a draft content pack with brief, script outline, shot list, prompts, captions, checklist, risk notes, and next actions.

## Intentionally Not Implemented Yet

- Paid media generation
- Live model calls
- Real OpenRouter integration
- fal.ai or Replicate integration
- URL scraping
- Vision model analysis
- Full video parsing
- Video keyframe extraction
- Audio transcription
- OCR for visible text
- Cost ledger or actual price tracking
- Asset scoring
- Export automation for CapCut or Canva
- Publishing calendar
- Platform performance tracking
- Authentication
- Database storage
- Deployment setup

## How To Run Locally

Run these commands in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Expected local URL:

```text
http://localhost:8501
```

## Current Git State

- Branch: `main`
- Baseline initial commit: `3abda8e Initial standalone Streamlit social content lab scaffold`
- Remote configured as `origin`: `https://github.com/Alx-B75/social-content-lab.git`
- No push has been performed by Codex.

## Important Constraints

- This is a standalone project.
- It must not depend on Places in Time code.
- No paid API calls are implemented yet.
- API keys must stay in `.env` or Streamlit secrets and must never be committed.
- Generated content and uploaded media under `content/` should remain ignored except `content/.gitkeep`.
- Code should remain simple and local-first.
- Python functions, classes, and modules should keep full docstrings.
- No inline comments unless there is a strong reason.

## Next Recommended Development Steps

1. Add lightweight tests for project creation, source analysis, routing, and content pack writing.
2. Add a project loader so existing local projects can be reopened from `content/`.
3. Add safer file-size checks and extension validation for uploads.
4. Improve source summaries for pasted text and manual descriptions while staying local-only.
5. Add optional keyframe extraction behind a clearly local tool path.
6. Add a simple asset scoring workflow in `asset-log.csv`.
7. Add export-oriented views for CapCut, Canva, Premiere, and DaVinci Resolve handoff.
8. Prepare future OpenRouter and media-provider integrations behind explicit user-triggered actions and rough cost warnings.
