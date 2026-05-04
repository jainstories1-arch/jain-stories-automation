import os
import json
import base64
import pickle
import time
from datetime import datetime
from io import BytesIO

import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.cloud import texttospeech
import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip

# =============================================================================
# CONFIGURATION FROM GITHUB SECRETS
# =============================================================================

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
SHEET_ID = os.environ.get('SHEET_ID')
PENDING_FOLDER_ID = os.environ.get('PENDING_FOLDER_ID')
APPROVED_FOLDER_ID = os.environ.get('APPROVED_FOLDER_ID')
PUBLISHED_FOLDER_ID = os.environ.get('PUBLISHED_FOLDER_ID')
REJECTED_FOLDER_ID = os.environ.get('REJECTED_FOLDER_ID')

# Service Account credentials (JSON as string)
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

# OAuth credentials (JSON as string) - Only needed for YouTube upload
CLIENT_SECRET_JSON = os.environ.get('CLIENT_SECRET')

# YouTube token (base64 encoded pickle) - Only needed for YouTube upload
TOKEN_PICKLE_B64 = os.environ.get('TOKEN_PICKLE')
DRIVE_TOKEN_B64 = os.environ.get('DRIVE_TOKEN')

# =============================================================================
# LOAD CREDENTIALS
# =============================================================================

def load_service_account_creds():
    """Load service account credentials from environment variable"""
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    return ServiceAccountCredentials.from_service_account_info(creds_dict, scopes=scopes)

def load_youtube_creds():
    """Load YouTube OAuth credentials from base64-encoded pickle"""
    try:
        # Decode base64 to bytes
        token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
        # Load pickle from bytes
        creds = pickle.loads(token_bytes)
        return creds
    except Exception as e:
        print(f"Error loading YouTube credentials: {e}")
        raise

# =============================================================================
# GOOGLE SHEETS FUNCTIONS
# =============================================================================

def get_sheet():
    """Connect to Google Sheet"""
    creds = load_service_account_creds()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet

def add_script_to_sheet(script_data):
    """Add generated script to Google Sheet"""
    sheet = get_sheet()
    row = [
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # Timestamp
        script_data['title'],
        script_data['script'],
        'PENDING_APPROVAL',  # Status
        '',  # Video URL (empty initially)
        ''   # Notes (empty initially)
    ]
    sheet.append_row(row)
    print(f"✅ Script added to sheet: {script_data['title']}")

def get_approved_scripts():
    """Get scripts with APPROVED status that haven't been processed yet"""
    sheet = get_sheet()
    all_records = sheet.get_all_records()
    
    # Filter for APPROVED scripts without video URLs (not yet processed)
    approved = []
    for idx, record in enumerate(all_records, start=2):  # start=2 because row 1 is header
        if record.get('Status') == 'APPROVED' and not record.get('Video URL'):
            record['_row_number'] = idx
            approved.append(record)
    
    return approved

def update_script_status(row_number, status, video_url='', notes=''):
    """Update script status in sheet"""
    sheet = get_sheet()
    sheet.update_cell(row_number, 4, status)  # Status column
    if video_url:
        sheet.update_cell(row_number, 5, video_url)  # Video URL column
    if notes:
        sheet.update_cell(row_number, 6, notes)  # Notes column

# =============================================================================
# GEMINI AI - SCRIPT GENERATION
# =============================================================================

def generate_jain_story_script():
    """Generate a Jain story script using Gemini AI"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = """
    Generate a short Jain story suitable for children aged 5-16 years.
    
    Requirements:
    - Story should be 20-25 seconds when read aloud (about 50-60 words)
    - Based on authentic Jain teachings, values, or historical events
    - Simple language appropriate for children
    - Positive moral lesson
    - Engaging and memorable
    
    Return ONLY a JSON object with this exact format:
    {
        "title": "Short catchy title (5-8 words)",
        "script": "The story script (50-60 words)"
    }
    
    Do not include any markdown, code blocks, or additional text.
    """
    
    response = model.generate_content(prompt)
    
    # Extract JSON from response
    response_text = response.text.strip()
    
    # Remove markdown code blocks if present
    if response_text.startswith('```'):
        response_text = response_text.split('```')[1]
        if response_text.startswith('json'):
            response_text = response_text[4:]
        response_text = response_text.strip()
    
    script_data = json.loads(response_text)
    print(f"✅ Generated script: {script_data['title']}")
    return script_data

# =============================================================================
# TEXT-TO-SPEECH
# =============================================================================

def create_voiceover(text, output_path='voiceover.mp3'):
    """Generate voiceover using Google Text-to-Speech"""
    # Load credentials for TTS
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    client = texttospeech.TextToSpeechClient.from_service_account_info(creds_dict)
    
    synthesis_input = texttospeech.SynthesisInput(text=text)
    
    voice = texttospeech.VoiceSelectionParams(
        language_code='en-US',
        name='en-US-Neural2-C',  # Child-friendly female voice
        ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
    )
    
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.95  # Slightly slower for children
    )
    
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    
    with open(output_path, 'wb') as out:
        out.write(response.audio_content)
    
    print(f"✅ Voiceover created: {output_path}")
    return output_path

# =============================================================================
# VIDEO CREATION
# =============================================================================

def create_background_image(title, width=1080, height=1920):
    """Create a simple background image with title"""
    # Create image with gradient background
    img = Image.new('RGB', (width, height), color='#2C3E50')
    draw = ImageDraw.Draw(img)
    
    # Try to use a nice font, fallback to default
    try:
        font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 80)
    except:
        font_title = ImageFont.load_default()
    
    # Draw title with text wrapping
    words = title.split()
    lines = []
    current_line = []
    
    for word in words:
        current_line.append(word)
        test_line = ' '.join(current_line)
        bbox = draw.textbbox((0, 0), test_line, font=font_title)
        if bbox[2] - bbox[0] > width - 100:
            current_line.pop()
            lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    # Draw title centered
    y_offset = (height - len(lines) * 100) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y_offset), line, fill='white', font=font_title)
        y_offset += 100
    
    img_path = 'background.png'
    img.save(img_path)
    print(f"✅ Background image created: {img_path}")
    return img_path

def create_video(title, audio_path, output_path='video.mp4'):
    """Create video from background image and audio"""
    # Create background
    bg_path = create_background_image(title)
    
    # Load audio to get duration
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    
    # Create video clip
    image_clip = ImageClip(bg_path).set_duration(duration)
    
    # Add audio
    video = image_clip.set_audio(audio_clip)
    
    # Export
    video.write_videofile(
        output_path,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        temp_audiofile='temp-audio.m4a',
        remove_temp=True
    )
    
    print(f"✅ Video created: {output_path}")
    return output_path

# =============================================================================
# GOOGLE DRIVE FUNCTIONS
# =============================================================================

def upload_to_drive(file_path, folder_id, filename):
    """Upload file to Google Drive"""
    token_bytes = base64.b64decode(DRIVE_TOKEN_B64)
creds = pickle.loads(token_bytes)
service = build('drive', 'v3', credentials=creds)
    
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    
    media = MediaFileUpload(file_path, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()
    
    print(f"✅ Uploaded to Drive: {file.get('webViewLink')}")
    return file.get('id'), file.get('webViewLink')

# =============================================================================
# YOUTUBE UPLOAD (Not used in GitHub Actions anymore - handled by Apps Script)
# =============================================================================

def upload_to_youtube(video_path, title, description):
    """Upload video to YouTube - This will be called by Apps Script, not GitHub Actions"""
    creds = load_youtube_creds()
    youtube = build('youtube', 'v3', credentials=creds)
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['Jain Stories', 'Children', 'Education', 'Moral Stories'],
            'categoryId': '27'  # Education category
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': True
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    response = request.execute()
    video_id = response['id']
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    print(f"✅ Uploaded to YouTube: {video_url}")
    return video_url

# =============================================================================
# MAIN WORKFLOW (GitHub Actions - Script Generation + Video Creation Only)
# =============================================================================

def main():
    """Main automation workflow - Runs daily at 9 AM"""
    print("=" * 60)
    print("JAIN STORIES AUTOMATION - STARTING")
    print("=" * 60)
    
    try:
        # STEP 1: Generate script
        print("\n[STEP 1] Generating Jain story script...")
        script_data = generate_jain_story_script()
        
        # STEP 2: Save to Google Sheet
        print("\n[STEP 2] Saving script to Google Sheet...")
        add_script_to_sheet(script_data)
        
        print("\n✅ Script generation complete!")
        print("👉 Please review the script in Google Sheet and mark it as APPROVED")
        
        # STEP 3: Check for approved scripts and create videos
        print("\n[STEP 3] Checking for approved scripts...")
        approved_scripts = get_approved_scripts()
        
        if not approved_scripts:
            print("No approved scripts found. Workflow complete.")
            return
        
        print(f"Found {len(approved_scripts)} approved script(s). Creating videos...")
        
        for script in approved_scripts:
            print(f"\n📝 Processing: {script['Title']}")
            
            # Create voiceover
            print("Creating voiceover...")
            audio_path = create_voiceover(script['Script'])
            
            # Create video
            print("Creating video...")
            video_filename = f"{script['Title'].replace(' ', '_')}_{int(time.time())}.mp4"
            video_path = create_video(script['Title'], audio_path, video_filename)
            
            # Upload to Drive (Pending folder)
            print("Uploading to Google Drive (Pending Upload folder)...")
            file_id, drive_url = upload_to_drive(
                video_path,
                PENDING_FOLDER_ID,
                video_filename
            )
            
            # Update sheet with Drive URL and status
            row_num = script['_row_number']
            update_script_status(
                row_num,
                status='VIDEO_CREATED',
                video_url=drive_url,
                notes='Video in Pending Upload folder. Move to Approved to publish.'
            )
            
            print(f"\n✅ Video ready for review: {drive_url}")
            print("👉 Watch the video in Google Drive 'Pending Upload' folder")
            print("👉 Move it to 'Approved' folder to auto-publish to YouTube")
        
        print("\n" + "=" * 60)
        print("AUTOMATION COMPLETE")
        print("=" * 60)
        print("\nNOTE: YouTube upload will happen automatically when you move")
        print("      videos from 'Pending Upload' to 'Approved' folder.")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
