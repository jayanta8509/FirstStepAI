import os
import re
from supadata import Supadata
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("API_KEY")
supadata = Supadata(api_key=API_KEY)

openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()


def is_youtube_url(url):
    """Check if the given URL or text contains a YouTube URL"""
    youtube_patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+'  # Added shorts support
    ]

    for pattern in youtube_patterns:
        if re.search(pattern, url):  # Changed from re.match to re.search
            return True
    return False


def summarize_with_gpt4o_mini(transcript_text, max_words=200):
    """
    Summarize YouTube transcript using GPT-4o-mini

    Args:
        transcript_text: Full transcript text
        max_words: Maximum word count for summary (default: 200)

    Returns:
        str: Summarized text
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"You are a helpful assistant that summarizes YouTube video transcripts. Create a clear, concise summary in maximum {max_words} words. Focus on the key points, main ideas, and any actionable insights."
                },
                {
                    "role": "user",
                    "content": f"Please summarize this YouTube video transcript:\n\n{transcript_text}"
                }
            ],
            temperature=0.5,
            max_tokens=1000  # Enough for ~200 words
        )

        summary = response.choices[0].message.content
        print(f"✅ Summary generated ({len(summary.split())} words)")
        return summary

    except Exception as e:
        print(f"❌ Error summarizing with GPT-4o-mini: {e}")
        # Return original text if summarization fails
        return transcript_text


def process_any_input(url):
    """
    Process YouTube URL and return summarized transcript

    Args:
        url: YouTube URL (or text containing YouTube URL)

    Returns:
        str: Summarized transcript (max 200 words) or full text if summarization fails
    """
    # Extract YouTube URL if text contains more than just the URL
    if is_youtube_url(url):
        youtube_url = url
        # Check if there's additional text before/after the URL
        for pattern in [
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
            r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
            r'(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+',
            r'(?:https?://)?(?:www\.)?youtube\.com/v/[\w-]+',
            r'(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+'
        ]:
            match = re.search(pattern, url)
            if match:
                youtube_url = match.group(0)
                if not youtube_url.startswith('http'):
                    youtube_url = 'https://' + youtube_url
                break

        print(f"🎬 Processing YouTube video: {youtube_url}")

        try:
            # Get transcript using supadata
            transcript = supadata.transcript(url=youtube_url)
            full_text = " ".join([chunk.text for chunk in transcript.content])

            print(f"📝 Full transcript length: {len(full_text.split())} words")

            # Summarize using GPT-4o-mini (max 200 words)
            print("🤖 Summarizing with GPT-4o-mini...")
            summary = summarize_with_gpt4o_mini(full_text, max_words=200)
            # print(summary)

            return summary

        except Exception as e:
            print(f"❌ Error processing YouTube video: {e}")
            return f"❌ Failed to process YouTube video: {youtube_url}\nError: {str(e)}"

    else:
        return "❌ No valid YouTube URL found in input"
