import os
import uuid
import logging
import tempfile
import threading
import queue
import time
import csv
import requests
from pathlib import Path

import subprocess
import json
from flask import Flask, request, jsonify, render_template, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

# Import our new FFmpeg-based video creation module
import csv_to_video_ffmpeg

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Queue system for bulk conversion
conversion_queue = queue.Queue()
queue_status = {}  # Track status of each file in queue
queue_lock = threading.Lock()

# Clear queue status on startup
with queue_lock:
    queue_status.clear()

# Configuration for concurrent processing
MAX_CONCURRENT_CONVERSIONS = 2
active_conversions = 0
active_conversions_lock = threading.Lock()

def update_queue_status(file_id, status, message=None, download_url=None, filename=None):
    """Update the status of a file in the queue."""
    with queue_lock:
        if file_id not in queue_status:
            queue_status[file_id] = {
                'status': status,
                'message': message or '',
                'download_url': download_url,
                'filename': filename,
                'timestamp': time.time()
            }
        else:
            queue_status[file_id]['status'] = status
            if message:
                queue_status[file_id]['message'] = message
            if download_url:
                queue_status[file_id]['download_url'] = download_url
            if filename:
                queue_status[file_id]['filename'] = filename
            queue_status[file_id]['timestamp'] = time.time()

def process_conversion_queue():
    """Worker function to process conversion queue."""
    global active_conversions
    
    while True:
        try:
            # Get item from queue (blocking)
            item = conversion_queue.get()
            if item is None:  # Sentinel to stop worker
                break
                
            file_id = item['file_id']
            input_path = item['input_path']
            output_path = item['output_path']
            original_filename = item['original_filename']
            
            # Update status to processing
            update_queue_status(file_id, 'processing', 'Conversion in progress...')
            
            # Check if we can start a new conversion
            with active_conversions_lock:
                if active_conversions >= MAX_CONCURRENT_CONVERSIONS:
                    # Put back in queue and wait
                    conversion_queue.put(item)
                    time.sleep(1)
                    continue
                active_conversions += 1
            
            try:
                # Convert the file
                success, message = convert_webm_to_mp4(input_path, output_path)
                
                if success:
                    update_queue_status(
                        file_id, 
                        'completed', 
                        'Conversion completed successfully',
                        f"/api/download/{file_id}",
                        original_filename
                    )
                else:
                    update_queue_status(file_id, 'error', message)
                    
            except Exception as e:
                logger.error(f"Error processing file {file_id}: {str(e)}")
                update_queue_status(file_id, 'error', f"Processing error: {str(e)}")
            finally:
                # Clean up input file
                cleanup_file(input_path)
                
                # Decrement active conversions
                with active_conversions_lock:
                    active_conversions -= 1
                    
                # Mark task as done
                conversion_queue.task_done()
                
        except Exception as e:
            logger.error(f"Queue processing error: {str(e)}")
            time.sleep(1)

# Start queue processing worker thread
queue_worker = threading.Thread(target=process_conversion_queue, daemon=True)
queue_worker.start()


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
ALLOWED_EXTENSIONS = {'webm', 'csv'}

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

def _decode_data_url_to_file(data_url: str, out_path: str) -> bool:
    """Decode a data: URL (base64) to a file on disk."""
    try:
        import re, base64
        m = re.match(r"^data:([^;]+);base64,(.*)$", data_url)
        if not m:
            return False
        b64 = m.group(2)
        with open(out_path, 'wb') as f:
            f.write(base64.b64decode(b64))
        return True
    except Exception as e:
        logger.error(f"Failed to decode data URL: {e}")
        return False

def _download_or_decode_image_to_file(src: str, out_path: str) -> bool:
    """Save an image to disk from either data URL or http(s) URL."""
    try:
        if isinstance(src, str) and src.startswith('data:'):
            return _decode_data_url_to_file(src, out_path)
        if isinstance(src, str) and (src.startswith('http://') or src.startswith('https://')):
            ok, msg = download_image(src, out_path)
            return ok
        # Treat as local path if exists
        if isinstance(src, str) and os.path.exists(src):
            from shutil import copyfile
            copyfile(src, out_path)
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to obtain image: {e}")
        return False

def _probe_duration_seconds(media_path: str) -> float:
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', media_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout or '{}')
        dur = float(data.get('format', {}).get('duration', '0') or 0)
        if dur <= 0:
            # Try stream duration
            for s in data.get('streams', []):
                if 'duration' in s:
                    dur = max(dur, float(s['duration']))
        return max(0.0, dur)
    except Exception:
        return 0.0

def _build_srt_from_scenes(scenes, durations, out_path: str):
    try:
        def fmt(t):
            h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int((t % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        t = 0.0
        with open(out_path, 'w', encoding='utf-8') as f:
            idx = 1
            for i, sc in enumerate(scenes):
                text = (sc.get('text') or '').strip()
                if not text:
                    d = durations[i]
                    t += d
                    continue
                d = durations[i]
                start = t; end = t + d
                f.write(f"{idx}\n")
                f.write(f"{fmt(start)} --> {fmt(end)}\n")
                f.write(text.replace('\n', ' ') + "\n\n")
                t = end; idx += 1
    except Exception as e:
        logger.warning(f"Failed to create SRT: {e}")

def synthesize_speech(text, output_path, language_code="en-US", voice_name="en-US-Standard-C", api_key=None):
    """Synthesize speech from text using Gemini TTS."""
    try:
        import os
        import json
        import requests
        
        # Use provided API key or get from environment variables
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set. Skipping speech synthesis.")
            return False, "GEMINI_API_KEY not set"
        
        # Set up the API endpoint
        model = "gemini-2.0-flash"
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}"
        
        # Prepare the request payload
        payload = {
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": text
                }]
            }],
            "generationConfig": {
                "responseModalities": ["audio"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_name
                        }
                    }
                }
            }
        }
        
        # Make the API request
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        
        if response.status_code != 200:
            logger.error(f"Gemini TTS API error: {response.status_code} - {response.text}")
            # Parse error message if possible
            try:
                error_data = response.json()
                error_message = error_data.get("error", {}).get("message", "Unknown error")
                return False, f"Gemini TTS API error: {response.status_code} - {error_message}"
            except:
                return False, f"Gemini TTS API error: {response.status_code}"
        
        # Parse the response
        response_data = response.json()
        
        # Extract audio data from the response
        audio_data = None
        for item in response_data:
            if "candidates" in item and len(item["candidates"]) > 0:
                candidate = item["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "inlineData" in part and part["inlineData"]["mimeType"].startswith("audio/"):
                            audio_data = part["inlineData"]["data"]
                            break
            if audio_data:
                break
        
        if not audio_data:
            logger.error("No audio data found in Gemini TTS response")
            return False, "No audio data found in response"
        
        # Decode base64 audio data and save to file
        import base64
        audio_bytes = base64.b64decode(audio_data)
        
        with open(output_path, "wb") as out:
            out.write(audio_bytes)
            logger.info(f"Audio content written to file: {output_path}")
            
        return True, "Speech synthesized successfully"
        
    except Exception as e:
        logger.error(f"Error synthesizing speech with Gemini TTS: {str(e)}")
        return False, f"Error synthesizing speech: {str(e)}"

def download_image(url, save_path):
    """Download an image from a URL and save it to the specified path."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with open(save_path, 'wb') as f:
            f.write(response.content)
            
        return True, "Image downloaded successfully"
    except Exception as e:
        logger.error(f"Error downloading image from {url}: {str(e)}")
        return False, f"Error downloading image: {str(e)}"

def create_video_from_images(image_paths, output_path, duration_per_image=3, narration_texts=None, language_code="en-US", voice_name="en-US-Standard-C", api_key=None):
    """Create a video slideshow from a list of image paths using ffmpeg with optional voice narration."""
    try:
        temp_dir = os.path.dirname(image_paths[0]) if image_paths else UPLOAD_FOLDER
        
        # Create a temporary text file with the list of images
        temp_file = os.path.join(temp_dir, f"temp_{uuid.uuid4()}.txt")
        
        with open(temp_file, 'w') as f:
            for image_path in image_paths:
                # Each image will be shown for duration_per_image seconds
                f.write(f"file '{image_path}'\nduration {duration_per_image}\n")
            # Add the last image again to ensure it's shown for the full duration
            f.write(f"file '{image_paths[-1]}'\n")
        
        # If narration texts are provided, create audio files and combine with video
        if narration_texts and len(narration_texts) > 0:
            # Create audio files for each narration text
            audio_files = []
            for i, text in enumerate(narration_texts):
                if text.strip():
                    audio_path = os.path.join(temp_dir, f"narration_{i}.mp3")
                    success, message = synthesize_speech(text, audio_path, language_code, voice_name, api_key)
                    if success:
                        audio_files.append(audio_path)
                    else:
                        logger.warning(f"Failed to synthesize speech for text {i}: {message}")
            
            # If we have audio files, create a combined audio track
            if audio_files:
                # Create a temporary file list for audio concatenation
                audio_list_file = os.path.join(temp_dir, f"audio_list_{uuid.uuid4()}.txt")
                with open(audio_list_file, 'w') as f:
                    for audio_file in audio_files:
                        f.write(f"file '{audio_file}'\n")
                
                # Concatenate audio files
                combined_audio_path = os.path.join(temp_dir, f"combined_narration_{uuid.uuid4()}.mp3")
                cmd = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', audio_list_file,
                    '-c', 'copy',
                    '-y',
                    combined_audio_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                
                # Clean up audio list file
                if os.path.exists(audio_list_file):
                    os.remove(audio_list_file)
                
                # Clean up individual audio files
                for audio_file in audio_files:
                    if os.path.exists(audio_file):
                        os.remove(audio_file)
                
                if result.returncode == 0 and os.path.exists(combined_audio_path):
                    # Use ffmpeg to create the video with audio
                    cmd = [
                        'ffmpeg',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', temp_file,
                        '-i', combined_audio_path,
                        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
                        '-c:v', 'libx264',
                        '-c:a', 'aac',
                        '-strict', 'experimental',
                        '-r', '30',
                        '-pix_fmt', 'yuv420p',
                        '-y',
                        output_path
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    
                    # Clean up combined audio file
                    if os.path.exists(combined_audio_path):
                        os.remove(combined_audio_path)
                else:
                    # If audio creation failed, create video without audio
                    logger.warning("Failed to create combined audio, creating video without audio")
                    cmd = [
                        'ffmpeg',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', temp_file,
                        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
                        '-c:v', 'libx264',
                        '-r', '30',
                        '-pix_fmt', 'yuv420p',
                        '-y',
                        output_path
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            else:
                # No audio files created, create video without audio
                cmd = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', temp_file,
                    '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
                    '-c:v', 'libx264',
                    '-r', '30',
                    '-pix_fmt', 'yuv420p',
                    '-y',
                    output_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        else:
            # No narration texts, create video without audio
            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', temp_file,
                '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
                '-c:v', 'libx264',
                '-r', '30',
                '-pix_fmt', 'yuv420p',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        # Clean up the temporary file
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        if result.returncode != 0:
            error_msg = f"FFmpeg video creation failed: {result.stderr}"
            logger.error(error_msg)
            return False, error_msg
        
        logger.info(f"Video created successfully: {output_path}")
        return True, "Video created successfully"
        
    except subprocess.TimeoutExpired:
        error_msg = "Video creation timed out"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Video creation error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def process_csv_and_create_video(csv_path, duration_per_image=3, language_code="en-US", voice_name="en-US-Standard-C", api_key=None):
    """Process a CSV file and create separate videos for each product from the images."""
    try:
        temp_image_dir = os.path.join(UPLOAD_FOLDER, f"temp_images_{uuid.uuid4()}")
        os.makedirs(temp_image_dir, exist_ok=True)
        
        # Read the CSV file
        with open(csv_path, 'r', encoding='utf-8') as f:
            # Try to detect the dialect
            sample = f.read(1024)
            f.seek(0)
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample)
            has_header = sniffer.has_header(sample)
            
            reader = csv.reader(f, dialect)
            
            # Get headers if present
            if has_header:
                headers = next(reader)
            else:
                headers = None
                
            # Find important columns
            image_columns = []
            product_title_col = None
            product_description_col = None
            brand_col = None
            price_col = None
            
            if headers:
                for i, header in enumerate(headers):
                    header_lower = header.lower()
                    if 'image' in header_lower or 'url' in header_lower:
                        image_columns.append(i)
                    elif 'product title' in header_lower or 'product_title' in header_lower:
                        product_title_col = i
                    elif 'product description' in header_lower or 'product_description' in header_lower:
                        product_description_col = i
                    elif 'brand' in header_lower:
                        brand_col = i
                    elif 'price' in header_lower and 'currency' not in header_lower:
                        price_col = i
            else:
                # If no headers, use default column indices based on example.csv
                image_columns = [19, 20, 21, 22, 23, 24]  # Image URL columns
                product_title_col = 2  # Product Title column
                product_description_col = 20  # Product Description column
                brand_col = 3  # Brand column
                price_col = 4  # Current Price column
            
            # Process each row (product)
            product_videos = []
            for row_num, row in enumerate(reader):
                image_paths = []
                # Process image columns for this row
                for col_index in image_columns:
                    if col_index < len(row):
                        image_url = row[col_index].strip()
                        # Check if it looks like a URL
                        if image_url.startswith('http') and not image_url.lower().endswith('.mp4'):
                            # Download the image
                            image_filename = f"image_{row_num}_{col_index}.jpg"
                            image_path = os.path.join(temp_image_dir, image_filename)
                            
                            success, message = download_image(image_url, image_path)
                            if success and os.path.exists(image_path):
                                image_paths.append(image_path)
                
                # If we have images for this product, create a video
                if image_paths:
                    # Extract product information for narration
                    narration_texts = []
                    
                    # Get product title
                    product_title = ""
                    if product_title_col is not None and product_title_col < len(row):
                        product_title = row[product_title_col].strip()
                    
                    # Get product description
                    product_description = ""
                    if product_description_col is not None and product_description_col < len(row):
                        product_description = row[product_description_col].strip()
                    
                    # Get brand
                    brand = ""
                    if brand_col is not None and brand_col < len(row):
                        brand = row[brand_col].strip()
                    
                    # Get price
                    price = ""
                    if price_col is not None and price_col < len(row):
                        price = row[price_col].strip()
                    
                    # Create narration text
                    if product_title:
                        narration_texts.append(f"Check out this amazing product: {product_title}")
                    
                    if brand:
                        narration_texts.append(f"Brand: {brand}")
                    
                    if product_description:
                        # Split long descriptions into multiple sentences
                        sentences = product_description.split('.')
                        for sentence in sentences:
                            sentence = sentence.strip()
                            if sentence:
                                narration_texts.append(sentence)
                    
                    if price:
                        narration_texts.append(f"Price: {price}")
                    
                    # Add a call to action
                    narration_texts.append("Don't miss out on this great deal!")
                    
                    # Create a separate output path for this product
                    product_output_path = os.path.join(UPLOAD_FOLDER, f"product_{row_num}_output.mp4")
                    success, message = create_video_from_images(
                        image_paths, 
                        product_output_path, 
                        duration_per_image, 
                        narration_texts, 
                        language_code, 
                        voice_name,
                        api_key
                    )
                    if success:
                        product_videos.append({
                            'product_id': row_num,
                            'output_path': product_output_path,
                            'image_count': len(image_paths)
                        })
                    
                    # Clean up downloaded images for this product
                    for image_path in image_paths:
                        if os.path.exists(image_path):
                            os.remove(image_path)
            
            # Clean up temp directory
            if os.path.exists(temp_image_dir):
                os.rmdir(temp_image_dir)
            
            # If we created any product videos, return success
            if product_videos:
                return True, product_videos
            else:
                return False, "No valid image URLs found in CSV file"
            
    except Exception as e:
        logger.error(f"Error processing CSV file: {str(e)}")
        return False, f"Error processing CSV file: {str(e)}"

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
        # Create output filename with same name but .mp4 extension
        output_name = os.path.splitext(original_filename)[0] + '.mp4'
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

@app.route('/api/render-video', methods=['POST'])
def render_video_from_assets():
    """
    Render a vertical video (1080x1920) from client-provided assets.

    Expected JSON body:
    {
      "topic": "...",                      // optional
      "scriptData": { "scenes": [{"text": "...", "startTime": 0, "endTime": 3}, ...] },
      "images": ["data:image/png;base64,...", ...], // first may be thumbnail
      "audioSrc": "data:audio/mpeg;base64,...",
      "options": { "width":1080, "height":1920, "fps":30, "showSubtitles":true, "fontFamily":"DejaVuSans", "fontSize":40, "watermark":"@channel" }
    }
    Returns: { success, file_id, download_url }
    """
    try:
        data = request.get_json(silent=True) or {}
        images = data.get('images') or []
        audio_src = data.get('audioSrc') or data.get('audio')
        script = data.get('scriptData') or {}
        scenes = script.get('scenes') or []
        opts = data.get('options') or {}

        if not images or not audio_src:
            return jsonify({ 'error': 'images and audioSrc are required' }), 400

        width = int(opts.get('width', 1080))
        height = int(opts.get('height', 1920))
        fps = int(opts.get('fps', 30))
        show_subs = bool(opts.get('showSubtitles', True))
        font_family = opts.get('fontFamily', 'DejaVuSans')
        font_size = int(opts.get('fontSize', 40))
        watermark = opts.get('watermark', '')

        file_id = str(uuid.uuid4())
        temp_dir = os.path.join(UPLOAD_FOLDER, f"render_{file_id}")
        os.makedirs(temp_dir, exist_ok=True)

        # Save audio
        audio_path = os.path.join(temp_dir, 'audio')
        # Determine extension from mime if present
        audio_ext = 'mp3'
        if isinstance(audio_src, str) and audio_src.startswith('data:'):
            try:
                mime = audio_src.split(';', 1)[0].split(':', 1)[1]
                if 'ogg' in mime:
                    audio_ext = 'ogg'
                elif 'wav' in mime:
                    audio_ext = 'wav'
                elif 'mpeg' in mime or 'mp3' in mime:
                    audio_ext = 'mp3'
            except Exception:
                pass
        audio_path = audio_path + f'.{audio_ext}'
        if isinstance(audio_src, str) and audio_src.startswith('data:'):
            if not _decode_data_url_to_file(audio_src, audio_path):
                return jsonify({ 'error': 'Failed to decode audioSrc data URL' }), 400
        elif isinstance(audio_src, str) and (audio_src.startswith('http://') or audio_src.startswith('https://')):
            ok, msg = download_image(audio_src, audio_path)
            if not ok:
                return jsonify({ 'error': f'Failed to download audio: {msg}' }), 400
        else:
            return jsonify({ 'error': 'audioSrc must be a data URL or http(s) URL' }), 400

        # Optionally convert audio to WAV for consistent ffmpeg muxing
        wav_audio_path = os.path.join(temp_dir, 'audio.wav')
        try:
            cmd = ['ffmpeg', '-i', audio_path, '-ac', '2', '-ar', '44100', '-y', wav_audio_path]
            subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            use_audio_path = wav_audio_path if os.path.exists(wav_audio_path) else audio_path
        except Exception:
            use_audio_path = audio_path

        # Determine total audio duration
        total_audio_sec = _probe_duration_seconds(use_audio_path)

        # Decide which images to use for scenes (skip thumbnail if count matches)
        image_list = images
        if len(images) == len(scenes) + 1:
            image_list = images[1:]

        # Save images to files and prepare durations
        frame_paths = []
        for i, img in enumerate(image_list):
            out = os.path.join(temp_dir, f"frame_{i:03d}.png")
            if not _download_or_decode_image_to_file(img, out):
                # fallback to blank frame
                cmd = ['ffmpeg', '-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}', '-vframes', '1', '-y', out]
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            frame_paths.append(out)

        if not frame_paths:
            return jsonify({ 'error': 'No valid frames available' }), 400

        num_scenes = min(len(scenes) if scenes else len(frame_paths), len(frame_paths))
        if num_scenes <= 0:
            num_scenes = len(frame_paths)

        # Compute per-scene durations
        durations = []
        if scenes:
            for i in range(num_scenes):
                st = scenes[i].get('startTime'); en = scenes[i].get('endTime')
                if isinstance(st, (int, float)) and isinstance(en, (int, float)) and en > st:
                    durations.append(float(en - st))
        if not durations:
            # Even distribution
            base = (total_audio_sec / num_scenes) if total_audio_sec > 0 else 3.0
            durations = [base for _ in range(num_scenes)]

        # Build concat list file
        list_path = os.path.join(temp_dir, 'frames.txt')
        with open(list_path, 'w') as f:
            for i in range(num_scenes):
                f.write(f"file '{frame_paths[i]}'\n")
                f.write(f"duration {durations[i]}\n")
            # Repeat last frame once per concat demuxer rules
            f.write(f"file '{frame_paths[num_scenes-1]}'\n")

        # Create slideshow video scaled to target
        slideshow_path = os.path.join(temp_dir, 'slideshow.mp4')
        vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_path,
            '-vf', vf, '-r', str(fps), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', slideshow_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            return jsonify({ 'error': f"Failed to create slideshow: {result.stderr}" }), 500

        # Optional subtitles
        video_for_mux = slideshow_path
        srt_path = None
        if show_subs and scenes:
            srt_path = os.path.join(temp_dir, 'captions.srt')
            _build_srt_from_scenes(scenes[:num_scenes], durations, srt_path)
            subtitled_path = os.path.join(temp_dir, 'subtitled.mp4')
            cmd = [
                'ffmpeg', '-i', slideshow_path,
                '-vf', f"subtitles={srt_path}", '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', subtitled_path
            ]
            res2 = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if res2.returncode == 0 and os.path.exists(subtitled_path):
                video_for_mux = subtitled_path

        # Optional watermark
        if watermark:
            watermarked_path = os.path.join(temp_dir, 'watermarked.mp4')
            drawtext = f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='{watermark}':fontcolor=white@0.8:fontsize=24:x=w-tw-10:y=10"
            cmd = ['ffmpeg', '-i', video_for_mux, '-vf', drawtext, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', watermarked_path]
            res3 = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if res3.returncode == 0 and os.path.exists(watermarked_path):
                video_for_mux = watermarked_path

        # Mux with audio
        out_filename = f"{file_id}_render.mp4"
        out_path = os.path.join(UPLOAD_FOLDER, out_filename)
        cmd = ['ffmpeg', '-i', video_for_mux, '-i', use_audio_path, '-c:v', 'copy', '-c:a', 'aac', '-shortest', '-y', out_path]
        res4 = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res4.returncode != 0 or not os.path.exists(out_path):
            return jsonify({ 'error': f"Failed to mux audio: {res4.stderr}" }), 500

        # Success
        return jsonify({
            'success': True,
            'file_id': file_id,
            'download_url': f"/api/download-render/{file_id}",
        }), 200
    except Exception as e:
        logger.error(f"Render error: {e}")
        return jsonify({ 'error': f'Server error: {str(e)}' }), 500

@app.route('/api/download-render/<file_id>')
def download_render(file_id):
    try:
        uuid.UUID(file_id)
        out_path = os.path.join(UPLOAD_FOLDER, f"{file_id}_render.mp4")
        if not os.path.exists(out_path):
            return jsonify({ 'error': 'File not found or has been cleaned up' }), 404
        return send_file(out_path, as_attachment=True, download_name=f"render_{file_id}.mp4", mimetype='video/mp4')
    except ValueError:
        return jsonify({ 'error': 'Invalid file ID' }), 400
    except Exception as e:
        logger.error(f"Download render error: {e}")
        return jsonify({ 'error': f'Server error: {str(e)}' }), 500

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
        
        # Use the original filename with .mp4 extension for download
        original_filename = queue_status.get(file_id, {}).get('filename', f'converted_{file_id}.mp4')
        # If it's a CSV file, change the base name to indicate it's a video
        if original_filename.lower().endswith('.csv'):
            base_name = os.path.splitext(original_filename)[0]
            download_name = f"{base_name}_video.mp4"
        else:
            download_name = os.path.splitext(original_filename)[0] + '.mp4'
        
        return send_file(
            output_path,
            as_attachment=True,
            download_name=download_name,
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
    
    # Get queue status
    with queue_lock:
        queue_size = conversion_queue.qsize()
        active_jobs = len(queue_status)
    
    return jsonify({
        'status': 'online',
        'ffmpeg_available': ffmpeg_available,
        'max_file_size_mb': app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024),
        'supported_formats': ['webm', 'csv'],
        'queue_size': queue_size,
        'active_jobs': active_jobs
    })

@app.route('/api/bulk-convert', methods=['POST'])
def bulk_convert_videos():
    """API endpoint for bulk converting webm to mp4."""
    try:
        # Check if files are present in request
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': 'No files selected'}), 400
        
        # Validate files and add to queue
        queued_files = []
        rejected_files = []
        
        for file in files:
            if file.filename == '':
                continue
                
            if not allowed_file(file.filename):
                rejected_files.append({
                    'filename': file.filename,
                    'reason': 'Invalid file type. Only WebM files are allowed'
                })
                continue
            
            # Generate unique filenames
            file_id = str(uuid.uuid4())
            original_filename = secure_filename(file.filename or 'unknown.webm')
            # Create output filename with same name but .mp4 extension
            output_name = os.path.splitext(original_filename)[0] + '.mp4'
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
                rejected_files.append({
                    'filename': original_filename,
                    'reason': validation_message
                })
                continue
            
            # Add to conversion queue
            conversion_queue.put({
                'file_id': file_id,
                'input_path': input_path,
                'output_path': output_path,
                'original_filename': original_filename
            })
            
            # Initialize queue status
            update_queue_status(file_id, 'queued', 'Waiting in queue...', filename=original_filename)
            
            queued_files.append({
                'file_id': file_id,
                'filename': original_filename
            })
        
        return jsonify({
            'success': True,
            'message': f'{len(queued_files)} files queued for conversion, {len(rejected_files)} files rejected',
            'queued_files': queued_files,
            'rejected_files': rejected_files
        })
        
    except RequestEntityTooLarge:
        return jsonify({'error': 'File too large. Maximum size is 500MB'}), 413
    except Exception as e:
        logger.error(f"Bulk conversion error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/queue-status')
def get_queue_status():
    """Get the status of all files in the conversion queue."""
    try:
        with queue_lock:
            # Create a copy of queue status
            status_copy = {}
            for file_id, status_info in queue_status.items():
                status_copy[file_id] = status_info.copy()
        
        return jsonify({
            'success': True,
            'queue_status': status_copy,
            'queue_size': conversion_queue.qsize()
        })
    except Exception as e:
        logger.error(f"Queue status error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/csv-to-video', methods=['POST'])
def csv_to_video():
    """API endpoint for creating videos from CSV files with product data using FFmpeg rendering."""
    try:
        # Check if file is present in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Only CSV files are allowed'}), 400
        
        # Get parameters for FFmpeg-based video creation
        duration_per_scene = float(request.form.get('duration_per_scene', 5.0))
        if duration_per_scene < 1 or duration_per_scene > 30:
            duration_per_scene = 5.0
            
        voice_name = request.form.get('voice_name', 'Zephyr')
        gemini_api_key = request.form.get('gemini_api_key')
        show_subtitles = request.form.get('show_subtitles', 'true').lower() == 'true'
        font_style = request.form.get('font_style', 'Sarabun')
        font_size = int(request.form.get('font_size', 60))
        watermark = request.form.get('watermark', '')
        outro_text = request.form.get('outro_text', '')
        
        # Generate unique ID for this batch
        file_id = str(uuid.uuid4())
        original_filename = secure_filename(file.filename or 'unknown.csv')
        input_filename = f"{file_id}_input.csv"
        output_dir = os.path.join(UPLOAD_FOLDER, f"product_videos_{file_id}")
        
        input_path = os.path.join(UPLOAD_FOLDER, input_filename)
        
        # Save uploaded file
        file.save(input_path)
        logger.info(f"CSV file uploaded: {input_path}")
        
        # Process the CSV and create videos using our new FFmpeg-based approach
        success, result = csv_to_video_ffmpeg.process_csv_and_create_videos(
            input_path,
            output_dir,
            duration_per_scene,
            voice_name,
            gemini_api_key,
            show_subtitles,
            font_style,
            font_size,
            watermark,
            outro_text
        )
        
        # Clean up input file
        cleanup_file(input_path)
        
        if not success:
            return jsonify({'error': result[0].get('message', 'Failed to create videos')}), 500
        
        # Create download URLs for each product video
        product_videos = []
        for video_info in result:
            if not video_info.get('error'):
                product_id = video_info['product_id']
                product_title = video_info['product_title']
                # Create a safe filename for download
                safe_title = "".join(c for c in product_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                if not safe_title:
                    safe_title = f"product_{product_id}"
                download_filename = f"{safe_title.replace(' ', '_')}.mp4"
                
                product_videos.append({
                    'product_id': product_id,
                    'product_title': product_title,
                    'download_url': f"/api/download-product-video-ffmpeg/{file_id}/{download_filename}",
                    'message': video_info.get('message', 'Video created successfully')
                })
        
        return jsonify({
            'success': True,
            'message': f'Created {len(product_videos)} product videos',
            'file_id': file_id,
            'original_filename': original_filename,
            'product_videos': product_videos
        })
        
    except RequestEntityTooLarge:
        return jsonify({'error': 'File too large. Maximum size is 500MB'}), 413
    except Exception as e:
        logger.error(f"CSV to video error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/download-product-video/<file_id>/<product_id>')
def download_product_video(file_id, product_id):
    """Download generated product video file."""
    try:
        # Validate file_id format (should be a valid UUID)
        uuid.UUID(file_id)
        
        # Validate product_id is a number
        product_id = int(product_id)
        
        output_filename = f"product_{product_id}_output.mp4"
        output_path = os.path.join(UPLOAD_FOLDER, output_filename)
        
        if not os.path.exists(output_path):
            return jsonify({'error': 'File not found or has been cleaned up'}), 404
        
        # Use a descriptive filename for download
        download_name = f"product_{product_id}_video.mp4"
        
        return send_file(
            output_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='video/mp4'
        )
        
    except ValueError:
        return jsonify({'error': 'Invalid file ID or product ID'}), 400
    except Exception as e:
        logger.error(f"Product video download error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/api/download-product-video-ffmpeg/<file_id>/<filename>')
def download_product_video_ffmpeg(file_id, filename):
    """Download generated product video file created with FFmpeg."""
    try:
        # Validate file_id format (should be a valid UUID)
        uuid.UUID(file_id)
        
        # Validate filename
        if not filename or '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Construct the path to the video file
        output_dir = os.path.join(UPLOAD_FOLDER, f"product_videos_{file_id}")
        output_path = os.path.join(output_dir, filename)
        
        if not os.path.exists(output_path):
            return jsonify({'error': 'File not found or has been cleaned up'}), 404
        
        return send_file(
            output_path,
            as_attachment=True,
            download_name=filename,
            mimetype='video/mp4'
        )
        
    except ValueError:
        return jsonify({'error': 'Invalid file ID'}), 400
    except Exception as e:
        logger.error(f"FFmpeg product video download error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

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
    import sys
    port = 5000
    if len(sys.argv) > 1 and sys.argv[1] == '--port':
        port = int(sys.argv[2])
    app.run(host='0.0.0.0', port=port, debug=True)
