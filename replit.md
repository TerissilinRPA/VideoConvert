# WebM to MP4 Converter

## Overview

A Flask-based web application that provides WebM to MP4 video conversion functionality. The application allows users to upload WebM video files through a web interface and converts them to MP4 format using FFmpeg. The system features a responsive Bootstrap-based frontend with real-time status checking, file validation, and download capabilities.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Web Framework
- **Flask**: Chosen as the lightweight web framework for handling HTTP requests, file uploads, and serving the web interface
- **Single-file architecture**: Main application logic contained in `app.py` with a simple `main.py` entry point for easy deployment

### Frontend Architecture
- **Bootstrap-based UI**: Uses Bootstrap 5 with a dark theme for modern, responsive design
- **Vanilla JavaScript**: Custom JavaScript (`app.js`) handles client-side interactions, AJAX requests, and UI updates
- **Template-based rendering**: Flask templates with Jinja2 for server-side HTML generation

### File Processing Pipeline
- **Temporary file storage**: Uses system temporary directory for uploaded files to avoid persistence issues
- **File validation**: Multi-layer validation including file extension checking and FFmpeg-based content validation
- **FFmpeg integration**: Core video conversion engine using the `ffmpeg-python` wrapper library
- **Secure file handling**: Implements filename sanitization and file size limits (500MB maximum)

### API Design
- **RESTful endpoints**: Clean separation between file upload, conversion, and status checking endpoints
- **Status monitoring**: Dedicated health check endpoint to verify FFmpeg availability
- **Error handling**: Comprehensive error responses with appropriate HTTP status codes

### Security Measures
- **File type restrictions**: Only allows WebM files based on extension and content validation
- **Filename sanitization**: Uses Werkzeug's secure_filename utility to prevent path traversal attacks
- **File size limits**: Configurable upload size limits to prevent resource exhaustion
- **Content validation**: Uses FFmpeg to verify actual file format beyond extension checking

## External Dependencies

### Core Dependencies
- **FFmpeg**: System-level video processing engine for format conversion
- **ffmpeg-python**: Python wrapper for FFmpeg command execution
- **Flask**: Web framework for HTTP handling and templating
- **Werkzeug**: WSGI utilities for secure file handling

### Frontend Libraries
- **Bootstrap 5**: CSS framework with dark theme variant from Replit CDN
- **Font Awesome 6**: Icon library for UI elements
- **Axios**: HTTP client library for API communication (referenced in JavaScript)

### System Requirements
- **Python 3.x**: Runtime environment
- **FFmpeg binary**: Must be installed and available in system PATH
- **Temporary file system**: Requires write access to system temp directory