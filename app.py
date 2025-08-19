import os
import uuid
import logging
import tempfile
from pathlib import Path

import subprocess
import json
from flask import Flask, request, jsonify, render_template, send_file, flash, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")


# Add CORS headers to all responses
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size
UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'webm'}

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_webm_file(file_path):
    """Validate that the uploaded file is actually a webm video file."""
    try:
        # Use ffprobe to get file information
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return False, "Invalid video file format"
        
        probe_data = json.loads(result.stdout)
        
        # Check for video streams
        video_streams = [stream for stream in probe_data.get('streams', []) if stream.get('codec_type') == 'video']
        if not video_streams:
            return False, "No video stream found in file"
        
        # Check if it's a webm container
        format_name = probe_data.get('format', {}).get('format_name', '')
        if 'webm' not in format_name.lower() and 'matroska' not in format_name.lower():
            return False, "File is not a valid WebM format"
        
        return True, "Valid WebM file"
    except subprocess.TimeoutExpired:
        logger.error("File validation timed out")
        return False, "File validation timed out"
    except Exception as e:
        logger.error(f"Error validating file: {str(e)}")
        return False, f"Error validating file: {str(e)}"

def convert_webm_to_mp4(input_path, output_path):
    """Convert webm file to mp4 using ffmpeg."""
    try:
        logger.info(f"Starting conversion: {input_path} -> {output_path}")
        
        # Use ffmpeg command directly
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',  # H.264 video codec
            '-c:a', 'aac',      # AAC audio codec
            '-crf', '23',       # Constant Rate Factor for quality
            '-preset', 'medium', # Encoding speed preset
            '-y',               # Overwrite output file
            output_path
        ]
        
        # Run the conversion
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # 10 minute timeout
        
        if result.returncode != 0:
            error_msg = f"FFmpeg conversion failed: {result.stderr}"
            logger.error(error_msg)
            return False, error_msg
        
        logger.info(f"Conversion completed successfully: {output_path}")
        return True, "Conversion successful"
        
    except subprocess.TimeoutExpired:
        error_msg = "Conversion timed out - file may be too large"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Conversion error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def cleanup_file(file_path):
    """Safely remove a file."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up file: {file_path}")
    except Exception as e:
        logger.error(f"Error cleaning up file {file_path}: {str(e)}")

@app.route('/')
def index():
    """Render the main page with upload interface."""
    return render_template('index.html')

@app.route('/api/convert', methods=['POST'])
def convert_video():
    """API endpoint for converting webm to mp4."""
    try:
        # Check if file is present in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Only WebM files are allowed'}), 400
        
        # Generate unique filenames
        file_id = str(uuid.uuid4())
        original_filename = secure_filename(file.filename or 'unknown.webm')
        input_filename = f"{file_id}_input.webm"
        output_filename = f"{file_id}_output.mp4"
        
        input_path = os.path.join(UPLOAD_FOLDER, input_filename)
        output_path = os.path.join(UPLOAD_FOLDER, output_filename)
        
        # Save uploaded file
        file.save(input_path)
        logger.info(f"File uploaded: {input_path}")
        
        # Validate the uploaded file
        is_valid, validation_message = validate_webm_file(input_path)
        if not is_valid:
            cleanup_file(input_path)
            return jsonify({'error': validation_message}), 400
        
        # Convert the file
        success, message = convert_webm_to_mp4(input_path, output_path)
        
        if not success:
            cleanup_file(input_path)
            cleanup_file(output_path)
            return jsonify({'error': message}), 500
        
        # Clean up input file
        cleanup_file(input_path)
        
        # Check if output file was created
        if not os.path.exists(output_path):
            return jsonify({'error': 'Conversion failed - output file not created'}), 500
        
        return jsonify({
            'success': True,
            'message': 'Conversion completed successfully',
            'file_id': file_id,
            'original_filename': original_filename,
            'download_url': f"/api/download/{file_id}"
        })
        
    except RequestEntityTooLarge:
        return jsonify({'error': 'File too large. Maximum size is 500MB'}), 413
    except Exception as e:
        logger.error(f"Conversion error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/download/<file_id>')
def download_file(file_id):
    """Download converted mp4 file."""
    try:
        # Validate file_id format (should be a valid UUID)
        uuid.UUID(file_id)
        
        output_filename = f"{file_id}_output.mp4"
        output_path = os.path.join(UPLOAD_FOLDER, output_filename)
        
        if not os.path.exists(output_path):
            return jsonify({'error': 'File not found or has been cleaned up'}), 404
        
        # Send file and schedule cleanup after download
        def remove_file(response):
            cleanup_file(output_path)
            return response
        
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"converted_{file_id}.mp4",
            mimetype='video/mp4'
        )
        
    except ValueError:
        return jsonify({'error': 'Invalid file ID'}), 400
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/status')
def api_status():
    """Check API status and ffmpeg availability."""
    try:
        # Test ffmpeg availability
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        ffmpeg_available = result.returncode == 0
    except Exception:
        ffmpeg_available = False
    
    return jsonify({
        'status': 'online',
        'ffmpeg_available': ffmpeg_available,
        'max_file_size_mb': app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024),
        'supported_formats': ['webm']
    })

@app.errorhandler(413)
def too_large(e):
    """Handle file too large error."""
    return jsonify({'error': 'File too large. Maximum size is 500MB'}), 413

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return render_template('index.html'), 404

@app.errorhandler(500)
def server_error(e):
    """Handle server errors."""
    logger.error(f"Server error: {str(e)}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    flash('An internal error occurred. Please try again.', 'error')
    return render_template('index.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
