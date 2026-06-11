# Social Content Lab

Social Content Lab is a local-first pre-production tool for planning AI-assisted social media content. It helps a director collect instructions, organise references, answer clarifying questions, choose a sensible production route, estimate rough cost bands, and export a structured content pack.

## MVP Scope

This first version focuses on planning and pre-production. It creates local project folders, stores source metadata, analyses references with lightweight local heuristics, recommends a workflow route, and writes draft briefs, scripts, prompts, captions, storyboards, asset logs, and project metadata.

## Setup

Run these commands in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The app should open at:

```text
http://localhost:8501
```

## Environment

Copy `.env.example` to `.env` when you are ready to add real API keys. The MVP does not require API keys.

For optional LLM-assisted text planning, set:

```text
OPENROUTER_API_KEY=your_key_here
```

OpenRouter is the router/provider. The selected underlying model performs the writing and planning. Deterministic content generation remains available without an API key.

## Optional OpenRouter Text Planning

The app can refresh a live OpenRouter model catalogue, cache it locally, and use a model advisor to recommend selected models for jobs such as hooks, captions, scripts, storyboard notes, prompt packs, risk review, and full content packs.

The catalogue cache is stored at:

```text
cache/openrouter-model-catalog.json
```

The `cache/` folder is ignored by Git. Refresh the catalogue from the optional LLM-assisted text planning section in the app. Cost estimates and model recommendations depend on the latest catalogue refresh; stale catalogue data may make recommendations unreliable.

When generating an LLM-assisted draft via OpenRouter, the app sends only text planning context: director instructions, source metadata summaries, manually entered selected-frame descriptions, and risk/source-use constraints. It does not send uploaded media files, extracted frames, absolute local paths, secrets, or API keys.

Saved LLM-assisted drafts are written separately as `.llm.md` files and `llm-output.json`, leaving deterministic project files intact. Review all LLM output before publication.

## Optional FFmpeg Support

FFmpeg is optional but recommended for video source planning. When `ffmpeg` and `ffprobe` are available on PATH, Social Content Lab can read basic video metadata and extract local reference frames from uploaded videos.

Check availability in Windows PowerShell:

```powershell
ffmpeg -version
ffprobe -version
```

If FFmpeg is unavailable, the app remains usable. Video uploads are still saved and indexed, but frame extraction is disabled until FFmpeg is installed and available on PATH.

## Manual Frame Descriptions

Extracted video frames can be assigned roles such as hero frame, visual reference, possible background, needs review, do not use, or unselected. The app lets you add manual structured descriptions for selected frames, including visible subject, setting, mood, visual style, on-screen text, rights notes, risk notes, recommended use, and avoid-use guidance.

Those manual descriptions feed into the deterministic content pack, shot list, image prompt, video prompt, risk notes, and selected-frame preview. No AI vision analysis is implemented yet; the frame interpretation comes only from local metadata and user-entered descriptions.

## What Is Not Implemented Yet

The app does not perform paid image/video/media generation, URL scraping, AI vision analysis, full video parsing, audio transcription, OCR, authentication, database storage, deployment, or platform publishing. Optional OpenRouter text planning is the only live model call path.

## Future Roadmap

- Broader OpenRouter planning workflows and saved prompt presets
- fal.ai or Replicate integration
- Audio transcription
- OCR for visible text
- Cost tracking
- Asset scoring
- Export to CapCut/Canva workflow
- Publishing calendar
- Platform performance tracking
