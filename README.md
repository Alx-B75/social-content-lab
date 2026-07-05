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

## Review And Final Pack

The app can compare deterministic and LLM-assisted pack sections side by side. For each brief, script, storyboard, prompt pack, and caption section, the reviewer can select the deterministic version, the LLM-assisted version, or custom text.

Selections, reviewer notes, export history, and status (`draft`, `needs_review`, `approved`, or `published`) are saved locally in `review-state.json`. Export creates attributed final files and a combined `final-pack.md` without changing the original deterministic or LLM files.

Review state and final outputs remain under the project's ignored `content/` folder. Export is blocked when selected text contains secret-like values, absolute local paths, or local media/cache paths.

## Generate Video MVP

The app includes a controlled `Generate Video` section downstream of the content/review workflow. It can discover prompt sources in this order: `final-prompts.md`, `prompts.llm.md`, `prompts.md`, then a custom prompt entered in the UI.

The workflow analyses the reviewed prompt, selected extracted frame references, duration, aspect ratio, risk notes, and user preference (`cheapest sensible`, `balanced`, or `quality-first`). A video model/provider advisor recommends a generation route and provider/model instead of using a static provider dropdown.

The mock local provider remains available for safe testing:

- It can exercise text-to-video and image-to-video workflow paths without paid calls.
- It attempts to create a local placeholder MP4 with FFmpeg when available.
- If MP4 creation is not practical, it saves metadata only with `mock_completed_no_video`.
- It does not create real provider-generated video.

OpenRouter is the intended routing layer for real video generation where OpenRouter supports the needed modality. When `OPENROUTER_API_KEY` is configured, the app can refresh a dedicated OpenRouter video model catalogue from `GET /api/v1/videos/models`, cache it locally, recommend OpenRouter-routed video models, submit a real job through `POST /api/v1/videos`, poll status, download the completed MP4, and save local metadata.

Real OpenRouter video generation can spend credits. The UI includes:

- A `Low-risk OpenRouter video smoke test` preset for a five-second text-to-video validation clip with no people, faces, logos, readable text, or copyrighted characters.
- A request preview showing provider/model, mode, prompt source, duration, aspect/resolution, whether a selected reference frame will be sent, and estimated cost or cost unknown.
- A default max test spend of `$1.00`.
- Blocking when known estimated cost exceeds the max spend.
- An extra acknowledgement when cost is unknown.
- Explicit confirmation before submitting a real OpenRouter video job.

Image-to-video may send only the selected extracted frame image after explicit consent and only when the selected OpenRouter model advertises frame-image support. Full uploaded videos, absolute local paths, API keys, and secrets are never sent in provider payload previews or normal metadata.

Generated video outputs and metadata are saved under:

```text
content/<project-id>/outputs/video/
```

Generated videos, uploaded media, project outputs, caches, logs, and local secrets remain ignored by Git. Every generated video asset is logged in `asset-log.csv` as requiring human review before publication.

## Optional FFmpeg Support

FFmpeg is optional but recommended for video source planning. When `ffmpeg` and `ffprobe` are available on PATH, Social Content Lab can read basic video metadata and extract local reference frames from uploaded videos.

Check availability in Windows PowerShell:

```powershell
ffmpeg -version
ffprobe -version
```

If FFmpeg is unavailable, the app remains usable. Video uploads are still saved and indexed, but frame extraction is disabled until FFmpeg is installed and available on PATH.

## Frame Interpretation

Extracted video frames can be assigned roles such as hero frame, visual reference, possible background, needs review, do not use, or unselected. The app lets you add manual structured descriptions for selected frames, including visible subject, setting, mood, visual style, on-screen text, rights notes, risk notes, recommended use, and avoid-use guidance.

The local deterministic prefill can populate missing fields from frame position, source purpose, and project context. It does not inspect pixels or make visual claims, preserves existing values by default, and marks suggestions for human review.

Optional AI frame prefill is available through a concrete vision-capable model routed by OpenRouter. It is disabled until the user selects specific extracted frames and explicitly consents to the paid call. Only those selected frame images and safe project text are sent. Original videos, uploaded source files, API keys, and absolute local paths are never included. AI-prefilled fields retain model/provenance metadata and require human review before publication.

Manual, local, and reviewed AI descriptions feed into the deterministic content pack, shot list, image prompt, video prompt, risk notes, and selected-frame preview.

## What Is Not Implemented Yet

The app does not perform direct Runway/Pika/Kling/etc. integration, URL scraping, full video parsing, audio transcription, OCR, authentication, database storage, deployment, or platform publishing. OpenRouter text planning, explicitly consented selected-frame vision prefill, and explicitly consented OpenRouter-routed video generation are the only live model call paths.

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
