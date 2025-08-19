import os
import uuid
import logging
import tempfile
from pathlib import Path

import ffmpeg
from flask import Flask, request, jsonify, render_template, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

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
        probe = ffmpeg.probe(file_path)
        video_streams = [stream for stream in probe['streams'] if stream['codec_type'] == 'video']
        if not video_streams:
            return False, "No video stream found in file"
        
        # Check if it's a webm container
        format_name = probe['format']['format_name']
        if 'webm' not in format_name.lower() and 'matroska' not in format_name.lower():
            return False, "File is not a valid WebM format"
        
        return True, "Valid WebM file"
    except Exception as e:
        logger.error(f"Error validating file: {str(e)}")
        return False, f"Error validating file: {str(e)}"

def convert_webm_to_mp4(input_path, output_path):
    """Convert webm file to mp4 using ffmpeg."""
    try:
        logger.info(f"Starting conversion: {input_path} -> {output_path}")
        
        # Use ffmpeg-python to convert webm to mp4
        stream = ffmpeg.input(input_path)
        stream = ffmpeg.output(stream, output_path, 
                             vcodec='libx264',  # H.264 video codec
                             acodec='aac',      # AAC audio codec
                             crf=23,            # Constant Rate Factor for quality
                             preset='medium')   # Encoding speed preset
        
        # Run the conversion
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        
        logger.info(f"Conversion completed successfully: {output_path}")
        return True, "Conversion successful"
        
    except ffmpeg.Error as e:
        error_msg = f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}"
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
        try:
            ffmpeg.probe('pipe:', f_format='lavfi', sources='testsrc=duration=1:size=32x32:rate=1')
            ffmpeg_available = True
        except Exception:
            ffmpeg_available = False
    except:
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
