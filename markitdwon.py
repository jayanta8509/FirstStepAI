import os
import re
import tempfile
import shutil
from pathlib import Path
from markitdown import MarkItDown
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()

def is_youtube_url(url):
    """Check if the given URL is a YouTube URL"""
    youtube_patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/[\w-]+'
    ]
    
    for pattern in youtube_patterns:
        if re.match(pattern, url):
            return True
    return False

def download_youtube_captions(youtube_url, output_dir):
    """Try to download YouTube captions directly (more reliable than audio transcription)"""
    try:
        import yt_dlp
        
        # Configure yt-dlp to download captions/subtitles
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,  # Also try auto-generated captions
            'subtitleslangs': ['en', 'en-US', 'en-GB'],  # English captions
            'subtitlesformat': 'vtt',
            'skip_download': True,  # Only download captions, not video
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get video info
            info = ydl.extract_info(youtube_url, download=False)
            title = info.get('title', 'video')
            
            # Try to download captions
            ydl.download([youtube_url])
            
            # Look for caption files
            for file in os.listdir(output_dir):
                if file.endswith('.vtt') and title.replace('/', '_').replace('\\', '_') in file:
                    # Read and clean the VTT file
                    with open(os.path.join(output_dir, file), 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Basic VTT cleaning - remove timestamps and formatting
                    lines = content.split('\n')
                    text_lines = []
                    for line in lines:
                        line = line.strip()
                        # Skip VTT headers, timestamps, and empty lines
                        if (line and 
                            not line.startswith('WEBVTT') and 
                            not line.startswith('NOTE') and
                            not '-->' in line and
                            not line.isdigit()):
                            text_lines.append(line)
                    
                    return ' '.join(text_lines)
            
            return None, "No captions found for this video"
                
    except ImportError:
        return None, "yt-dlp is not installed"
    except Exception as e:
        return None, f"Error downloading captions: {str(e)}"

def download_youtube_video(youtube_url, output_dir):
    """Download YouTube video and return the path to downloaded file"""
    try:
        import yt_dlp
        
        # Configure yt-dlp to download and convert audio to mp3
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,  # Only download single video, not playlist
            'quiet': False,      # Show download progress
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # Get video info first
                info = ydl.extract_info(youtube_url, download=False)
                title = info.get('title', 'video')
                print(f"Video title: {title}")
                
                # Download and convert the video
                ydl.download([youtube_url])
                
                # Find the downloaded mp3 file with better matching
                for file in os.listdir(output_dir):
                    if file.endswith('.mp3'):
                        # More flexible matching - just check if it's an mp3
                        return os.path.join(output_dir, file)
                
                # If no mp3 found, list all files for debugging
                all_files = os.listdir(output_dir)
                print(f"Files in temp directory: {all_files}")
                
                # Try to find any audio file
                audio_extensions = ['.mp3', '.m4a', '.wav', '.webm', '.ogg']
                for file in all_files:
                    for ext in audio_extensions:
                        if file.endswith(ext):
                            print(f"Found audio file: {file}")
                            return os.path.join(output_dir, file)
                            
            except Exception as download_error:
                return None, f"Download failed: {str(download_error)}"
                
    except ImportError:
        return None, "yt-dlp is not installed. Please install it with: pip install yt-dlp"
    except Exception as e:
        return None, f"Error setting up YouTube downloader: {str(e)}"
    
    return None, "No audio file found after download"

def process_any_input(user_input):
    """
    Universal function to process any input: YouTube URLs, local files, or file paths.
    
    Args:
        user_input (str): Can be:
            - YouTube URL (any format)
            - Local file path 
            - File name in current directory
            
    Returns:
        str: Processed text content
    """
    try:
        # Initialize MarkItDown with OpenAI for better image processing
        if openai_api_key:
            md = MarkItDown(llm_client=client, llm_model="gpt-4o")
            print("🤖 Using AI-enhanced processing (with image descriptions)")
        else:
            md = MarkItDown()
            print("📝 Using basic processing (no AI image descriptions)")
        
        # Check if input is a YouTube URL
        if is_youtube_url(user_input):
            print(f"🎬 Processing YouTube video: {user_input}")
            
            # Create temporary directory for download
            with tempfile.TemporaryDirectory() as temp_dir:
                # Method 1: Try captions first (most reliable)
                print("📋 Trying to download captions...")
                captions_result = download_youtube_captions(user_input, temp_dir)
                
                if captions_result and not isinstance(captions_result, tuple):
                    print("✅ Captions found and processed!")
                    return f"""=== YouTube Video ===
URL: {user_input}
Source: Video Captions

{captions_result}"""
                
                # Method 2: Fallback to audio transcription
                print("🎵 Captions not available, trying audio transcription...")
                downloaded_file = download_youtube_video(user_input, temp_dir)
                
                if downloaded_file and isinstance(downloaded_file, str):
                    try:
                        result = md.convert(downloaded_file)
                        if result and result.text_content:
                            return f"""=== YouTube Video ===
URL: {user_input}
Source: Audio Transcription

{result.text_content}"""
                        else:
                            return f"❌ YouTube video downloaded but no content could be extracted from audio."
                    except Exception as e:
                        return f"""❌ YouTube Processing Failed
URL: {user_input}

Both caption download and audio transcription failed.
Error: {str(e)}

Try:
- A video with captions (CC button visible)
- A shorter video (< 10 minutes)  
- Again later (API limits)"""
                
                else:
                    return f"❌ Failed to download YouTube video: {user_input}"
        
        # Handle local files
        else:
            # Convert to Path object and handle relative paths
            if not os.path.isabs(user_input):
                # If relative path, make it relative to current directory
                file_path = Path(user_input)
            else:
                file_path = Path(user_input)
            
            # Check if file exists
            if not file_path.exists():
                return f"❌ File not found: {user_input}\nMake sure the file exists and the path is correct."
            
            # Check if it's a directory (not supported)
            if file_path.is_dir():
                return f"❌ Folders not supported: {user_input}\nPlease provide a single file path."
            
            # Process the file
            print(f"📄 Processing file: {file_path.name}")
            
            try:
                result = md.convert(str(file_path))
                
                if result and result.text_content:
                    return f"""=== File: {file_path.name} ===
Path: {str(file_path)}
Size: {file_path.stat().st_size / 1024:.1f} KB

{result.text_content}"""
                else:
                    # Specific guidance based on file type
                    ext = file_path.suffix.lower()
                    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
                        if openai_api_key:
                            return f"❌ Image processed but no content found: {file_path.name}\nThis might mean the image has no readable text or recognizable content."
                        else:
                            return f"❌ Image processing limited: {file_path.name}\nFor better image descriptions, add your OpenAI API key to .env file."
                    else:
                        return f"❌ File processed but no content extracted: {file_path.name}\nThe file might be empty, corrupted, or unsupported."
                        
            except Exception as e:
                return f"❌ Error processing file: {file_path.name}\nError: {str(e)}"
    
    except Exception as e:
        return f"❌ Unexpected error: {str(e)}"

# Simple example usage function
def main():
    """Example of how to use the universal processor"""
    
    # Example inputs - uncomment what you want to test
    
    # Test with YouTube URL
    test_input = "https://www.youtube.com/watch?v=6-2ra25RVRs"
    
    # Test with local file
    # test_input = "Chat.png"
    
    # Test with full file path  
    # test_input = r"C:\Users\pc\Downloads\example.pdf"
    
    print("🚀 Starting universal processor...")
    result = process_any_input(test_input)
    print("\n" + "="*50)
    print(result)
    print("="*50)

# Keep the old functions for backward compatibility
def convert_file_or_youtube(input_path):
    """Legacy function - use process_any_input() instead"""
    return process_any_input(input_path)

# # Example usage
# if __name__ == "__main__":
#     print("🚀 Universal File & YouTube Processor")
#     print("="*50)
    
#     # You can test any of these inputs by uncommenting them:
    
#     # Test 1: YouTube URL
#     # user_input = "https://www.youtube.com/watch?v=jgyTwWtvMdE"
    
#     # # Test 2: Local image with AI description (if OpenAI key is set)
#     # user_input = "Diagram V5.txt"
    
#     # Test 3: Any file in current directory
#     user_input = "README.md"
    
#     # Process the input
#     result = process_any_input(user_input)
#     print(result)