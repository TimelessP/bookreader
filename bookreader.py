import contextlib
with contextlib.redirect_stdout(None):
    import pygame
    pygame.mixer.init()

import json
import os
import threading
import time
import tkinter as tk
import wave
from pathlib import Path
from tkinter import filedialog
from typing import Union
import mutagen
import piper
import pygame.mixer
import requests
from pydub import AudioSegment


class TTS:
    def __init__(self, voice: str = None, model_path: str = None, config_path: str = None):
        """Initialize the Text-to-Speech engine with a specified voice."""
        available_voices = {
            "alan": ["medium", "low"],
            "alba": ["medium"],
            "aru": ["medium"],
            "cori": ["medium"],
            "jenny_dioco": ["medium"],
            "northern_english_male": ["medium"],
            "semaine": ["medium"],
            "southern_english_female": ["low"],
            "vctk": ["medium"]
        }
        self.voice = voice or "jenny_dioco"
        quality = 'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'
        self.model_path = model_path or f"en_GB-{self.voice}-{quality}.onnx"
        self.config_path = config_path or f"en_GB-{self.voice}-{quality}.onnx.json"
        self.voice_model_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/{self.voice}/{quality}/en_GB-{self.voice}-{quality}.onnx"
        self.voice_config_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/{self.voice}/{quality}/en_GB-{self.voice}-{quality}.onnx.json"

        if not Path(self.model_path).exists():
            self.download_file(self.voice_model_url, self.model_path)
        if not Path(self.config_path).exists():
            self.download_file(self.voice_config_url, self.config_path)
        self.voice_model = piper.PiperVoice.load(self.model_path, self.config_path)

    def download_file(self, url: str, path: str) -> None:
        """Download a file from a URL to the specified path."""
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def synthesize_to_file(self, text: str, wav_file_path: Union[Path, str], length_scale: float = 1.0) -> None:
        """Synthesize text to a WAV file."""
        with wave.open(str(wav_file_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            self.voice_model.synthesize(text, wav_file, length_scale=length_scale)


class BookReader:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Book Reader")
        self.window.geometry("400x650")
        self.window.minsize(400, 350)
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.tts = TTS()
        self.current_file = None
        self.duration = None
        self.last_folder = str(Path.home())
        self.position = 0
        self.is_playing = False
        self.is_processing = False
        self.cancel_processing = False
        self.config_path = Path.home() / ".bookreader_config.json"
        self.temp_dir = Path(".temp_audio")
        self.temp_dir.mkdir(exist_ok=True)

        self.setup_ui()
        self.load_config()
        self.setup_keybindings()
        if self.current_file:
            self.calculate_duration()

    def setup_ui(self) -> None:
        """Set up the user interface with a scrollable frame."""
        # Main frame to hold canvas and scrollbar
        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Canvas and vertical scrollbar setup
        self.canvas = tk.Canvas(self.main_frame)
        self.v_scrollbar = tk.Scrollbar(self.main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)

        # Pack scrollbar and canvas
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Inner frame inside the canvas
        self.inner_frame = tk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW)

        # Bind events to handle resizing and scrolling
        self.inner_frame.bind("<Configure>", self.update_scroll_region)
        self.window.bind("<Configure>", self.on_window_resize)

        # Add UI widgets to inner_frame
        self.url_entry = tk.Entry(self.inner_frame, width=40)
        self.url_entry.pack(fill=tk.X, pady=5)
        self.download_button = tk.Button(self.inner_frame, text="Download", command=self.download_url)
        self.download_button.pack(fill=tk.X, pady=5)
        self.error_label = tk.Label(self.inner_frame, text="", fg="red")
        self.error_label.pack(fill=tk.X, pady=5)
        self.current_file_label = tk.Label(self.inner_frame, text=os.path.basename(
            self.current_file) if self.current_file else "No file selected")
        self.current_file_label.pack(fill=tk.X, pady=10)
        self.select_button = tk.Button(self.inner_frame, text="Select File", command=self.select_file)
        self.select_button.pack(fill=tk.X, pady=5)
        self.play_button = tk.Button(self.inner_frame, text="Play", command=self.play)
        self.play_button.pack(fill=tk.X, pady=5)
        self.pause_button = tk.Button(self.inner_frame, text="Pause", command=self.pause)
        self.pause_button.pack(fill=tk.X, pady=5)
        self.resume_button = tk.Button(self.inner_frame, text="Resume", command=self.resume)
        self.resume_button.pack(fill=tk.X, pady=5)
        self.stop_button = tk.Button(self.inner_frame, text="Stop", command=self.stop)
        self.stop_button.pack(fill=tk.X, pady=5)
        self.skip_back_button = tk.Button(self.inner_frame, text="< 10s", command=self.skip_backward)
        self.skip_back_button.pack(fill=tk.X, pady=5)
        self.skip_forward_button = tk.Button(self.inner_frame, text="10s >", command=self.skip_forward)
        self.skip_forward_button.pack(fill=tk.X, pady=5)
        self.cancel_button = tk.Button(self.inner_frame, text="Cancel", command=self.cancel, state=tk.DISABLED)
        self.cancel_button.pack(fill=tk.X, pady=5)

        # Playback scrollbar and status bar at the bottom
        self.playback_scrollbar = tk.Scale(self.window, from_=0, to=100, orient=tk.HORIZONTAL,
                                           command=self.on_scrollbar_move)
        self.playback_scrollbar.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        self.status_bar = tk.Label(self.window, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Initial UI updates
        self.update_button_states()
        self.update_playback_scrollbar()

    def update_scroll_region(self, event=None) -> None:
        """Update the canvas scroll region based on the inner_frame's size."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_window_resize(self, event: tk.Event) -> None:
        """Adjust the canvas window size when the window is resized."""
        canvas_width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self.canvas_window, width=canvas_width)
        self.update_scroll_region()

    def setup_keybindings(self) -> None:
        """Set up keyboard shortcuts."""
        self.window.bind("<space>", self.toggle_playback)

    def on_closing(self) -> None:
        """Handle window closing by stopping playback and processing."""
        if self.is_playing:
            self.stop()
        if self.is_processing:
            self.cancel()
            time.sleep(0.5)
        pygame.mixer.quit()
        self.window.destroy()

    def load_config(self) -> None:
        """Load configuration from a JSON file."""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                self.current_file = config.get('audio_file')
                self.position = config.get('position', 0)
                self.last_folder = config.get('last_folder', str(Path.home()))
            if self.current_file and not os.path.exists(self.current_file):
                self.current_file = None
            self.current_file_label.config(
                text=os.path.basename(self.current_file) if self.current_file else "No file selected")
            self.update_button_states()
            self.update_playback_scrollbar()

    def save_config(self) -> None:
        """Save current configuration to a JSON file."""
        config = {
            'audio_file': self.current_file,
            'position': self.position,
            'last_folder': self.last_folder
        }
        with open(self.config_path, 'w') as f:
            json.dump(config, f)

    def calculate_duration(self) -> None:
        """Start calculating the audio duration in a background thread."""
        if self.duration is None and self.current_file:
            self.status_bar.config(text="Calculating duration...")
            threading.Thread(target=self._calculate_duration_thread, daemon=True).start()

    def _calculate_duration_thread(self) -> None:
        """Calculate the audio duration using mutagen in a background thread."""
        try:
            audio = mutagen.File(self.current_file)
            self.duration = int(audio.info.length)
        except Exception as e:
            print(f"Error calculating duration: {e}")
            self.duration = 0
        self.window.after(0, self._update_ui_after_duration)

    def _update_ui_after_duration(self) -> None:
        """Update the UI after duration calculation."""
        self.update_playback_scrollbar()
        self.update_status_bar()

    def get_audio_duration(self) -> int:
        """Return the cached audio duration, or 0 if not yet calculated."""
        return self.duration if self.duration is not None else 0

    def update_button_states(self) -> None:
        """Update the state of buttons based on current conditions."""
        if self.is_processing:
            self.download_button.config(state=tk.DISABLED)
            self.select_button.config(state=tk.DISABLED)
            self.play_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.DISABLED)
            self.resume_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.skip_back_button.config(state=tk.DISABLED)
            self.skip_forward_button.config(state=tk.DISABLED)
            self.cancel_button.config(state=tk.NORMAL)
        else:
            self.download_button.config(state=tk.NORMAL)
            self.select_button.config(state=tk.NORMAL)
            self.play_button.config(state=tk.NORMAL if self.current_file else tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL if self.is_playing else tk.DISABLED)
            self.resume_button.config(
                state=tk.NORMAL if not self.is_playing and pygame.mixer.music.get_busy() else tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL if pygame.mixer.music.get_busy() else tk.DISABLED)
            self.skip_back_button.config(state=tk.NORMAL if self.current_file else tk.DISABLED)
            self.skip_forward_button.config(state=tk.NORMAL if self.current_file else tk.DISABLED)
            self.cancel_button.config(state=tk.DISABLED)
        if not self.is_processing and not self.is_playing and not pygame.mixer.music.get_busy():
            self.status_bar.config(text="Ready")

    def update_playback_scrollbar(self) -> None:
        """Update the playback scrollbar based on the current duration and position."""
        if self.duration is not None:
            self.playback_scrollbar.config(to=self.duration, resolution=1)
            self.playback_scrollbar.set(self.position)
        else:
            self.playback_scrollbar.config(to=100, resolution=1)
            self.playback_scrollbar.set(0)

    def on_scrollbar_move(self, value: str) -> None:
        """Handle scrollbar movement to adjust playback position."""
        self.position = int(float(value))
        self.update_status_bar()
        if self.is_playing:
            pygame.mixer.music.stop()
            self.play()
        self.save_config()

    def download_url(self) -> None:
        """Initiate downloading a file from a URL."""
        url = self.url_entry.get().strip()
        if not url:
            self.error_label.config(text="Please enter a URL")
            self.status_bar.config(text="Error: No URL provided")
            return

        self.is_processing = True
        self.cancel_processing = False
        self.status_bar.config(text="Downloading...")
        self.update_button_states()
        threading.Thread(target=self._download_url_thread, args=(url,), daemon=True).start()

    def _download_url_thread(self, url: str) -> None:
        """Download a file from a URL in a background thread."""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            file_name = url.split('/')[-1] or "downloaded.txt"
            if not file_name.endswith('.txt'):
                file_name += '.txt'
            download_path = self.temp_dir / file_name

            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.cancel_processing:
                        break
                    f.write(chunk)

            if not self.cancel_processing and os.path.exists(download_path):
                self.duration = None
                self.current_file = self.prepare_audio_file(str(download_path))
                if self.current_file:
                    self.position = 0
                    self.current_file_label.config(text=os.path.basename(self.current_file))
                    self.calculate_duration()
                    self.save_config()
                    self.error_label.config(text="")
                    self.status_bar.config(text="Ready")
            else:
                self.status_bar.config(text="Download cancelled")
                if os.path.exists(download_path):
                    os.remove(download_path)
        except requests.RequestException as e:
            self.error_label.config(text=f"Download failed: {str(e)}")
            self.status_bar.config(text=f"Download failed: {str(e)}")
        finally:
            self.is_processing = False
            self.update_button_states()

    def select_file(self) -> None:
        """Open a file dialog to select a text or audio file."""
        file_path = filedialog.askopenfilename(
            initialdir=self.last_folder,
            filetypes=[("Text files", "*.txt"), ("Audio files", "*.wav *.mp3")]
        )
        if file_path:
            self.last_folder = str(Path(file_path).parent)
            self.is_processing = True
            self.cancel_processing = False
            self.status_bar.config(text="Loading file...")
            self.update_button_states()
            threading.Thread(target=self._select_file_thread, args=(file_path,), daemon=True).start()

    def _select_file_thread(self, file_path: str) -> None:
        """Process the selected file in a background thread."""
        self.duration = None
        self.current_file = self.prepare_audio_file(file_path)
        if not self.cancel_processing and self.current_file:
            self.position = 0
            self.current_file_label.config(text=os.path.basename(self.current_file))
            self.calculate_duration()
            self.save_config()
            self.error_label.config(text="")
            self.status_bar.config(text="Ready")
        else:
            self.status_bar.config(text="File selection cancelled")
        self.is_processing = False
        self.update_button_states()

    def smart_chunk_text(self, text: str, base_size: int = 1000, max_extra: int = 512) -> list:
        """Split text into chunks at logical boundaries."""
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + base_size, len(text))
            if end < len(text):
                extra_end = min(end + max_extra, len(text))
                full_stop = text.find('.', end, extra_end)
                double_newline = text.find('\n\n', end, extra_end)

                if full_stop != -1 and (double_newline == -1 or full_stop < double_newline):
                    end = full_stop + 1
                elif double_newline != -1:
                    end = double_newline + 2
                else:
                    end = extra_end

            chunks.append(text[start:end].strip())
            start = end
        return chunks

    def prepare_audio_file(self, file_path: str) -> Union[str, None]:
        """Prepare an audio file from a text or audio file."""
        output_mp3 = self.temp_dir / f"{Path(file_path).stem}.mp3"

        if file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read().strip()
            if not text:
                self.error_label.config(text="Text file is empty")
                return None

            chunks = self.smart_chunk_text(text)  # Assuming this splits text into chunks
            if not chunks:
                self.error_label.config(text="No valid text chunks to process")
                return None

            wav_files = []
            total_chunks = len(chunks)

            for i, chunk in enumerate(chunks):
                if self.cancel_processing:  # Assuming cancel flag exists
                    for wav in wav_files:
                        if os.path.exists(wav):
                            os.remove(wav)
                    return None
                temp_wav = self.temp_dir / f"chunk_{i}.wav"
                self.tts.synthesize_to_file(chunk, temp_wav)  # Assuming TTS method
                wav_files.append(temp_wav)
                self.status_bar.config(text=f"Converting TTS: {i + 1}/{total_chunks} chunks")
                self.window.update_idletasks()

            combined = AudioSegment.empty()
            for i, wav in enumerate(wav_files):
                try:
                    segment = AudioSegment.from_wav(wav)
                    if len(segment) > 0:  # Skip empty segments
                        combined += segment
                    else:
                        print(f"Warning: Empty WAV file {wav}")
                except Exception as e:
                    print(f"Error processing WAV file {wav}: {e}")
                finally:
                    os.remove(wav)
                self.status_bar.config(text=f"Combining audio: {i + 1}/{total_chunks} chunks")
                self.window.update_idletasks()

            if combined and not self.cancel_processing:
                try:
                    combined.export(output_mp3, format="mp3", bitrate="192k")  # Standard bitrate
                    return str(output_mp3)
                except Exception as e:
                    print(f"Error exporting MP3: {e}")
                    self.error_label.config(text="Failed to export MP3")
                    return None
            return None
        elif file_path.endswith(('.wav', '.mp3')) and os.path.exists(file_path):
            return file_path
        return None

    def play_audio(self) -> None:
        """Play the audio file from the current position without looping."""
        if not self.current_file or not os.path.exists(self.current_file):
            self.error_label.config(text="No valid audio file to play")
            return

        try:
            pygame.mixer.music.load(self.current_file)  # Load the file once
            pygame.mixer.music.play(start=self.position)  # Start at the current position (in seconds)
        except pygame.error as e:
            self.error_label.config(text="Failed to play audio file")
            self.is_playing = False
            self.update_button_states()
            return

        self.is_playing = True
        while pygame.mixer.music.get_busy() and self.is_playing:
            # Update position using get_pos()
            pos_ms = pygame.mixer.music.get_pos()  # Returns time in milliseconds
            if pos_ms >= 0:
                self.position += pos_ms / 1000.0  # Convert to seconds and accumulate
                self.update_playback_scrollbar()  # Update UI if applicable
                self.update_status_bar()
            self.update_button_states()
            time.sleep(1.0)  # Check every second

        # Playback finished or stopped
        self.is_playing = False
        self.position = 0  # Reset position when done
        self.update_button_states()
        self.update_status_bar()

    def play(self) -> None:
        """Start or restart playback."""
        if not self.current_file or (self.is_playing and pygame.mixer.music.get_busy()):
            return

        self.status_bar.config(text="Playing...")
        threading.Thread(target=self.play_audio, daemon=True).start()

    def update_button_states(self) -> None:
        """Update button states based on playback conditions."""
        self.play_button.config(state='normal' if self.current_file and not self.is_playing else 'disabled')
        self.pause_button.config(state='normal' if self.is_playing else 'disabled')
        self.resume_button.config(
            state='normal' if not self.is_playing and pygame.mixer.music.get_busy() else 'disabled')
        self.stop_button.config(state='normal' if pygame.mixer.music.get_busy() else 'disabled')

    def pause(self) -> None:
        """Pause the current playback."""
        if self.is_playing and pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()  # Pause the audio
            self.is_playing = False  # Update playing state
            self.update_button_states()  # Refresh button states
            self.update_status_bar()  # Update UI

    def resume(self) -> None:
        """Resume paused playback."""
        if not self.is_playing and pygame.mixer.music.get_busy():
            pygame.mixer.music.unpause()
            self.is_playing = True
            self.update_button_states()
            self.update_status_bar()

    def stop(self) -> None:
        """Stop playback and reset position."""
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        self.is_playing = False
        self.position = 0
        self.update_playback_scrollbar()
        self.save_config()
        self.update_button_states()
        self.status_bar.config(text="Ready")

    def skip_backward(self) -> None:
        """Skip 10 seconds backward."""
        if self.current_file:
            self.position = max(0, self.position - 10)
            if self.is_playing:
                pygame.mixer.music.stop()
                self.play()
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.save_config()

    def skip_forward(self) -> None:
        """Skip 10 seconds forward."""
        if self.current_file:
            total = self.get_audio_duration()
            self.position = min(total, self.position + 10) if total > 0 else self.position + 10
            if self.is_playing:
                pygame.mixer.music.stop()
                self.play()
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.save_config()

    def cancel(self) -> None:
        """Cancel ongoing processing."""
        self.cancel_processing = True
        self.status_bar.config(text="Cancelling...")

    def toggle_playback(self, event: tk.Event = None) -> None:
        """Toggle between play, pause, and resume with the spacebar."""
        if not self.current_file:
            return
        if not self.is_playing and not pygame.mixer.music.get_busy():
            self.play()
        elif self.is_playing:
            self.pause()
        else:
            self.resume()

    def format_time(self, seconds: float) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"

    def update_status_bar(self) -> None:
        """Update the status bar with current playback information."""
        if self.is_processing:
            return
        total = self.get_audio_duration()
        if self.duration is None and self.current_file:
            self.status_bar.config(text="Calculating duration...")
        elif self.is_playing or pygame.mixer.music.get_busy():
            self.status_bar.config(
                text=f"Playing - Position: {self.format_time(self.position)} / Total: {self.format_time(total)} / Remaining: {self.format_time(max(0, total - self.position))}")
        elif self.current_file:
            self.status_bar.config(
                text=f"Stopped - Position: {self.format_time(self.position)} / Total: {self.format_time(total)} / Remaining: {self.format_time(max(0, total - self.position))}")
        else:
            self.status_bar.config(text="Ready")

    def run(self) -> None:
        """Start the Tkinter main loop."""
        self.window.mainloop()


def main() -> None:
    """Entry point for the application."""
    app = BookReader()
    app.run()


if __name__ == '__main__':
    main()
