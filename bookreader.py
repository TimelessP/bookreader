import json
import os
import threading
import time
import tkinter as tk
import wave
from pathlib import Path
from tkinter import filedialog
from typing import Union

import piper
import pygame.mixer
import requests
from pydub import AudioSegment


class TTS:
    def __init__(self, voice: str = None, model_path: str = None, config_path: str = None):
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
        self.model_path = model_path or f"en_GB-{self.voice}-{'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'}.onnx"
        self.config_path = config_path or f"en_GB-{self.voice}-{'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'}.onnx.json"
        self.voice_model_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/{self.voice}/{'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'}/en_GB-{self.voice}-{'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'}.onnx"
        self.voice_config_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/{self.voice}/{'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'}/en_GB-{self.voice}-{'medium' if self.voice in available_voices and 'medium' in available_voices[self.voice] else 'low'}.onnx.json"

        if not Path(self.model_path).exists():
            self.download_file(self.voice_model_url, self.model_path)
        if not Path(self.config_path).exists():
            self.download_file(self.voice_config_url, self.config_path)
        self.voice_model = piper.PiperVoice.load(self.model_path, self.config_path)

    def download_file(self, url, path):
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def synthesize_to_file(self, text: str, wav_file_path: Union[Path, str], length_scale: float = 1.0):
        with wave.open(str(wav_file_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            self.voice_model.synthesize(text, wav_file, length_scale=length_scale)


class BookReader:
    def __init__(self):
        pygame.mixer.init()
        self.window = tk.Tk()
        self.window.title("Book Reader")
        self.window.geometry("400x650")  # Minimum height includes controls, scrollbar, and status bar
        self.window.minsize(400, 350)  # Minimum height for scrollbar and status bar

        self.tts = TTS()
        self.current_file = None
        self.last_folder = str(Path.home())
        self.position = 0
        self.is_playing = False
        self.is_processing = False
        self.cancel_processing = False
        self.config_path = Path.home() / ".bookreader_config.json"
        self.temp_dir = Path(".temp_audio")

        self.load_config()
        self.setup_ui()
        self.setup_keybindings()

    def setup_ui(self):
        # Main frame with vertical scrollbar
        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.main_frame)
        self.v_scrollbar = tk.Scrollbar(self.main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW, width=self.window.winfo_screenwidth())

        # Bind configure to update scroll region
        self.inner_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window.bind("<Configure>", self.on_window_resize)

        # Controls anchored to top
        self.url_entry = tk.Entry(self.inner_frame, width=40)
        self.url_entry.pack(fill=tk.X, pady=5)
        self.download_button = tk.Button(self.inner_frame, text="Download", command=self.download_url)
        self.download_button.pack(fill=tk.X, pady=5)
        self.error_label = tk.Label(self.inner_frame, text="", fg="red")
        self.error_label.pack(fill=tk.X, pady=5)

        self.current_file_label = tk.Label(self.inner_frame, text=self.current_file or "No file selected")
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

        # Playback scrollbar (outside scrollable area)
        self.playback_scrollbar = tk.Scale(self.window, from_=0, to=100, orient=tk.HORIZONTAL,
                                           command=self.on_scrollbar_move)
        self.playback_scrollbar.pack(fill=tk.X, side=tk.BOTTOM, pady=5)

        # Status bar (outside scrollable area)
        self.status_bar = tk.Label(self.window, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.update_button_states()
        self.update_playback_scrollbar()

    def on_window_resize(self, event):
        self.canvas.itemconfig(self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW),
                               width=event.width)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def setup_keybindings(self):
        self.window.bind("<space>", self.toggle_playback)

    def load_config(self):
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                self.current_file = config.get('audio_file')
                self.position = config.get('position', 0)
                self.last_folder = config.get('last_folder', str(Path.home()))
            if self.current_file and os.path.exists(self.current_file):
                self.audio_file = self.current_file
                self.update_playback_scrollbar()

    def save_config(self):
        config = {
            'audio_file': self.current_file,
            'position': self.position,
            'last_folder': self.last_folder
        }
        with open(self.config_path, 'w') as f:
            json.dump(config, f)

    def update_button_states(self):
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

    def update_playback_scrollbar(self):
        total = self.get_audio_duration()
        if total > 0:
            self.playback_scrollbar.config(to=total, resolution=1)
            self.playback_scrollbar.set(self.position)
        else:
            self.playback_scrollbar.config(to=100, resolution=1)
            self.playback_scrollbar.set(0)

    def on_scrollbar_move(self, value):
        self.position = int(float(value))
        self.update_status_bar()
        if self.is_playing:
            pygame.mixer.music.stop()
            self.play()
        self.save_config()

    def download_url(self):
        url = self.url_entry.get().strip()
        if not url:
            self.error_label.config(text="Please enter a URL")
            self.status_bar.config(text="Error: No URL provided")
            return

        self.is_processing = True
        self.cancel_processing = False
        self.status_bar.config(text="Downloading...")
        self.update_button_states()
        threading.Thread(target=self._download_url_thread, args=(url,)).start()

    def _download_url_thread(self, url):
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            file_name = url.split('/')[-1] or "downloaded.txt"
            if not file_name.endswith('.txt'):
                file_name += '.txt'
            download_path = self.temp_dir / file_name
            self.temp_dir.mkdir(exist_ok=True)

            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            if not self.cancel_processing:
                self.current_file = self.prepare_audio_file(str(download_path))
                self.position = 0
                self.current_file_label.config(
                    text=os.path.basename(self.current_file) if self.current_file else "No file selected")
                self.update_playback_scrollbar()
                self.save_config()
                self.error_label.config(text="")
                self.status_bar.config(text="Ready")
            else:
                self.status_bar.config(text="")
        except requests.RequestException as e:
            self.error_label.config(text=f"Download failed: {str(e)}")
            self.status_bar.config(text=f"Download failed: {str(e)}")
        finally:
            self.is_processing = False
            self.update_button_states()

    def select_file(self):
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
            threading.Thread(target=self._select_file_thread, args=(file_path,)).start()

    def _select_file_thread(self, file_path):
        self.current_file = self.prepare_audio_file(file_path)
        if not self.cancel_processing:
            self.position = 0
            self.current_file_label.config(
                text=os.path.basename(self.current_file) if self.current_file else "No file selected")
            self.update_playback_scrollbar()
            self.save_config()
            self.error_label.config(text="")
            self.status_bar.config(text="Ready")
        else:
            self.status_bar.config(text="")
        self.is_processing = False
        self.update_button_states()

    def smart_chunk_text(self, text, base_size=1000, max_extra=512):
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

            chunks.append(text[start:end])
            start = end
        return chunks

    def prepare_audio_file(self, file_path):
        self.temp_dir.mkdir(exist_ok=True)
        output_mp3 = self.temp_dir / f"{Path(file_path).stem}.mp3"

        if file_path.endswith('.txt'):
            with open(file_path, 'r') as f:
                text = f.read()

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
                self.status_bar.config(text=f"Converting TTS: {i + 1}/{total_chunks} chunks")
                self.window.update_idletasks()

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
                self.status_bar.config(text=f"Combining audio: {i + 1}/{total_chunks} chunks")
                self.window.update_idletasks()

            if combined and not self.cancel_processing:
                combined.export(output_mp3, format="mp3")
                for wav in wav_files:
                    if os.path.exists(wav):
                        os.remove(wav)
                return str(output_mp3)
            return None
        elif file_path.endswith(('.wav', '.mp3')):
            self.status_bar.config(text="Ready")
            return file_path

    def play_audio(self):
        if not self.current_file:
            return

        self.is_playing = True
        pygame.mixer.music.load(self.current_file)
        pygame.mixer.music.play(start=self.position)

        start_time = time.time()
        while pygame.mixer.music.get_busy() and self.is_playing:
            elapsed = time.time() - start_time
            self.position = int(elapsed + self.position)
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.update_button_states()
            time.sleep(1)

        self.is_playing = False
        self.update_button_states()
        self.update_status_bar()

    def play(self):
        if not self.current_file or (self.is_playing and pygame.mixer.music.get_busy()):
            return

        self.status_bar.config(text="Playing...")
        threading.Thread(target=self.play_audio).start()

    def pause(self):
        if self.is_playing and pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.is_playing = False
            self.save_config()
            self.update_button_states()
            self.update_status_bar()

    def resume(self):
        if not self.is_playing and pygame.mixer.music.get_busy():
            pygame.mixer.music.unpause()
            self.is_playing = True
            self.status_bar.config(text="Playing...")
            threading.Thread(target=self.update_position_while_playing).start()

    def stop(self):
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        self.is_playing = False
        self.position = 0
        self.update_playback_scrollbar()
        self.save_config()
        self.update_button_states()
        self.status_bar.config(text="Ready")

    def skip_backward(self):
        if self.current_file:
            self.position = max(0, self.position - 10)
            if self.is_playing:
                pygame.mixer.music.stop()
                self.play()
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.save_config()

    def skip_forward(self):
        if self.current_file:
            total = self.get_audio_duration()
            self.position = min(total, self.position + 10)
            if self.is_playing:
                pygame.mixer.music.stop()
                self.play()
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.save_config()

    def cancel(self):
        self.cancel_processing = True
        self.status_bar.config(text="Cancelling...")

    def update_position_while_playing(self):
        while self.is_playing and pygame.mixer.music.get_busy():
            self.position += 1
            self.update_playback_scrollbar()
            self.update_status_bar()
            self.update_button_states()
            time.sleep(1)

    def toggle_playback(self, event=None):
        if not self.current_file:
            return
        if not self.is_playing and not pygame.mixer.music.get_busy():
            self.play()
        elif self.is_playing:
            self.pause()
        else:
            self.resume()

    def get_audio_duration(self):
        if not self.current_file:
            return 0
        audio = AudioSegment.from_file(self.current_file)
        return len(audio) // 1000

    def format_time(self, seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def update_status_bar(self):
        if self.is_processing:
            return  # Let processing messages take precedence
        total = self.get_audio_duration()
        if self.is_playing or pygame.mixer.music.get_busy():
            self.status_bar.config(
                text=f"Playing - Position: {self.format_time(self.position)} / Total: {self.format_time(total)} / Remaining: {self.format_time(max(0, total - self.position))}")
        elif self.current_file:
            self.status_bar.config(
                text=f"Stopped - Position: {self.format_time(self.position)} / Total: {self.format_time(total)} / Remaining: {self.format_time(max(0, total - self.position))}")
        else:
            self.status_bar.config(text="Ready")

    def run(self):
        self.window.mainloop()


def main():
    app = BookReader()
    app.run()


if __name__ == '__main__':
    main()
