import os
import uuid
import logging
import tempfile
import subprocess
import json
import csv
import requests
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import base64

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def synthesize_speech_with_gemini(text: str, output_path: str, voice_name: str = "Zephyr", api_key: str = None) -> Tuple[bool, str]:
    """Synthesize speech from text using Gemini TTS."""
    try:
        # Use provided API key or get from environment variables
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set. Skipping speech synthesis.")
            return False, "GEMINI_API_KEY not set"
        
        # Set up the API endpoint
        model = "gemini-2.5-flash-preview-tts"
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
        audio_bytes = base64.b64decode(audio_data)
        
        with open(output_path, "wb") as out:
            out.write(audio_bytes)
            logger.info(f"Audio content written to file: {output_path}")
            
        return True, "Speech synthesized successfully"
        
    except Exception as e:
        logger.error(f"Error synthesizing speech with Gemini TTS: {str(e)}")
        return False, f"Error synthesizing speech: {str(e)}"

def download_image(url: str, save_path: str) -> Tuple[bool, str]:
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

def create_wav_header(sample_rate: int = 24000, bits_per_sample: int = 16, channels: int = 1) -> bytes:
    """Create a WAV file header."""
    import struct
    
    # Calculate derived values
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    
    # Create header
    header = b'RIFF'
    header += struct.pack('<I', 36)  # Placeholder for file size
    header += b'WAVE'
    header += b'fmt '
    header += struct.pack('<I', 16)  # Subchunk1Size
    header += struct.pack('<H', 1)   # AudioFormat (PCM)
    header += struct.pack('<H', channels)
    header += struct.pack('<I', sample_rate)
    header += struct.pack('<I', byte_rate)
    header += struct.pack('<H', block_align)
    header += struct.pack('<H', bits_per_sample)
    header += b'data'
    header += struct.pack('<I', 0)   # Placeholder for data size
    
    return header

def convert_audio_to_wav(input_path: str, output_path: str) -> Tuple[bool, str]:
    """Convert audio file to WAV format using ffmpeg."""
    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-acodec', 'pcm_s16le',
            '-ar', '24000',
            '-ac', '1',
            '-y',
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            error_msg = f"FFmpeg audio conversion failed: {result.stderr}"
            logger.error(error_msg)
            return False, error_msg
        
        logger.info(f"Audio converted successfully: {output_path}")
        return True, "Audio converted successfully"
        
    except subprocess.TimeoutExpired:
        error_msg = "Audio conversion timed out"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Audio conversion error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def create_video_from_product_data(
    product_data: Dict, 
    output_path: str, 
    duration_per_scene: float = 5.0,
    voice_name: str = "Zephyr",
    api_key: str = None,
    show_subtitles: bool = True,
    font_style: str = "Sarabun",
    font_size: int = 60,
    watermark: str = "",
    outro_text: str = ""
) -> Tuple[bool, str]:
    """
    Create a video from product data using FFmpeg with narration.
    
    Args:
        product_data: Dictionary containing product information
        output_path: Path to save the output video
        duration_per_scene: Duration for each scene in seconds
        voice_name: Voice name for narration
        api_key: Gemini API key
        show_subtitles: Whether to show subtitles
        font_style: Font style for subtitles
        font_size: Font size for subtitles
        watermark: Watermark text
        outro_text: Outro text to append to narration
    """
    try:
        # Create temporary directory for assets
        temp_dir = tempfile.mkdtemp(prefix="product_video_")
        logger.info(f"Created temporary directory: {temp_dir}")
        
        # Extract product information
        product_title = product_data.get("Product Title", "")
        brand = product_data.get("Brand", "")
        current_price = product_data.get("Current Price", "")
        original_price = product_data.get("Original Price", "")
        currency = product_data.get("Currency", "")
        discount_percentage = product_data.get("Discount Percentage", "")
        product_description = product_data.get("Product Description", "")
        image_urls = []
        
        # Collect image URLs (main image + additional images)
        if "Main Image URL" in product_data and product_data["Main Image URL"]:
            image_urls.append(product_data["Main Image URL"])
        
        for i in range(1, 6):
            key = f"Additional Image {i}"
            if key in product_data and product_data[key]:
                image_urls.append(product_data[key])
        
        # Download images
        image_paths = []
        for i, url in enumerate(image_urls):
            if url and url.startswith('http'):
                image_path = os.path.join(temp_dir, f"image_{i}.jpg")
                success, message = download_image(url, image_path)
                if success and os.path.exists(image_path):
                    image_paths.append(image_path)
                else:
                    logger.warning(f"Failed to download image {i}: {message}")
        
        if not image_paths:
            return False, "No valid images found for product"
        
        # Create narration script
        narration_parts = []
        
        # Product introduction
        if product_title:
            narration_parts.append(f"Check out this amazing product: {product_title}")
        
        # Brand information
        if brand:
            narration_parts.append(f"Brand: {brand}")
        
        # Price information
        price_info = []
        if current_price and current_price != "Not Available":
            price_info.append(f"Current price: {current_price} {currency}")
        if original_price and original_price != "Not Available":
            price_info.append(f"Original price: {original_price} {currency}")
        if discount_percentage and discount_percentage != "Not Available":
            price_info.append(f"Discount: {discount_percentage}% off")
        
        if price_info:
            narration_parts.append(". ".join(price_info))
        
        # Product description
        if product_description and product_description != "Not Available":
            # Split long descriptions into sentences
            sentences = product_description.split('.')
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence and not sentence.lower().startswith("not available"):
                    narration_parts.append(sentence)
        
        # Add outro text if provided
        if outro_text:
            narration_parts.append(outro_text)
        
        # Combine narration parts
        full_narration = " \n\n ".join(narration_parts)
        
        if not full_narration.strip():
            return False, "No narration content generated"
        
        # Synthesize speech
        audio_path = os.path.join(temp_dir, "narration.mp3")
        success, message = synthesize_speech_with_gemini(full_narration, audio_path, voice_name, api_key)
        
        if not success:
            return False, f"Failed to synthesize speech: {message}"
        
        # Convert audio to WAV for better compatibility
        wav_audio_path = os.path.join(temp_dir, "narration.wav")
        success, message = convert_audio_to_wav(audio_path, wav_audio_path)
        
        if not success:
            return False, f"Failed to convert audio: {message}"
        
        # Get audio duration
        try:
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', wav_audio_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            probe_data = json.loads(result.stdout)
            audio_duration = float(probe_data['format']['duration'])
        except Exception as e:
            logger.warning(f"Could not determine audio duration, using estimated duration: {str(e)}")
            # Estimate based on number of characters (rough approximation)
            audio_duration = len(full_narration) / 15.0  # ~15 chars per second
        
        # Calculate number of scenes needed to match audio duration
        num_scenes = max(1, int(audio_duration / duration_per_scene))
        actual_duration_per_scene = audio_duration / num_scenes
        
        # Create video scenes
        scene_files = []
        for i in range(num_scenes):
            # Determine which image to use for this scene
            image_index = min(i, len(image_paths) - 1)
            image_path = image_paths[image_index]
            
            scene_path = os.path.join(temp_dir, f"scene_{i:03d}.png")
            scene_files.append(scene_path)
            
            # Create scene with image (using ffmpeg for resizing and formatting)
            cmd = [
                'ffmpeg',
                '-i', image_path,
                '-vf', f'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1',
                '-y',
                scene_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                logger.warning(f"Failed to create scene {i}: {result.stderr}")
                # Use a blank frame as fallback
                cmd = [
                    'ffmpeg',
                    '-f', 'lavfi',
                    '-i', 'color=c=black:s=1080x1920',
                    '-vf', 'scale=1080:1920',
                    '-vframes', '1',
                    '-y',
                    scene_path
                ]
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # Create slideshow video
        slideshow_path = os.path.join(temp_dir, "slideshow.mp4")
        
        # Create file list for slideshow
        file_list_path = os.path.join(temp_dir, "file_list.txt")
        with open(file_list_path, 'w') as f:
            for scene_file in scene_files:
                f.write(f"file '{scene_file}'\nduration {actual_duration_per_scene}\n")
            # Add the last file again to ensure it's shown for the full duration
            f.write(f"file '{scene_files[-1]}'\n")
        
        # Create slideshow with Ken Burns effect
        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', file_list_path,
            '-vf', 'zoompan=z=min(zoom+0.0015,1.5):x=(iw-iw/zoom)/2:y=(ih-ih/zoom)/2:d=250',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-y',
            slideshow_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            error_msg = f"FFmpeg slideshow creation failed: {result.stderr}"
            logger.error(error_msg)
            return False, error_msg
        
        # Add subtitles if enabled
        if show_subtitles and full_narration:
            subtitled_path = os.path.join(temp_dir, "subtitled.mp4")
            
            # Create subtitle file
            subtitle_path = os.path.join(temp_dir, "subtitles.srt")
            create_srt_file(full_narration, subtitle_path, audio_duration)
            
            # Burn subtitles into video
            cmd = [
                'ffmpeg',
                '-i', slideshow_path,
                '-vf', f"subtitles={subtitle_path}:force_style='FontName={font_style},FontSize={font_size},PrimaryColour=&H00FFFFFF,Outline=2,Shadow=1'",
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-y',
                subtitled_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.warning(f"Failed to add subtitles: {result.stderr}")
                subtitled_path = slideshow_path
        else:
            subtitled_path = slideshow_path
        
        # Add watermark if provided
        if watermark:
            watermarked_path = os.path.join(temp_dir, "watermarked.mp4")
            
            cmd = [
                'ffmpeg',
                '-i', subtitled_path,
                '-vf', f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='{watermark}':fontcolor=white@0.8:fontsize=24:x=w-tw-10:y=10",
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-y',
                watermarked_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.warning(f"Failed to add watermark: {result.stderr}")
                watermarked_path = subtitled_path
        else:
            watermarked_path = subtitled_path
        
        # Combine video and audio
        cmd = [
            'ffmpeg',
            '-i', watermarked_path,
            '-i', wav_audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-strict', 'experimental',
            '-y',
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            error_msg = f"FFmpeg video and audio combination failed: {result.stderr}"
            logger.error(error_msg)
            return False, error_msg
        
        # Clean up temporary files
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary directory: {str(e)}")
        
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

def create_srt_file(text: str, output_path: str, total_duration: float) -> None:
    """Create an SRT subtitle file from text."""
    try:
        # Split text into sentences
        sentences = text.split('\n\n')
        if not sentences:
            sentences = [text]
        
        # Calculate duration per sentence
        sentence_duration = total_duration / len(sentences)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, sentence in enumerate(sentences):
                if not sentence.strip():
                    continue
                    
                start_time = i * sentence_duration
                end_time = (i + 1) * sentence_duration
                
                # Format time as HH:MM:SS,mmm
                start_str = format_time(start_time)
                end_str = format_time(end_time)
                
                f.write(f"{i+1}\n")
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{sentence.strip()}\n\n")
    except Exception as e:
        logger.error(f"Error creating SRT file: {str(e)}")

def format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def process_csv_and_create_videos(
    csv_path: str,
    output_dir: str,
    duration_per_scene: float = 5.0,
    voice_name: str = "Zephyr",
    api_key: str = None,
    show_subtitles: bool = True,
    font_style: str = "Sarabun",
    font_size: int = 60,
    watermark: str = "",
    outro_text: str = ""
) -> Tuple[bool, List[Dict]]:
    """
    Process a CSV file and create separate videos for each product.
    
    Args:
        csv_path: Path to the CSV file
        output_dir: Directory to save output videos
        duration_per_scene: Duration for each scene in seconds
        voice_name: Voice name for narration
        api_key: Gemini API key
        show_subtitles: Whether to show subtitles
        font_style: Font style for subtitles
        font_size: Font size for subtitles
        watermark: Watermark text
        outro_text: Outro text to append to narration
        
    Returns:
        Tuple of (success, list of video info dictionaries)
    """
    try:
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
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
                
            # Process each row (product)
            product_videos = []
            for row_num, row in enumerate(reader):
                # Create product data dictionary
                product_data = {}
                if headers:
                    for i, header in enumerate(headers):
                        if i < len(row):
                            product_data[header] = row[i]
                else:
                    # If no headers, use default column indices based on example.csv
                    # This is a simplified mapping for demonstration
                    field_mapping = {
                        2: "Product Title",
                        3: "Brand",
                        4: "Current Price",
                        5: "Original Price",
                        6: "Currency",
                        7: "Discount Percentage",
                        20: "Product Description",
                        21: "Main Image URL"
                    }
                    for i in range(1, 6):
                        field_mapping[21 + i] = f"Additional Image {i}"
                    
                    for col_index, field_name in field_mapping.items():
                        if col_index < len(row):
                            product_data[field_name] = row[col_index]
                
                # Create a separate output path for this product
                safe_title = "".join(c for c in product_data.get("Product Title", f"product_{row_num}") if c.isalnum() or c in (' ', '-', '_')).rstrip()
                if not safe_title:
                    safe_title = f"product_{row_num}"
                
                output_path = os.path.join(output_dir, f"{safe_title.replace(' ', '_')}.mp4")
                
                # Create video for this product
                success, message = create_video_from_product_data(
                    product_data,
                    output_path,
                    duration_per_scene,
                    voice_name,
                    api_key,
                    show_subtitles,
                    font_style,
                    font_size,
                    watermark,
                    outro_text
                )
                
                if success:
                    product_videos.append({
                        'product_id': row_num,
                        'output_path': output_path,
                        'product_title': product_data.get("Product Title", f"Product {row_num}"),
                        'message': message
                    })
                else:
                    logger.error(f"Failed to create video for product {row_num}: {message}")
                    product_videos.append({
                        'product_id': row_num,
                        'output_path': None,
                        'product_title': product_data.get("Product Title", f"Product {row_num}"),
                        'message': message,
                        'error': True
                    })
            
            # If we created any product videos, return success
            if product_videos:
                successful_videos = [v for v in product_videos if not v.get('error')]
                if successful_videos:
                    return True, product_videos
                else:
                    return False, product_videos
            else:
                return False, [{"error": True, "message": "No valid products found in CSV file"}]
            
    except Exception as e:
        logger.error(f"Error processing CSV file: {str(e)}")
        return False, [{"error": True, "message": f"Error processing CSV file: {str(e)}"}]

# Example usage
if __name__ == "__main__":
    # Example of how to use the functions
    # This would typically be called from a web API endpoint
    
    # Example product data (as would be extracted from CSV)
    sample_product = {
        "Product Title": "COM505 TARA Pants",
        "Brand": "TARA.CLOSET",
        "Current Price": "330.00",
        "Original Price": "Not Available",
        "Currency": "THB",
        "Discount Percentage": "65",
        "Product Description": "กางเกงช้างขายาว ทรงขากระบอกใหญ่ เอวยางยืด ลายผ้าขา 2 ข้างตรงกัน ผ้าไหมอิตาลีพิมพ์ลายดิจิตอล ลายพิมพ์ชัด สีไม่ตก ใส่แล้วดูมีราคา ผ้าเบาใส่สบาย",
        "Main Image URL": "https://cf.shopee.co.th/file/th-11134207-7rasd-m4r4umajaxmy7a",
        "Additional Image 1": "https://cf.shopee.co.th/file/th-11134207-7ras8-m4r4wqm9m04zec",
        "Additional Image 2": "https://cf.shopee.co.th/file/th-11134207-7rasc-m4r4yk81lscq99"
    }
    
    # Create a video for this product
    # success, message = create_video_from_product_data(
    #     sample_product,
    #     "output_video.mp4",
    #     duration_per_scene=5.0,
    #     voice_name="Zephyr",
    #     api_key=os.environ.get("GEMINI_API_KEY"),
    #     show_subtitles=True,
    #     font_style="Sarabun",
    #     font_size=60,
    #     watermark="@yourchannel",
    #     outro_text="Don't forget to like and subscribe for more amazing products!"
    # )
    # 
    # print(f"Video creation {'successful' if success else 'failed'}: {message}")
    pass
