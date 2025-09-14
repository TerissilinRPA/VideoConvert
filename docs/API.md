# VideoConvert API Reference

This document describes the HTTP API exposed by the Flask app for converting videos, generating videos from CSV, and rendering videos from client-provided assets.

- Base URL: http://localhost:5000
- CORS: Enabled for all origins (`*`)
- Authentication: None (recommend placing behind your own auth/proxy in production)
- Content types: `application/json` for JSON APIs; `multipart/form-data` for file uploads
- Requirement: FFmpeg must be installed and available on PATH

## Status
- GET `/api/status`
  - Returns service health and ffmpeg availability
  - 200 response body:
    ```json
    {
      "status": "online",
      "ffmpeg_available": true,
      "max_file_size_mb": 500,
      "supported_formats": ["webm", "csv"],
      "queue_size": 0,
      "active_jobs": 0
    }
    ```

## WebM → MP4 (single)
- POST `/api/convert`
  - Content-Type: `multipart/form-data`
  - Form fields:
    - `file` (required): WebM video file
  - 200 response body:
    ```json
    {
      "success": true,
      "message": "Conversion completed successfully",
      "file_id": "<uuid>",
      "original_filename": "input.webm",
      "download_url": "/api/download/<uuid>"
    }
    ```
  - Errors: 400 (validation), 413 (too large), 500 (server)
- GET `/api/download/<file_id>`
  - Sends the converted MP4 as attachment

## WebM → MP4 (bulk queue)
- POST `/api/bulk-convert`
  - Content-Type: `multipart/form-data`
  - Form fields:
    - `files` (required, multiple): WebM files
  - 200 response body includes queued and rejected files with IDs
- GET `/api/queue-status`
  - Returns current queue items and their status

## CSV → Video (FFmpeg renderer)
- POST `/api/csv-to-video`
  - Content-Type: `multipart/form-data`
  - Form fields:
    - `file` (required): CSV containing product rows with image URLs (see `example.csv`)
    - `duration_per_scene` (optional, float): seconds per scene (default 5.0)
    - `voice_name` (optional): Gemini TTS voice (default `Zephyr`)
    - `gemini_api_key` (optional): API key for TTS; if omitted, uses `GEMINI_API_KEY` env var
    - `show_subtitles` (optional, bool): default `true`
    - `font_style` (optional): default `Sarabun`
    - `font_size` (optional, int): default `60`
    - `watermark` (optional): text watermark
    - `outro_text` (optional): extra narration appended at the end
  - 200 response body:
    ```json
    {
      "success": true,
      "message": "Created <n> product videos",
      "file_id": "<uuid>",
      "original_filename": "input.csv",
      "product_videos": [
        {
          "product_id": 0,
          "product_title": "...",
          "download_url": "/api/download-product-video-ffmpeg/<file_id>/<safe_title>.mp4",
          "message": "Video created successfully"
        }
      ]
    }
    ```
- GET `/api/download-product-video-ffmpeg/<file_id>/<filename>`
  - Sends the generated MP4 for a specific product

## Render From Assets (client manifest)
- POST `/api/render-video`
  - Content-Type: `application/json`
  - Request body:
    ```json
    {
      "topic": "Optional title",
      "scriptData": {
        "scenes": [
          { "text": "Line 1", "startTime": 0, "endTime": 3 },
          { "text": "Line 2", "startTime": 3, "endTime": 6 }
        ]
      },
      "images": [
        "data:image/png;base64,<...>",
        "data:image/png;base64,<...>"
      ],
      "audioSrc": "data:audio/mpeg;base64,<...>",
      "options": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "showSubtitles": true,
        "fontFamily": "DejaVuSans",
        "fontSize": 40,
        "watermark": "@yourhandle"
      }
    }
    ```
  - Notes:
    - If `images.length === scenes.length + 1`, the first image is treated as a thumbnail and skipped.
    - If `startTime/endTime` are omitted, scene durations are evenly distributed across the audio duration (fallback 3s each if audio duration not detected).
    - Subtitles are burned-in from `scenes[i].text` when `showSubtitles` is true.
  - 200 response body:
    ```json
    {
      "success": true,
      "file_id": "<uuid>",
      "download_url": "/api/download-render/<uuid>"
    }
    ```
- GET `/api/download-render/<file_id>`
  - Sends the rendered MP4

## Curl Examples

### Single WebM → MP4
```bash
curl -F "file=@/path/to/video.webm" \
  http://localhost:5000/api/convert
```

### CSV → Video with options
```bash
curl -F "file=@example.csv" \
  -F "duration_per_scene=4.0" \
  -F "voice_name=Zephyr" \
  -F "show_subtitles=true" \
  -F "font_style=Sarabun" \
  -F "font_size=60" \
  -F "watermark=@yourchannel" \
  http://localhost:5000/api/csv-to-video
```

### Render From Assets (JSON)
```bash
curl -X POST http://localhost:5000/api/render-video \
  -H 'Content-Type: application/json' \
  -d '{
    "topic": "My Short",
    "scriptData": {"scenes":[{"text":"Hello","startTime":0,"endTime":2},{"text":"World","startTime":2,"endTime":4}]},
    "images": ["data:image/png;base64,iVBORw0KGgoAAA..."],
    "audioSrc": "data:audio/mpeg;base64,/+MYxAAAA...",
    "options": {"width":1080,"height":1920,"fps":30,"showSubtitles":true}
  }'
```

## Errors
- 400: Validation errors or missing parameters
- 413: Upload too large (limit 500 MB)
- 500: Server errors (see logs)

## Environment Variables
- `SESSION_SECRET`: Flask session secret
- `GEMINI_API_KEY`: Used by CSV/FFmpeg TTS helpers when not provided in requests

## Notes
- This API performs video processing with FFmpeg; ensure your deployment environment provides sufficient CPU and disk.
- In production, front the service with authentication and storage lifecycle for generated files.

