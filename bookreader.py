import contextlib
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

with contextlib.redirect_stdout(None):  # Suppress pygame welcome message
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
        """Initialize the BookReader application."""
        pygame.mixer.init()
        self.window = tk.Tk()
        self.window.title("Book Reader")
        self.window.geometry("400x650")
        self.window.minsize(400, 350)
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.tts = TTS()
        self.current_file = None
        self.duration = None
        self.last_folder = str(Path.home())
        self.position = 0.0   # in seconds
        self.is_playing = False
        self.is_paused = False
        self.is_processing = False
        self.cancel_processing = False
        self.config_path = Path.home() / ".bookreader_config.json"
        self.temp_dir = Path(".temp_audio")
        self.temp_dir.mkdir(exist_ok=True)

        # Flag to suspend scrollbar event while programmatically updating its value
        self.suspend_scroll_event = False

        self.setup_ui()
        self.load_config()
        self.setup_keybindings()
        if self.current_file:
            self.calculate_duration()

    def download_url(self) -> None:
        """Download a file from a URL."""
        url = self.url_entry.get().strip()
        if not url:
            self.set_error_label("URL is empty")
            return
        self.is_processing = True
        self.cancel_processing = False
        self.status_bar.config(text="Downloading...")
        self.update_button_states()
        threading.Thread(target=self._download_url_thread, args=(url,), daemon=True).start()

    def setup_ui(self) -> None:
        """Set up the user interface with a scrollable frame."""
        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.main_frame)
        self.v_scrollbar = tk.Scrollbar(self.main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner_frame = tk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW,
                                                       width=self.window.winfo_width())

        self.inner_frame.bind("<Configure>", self.update_scroll_region)
        self.canvas.bind("<Configure>", self.on_canvas_configure)

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

        self.playback_scrollbar = tk.Scale(self.window, from_=0, to=100, orient=tk.HORIZONTAL,
                                           command=self.on_scrollbar_move)
        self.playback_scrollbar.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        self.status_bar = tk.Label(self.window, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.update_button_states()
        self.update_playback_scrollbar()

    def update_scroll_region(self, event=None) -> None:
        """Update the canvas scroll region based on the inner_frame's size."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

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

    def _calculate_duration_thread(self):
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

    def update_button_states(self):
        # Play button enabled only if a file is selected and not currently playing
        if self.current_file and not self.is_playing and not pygame.mixer.music.get_busy():
            self.play_button.config(state='normal')
        else:
            self.play_button.config(state='disabled')
        # Pause enabled only when playing
        if self.is_playing:
            self.pause_button.config(state='normal')
        else:
            self.pause_button.config(state='disabled')
        # Resume enabled only when paused
        if self.is_paused:
            self.resume_button.config(state='normal')
        else:
            self.resume_button.config(state='disabled')
        # Stop enabled if something is playing or paused
        if pygame.mixer.music.get_busy() or self.is_paused:
            self.stop_button.config(state='normal')
        else:
            self.stop_button.config(state='disabled')
        if self.current_file:
            self.skip_back_button.config(state='normal')
            self.skip_forward_button.config(state='normal')
        else:
            self.skip_back_button.config(state='disabled')
            self.skip_forward_button.config(state='disabled')
        self.cancel_button.config(state='normal' if self.is_processing else 'disabled')

    def update_playback_scrollbar(self) -> None:
        """Update the playback scrollbar based on the current duration and position."""
        if self.duration is not None:
            self.playback_scrollbar.config(to=self.duration, resolution=1)
        else:
            self.playback_scrollbar.config(to=100, resolution=1)
        # Suspend the callback when updating the scrollbar programmatically
        self.suspend_scroll_event = True
        self.playback_scrollbar.set(self.position)
        # Unset suspend_scroll_event after a short delay to avoid jitter
        self.window.after(50, self._unset_suspend_scroll)

    def _unset_suspend_scroll(self):
        self.suspend_scroll_event = False

    def on_scrollbar_move(self, value: str) -> None:
        """Handle scrollbar movement to adjust playback position."""
        if self.suspend_scroll_event:
            return
        new_position = float(value)
        self.position = new_position
        self.update_status_bar()
        # If the user drags the scrollbar while playing or paused, restart playback from the new position.
        if self.is_playing or self.is_paused:
            pygame.mixer.music.stop()
            self.play()
        self.save_config()

    def on_canvas_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

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
                    self.set_error_label("")
                    self.status_bar.config(text="Ready")
            else:
                self.status_bar.config(text="Download cancelled")
                if os.path.exists(download_path):
                    os.remove(download_path)
        except requests.RequestException as e:
            self.set_error_label(f"Download failed: {str(e)}")
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

    def _select_file_thread(self, file_path: str):
        self.duration = None
        self.current_file = self.prepare_audio_file(file_path)
        if not self.cancel_processing and self.current_file:
            self.position = 0
            self.set_current_file_label(os.path.basename(self.current_file))
            self.calculate_duration()
            self.save_config()
            self.set_error_label("")
            self.set_status_bar("Ready")
        else:
            self.set_status_bar("File selection cancelled")
        self.window.after(0, self.update_ui_after_processing)

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
        output_mp3 = self.temp_dir / f"{Path(file_path).stem}.mp3"

        if file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read().strip()
            if not text:
                self.set_error_label("Text file is empty")
                return None

            chunks = self.smart_chunk_text(text)
            wav_files = []
            total_chunks = len(chunks)

            for i, chunk in enumerate(chunks):
                if self.cancel_processing:
                    for wav in wav_files:
                        if os.path.exists(wav):
                            os.remove(wav)
                    return None
                temp_wav = self.temp_dir / f"chunk_{i}.wav"
                self.tts.synthesize_to_file(chunk, temp_wav)
                wav_files.append(temp_wav)
                self.set_status_bar(f"Converting TTS: {i + 1}/{total_chunks} chunks")

            if self.cancel_processing:
                for wav in wav_files:
                    if os.path.exists(wav):
                        os.remove(wav)
                return None

            combined = AudioSegment.empty()
            for i, wav in enumerate(wav_files):
                if self.cancel_processing:
                    combined = None
                    break
                combined += AudioSegment.from_wav(wav)
                os.remove(wav)
                self.set_status_bar(f"Combining audio: {i + 1}/{total_chunks} chunks")

            if combined and not self.cancel_processing:
                # Export with a constant bitrate to avoid decoding issues
                combined.export(output_mp3, format="mp3", bitrate="128k")
                return str(output_mp3)
            return None
        elif file_path.endswith(('.wav', '.mp3')) and os.path.exists(file_path):
            return file_path
        return None

    def update_position(self):
        """Periodically update playback position using the mixer's get_pos()."""
        if self.is_playing and pygame.mixer.music.get_busy():
            # get_pos returns elapsed ms since play() (or unpause) was called.
            elapsed_ms = pygame.mixer.music.get_pos()
            if elapsed_ms >= 0:
                self.position = self.play_start_position + (elapsed_ms / 1000.0)
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.window.after(100, self.update_position)
        # If playback stops naturally, update state
        elif not self.is_paused:
            self.is_playing = False
            self.position = 0
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.update_button_states()

    def play(self):
        if not self.current_file:
            return
        # Reinitialize mixer to avoid state issues
        pygame.mixer.quit()
        pygame.mixer.init()
        pygame.mixer.music.load(self.current_file)
        # Start playback from the stored position (in seconds)
        pygame.mixer.music.play(start=self.position)
        self.is_playing = True
        self.is_paused = False
        # Store the base position for get_pos() calculations.
        self.play_start_position = self.position
        self.update_button_states()
        self.update_status_bar()
        self.window.after(100, self.update_position)

    def pause(self):
        if self.is_playing and pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.is_paused = True
            self.is_playing = False
            # Update buttons: disable Pause, enable Resume.
            self.update_button_states()
            self.update_status_bar()

    def resume(self):
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.is_playing = True
            # When resuming, update our base position using the stored position.
            self.play_start_position = self.position
            self.update_button_states()
            self.status_bar.config(text="Playing...")
            self.window.after(100, self.update_position)

    def stop(self):
        if pygame.mixer.music.get_busy() or self.is_paused:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.position = 0
        self.update_playback_scrollbar()
        self.save_config()
        self.update_button_states()
        self.status_bar.config(text="Ready")

    def skip_forward(self):
        if self.current_file:
            total = self.get_audio_duration()
            self.position = min(total, self.position + 10) if total > 0 else self.position + 10
            if self.is_playing or self.is_paused:
                pygame.mixer.music.stop()
                self.play()
            else:
                self.update_playback_scrollbar()
                self.update_status_bar()
            self.save_config()

    def skip_backward(self):
        if self.current_file:
            self.position = max(0, self.position - 10)
            if self.is_playing or self.is_paused:
                pygame.mixer.music.stop()
                self.play()
            else:
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
        if not self.is_playing and not self.is_paused and not pygame.mixer.music.get_busy():
            self.play()
        elif self.is_playing:
            self.pause()
        elif self.is_paused:
            self.resume()

    def format_time(self, seconds: int) -> str:
        """Format seconds into HH:MM:SS."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"

    def set_status_bar(self, text):
        self.window.after(0, lambda: self.status_bar.config(text=text))

    def set_current_file_label(self, text):
        self.window.after(0, lambda: self.current_file_label.config(text=text))

    def set_error_label(self, text):
        self.window.after(0, lambda: self.error_label.config(text=text))

    def update_ui_after_processing(self):
        self.is_processing = False
        self.update_button_states()
        self.set_status_bar("Ready")

    def update_status_bar(self) -> None:
        """Update the status bar with current playback information."""
        if self.is_processing:
            return
        total = self.get_audio_duration()
        if self.duration is None and self.current_file:
            self.status_bar.config(text="Calculating duration...")
        elif self.is_playing or (pygame.mixer.music.get_busy() and not self.is_paused):
            self.status_bar.config(
                text=f"Playing - Position: {self.format_time(int(self.position))} / Total: {self.format_time(total)} / Remaining: {self.format_time(max(0, total - int(self.position)))}")
        elif self.current_file:
            self.status_bar.config(
                text=f"Stopped - Position: {self.format_time(int(self.position))} / Total: {self.format_time(total)} / Remaining: {self.format_time(max(0, total - int(self.position)))}")
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
