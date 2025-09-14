# WebM to MP4 Converter with Gemini TTS

## Overview

A Flask-based web application that provides WebM to MP4 video conversion functionality. The application allows users to upload WebM video files through a web interface and converts them to MP4 format using FFmpeg. The system also features CSV to video conversion with Gemini Text-to-Speech narration.

## Features

- Convert WebM videos to MP4 format
- Create videos from CSV files with image URLs
- Add voice narration using Gemini TTS
- Bulk conversion support with queue system
- Responsive web interface with real-time status updates

## Setup Instructions

### Prerequisites

- Python 3.11+
- FFmpeg installed and available in system PATH
- Google Cloud account with Gemini API access

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd VideoConvert
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Environment Variables

The application requires the following environment variables to be set:

- `SESSION_SECRET`: Secret key for Flask sessions
- `GEMINI_API_KEY`: Google Cloud API key for Gemini TTS

You can set these in your environment:
```bash
export SESSION_SECRET="your-secret-key"
export GEMINI_API_KEY="your-gemini-api-key"
```

### Running the Application

```bash
python main.py
```

The application will be available at http://localhost:5000

## Usage

1. Access the web interface at http://localhost:5000
2. Choose between:
   - WebM to MP4 conversion: Upload WebM files for conversion
   - CSV to Video: Upload a CSV file with image URLs to create a slideshow video with voice narration
3. Download the converted files when processing is complete

## API Endpoints

- `POST /api/convert` - Convert WebM to MP4
- `POST /api/bulk-convert` - Queue multiple WebM files for conversion
- `GET /api/queue-status` - Get conversion queue status
- `POST /api/csv-to-video` - Create videos from CSV (FFmpeg renderer + Gemini TTS)
- `POST /api/render-video` - Render vertical video from images + audio + scenes (manifest)
- `GET /api/download/<file_id>` - Download converted MP4 file
- `GET /api/download-render/<file_id>` - Download rendered MP4 from manifest
- `GET /api/download-product-video-ffmpeg/<file_id>/<filename>` - Download generated CSV product video
- `GET /api/status` - Check API status and FFmpeg availability

For full request/response details and curl examples, see `docs/API.md`.

## Deployment

The application is configured for deployment on Replit with Nixpacks. The `nixpacks.toml` file contains the deployment configuration.

## Dependencies

See `requirements.txt` for a complete list of Python dependencies.
