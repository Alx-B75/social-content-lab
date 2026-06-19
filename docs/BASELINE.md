# Project Baseline

## Project Purpose

Social Content Lab is a standalone, local-first Streamlit MVP for planning AI-assisted social media content. It helps a director capture instructions, collect reference sources, answer clarifying questions, choose a production route, estimate rough cost bands, and export a structured pre-production content pack.

## Current Stack

- Python 3.12
- Streamlit
- Pydantic
- python-dotenv
- Pillow for basic image metadata
- httpx for optional OpenRouter API requests
- Optional FFmpeg and ffprobe for local video metadata and frame extraction
- Optional OpenRouter text planning through a selected model routed by OpenRouter
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
cache/                  Ignored local API/catalogue cache files
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
- Extracts local video reference frames when FFmpeg and ffprobe are available on PATH.
- Lets selected video frames be marked as hero frames, visual references, possible backgrounds, needs review, do not use, or unselected.
- Lets selected video frames be manually described with subject, setting, mood, visual style, on-screen text, rights notes, risk notes, recommended use, and avoid-use guidance.
- Prefills missing frame fields locally from frame position and project/source context without claiming visual inspection.
- Optionally analyses explicitly selected extracted frames through a concrete OpenRouter vision model after per-action consent and cost warning.
- Stores frame prefill source, model, timestamp, confidence, field provenance, and human-review status in `frame-index.json`.
- Feeds selected frame roles and manual descriptions into deterministic shot lists, prompt packs, risk notes, and content pack previews.
- Stores URL and manual-description source metadata without scraping.
- Summarises pasted text with a local preview, word count, and likely use-case heuristic.
- Presents grouped clarifying questions in the requested planning categories.
- Recommends a workflow route, provider type, rough cost band, rationale, warnings, and next step.
- Generates and saves a draft content pack with brief, script outline, shot list, prompts, captions, checklist, risk notes, and next actions.
- Optionally refreshes and caches the OpenRouter model catalogue locally.
- Optionally advises selected models for text-planning jobs using catalogue capability and pricing metadata.
- Optionally generates LLM-assisted text drafts via a selected model routed through OpenRouter.
- Saves LLM-assisted drafts separately from deterministic files as `.llm.md`, `llm-output.json`, and raw output where needed.
- Compares deterministic and LLM-assisted pack sections side by side.
- Persists section selections, custom text, reviewer notes, status, and export history in `review-state.json`.
- Exports attributed final section files and a combined `final-pack.md` without modifying source packs.

## Intentionally Not Implemented Yet

- Paid image/video/media generation
- fal.ai or Replicate integration
- URL scraping
- Automatic or unconsented vision analysis
- Sending original videos or uploaded source media to vision models
- Full video parsing
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

## Optional OpenRouter Text Planning

OpenRouter is the router/provider layer. The selected underlying model performs the writing and planning.

Configuration is read from `.env` or the environment:

```text
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_APP_NAME=Social Content Lab
OPENROUTER_DEFAULT_MODEL=
OPENROUTER_CATALOG_CACHE_PATH=cache/openrouter-model-catalog.json
```

The model catalogue cache is local and ignored by Git. Catalogue data is considered fresh for 24 hours, stale from 24 hours to 7 days, and very stale after 7 days. Cost estimates and model recommendations depend on catalogue freshness.

Text-planning calls do not send uploaded media, extracted frames, absolute local paths, API keys, or secrets. Optional vision prefill sends only the extracted frame images explicitly selected by the user plus safe project text after consent. It never sends original videos, uploaded source files, absolute local paths, or secrets. All model output must be reviewed before publication.

## Review And Final Pack

The review panel supports deterministic, LLM-assisted, and custom choices for brief, script, storyboard, prompts, and captions. Review status can be `draft`, `needs_review`, `approved`, or `published`. Final exports retain section-source attribution and remain local under ignored project folders in `content/`.

Final export creates `final-brief.md`, `final-script.md`, `final-storyboard.md`, `final-prompts.md`, `final-captions.md`, and `final-pack.md`. Suspicious secret-like text, absolute paths, and local media/cache paths block export until reviewed.

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

## Optional FFmpeg Checks

FFmpeg is optional. To enable local video metadata and keyframe extraction, install FFmpeg and confirm these commands work in Windows PowerShell:

```powershell
ffmpeg -version
ffprobe -version
```

If FFmpeg is unavailable, the app still runs and stores video sources, but frame extraction controls show a clear warning.

## Current Git State

- Branch: `main`
- Baseline initial commit: `3abda8e Initial standalone Streamlit social content lab scaffold`
- Remote configured as `origin`: `https://github.com/Alx-B75/social-content-lab.git`
- `main` has been pushed to `origin`.

## Important Constraints

- This is a standalone project.
- It must not depend on Places in Time code.
- Paid OpenRouter calls are optional, explicit, and disabled until the user acknowledges cost and any required media consent.
- API keys must stay in `.env` or Streamlit secrets and must never be committed.
- The OpenRouter API key must never be displayed, logged, cached, or written into project files.
- OpenRouter should be described as the router/provider; the selected model should be described as the text generator.
- Text-planning calls must not send uploaded media or extracted frames to OpenRouter.
- Vision prefill may send only explicitly selected extracted frame images after user consent; original videos and uploaded source media must never be sent.
- Generated content and uploaded media under `content/` should remain ignored except `content/.gitkeep`.
- Local catalogue/API cache files under `cache/` should remain ignored.
- Code should remain simple and local-first.
- Local and AI frame prefills must preserve existing values by default and remain visibly marked for human review.
- Python functions, classes, and modules should keep full docstrings.
- No inline comments unless there is a strong reason.

## Next Recommended Development Steps

1. Add lightweight tests for project creation, source analysis, routing, and content pack writing.
2. Add a project loader so existing local projects can be reopened from `content/`.
3. Add safer file-size checks and extension validation for uploads.
4. Improve source summaries for pasted text and manual descriptions while staying local-only.
5. Add a simple asset scoring workflow in `asset-log.csv`.
6. Add export-oriented views for CapCut, Canva, Premiere, and DaVinci Resolve handoff.
7. Add optional OCR or transcription as local-first tools if needed.
8. Expand OpenRouter planning workflows behind explicit user-triggered actions and rough cost warnings.
