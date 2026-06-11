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

The app does not perform paid media generation, live model calls, URL scraping, AI vision analysis, full video parsing, audio transcription, OCR, authentication, database storage, deployment, or platform publishing.

## Future Roadmap

- Real OpenRouter integration
- fal.ai or Replicate integration
- Audio transcription
- OCR for visible text
- Cost tracking
- Asset scoring
- Export to CapCut/Canva workflow
- Publishing calendar
- Platform performance tracking
