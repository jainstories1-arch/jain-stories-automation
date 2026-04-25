"""
Jain Stories Automation - Main Script
Generates daily Jain story content for children and automates YouTube publishing
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
import argparse

# Google APIs
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.cloud import texttospeech
import google.generativeai as genai

# Image and video processing
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip

# Utilities
import gspread
import pickle
import requests
from io import BytesIO

# Configuration
SCOPES_YOUTUBE = ['https://www.googleapis.com/auth/youtube.upload']
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']
SCOPES_SHEETS = ['https://www.googleapis.com/auth/spreadsheets']

class JainStoriesAutomation:
    def __init__(self):
        self.setup_credentials()
        self.setup_services()
        
    def setup_credentials(self):
        """Initialize all API credentials"""
        # Service account for Drive and Sheets
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            self.service_creds = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=SCOPES_DRIVE + SCOPES_SHEETS
            )
        
        # YouTube OAuth
        self.youtube_creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                self.youtube_creds = pickle.load(token)
        
        # Gemini API
        gemini_key = os.environ.get('GEMINI_API_KEY')
        if gemini_key:
            genai.configure(api_key=gemini_key)
        
    def setup_services(self):
        """Initialize Google API services"""
        self.drive_service = build('drive', 'v3', credentials=self.service_creds)
        self.sheets_client = gspread.authorize(self.service_creds)
        
        if self.youtube_creds:
            self.youtube_service = build('youtube', 'v3', credentials=self.youtube_creds)
        
        self.tts_client = texttospeech.TextToSpeechClient(credentials=self.service_creds)
        self.gemini_model = genai.GenerativeModel('gemini-pro')
    
    def generate_script(self):
        """Generate a Jain story script using Gemini AI"""
        prompt = """
        Create a short Jain story suitable for children aged 5-16 years.
        The story should:
        - Be based on authentic Jain teachings, Aagam texts, or historical Jain figures
        - Have a clear moral lesson about non-violence, truth, or compassion
        - Be 150-200 words (suitable for 20-25 second video)
        - Use simple, engaging language
        - Include a title and specify recommended age group (5-8, 9-12, or 13-16)
        
        Format your response as JSON:
        {
            "title": "Story Title",
            "script": "The full story text...",
            "moral": "The key lesson",
            "age_group": "9-12"
        }
        
        Generate a new unique story now.
        """
        
        try:
            response = self.gemini_model.generate_content(prompt)
            text = response.text.strip()
            
            # Extract JSON from response
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0].strip()
            elif '```' in text:
                text = text.split('```')[1].split('```')[0].strip()
            
            story_data = json.loads(text)
            return story_data
        except Exception as e:
            print(f"Error generating script: {e}")
            return None
    
    def save_to_sheet(self, story_data):
        """Save generated script to Google Sheets"""
        sheet_id = os.environ.get('SHEET_ID')
        sheet = self.sheets_client.open_by_key(sheet_id).sheet1
        
        today = datetime.now().strftime('%Y-%m-%d')
        row = [
            today,
            story_data['title'],
            story_data['script'],
            story_data['age_group'],
            'PENDING',
            '',  # Video link
            ''   # YouTube link
        ]
        
        sheet.append_row(row)
        print(f"Script saved to sheet: {story_data['title']}")
    
    def check_approved_scripts(self):
        """Check for approved scripts ready for video creation"""
        sheet_id = os.environ.get('SHEET_ID')
        sheet = self.sheets_client.open_by_key(sheet_id).sheet1
        
        all_rows = sheet.get_all_values()
        approved_scripts = []
        
        for idx, row in enumerate(all_rows[1:], start=2):  # Skip header
            if len(row) >= 5 and row[4] == 'APPROVED' and (len(row) < 6 or not row[5]):
                approved_scripts.append({
                    'row_index': idx,
                    'date': row[0],
                    'title': row[1],
                    'script': row[2],
                    'age_group': row[3]
                })
        
        return approved_scripts
    
    def generate_voiceover(self, text, output_file):
        """Generate audio from text using Google Text-to-Speech"""
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code='en-US',
            name='en-US-Neural2-C',  # Child-friendly voice
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.9  # Slightly slower for kids
        )
        
        response = self.tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        with open(output_file, 'wb') as out:
            out.write(response.audio_content)
        
        print(f"Voiceover created: {output_file}")
    
    def create_background_image(self, title, output_file, width=1080, height=1920):
        """Create a simple background image with title overlay"""
        # Create gradient background (saffron to white - Jain colors)
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        
        # Gradient from saffron to white
        for y in range(height):
            r = int(255 - (255 - 255) * (y / height))
            g = int(140 + (255 - 140) * (y / height))
            b = int(0 + (255 - 0) * (y / height))
            draw.rectangle([(0, y), (width, y+1)], fill=(r, g, b))
        
        # Add title text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
        except:
            font = ImageFont.load_default()
        
        # Add semi-transparent overlay for text readability
        overlay = Image.new('RGBA', (width, 400), (255, 255, 255, 180))
        img.paste(overlay, (0, height//2 - 200), overlay)
        
        # Draw title
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), title, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Center text
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # Add text shadow
        draw.text((x+3, y+3), title, font=font, fill=(0, 0, 0, 128))
        draw.text((x, y), title, font=font, fill=(139, 69, 19))  # Brown text
        
        # Add Jain symbol (Om or Swastika) - simple version
        draw.text((width//2 - 50, 100), "ૐ", font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 100), fill=(255, 140, 0))
        
        img.save(output_file)
        print(f"Background image created: {output_file}")
    
    def create_video(self, title, script, output_file):
        """Combine image and audio into video"""
        temp_dir = Path('/tmp/jain_videos')
        temp_dir.mkdir(exist_ok=True)
        
        image_file = temp_dir / f"{title[:30]}_bg.png"
        audio_file = temp_dir / f"{title[:30]}_audio.mp3"
        
        # Generate components
        self.create_background_image(title, str(image_file))
        self.generate_voiceover(script, str(audio_file))
        
        # Create video
        audio = AudioFileClip(str(audio_file))
        duration = audio.duration
        
        image_clip = ImageClip(str(image_file), duration=duration)
        
        # Combine
        video = image_clip.set_audio(audio)
        video.write_videofile(
            output_file,
            fps=24,
            codec='libx264',
            audio_codec='aac',
            temp_audiofile=str(temp_dir / 'temp-audio.m4a'),
            remove_temp=True
        )
        
        # Cleanup
        image_file.unlink()
        audio_file.unlink()
        
        print(f"Video created: {output_file}")
    
    def upload_to_drive(self, file_path, folder_id):
        """Upload video to Google Drive"""
        file_metadata = {
            'name': Path(file_path).name,
            'parents': [folder_id]
        }
        
        media = MediaFileUpload(file_path, mimetype='video/mp4')
        
        file = self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        print(f"Uploaded to Drive: {file.get('webViewLink')}")
        return file.get('webViewLink')
    
    def check_approved_videos(self):
        """Check for videos moved to Approved folder"""
        approved_folder_id = os.environ.get('APPROVED_FOLDER_ID')
        
        results = self.drive_service.files().list(
            q=f"'{approved_folder_id}' in parents and mimeType='video/mp4'",
            fields='files(id, name, webViewLink)'
        ).execute()
        
        return results.get('files', [])
    
    def upload_to_youtube(self, video_path, title, description):
        """Upload video to YouTube as a Short"""
        body = {
            'snippet': {
                'title': title[:100],  # YouTube title limit
                'description': description,
                'tags': ['Jainism', 'Kids Stories', 'Moral Stories', 'Jain Values', 'Children Education'],
                'categoryId': '27'  # Education category
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': True
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
        
        request = self.youtube_service.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        
        response = request.execute()
        video_id = response['id']
        youtube_url = f"https://www.youtube.com/shorts/{video_id}"
        
        print(f"Uploaded to YouTube: {youtube_url}")
        return youtube_url
    
    def move_drive_file(self, file_id, new_folder_id):
        """Move file to different folder in Drive"""
        file = self.drive_service.files().get(fileId=file_id, fields='parents').execute()
        previous_parents = ','.join(file.get('parents', []))
        
        self.drive_service.files().update(
            fileId=file_id,
            addParents=new_folder_id,
            removeParents=previous_parents,
            fields='id, parents'
        ).execute()
    
    def update_sheet_status(self, row_index, video_link, youtube_link):
        """Update Google Sheet with video and YouTube links"""
        sheet_id = os.environ.get('SHEET_ID')
        sheet = self.sheets_client.open_by_key(sheet_id).sheet1
        
        sheet.update_cell(row_index, 6, video_link)  # Column F
        sheet.update_cell(row_index, 7, youtube_link)  # Column G
        sheet.update_cell(row_index, 5, 'PUBLISHED')  # Column E
    
    def run_daily_generation(self):
        """Main workflow: Generate and save daily script"""
        print("Starting daily script generation...")
        story_data = self.generate_script()
        
        if story_data:
            self.save_to_sheet(story_data)
            print("Daily script generation complete!")
        else:
            print("Failed to generate script.")
    
    def run_video_creation(self):
        """Create videos for approved scripts"""
        print("Checking for approved scripts...")
        approved = self.check_approved_scripts()
        
        pending_folder_id = os.environ.get('PENDING_FOLDER_ID')
        
        for script in approved:
            print(f"Creating video for: {script['title']}")
            
            video_file = f"/tmp/{script['date']}_{script['title'][:30]}.mp4"
            self.create_video(script['title'], script['script'], video_file)
            
            # Upload to Drive
            drive_link = self.upload_to_drive(video_file, pending_folder_id)
            
            # Update sheet
            self.update_sheet_status(script['row_index'], drive_link, '')
            
            # Cleanup
            Path(video_file).unlink()
    
    def run_youtube_upload(self):
        """Upload approved videos to YouTube"""
        print("Checking for approved videos...")
        videos = self.check_approved_videos()
        
        sheet_id = os.environ.get('SHEET_ID')
        sheet = self.sheets_client.open_by_key(sheet_id).sheet1
        published_folder_id = os.environ.get('PUBLISHED_FOLDER_ID')
        
        for video in videos:
            # Find corresponding sheet row
            all_rows = sheet.get_all_values()
            for idx, row in enumerate(all_rows[1:], start=2):
                if len(row) >= 6 and row[5] == video['webViewLink']:
                    title = row[1]
                    script = row[2]
                    
                    # Download video temporarily
                    temp_video = f"/tmp/{video['name']}"
                    request = self.drive_service.files().get_media(fileId=video['id'])
                    with open(temp_video, 'wb') as f:
                        f.write(request.execute())
                    
                    # Upload to YouTube
                    description = f"{script}\n\n#Jainism #MoralStories #KidsEducation"
                    youtube_url = self.upload_to_youtube(temp_video, title, description)
                    
                    # Update sheet
                    self.update_sheet_status(idx, row[5], youtube_url)
                    
                    # Move to Published folder
                    self.move_drive_file(video['id'], published_folder_id)
                    
                    # Cleanup
                    Path(temp_video).unlink()
                    break

def authorize_youtube():
    """One-time YouTube authorization"""
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_secret = os.environ.get('CLIENT_SECRET')
            if client_secret:
                client_config = json.loads(client_secret)
                flow = InstalledAppFlow.from_client_config(
                    client_config,
                    SCOPES_YOUTUBE
                )
                creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'client_secret.json',
                    SCOPES_YOUTUBE
                )
                creds = flow.run_local_server(port=0)
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    print("YouTube authorization successful!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-youtube', action='store_true', help='Authorize YouTube access')
    parser.add_argument('--generate-script', action='store_true', help='Generate daily script')
    parser.add_argument('--create-videos', action='store_true', help='Create videos from approved scripts')
    parser.add_argument('--upload-youtube', action='store_true', help='Upload approved videos to YouTube')
    
    args = parser.parse_args()
    
    if args.authorize_youtube:
        authorize_youtube()
    else:
        bot = JainStoriesAutomation()
        
        if args.generate_script:
            bot.run_daily_generation()
        elif args.create_videos:
            bot.run_video_creation()
        elif args.upload_youtube:
            bot.run_youtube_upload()
        else:
            # Default: run all workflows
            bot.run_daily_generation()
            bot.run_video_creation()
            bot.run_youtube_upload()
