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
APPROVED_FOLDER_ID = os.environ.get('APPROVED_FOLDER_ID')
PUBLISHED_FOLDER_ID = os.environ.get('PUBLISHED_FOLDER_ID')
REJECTED_FOLDER_ID = os.environ.get('REJECTED_FOLDER_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
CLIENT_SECRET_JSON = os.environ.get('CLIENT_SECRET')
TOKEN_PICKLE_B64 = os.environ.get('TOKEN_PICKLE')
DRIVE_TOKEN_B64 = os.environ.get('DRIVE_TOKEN')

def load_service_account_creds():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    return ServiceAccountCredentials.from_service_account_info(creds_dict, scopes=scopes)

def load_youtube_creds():
    try:
        token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
        creds = pickle.loads(token_bytes)
        return creds
    except Exception as e:
        print(f"Error loading YouTube credentials: {e}")
        raise

def get_sheet():
    creds = load_service_account_creds()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet

def add_script_to_sheet(script_data):
    sheet = get_sheet()
    row = [
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        script_data['title'],
        script_data['script'],
        'PENDING_APPROVAL',
        '',
        ''
    ]
    sheet.append_row(row)
    print(f"✅ Script added to sheet: {script_data['title']}")

def get_approved_scripts():
    sheet = get_sheet()
    all_records = sheet.get_all_records()
    approved = []
    for idx, record in enumerate(all_records, start=2):
        if record.get('Status') == 'APPROVED':
            record['_row_number'] = idx
            approved.append(record)
    return approved

def update_script_status(row_number, status, video_url='', notes=''):
    sheet = get_sheet()
    sheet.update_cell(row_number, 4, status)
    if video_url:
        sheet.update_cell(row_number, 5, video_url)
    if notes:
        sheet.update_cell(row_number, 6, notes)

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
    print(f"✅ Generated script: {script_data['title']}")
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
    print(f"✅ Voiceover created: {output_path}")
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
    print(f"✅ Background image created: {img_path}")
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
    print(f"✅ Video created: {output_path}")
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

def move_file_in_drive(file_url, from_folder_id, to_folder_id):
    """Move a file from one Drive folder to another"""
    try:
        token_bytes = base64.b64decode(DRIVE_TOKEN_B64)
        creds = pickle.loads(token_bytes)
        service = build('drive', 'v3', credentials=creds)
        if '/d/' in file_url:
            file_id = file_url.split('/d/')[1].split('/')[0]
        else:
            file_id = file_url.split('id=')[1].split('&')[0]
        service.files().update(
            fileId=file_id,
            addParents=to_folder_id,
            removeParents=from_folder_id,
            fields='id'
        ).execute()
        print(f"✅ File moved to Approved folder")
    except Exception as e:
        print(f"❌ Error moving file: {e}")

def main():
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

        # STEP 3: Check for approved scripts
        print("\n[STEP 3] Checking for approved scripts...")
        approved_scripts = get_approved_scripts()

        if not approved_scripts:
            print("No approved scripts found. Workflow complete.")
            return

        print(f"Found {len(approved_scripts)} approved script(s)...")

        for script in approved_scripts:
            print(f"\n📝 Processing: {script['Title']}")

            # If video already exists, just move it to Approved folder
            if script.get('Video URL'):
                print("Video already created. Moving to Approved folder...")
                move_file_in_drive(script['Video URL'], PENDING_FOLDER_ID, APPROVED_FOLDER_ID)
                continue

            # Otherwise create video
            print("Creating voiceover...")
            audio_path = create_voiceover(script['Script'])

            print("Creating video...")
            video_filename = f"{script['Title'].replace(' ', '_')}_{int(time.time())}.mp4"
            video_path = create_video(script['Title'], audio_path, video_filename)

            print("Uploading to Google Drive (Pending Upload folder)...")
            file_id, drive_url = upload_to_drive(
                video_path,
                PENDING_FOLDER_ID,
                video_filename
            )

            row_num = script['_row_number']
            update_script_status(
                row_num,
                status='VIDEO_CREATED',
                video_url=drive_url,
                notes='Video in Pending Upload folder. Move to Approved to publish.'
            )

            print(f"\n✅ Video ready for review: {drive_url}")

        print("\n" + "=" * 60)
        print("AUTOMATION COMPLETE")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
