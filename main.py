#!/usr/bin/env python3
"""
Jain Stories Automation - Main Script
Generates daily Jain stories, creates videos, and publishes to YouTube
"""

import os
import json
import pickle
import base64
import io
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2 import service_account
from google.cloud import texttospeech
import gspread
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mpy
import textwrap

# Scopes for Google APIs
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']
SCOPES_SHEETS = ['https://www.googleapis.com/auth/spreadsheets']

class JainStoriesAutomation:
    def __init__(self):
        self.service_creds = None
        self.youtube_creds = None
        self.drive_service = None
        self.sheets_service = None
        self.tts_client = None
        self.gemini_model = None
        self.sheet = None
        
    def setup_credentials(self):
        """Load credentials from environment variables"""
        print("[SETUP] Loading credentials from environment...")
        
        # Google Cloud Service Account (for Drive and Sheets)
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            self.service_creds = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=SCOPES_DRIVE + SCOPES_SHEETS
            )
            print("[✓] Service account credentials loaded")
        else:
            raise ValueError("GOOGLE_CREDENTIALS not found in environment")
        
        token_raw = os.environ.get('TOKEN_PICKLE') # Use TOKEN_PICKLE here
        if token_raw:
            try:
                # This .strip() is the "magic" that fixes the \x0a error
                token_bytes = token_raw.strip().encode('latin-1')
                self.youtube_creds = pickle.loads(token_bytes)
                print("[✓] YouTube credentials loaded")
            except Exception as e:
                print(f"[!] YouTube token error: {e}")
                self.youtube_creds = None

        
        # Gemini API Key
        gemini_key = os.environ.get('GEMINI_API_KEY')
        if gemini_key:
            genai.configure(api_key=gemini_key)
            self.gemini_model = genai.GenerativeModel('gemini-pro')
            print("[✓] Gemini API configured")
        else:
            raise ValueError("GEMINI_API_KEY not found in environment")
    
    def setup_services(self):
        """Initialize Google API services"""
        print("[SETUP] Initializing Google services...")
        
        # Drive service
        self.drive_service = build('drive', 'v3', credentials=self.service_creds)
        print("[✓] Drive service initialized")
        
        # Sheets service
        self.sheets_service = build('sheets', 'v4', credentials=self.service_creds)
        gspread_auth = gspread.service_account_from_dict(json.loads(os.environ.get('GOOGLE_CREDENTIALS')))
        
        sheet_id = os.environ.get('SHEET_ID')
        self.sheet = gspread_auth.open_by_key(sheet_id).sheet1
        print("[✓] Sheets service initialized")
        
        # Text-to-Speech client
        self.tts_client = texttospeech.TextToSpeechClient(credentials=self.service_creds)
        print("[✓] Text-to-Speech client initialized")
        
        # YouTube service (if credentials available)
        if self.youtube_creds:
            self.youtube_service = build('youtube', 'v3', credentials=self.youtube_creds)
            print("[✓] YouTube service initialized")
        else:
            self.youtube_service = None
            print("[!] YouTube service not available (will skip uploads)")
    
    def generate_script(self):
        """Generate a Jain story script using Gemini"""
        print("\n[GENERATE] Creating Jain story script...")
        
        prompt = """
        Create a short, engaging Jain story for children aged 5-16 years. 
        The story should:
        - Be 150-200 words long
        - Teach a moral lesson from Jain philosophy
        - Use simple, clear language
        - Be appropriate for YouTube Shorts (20-25 seconds when read aloud)
        - Focus on authentic Jain values like ahimsa (non-violence), truth, and compassion
        
        Format: Just the story text, no titles or explanations.
        """
        
        try:
            response = self.gemini_model.generate_content(prompt)
            script = response.text.strip()
            print(f"[✓] Script generated ({len(script)} characters)")
            return script
        except Exception as e:
            print(f"[!] Script generation failed: {e}")
            return None
    
    def create_video(self, script, video_path):
        """Create a video with voiceover and static background"""
        print(f"\n[VIDEO] Creating video: {video_path}...")
        
        try:
            # Generate audio using Text-to-Speech
            print("[VIDEO] Generating voiceover...")
            synthesis_input = texttospeech.SynthesisInput(text=script)
            voice = texttospeech.VoiceSelectionParams(
                language_code="en-IN",
                name="en-IN-Neural2-A"
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            response = self.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            audio_path = "/tmp/voiceover.mp3"
            with open(audio_path, 'wb') as out:
                out.write(response.audio_content)
            print("[✓] Voiceover generated")
            
            # Create background image
            print("[VIDEO] Creating background image...")
            img = Image.new('RGB', (1080, 1920), color=(25, 25, 112))  # Midnight blue
            draw = ImageDraw.Draw(img)
            
            # Add decorative elements
            draw.rectangle([20, 20, 1060, 1900], outline=(255, 215, 0), width=5)
            
            # Add text
            title = "Jain Story"
            wrapped_text = textwrap.fill(script, width=40)
            
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
                text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
            except:
                title_font = ImageFont.load_default()
                text_font = ImageFont.load_default()
            
            draw.text((540, 100), title, fill=(255, 215, 0), font=title_font, anchor="mm")
            draw.multiline_text((540, 600), wrapped_text, fill=(255, 255, 255), font=text_font, anchor="mm", align="center")
            
            image_path = "/tmp/background.png"
            img.save(image_path)
            print("[✓] Background image created")
            
            # Create video with audio
            print("[VIDEO] Combining audio and image...")
            audio = mpy.AudioFileClip(audio_path)
            image_clip = mpy.ImageClip(image_path)
            video = image_clip.set_duration(audio.duration).set_audio(audio)
            
            video.write_videofile(video_path, fps=24, verbose=False, logger=None)
            print(f"[✓] Video created: {video_path}")
            
            # Cleanup
            os.remove(audio_path)
            os.remove(image_path)
            
            return True
        except Exception as e:
            print(f"[!] Video creation failed: {e}")
            return False
    
    def save_to_sheet(self, script, video_link, status="PENDING_APPROVAL"):
        """Save script to Google Sheet"""
        print("\n[SHEET] Saving to Google Sheet...")
        
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.sheet.append_row([
                timestamp,
                script,
                status,
                video_link or "",
                ""
            ])
            print("[✓] Script saved to sheet")
            return True
        except Exception as e:
            print(f"[!] Sheet save failed: {e}")
            return False
    
    def upload_to_drive(self, video_path, folder_id):
        """Upload video to Google Drive"""
        print(f"\n[DRIVE] Uploading to Drive folder {folder_id}...")
        
        try:
            file_metadata = {
                'name': f"jain_story_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4",
                'parents': [folder_id]
            }
            
            media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            drive_link = file.get('webViewLink')
            print(f"[✓] Uploaded to Drive: {drive_link}")
            return drive_link
        except Exception as e:
            print(f"[!] Drive upload failed: {e}")
            return None
    
    def run_generate_script(self):
        """Run script generation workflow"""
        print("\n" + "="*50)
        print("JAIN STORIES AUTOMATION - SCRIPT GENERATION")
        print("="*50)
        
        try:
            self.setup_credentials()
            self.setup_services()
            
            # Generate script
            script = self.generate_script()
            if not script:
                print("[!] Failed to generate script")
                return
            
            # Save to sheet
            self.save_to_sheet(script, "", "PENDING_APPROVAL")
            
            print("\n[SUCCESS] Script generation complete!")
            print(f"Script: {script[:100]}...")
            
        except Exception as e:
            print(f"\n[ERROR] Workflow failed: {e}")
            import traceback
            traceback.print_exc()
    
    def run_create_video(self):
        """Run video creation workflow"""
        print("\n" + "="*50)
        print("JAIN STORIES AUTOMATION - VIDEO CREATION")
        print("="*50)
        
        try:
            self.setup_credentials()
            self.setup_services()
            
            # Get approved scripts from sheet
            rows = self.sheet.get_all_records()
            
            for i, row in enumerate(rows, start=2):  # Start from row 2 (skip header)
                if row.get('Status') == 'APPROVED':
                    script = row.get('Script')
                    video_path = f"/tmp/jain_story_{i}.mp4"
                    
                    # Create video
                    if self.create_video(script, video_path):
                        # Upload to Drive
                        pending_folder = os.environ.get('PENDING_FOLDER_ID')
                        drive_link = self.upload_to_drive(video_path, pending_folder)
                        
                        # Update sheet
                        self.sheet.update_cell(i, 4, drive_link or "")
                        self.sheet.update_cell(i, 3, "VIDEO_CREATED")
                        
                        os.remove(video_path)
            
            print("\n[SUCCESS] Video creation complete!")
            
        except Exception as e:
            print(f"\n[ERROR] Video workflow failed: {e}")
            import traceback
            traceback.print_exc()
    
    def run_upload_youtube(self):
        """Run YouTube upload workflow"""
        print("\n" + "="*50)
        print("JAIN STORIES AUTOMATION - YOUTUBE UPLOAD")
        print("="*50)
        
        if not self.youtube_service:
            print("[!] YouTube service not available, skipping upload")
            return
        
        try:
            self.setup_credentials()
            self.setup_services()
            
            # Get videos from Approved folder and upload to YouTube
            # This would be implemented based on your specific workflow
            
            print("\n[SUCCESS] YouTube upload complete!")
            
        except Exception as e:
            print(f"\n[ERROR] YouTube upload failed: {e}")


if __name__ == "__main__":
    import sys
    
    bot = JainStoriesAutomation()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--generate-script":
            bot.run_generate_script()
        elif sys.argv[1] == "--create-video":
            bot.run_create_video()
        elif sys.argv[1] == "--upload-youtube":
            bot.run_upload_youtube()
    else:
        # Default: run script generation
        bot.run_generate_script()
