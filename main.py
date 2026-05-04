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

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
SHEET_ID = os.environ.get('SHEET_ID')
PENDING_FOLDER_ID = os.environ.get('PENDING_FOLDER_ID')
PUBLISHED_FOLDER_ID = os.environ.get('PUBLISHED_FOLDER_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
DRIVE_TOKEN_B64 = os.environ.get('DRIVE_TOKEN')

def load_service_account_creds():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    return ServiceAccountCredentials.from_service_account_info(creds_dict, scopes=scopes)

def get_sheet():
    creds = load_service_account_creds()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet

def add_to_sheet(script_data, video_url):
    sheet = get_sheet()
    row = [
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        script_data['title'],
        script_data['script'],
        'PENDING_APPROVAL',
        video_url,
        ''
    ]
    sheet.append_row(row)
    print(f"✅ Added to sheet: {script_data['title']}")

def generate_jain_story_script():
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
    response_text = response.text.strip()
    if response_text.startswith('```'):
        response_text = response_text.split('```')[1]
        if response_text.startswith('json'):
            response_text = response_text[4:]
        response_text = response_text.strip()
    script_data = json.loads(response_text)
    print(f"✅ Generated story: {script_data['title']}")
    return script_data

def create_voiceover(text, output_path='voiceover.mp3'):
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    client = texttospeech.TextToSpeechClient.from_service_account_info(creds_dict)
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code='en-US',
        name='en-US-Neural2-C',
        ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.95
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    with open(output_path, 'wb') as out:
        out.write(response.audio_content)
    print(f"✅ Voiceover created")
    return output_path

def create_background_image(title, width=1080, height=1920):
    img = Image.new('RGB', (width, height), color='#2C3E50')
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 80)
    except:
        font_title = ImageFont.load_default()
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
    y_offset = (height - len(lines) * 100) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y_offset), line, fill='white', font=font_title)
        y_offset += 100
    img_path = 'background.png'
    img.save(img_path)
    print(f"✅ Background image created")
    return img_path

def create_video(title, audio_path, output_path='video.mp4'):
    bg_path = create_background_image(title)
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    image_clip = ImageClip(bg_path).set_duration(duration)
    video = image_clip.set_audio(audio_clip)
    video.write_videofile(
        output_path,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        temp_audiofile='temp-audio.m4a',
        remove_temp=True
    )
    print(f"✅ Video created")
    return output_path

def upload_to_drive(file_path, folder_id, filename):
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

def main():
    print("=" * 60)
    print("JAIN STORIES AUTOMATION - STARTING")
    print("=" * 60)

    try:
        # STEP 1: Generate story
        print("\n[STEP 1] Generating Jain story...")
        script_data = generate_jain_story_script()

        # STEP 2: Create voiceover
        print("\n[STEP 2] Creating voiceover...")
        audio_path = create_voiceover(script_data['script'])

        # STEP 3: Create video
        print("\n[STEP 3] Creating video...")
        video_filename = f"{script_data['title'].replace(' ', '_')}_{int(time.time())}.mp4"
        video_path = create_video(script_data['title'], audio_path, video_filename)

        # STEP 4: Upload to Drive (Pending Upload folder)
        print("\n[STEP 4] Uploading to Google Drive...")
        file_id, drive_url = upload_to_drive(video_path, PENDING_FOLDER_ID, video_filename)

        # STEP 5: Log to Google Sheet with PENDING_APPROVAL
        print("\n[STEP 5] Logging to Google Sheet...")
        add_to_sheet(script_data, drive_url)

        print("\n" + "=" * 60)
        print("✅ DONE — Video is in Pending Upload folder")
        print("👉 Watch the video, then change sheet status to APPROVED")
        print("👉 Apps Script will upload to YouTube automatically")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
