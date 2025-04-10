import os
import sys
import time
import json
import uuid
import logging
import requests
import platform
import subprocess
from datetime import datetime, timezone
from threading import Event
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from .utils import create_tar_archive, audio_file_path
from .random_mouse import random_mouse_movements

from monitoring import init_highlight, _send_failure_notification
from config import Settings


class JoinGoogleMeet:
    def __init__(self, meetlink, start_time_utc, end_time_utc, min_record_time=3600, bot_name="Google Bot", presigned_url_combined=None, presigned_url_audio=None, max_waiting_time=1800, project_settings:Settings=None, logger:logging=None):
        self.meetlink = meetlink
        self.start_time_utc = start_time_utc
        self.end_time_utc = end_time_utc
        self.min_record_time = min_record_time
        self.bot_name = bot_name
        self.browser = None
        self.recording_started = False
        self.recording_start_time = None
        self.stop_event = Event()
        self.recording_process = None
        self.presigned_url_combined = presigned_url_combined
        self.presigned_url_audio = presigned_url_audio
        self.id = str(uuid.uuid4())
        self.output_file = f"out/{self.id}"
        self.event_start_time = None
        self.need_retry = False
        self.thread_start_time = None
        self.max_waiting_time = max_waiting_time
        self.session_ended = False
        self.project_settings = project_settings
        self.logger = logger
        self.highlight = init_highlight(self.project_settings.HIGHLIGHT_PROJECT_ID, self.project_settings.ENVIRONMENT_NAME, "google-meet-bot")

    def setup_browser(self):
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--start-maximized')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-infobars')
        options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36')
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-application-cache")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument(f"user-data-dir=CueMeet{self.id}")

        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--use-fake-device-for-media-stream")

        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 0,
            "profile.default_content_setting_values.geolocation": 0,
            "profile.default_content_setting_values.notifications": 0
        })

        # Load the extensions
        options.add_argument('--load-extension=transcript_extension')
        options.add_experimental_option("prefs", {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        })

        browser_service = Service(ChromeDriverManager().install())

        try:
            self.browser = webdriver.Chrome(
                service=browser_service,
                options=options
            )
            self.logger.info("Headless browser launched successfully")
        except Exception as e:
            self.logger.error(f"Failed to launch the browser: {e}")
            self.end_session()


    def navigate_to_meeting(self):
        self.logger.info(f"Navigating to Google Meet link: {self.meetlink}")
        try:
            self.browser.get(self.meetlink)
            self.logger.info("Successfully navigated to the Google Meet link.")
        except Exception as e:
            self.logger.error(f"Failed to navigate to the meeting link: {e}")
            self.end_session()
        
        random_mouse_movements(self, duration_seconds=10)

        try:
            modals = self.browser.find_elements(By.XPATH, '//button[@jsname="IbE0S"]')
            if modals:
                modals[0].click()
                self.logger.info("Closed the initial modal dialog successfully.")
            else:
                self.logger.info("No modal dialog found to close.")
        except Exception as e:
            self.logger.error(f"Failed to navigate to or interact with the meeting link: {e}")


    def join_meeting(self):
        self.logger.info("Attempting to disable microphone and camera.")
        time.sleep(2)
        try:
            # Click the microphone button
            mic_button = WebDriverWait(self.browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//div[@aria-label="Turn off microphone"][contains(@class, "U26fgb")]'))
            )
            mic_button.click()
            self.logger.info("Microphone disabled successfully.")

            # Click the camera button
            camera_button = WebDriverWait(self.browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//div[@aria-label="Turn off camera"][contains(@class, "U26fgb")]'))
            )
            camera_button.click()
            self.logger.info("Camera disabled successfully.")
        except Exception as e:
            self.logger.error(f"Failed to disable microphone and camera: {e}")
        time.sleep(2)
        try: 
            name_input = WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Your name']"))
            )
            name_input.send_keys(self.bot_name)
            self.logger.info(f"Entered the bot name: {self.bot_name}")
        except Exception as e:
            self.logger.error("Failed to enter the bot's name: {e}")
        try:
            join_button = WebDriverWait(self.browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//span[contains(text(), "Ask to join")]'))
            )
            join_button.click()
            self.logger.info("Clicked the 'Ask to join' button successfully.")
        except Exception as e:
            self.logger.error("Failed to click 'Ask to join' button: {e}")
        time.sleep(4)


    def check_meeting_removal(self):        
        try:
            removed_text = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'been removed from the meeting')]"))
            )
            if removed_text:
                self.logger.info("Detected removal from meeting.")
                self.end_session()
        except TimeoutException:
            pass


    def check_meeting_end(self): 
        try:
            return_button = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'Return to home screen')]"))
            )
            if return_button:
                self.logger.info("Detected 'Return to home screen' button. Meeting has ended.")
                if self.recording_started:
                    self.end_session()
                else:
                    self.need_retry = True
        except TimeoutException:
            pass
        try:
            ended_message = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'The call ended because everyone left')]"))
            )
            if ended_message:
                self.logger.info("Detected 'The call ended because everyone left' button. Meeting has ended.")
                self.end_session()
        except TimeoutException:
            pass


    def handle_waiting_modal(self):
        try:
            modal_text = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Are you still there?')]"))
            )
            if modal_text:
                self.logger.info("Detected 'Are you still there?' modal.")
                keep_waiting_button = self.browser.find_element(By.XPATH, "//button[.//span[contains(text(), 'Keep waiting')]]")
                keep_waiting_button.click()
                self.logger.info("Clicked on 'Keep waiting' to continue the meeting.")
        except TimeoutException:
            pass
        except Exception as e:
            self.logger.error(f"Failed to handle the waiting modal: {e}")


    def check_join_page(self):
        # Checking for the waiting modal
        self.handle_waiting_modal()

        for classname in ['Jyj1Td', 'dHFSie']:
            try:
                text = self.browser.find_element(By.XPATH, f'//*[contains(@class, "{classname}")]').text.strip()
                if text:
                    self.logger.info(f"Current join page status: {text}")
                return text
            except:
                pass
        return ''


    def check_admission(self):
        try:
            # Check if admitted to the meeting
            admitted = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.XPATH, '//div[contains(@class, "u6vdEc")]'))
            )
            if admitted and not self.recording_started:
                self.logger.info("Admitted to the meeting. Starting recording...")
                self.start_recording()
                self.recording_started = True
        except TimeoutException:
            pass
        try:
            # Check if join request was denied
            denied_message = WebDriverWait(self.browser, 5).until(
                EC.any_of(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(text(), \"You can't join this call\")]")),
                    EC.presence_of_element_located((By.XPATH, "//div[contains(text(), \"You can't join this video call\")]"))
                )
            )
            if denied_message:
                is_timeout = WebDriverWait(self.browser, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(text(), \"No one responded to your request to join the call\")]"))
                )
                if is_timeout:
                    self.logger.error("Join request was denied 'No one responded'. Retrying the session...")
                    self.need_retry = True
                else: 
                    self.logger.error("Join request was denied 'User initialed'. Ending session...")
                    self.end_session()
        except TimeoutException:
            pass
        try:
            # Check for any error messages
            error_message = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.XPATH, '//div[contains(text(), "Denied your request to join")]'))
            )
            if error_message:
                self.logger.error("Join request was denied 'User initialed'. Ending session...")
                self.need_retry = True
        except TimeoutException:
            pass


    def attendee_count(self):
        time.sleep(2)
        count = -1
        try: 
            element = WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.XPATH, '//div[@class="gFyGKf BN1Lfc"]//div[@class="uGOf1d"]'))
            )
            count_text = element.get_attribute('textContent').strip()
            if count_text.isdigit():
                count = int(count_text)
        except TimeoutException:
            self.logger.error("Attendee count not found.")
        except NoSuchElementException:
            self.logger.info("Member count element not found. Likely the count is 0.")
        return count


    def start_recording(self):
        self.logger.info("Starting meeting audio recording with FFmpeg...")
        output_audio_file = f'{self.output_file}.opus'
        
        if platform.system() == 'Darwin':
            command = [
                "ffmpeg",
                "-f", "avfoundation",
                "-i", ":0",
                "-acodec", "libopus",
                "-b:a", "128k",
                "-ac", "1",  
                "-ar", "48000",
                output_audio_file
            ]
        elif platform.system() == 'Linux':  
            command = [
                "ffmpeg",
                "-f", "pulse",
                "-i", "virtual-sink.monitor",
                "-af", "aresample=async=1000",  # Help with audio synchronization
                "-acodec", "libopus",
                "-application", "audio",  # Optimize for audio quality
                "-b:a", "256k",  # Higher bitrate for better quality
                "-vbr", "on",  # Variable bitrate for better quality/size balance
                "-frame_duration", "60",  # Longer frames for more stable encoding
                "-ac", "1",
                "-ar", "48000",
                output_audio_file
            ]
        else:
            self.logger.error("Unsupported operating system for recording.")
            self.end_session()
        try:
            self.logger.info(f"Executing FFmpeg command: {' '.join(command)}")
            
            self.event_start_time = datetime.now(timezone.utc)
            self.recording_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.recording_started = True
            self.recording_start_time = time.perf_counter() 
            self.logger.info(f"Recording started. Output will be saved to {output_audio_file}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error starting FFmpeg: {e}")
            self.logger.error(f"FFmpeg output: {e.output}")


    def stop_recording(self):
        if self.recording_started and self.recording_process:
            self.logger.info("Stopping audio recording...")
            self.recording_process.terminate()
            try:
                self.recording_process.wait()
                self.logger.info("Recording stopped.")
            except subprocess.TimeoutExpired:
                self.logger.warning("Recording process did not terminate in time. Forcibly killing it.")
                self.recording_process.kill()
                self.logger.info("Recording process killed.")
        else:
            self.logger.info("No recording was started, nothing to stop.")


    def save_transcript(self):
        if not self.browser:
            self.logger.error("Browser is not available. Cannot save transcript.")
            return

        try:
            transcript_data = self.browser.execute_script("return localStorage.getItem('transcript');")
            chat_messages_data = self.browser.execute_script("return localStorage.getItem('chatMessages');")
            meeting_title = self.browser.execute_script("return localStorage.getItem('meetingTitle');")

            transcript = json.loads(transcript_data) if transcript_data else None
            chat_messages = json.loads(chat_messages_data) if chat_messages_data else None

            # Create a dictionary to hold all the data
            transcript_json = {
                'title': meeting_title if meeting_title else None,
                'meeting_start_time': self.event_start_time.isoformat() if self.event_start_time else None,
                'meeting_end_time': datetime.now(timezone.utc).isoformat(),
                'transcript': transcript,
                'chat_messages': chat_messages,
            }

            # Write the dictionary to a JSON file
            full_path = os.path.join(os.getcwd(), f"{self.output_file}.json")
            with open(full_path, 'w', encoding='utf-8') as file:
                json.dump(transcript_json, file, ensure_ascii=False, indent=2)
            self.logger.info(f"Transcript saved to {self.output_file}.json")
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON format in localStorage: {e}")
        except Exception as e:
            self.logger.error(f"Error downloading transcript: {e}")


    def upload_files(self):
        try: 
            if self.presigned_url_combined:
                full_path = create_tar_archive(f"{self.output_file}.json", f"{self.output_file}.opus", self.output_file)
                if full_path and os.path.exists(full_path):
                    self.logger.info(f"Attempting to upload the Tar file from path: {full_path}")
                    try:
                        self.logger.info(f"Uploading {f'{self.output_file}.tar'} to pre-signed URL...")
                        with open(full_path, 'rb') as file:
                            response = requests.put(self.presigned_url_combined, data=file, headers={'Content-Type': 'application/x-tar'})
                            response.raise_for_status()
                        self.logger.info("Tar file uploaded successfully.")
                    except Exception as e:
                        self.logger.error(f"Error uploading the Tar file: {e}")
                else:
                    self.logger.error(f"Tar file does not exist at: {full_path}")
            else:
                self.logger.info("No pre-signed Tar URL provided or no Tar file to upload.")
            
            if self.presigned_url_audio:
                full_path = audio_file_path(f"{self.output_file}.opus")
                if full_path and os.path.exists(full_path):
                    self.logger.info(f"Attempting to upload the Audio file from path: {full_path}")
                    try:
                        self.logger.info(f"Uploading {f'{self.output_file}.opus'} to pre-signed URL...")
                        with open(full_path, 'rb') as file:
                            response = requests.put(self.presigned_url_audio, data=file, headers={'Content-Type': 'audio/opus'})
                            response.raise_for_status()
                        self.logger.info("Audio file uploaded successfully.")
                    except Exception as e:
                        self.logger.error(f"Error uploading the Audio file: {e}")
                else:
                    self.logger.error(f"Audio file does not exist at: {full_path}")
            else:
                self.logger.info("No pre-signed Audio URL provided or no Audio file to upload.")
        except Exception as e:
            self.logger.error(f"Error during file upload: {e}")


    def end_session(self):
        if self.session_ended:
            self.logger.info("Session has already been ended. Skipping end_session method call.")
            return
        
        self.session_ended = True
        self.logger.info("Ending the session...")
        try:
            time.sleep(10)

            if self.browser and self.recording_started:
                self.logger.info("Initiating transcript save...")
                try:
                    self.save_transcript()
                    self.logger.info("Transcript is saved.")
                except Exception as e:
                    self.logger.error(f"Failed to save transcript: {e}")
                
            time.sleep(20)
            
            if self.browser:
                try:
                    self.browser.quit()
                    self.logger.info("Browser closed.")
                except Exception as e:
                    self.logger.error(f"Failed to close browser: {e}")
                
            self.stop_event.set()
            if self.recording_started:
                self.stop_recording()
                self.upload_files()
            else:
                self.logger.info("No recording was started during this session.")
        except Exception as e:
            self.logger.error("Error during session cleanup %s", str(e), exc_info=True)
        finally:
            self.logger.info("Session ended successfully.")
            sys.exit(0)


    def monitor_meeting(self, initial_elapsed_time=0):
        self.logger.info("Started monitoring the meeting.")
        start_time = time.perf_counter() - initial_elapsed_time

        low_member_count_end_time = None

        while not self.stop_event.is_set():
            current_time = time.perf_counter()
            elapsed_time = current_time - start_time
            # Before being admitted, check if max_waiting_time has been exceeded
            if not self.recording_started:
                if elapsed_time > self.max_waiting_time:
                    self.logger.info(f"Maximum waiting time ({self.max_waiting_time} seconds) exceeded. Ending session.")
                    break
            else: 
                recording_elapsed_time = current_time - self.recording_start_time
                if recording_elapsed_time > self.min_record_time:
                    self.logger.info(f"Minimum recording time ({self.min_record_time} seconds) reached. Ending session.")
                    break
            if self.need_retry:
                self.logger.info("Need to retry joining the meeting. Exiting monitoring loop.")
                break

            try:
                self.check_meeting_end()
                self.check_meeting_removal()
                self.check_admission()

                if self.check_join_page() not in ["Ready to join", "Asking to be let in...", "You can't join this call"]:
                    # We are in the meeting
                    members = self.attendee_count()
                    if members > 1:
                        # Other participants are present; reset the low member count timer
                        if low_member_count_end_time is not None:
                            self.logger.info("Member count increased. Cancelling 5-minute timer.")
                            low_member_count_end_time = None
                    else:
                        # Only the bot is in the meeting
                        if low_member_count_end_time is None:
                            low_member_count_end_time = current_time + 300  # 5 minutes
                            self.logger.info("Member count is 1 or less. Starting 5-minute timer.")
                        else:
                            time_left = int((low_member_count_end_time - current_time) / 60)
                            if time_left <= 0:
                                self.logger.info("Member count has been 1 or less for 5 minutes. Ending session.")
                                break
                            else:
                                self.logger.info(f"Member count still low. {time_left} minutes left before ending session.")
                else:
                    # Waiting to be admitted to the meeting
                    self.logger.info("Waiting to be admitted to the meeting.")
            except WebDriverException:
                self.logger.error("Browser has been closed. Stopping monitoring.")
                break
            except Exception as e:
                self.logger.error(f"Error during monitoring: {e}")
            time.sleep(2)


    def retry_join(self):
        self.logger.info("Retrying to join the meeting...")
        time.sleep(12)
        try:
            self.browser.refresh()
            self.navigate_to_meeting()
            self.join_meeting()
        except Exception as e:
            self.logger.error("Error during retry join: %s", str(e), exc_info=True)
            self.end_session()


    def run(self):
        try:
            self.logger.info("Meeting bot execution started.")
            self.setup_browser()
            self.navigate_to_meeting()
            self.join_meeting()

            self.thread_start_time = time.perf_counter()
            total_elapsed_time = 0

            self.stop_event.clear()
            self.need_retry = False

            while True:
                self.monitor_meeting(initial_elapsed_time=total_elapsed_time)
                total_elapsed_time = time.perf_counter() - self.thread_start_time

                if self.need_retry:
                    self.logger.info("Retry flag is set. Proceeding to retry joining the meeting.")
                    self.need_retry = False
                    self.retry_join()
                else:
                    self.logger.info("Monitoring completed without retry. Exiting.")
                    break

        except Exception as e:
            self.logger.error("An error occurred during the meeting session. %s", str(e), exc_info=True)
            if self.project_settings.DEBUG is False:
                _send_failure_notification(self.highlight, str(e), {
                    "meetlink": self.meetlink,
                    "start_time_utc": self.start_time_utc,
                    "recording_start_time": self.recording_start_time,
                })
        finally:
            self.logger.info("Finalizing the meeting session.")
            self.end_session()
        self.logger.info("Meeting bot has successfully completed its run.")