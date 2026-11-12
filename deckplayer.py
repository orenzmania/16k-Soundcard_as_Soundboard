import os
import sys
import json
import time
import threading
import ctypes
from ctypes import wintypes
import numpy as np
import sounddevice as sd
import soundfile as sf
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config_direct.json")
SAMPLE_RATE = 44100
CHUNK_MS = 50  # Faster 50ms chunks for tighter onset precision
CHUNK_SIZE = int(SAMPLE_RATE * (CHUNK_MS / 1000.0))
FEATURE_WINDOW = int(SAMPLE_RATE * 0.20)  # 200ms signature window
SILENCE_CHUNKS_REQUIRED = 6  # 300ms of silence required to re-arm

DEFAULT_SLOTS = [
    {"id": 1,  "name": "Slot 1 (Applause)",   "sig_file": "sig_1.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 2,  "name": "Slot 2 (Laughter)",   "sig_file": "sig_2.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 3,  "name": "Slot 3 (Gunshot)",    "sig_file": "sig_3.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 4,  "name": "Slot 4 (Crow)",       "sig_file": "sig_4.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 5,  "name": "Slot 5 (Ding)",       "sig_file": "sig_5.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 6,  "name": "Slot 6 (Slap)",       "sig_file": "sig_6.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 7,  "name": "Slot 7 (Airhorn)",    "sig_file": "sig_7.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 8,  "name": "Slot 8 (Cheer)",      "sig_file": "sig_8.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 9,  "name": "Slot 9 (Kiss)",       "sig_file": "sig_9.wav",  "audio_path": "", "lockout": 0.5},
    {"id": 10, "name": "Slot 10 (Countdown)", "sig_file": "sig_10.wav", "audio_path": "", "lockout": 3.5},
    {"id": 11, "name": "Slot 11 (Surprise)",  "sig_file": "sig_11.wav", "audio_path": "", "lockout": 0.5},
    {"id": 12, "name": "Slot 12 (Despise)",   "sig_file": "sig_12.wav", "audio_path": "", "lockout": 0.5},
    {"id": 13, "name": "Slot 13 (Attention)", "sig_file": "sig_13.wav", "audio_path": "", "lockout": 0.5},
    {"id": 14, "name": "Slot 14 (Music 1)",   "sig_file": "sig_14.wav", "audio_path": "", "lockout": 3.5},
    {"id": 15, "name": "Slot 15 (Music 2)",   "sig_file": "sig_15.wav", "audio_path": "", "lockout": 3.5},
    {"id": 16, "name": "Slot 16 (Stop/Mute)", "sig_file": "sig_16.wav", "audio_path": "STOP", "lockout": 0.5},
]


# --- NATIVE WINDOWS SYSTEM TRAY (ZERO EXTERNAL DEPENDENCIES) ---
class NativeTrayIcon:
    """Lightweight Windows system tray icon using ctypes Shell_NotifyIconW."""
    NIM_ADD = 0x00
    NIM_DELETE = 0x02
    NIF_MESSAGE = 0x01
    NIF_ICON = 0x02
    NIF_TIP = 0x04
    WM_USER = 0x0400
    WM_TRAYICON = WM_USER + 20
    WM_LBUTTONDBLCLK = 0x0203
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    IDI_APPLICATION = 32512

    def __init__(self, app_title, on_restore_callback):
        self.app_title = app_title
        self.on_restore = on_restore_callback
        self.hwnd = None
        self.active = False
        self._thread = None

    def show(self):
        if self.active:
            return
        self.active = True
        self._thread = threading.Thread(target=self._run_message_loop, daemon=True)
        self._thread.start()

    def hide(self):
        if not self.active:
            return
        self.active = False
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE

    def _run_message_loop(self):
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self.WM_TRAYICON:
                if lparam in (self.WM_LBUTTONDBLCLK, self.WM_LBUTTONUP, self.WM_RBUTTONUP):
                    self.on_restore()
                    return 0
            elif msg == 0x0002:  # WM_DESTROY
                self._remove_nid(hwnd)
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_ref = WNDPROCTYPE(wnd_proc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        class_name = f"SoundcardDeckTray_{int(time.time()*1000)}"
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wnd_proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wc))

        self.hwnd = user32.CreateWindowExW(0, class_name, "TrayHost", 0, 0, 0, 0, 0, 0, 0, hinst, None)
        hicon = user32.LoadIconW(0, ctypes.cast(self.IDI_APPLICATION, wintypes.LPCWSTR))

        self._send_nid(self.hwnd, self.NIM_ADD, hicon)

        msg = wintypes.MSG()
        while self.active and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._remove_nid(self.hwnd)
        user32.DestroyWindow(self.hwnd)
        user32.UnregisterClassW(class_name, hinst)
        self.hwnd = None

    def _send_nid(self, hwnd, action, hicon=0):
        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
            ]

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = f"{self.app_title} (Click to Restore)"[:127]
        ctypes.windll.shell32.Shell_NotifyIconW(action, ctypes.byref(nid))

    def _remove_nid(self, hwnd):
        if hwnd:
            self._send_nid(hwnd, self.NIM_DELETE)


def extract_fingerprint(audio_1d):
    """
    High-precision onset-aligned log-spectral fingerprint.
    Uses 5ms sliding energy windows to find exact attack and 6 sub-frames with mean subtraction
    to prevent false positives between similar soundcard effects.
    """
    if len(audio_1d) == 0:
        return None

    # Remove DC offset
    audio_1d = audio_1d - np.mean(audio_1d)
    peak = np.max(np.abs(audio_1d))
    if peak < 1e-4:
        return None

    # Normalize amplitude to 1.0 before feature extraction
    norm_audio = audio_1d / peak

    # Find exact energy attack using 5ms short-time energy blocks
    win_5ms = int(SAMPLE_RATE * 0.005)
    num_wins = len(norm_audio) // win_5ms
    if num_wins > 1:
        reshaped = norm_audio[:num_wins * win_5ms].reshape(num_wins, win_5ms)
        rms_envelope = np.sqrt(np.mean(reshaped**2, axis=1))
        max_env = np.max(rms_envelope)
        onset_frames = np.where(rms_envelope > (max_env * 0.25))[0]
        start_idx = max(0, (onset_frames[0] * win_5ms) - win_5ms) if len(onset_frames) > 0 else 0
    else:
        start_idx = 0

    segment = norm_audio[start_idx : start_idx + FEATURE_WINDOW]
    if len(segment) < FEATURE_WINDOW:
        segment = np.pad(segment, (0, FEATURE_WINDOW - len(segment)))

    # Extract 6 temporal slices across the 200ms window with log-frequency weighting
    num_slices = 6
    sub_len = FEATURE_WINDOW // num_slices
    features = []

    for i in range(num_slices):
        sub = segment[i * sub_len : (i + 1) * sub_len]
        windowed = sub * np.hanning(len(sub))
        spec = np.abs(np.fft.rfft(windowed))
        # Ignore sub-120Hz hum (first 4 bins) and keep up to ~9kHz
        min_bin = 4
        max_bin = min(len(spec), 280)
        band = spec[min_bin:max_bin]
        # Log-compression emphasizes harmonic structure over raw volume spikes
        log_band = np.log1p(band * 25.0)
        features.append(log_band)

    feat_vec = np.concatenate(features).astype(np.float32)
    # Zero-mean unit-variance normalization (Pearson correlation similarity)
    feat_vec = feat_vec - np.mean(feat_vec)
    norm = np.linalg.norm(feat_vec)
    if norm == 0:
        return None
    return feat_vec / norm


class AudioRouter:
    """Handles cached loading (.wav, .mp3, .ogg, .opus, .flac), resampling, and concurrent streaming."""
    def __init__(self, status_callback=None):
        self.cache = {}
        self.active_streams = []
        self.lock = threading.Lock()
        self.status_callback = status_callback

    def stop(self):
        with self.lock:
            for s in self.active_streams:
                try:
                    s.abort()
                except Exception:
                    pass
            self.active_streams.clear()

    def _load_audio_file(self, file_path):
        try:
            data, fs = sf.read(file_path, dtype='float32', always_2d=False)
            if len(data) > 0:
                return data, fs
        except Exception:
            pass

        with sf.SoundFile(file_path, 'r') as f:
            fs = f.samplerate
            blocks = [b for b in f.blocks(blocksize=32768, dtype='float32')]
            if not blocks:
                raise RuntimeError("Audio file decoded to 0 samples.")
            data = np.concatenate(blocks, axis=0)
            return data, fs

    def _prepare_audio(self, data, src_fs, target_fs):
        if data.ndim == 1:
            data = np.column_stack((data, data))
        elif data.shape[1] == 1:
            data = np.column_stack((data[:, 0], data[:, 0]))
        elif data.shape[1] > 2:
            data = data[:, :2]

        if src_fs != target_fs:
            num_samples = int(len(data) * target_fs / src_fs)
            orig_idx = np.linspace(0, len(data), len(data), endpoint=False)
            new_idx = np.linspace(0, len(data), num_samples, endpoint=False)
            ch0 = np.interp(new_idx, orig_idx, data[:, 0])
            ch1 = np.interp(new_idx, orig_idx, data[:, 1])
            data = np.column_stack((ch0, ch1))

        peak = np.max(np.abs(data))
        if peak > 0.80:
            data = data * (0.80 / peak)

        return data.astype(np.float32)

    def play(self, file_path, monitor_dev=None, broadcast_dev=None):
        self.stop()
        if not file_path or file_path == "STOP":
            return

        if not os.path.exists(file_path):
            if self.status_callback:
                self.status_callback(f"File not found: {os.path.basename(file_path)}", "red")
            return

        if file_path not in self.cache:
            try:
                data, fs = self._load_audio_file(file_path)
                self.cache[file_path] = (data, fs)
            except Exception as e:
                if self.status_callback:
                    self.status_callback(f"Load error ({os.path.basename(file_path)}): {e}", "red")
                return

        raw_data, src_fs = self.cache[file_path]

        def stream_worker(dev_id):
            if dev_id is None:
                return
            try:
                dev_info = sd.query_devices(dev_id)
                target_fs = int(dev_info['default_samplerate'])
                prepared_data = self._prepare_audio(raw_data, src_fs, target_fs)

                stream = sd.OutputStream(
                    samplerate=target_fs,
                    device=dev_id,
                    channels=2,
                    dtype='float32'
                )
                with self.lock:
                    self.active_streams.append(stream)

                with stream:
                    stream.write(prepared_data)
                    time.sleep(0.05)

                with self.lock:
                    if stream in self.active_streams:
                        self.active_streams.remove(stream)
            except Exception as e:
                if self.status_callback:
                    self.status_callback(f"Play error on [{dev_id}]: {str(e)[:60]}", "red")

        if monitor_dev is not None:
            threading.Thread(target=stream_worker, args=(monitor_dev,), daemon=True).start()
        if broadcast_dev is not None and broadcast_dev != monitor_dev:
            threading.Thread(target=stream_worker, args=(broadcast_dev,), daemon=True).start()


class SoundcardDirectDeckApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Soundcard Direct Soundboard Deck (16 Slots)")
        self.geometry("940x780")
        self.minsize(860, 600)

        self.router = AudioRouter(
            status_callback=lambda msg, col: self.after(0, lambda: self.lbl_last_hit.config(text=msg, foreground=col))
        )
        self.config_data = self.load_config()
        self.signatures = {}
        self.is_listening = False
        self.stream = None

        # Recording cancellation state
        self.is_recording_key = False
        self.cancel_recording_flag = False
        self.active_rec_label = None

        # Tray manager
        self.tray_icon = NativeTrayIcon(
            "Soundcard Soundboard Deck",
            on_restore_callback=lambda: self.after(0, self.restore_from_tray)
        )

        # Trigger & Tail Lockout State
        self.last_trigger_time = 0
        self.active_lockout_duration = 0.5
        self.waiting_for_silence = False
        self.silent_chunks_count = 0
        self.peak_rms_seen = 0.0

        self.prev_chunk = None
        self.capture_buffer = []
        self.is_capturing_live = False
        self.raw_accumulator = np.array([], dtype=np.float32)

        self.create_ui()
        self.load_all_signatures()
        self.refresh_devices()

        # Intercept window minimize event for Taskbar vs Tray option
        self.bind("<Unmap>", self.on_window_unmap)
        self.protocol("WM_DELETE_WINDOW", self.on_close_app)

    def load_config(self):
        config = {
            "in_device": "",
            "monitor_device": "",
            "broadcast_device": "",
            "threshold": 0.030,
            "match_threshold": 0.68,
            "minimize_mode": "Taskbar",
            "slots": [dict(s) for s in DEFAULT_SLOTS]
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    saved = json.load(f)
                    config.update(saved)
                    existing_count = len(config.get("slots", []))
                    if existing_count < 16:
                        config["slots"].extend([dict(s) for s in DEFAULT_SLOTS[existing_count:]])
                    for idx, s in enumerate(config["slots"]):
                        if "lockout" not in s:
                            s["lockout"] = DEFAULT_SLOTS[idx]["lockout"]
            except Exception:
                pass
        return config

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config_data, f, indent=2)

    def create_ui(self):
        dev_frame = ttk.LabelFrame(self, text=" Hardware & Routing Setup ", padding=10)
        dev_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(dev_frame, text="Soundcard Input:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.cb_in = ttk.Combobox(dev_frame, state="readonly", width=42)
        self.cb_in.grid(row=0, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(dev_frame, text="Headphones:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.cb_monitor = ttk.Combobox(dev_frame, state="readonly", width=42)
        self.cb_monitor.grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(dev_frame, text="Broadcast (Cable):").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.cb_broadcast = ttk.Combobox(dev_frame, state="readonly", width=42)
        self.cb_broadcast.grid(row=2, column=1, sticky="w", padx=4, pady=2)

        self.btn_refresh = ttk.Button(dev_frame, text="Refresh Audio Devices", command=self.refresh_devices)
        self.btn_refresh.grid(row=0, column=2, padx=10, sticky="ew")

        self.btn_toggle = ttk.Button(dev_frame, text="Start Listening", command=self.toggle_listening)
        self.btn_toggle.grid(row=1, column=2, rowspan=2, padx=10, sticky="nsew")

        self.btn_help = ttk.Button(dev_frame, text="Help / Guide", width=14, command=self.show_help_window)
        self.btn_help.grid(row=0, column=3, padx=5, sticky="ew")

        # Minimize Mode Selector (Taskbar vs System Tray)
        min_frame = ttk.Frame(dev_frame)
        min_frame.grid(row=1, column=3, rowspan=2, padx=5, sticky="nsew")
        ttk.Label(min_frame, text="When Minimized:").pack(anchor="w")
        self.min_mode_var = tk.StringVar(value=self.config_data.get("minimize_mode", "Taskbar"))
        self.cb_min_mode = ttk.Combobox(min_frame, textvariable=self.min_mode_var, values=["Taskbar", "System Tray"], state="readonly", width=13)
        self.cb_min_mode.pack(anchor="w", pady=2)
        self.cb_min_mode.bind("<<ComboboxSelected>>", self.on_min_mode_change)

        # High-Precision Noise Gate Slider + Fine Spinbox + Live & Peak RMS Meter
        thresh_frame = ttk.Frame(dev_frame)
        thresh_frame.grid(row=3, column=0, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Label(thresh_frame, text="Noise Gate (RMS):").pack(side="left", padx=4)

        self.threshold_var = tk.DoubleVar(value=self.config_data.get("threshold", 0.030))
        self.slider = ttk.Scale(
            thresh_frame, from_=0.001, to_=0.250,
            variable=self.threshold_var, orient="horizontal",
            command=self.on_threshold_slider
        )
        self.slider.pack(side="left", fill="x", expand=True, padx=4)

        self.spin_thresh = ttk.Spinbox(
            thresh_frame, from_=0.001, to=0.250, increment=0.001,
            textvariable=self.threshold_var, width=7, format="%.3f",
            command=self.on_threshold_spin
        )
        self.spin_thresh.pack(side="left", padx=2)
        self.spin_thresh.bind("<Return>", lambda e: self.on_threshold_spin())

        self.lbl_live_rms = ttk.Label(thresh_frame, text="Live: 0.000 | Peak: 0.000", font=("Consolas", 9), width=26)
        self.lbl_live_rms.pack(side="left", padx=6)

        btn_reset_peak = ttk.Button(thresh_frame, text="Reset Peak", width=10, command=self.reset_peak_rms)
        btn_reset_peak.pack(side="left", padx=2)

        # Match Confidence Slider
        match_frame = ttk.Frame(dev_frame)
        match_frame.grid(row=4, column=0, columnspan=4, sticky="we", pady=(4, 0))
        ttk.Label(match_frame, text="Min Match Score:").pack(side="left", padx=4)
        self.match_var = tk.DoubleVar(value=self.config_data.get("match_threshold", 0.68))
        self.match_slider = ttk.Scale(match_frame, from_=0.40, to_=0.95, variable=self.match_var, orient="horizontal", command=self.on_match_change)
        self.match_slider.pack(side="left", fill="x", expand=True, padx=4)
        self.lbl_match = ttk.Label(match_frame, text=f"{int(self.match_var.get()*100)}%", width=6)
        self.lbl_match.pack(side="left", padx=2)

        # 2. Status Bar + Stop Recording Button
        status_frame = ttk.Frame(self, padding=5)
        status_frame.pack(fill="x", padx=10)
        self.lbl_status = ttk.Label(status_frame, text="Status: Idle", font=("Segoe UI", 9, "bold"), foreground="gray")
        self.lbl_status.pack(side="left")

        self.btn_stop_rec = ttk.Button(
            status_frame, text="Stop Recording Sample",
            command=self.stop_recording_sample, state="disabled"
        )
        self.btn_stop_rec.pack(side="left", padx=12)

        self.lbl_last_hit = ttk.Label(status_frame, text="Last Action: None", font=("Segoe UI", 9))
        self.lbl_last_hit.pack(side="right")

        # 3. 16 Sound Mapping Rows
        container = ttk.LabelFrame(self, text=" Physical Button to Audio File Mappings (16 Slots) ", padding=5)
        container.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)

        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.bind_all("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.build_slot_rows()

    def on_min_mode_change(self, event=None):
        self.config_data["minimize_mode"] = self.min_mode_var.get()
        self.save_config()

    def on_window_unmap(self, event):
        if event.widget == self and self.state() == "iconic":
            if self.min_mode_var.get() == "System Tray":
                self.withdraw()
                self.tray_icon.show()

    def restore_from_tray(self):
        self.tray_icon.hide()
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def on_close_app(self):
        self.tray_icon.hide()
        self.is_listening = False
        self.cancel_recording_flag = True
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.destroy()

    def reset_peak_rms(self):
        self.peak_rms_seen = 0.0
        self.lbl_live_rms.config(text="Live: 0.000 | Peak: 0.000")

    def build_slot_rows(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        headers = ["Slot Label", "Fingerprint", "Record Key", "Lockout(s)", "Custom Audio File (.wav, .mp3, .ogg)", "Browse", "Play"]
        for col, h in enumerate(headers):
            lbl = ttk.Label(self.scroll_frame, text=h, font=("Segoe UI", 9, "bold"))
            lbl.grid(row=0, column=col, padx=5, pady=4, sticky="w")

        for idx, slot in enumerate(self.config_data["slots"]):
            r = idx + 1

            name_var = tk.StringVar(value=slot["name"])
            ent_name = ttk.Entry(self.scroll_frame, textvariable=name_var, width=18)
            ent_name.grid(row=r, column=0, padx=4, pady=3)
            name_var.trace_add("write", lambda *_, i=idx, v=name_var: self.update_slot(i, "name", v.get()))

            sig_path = os.path.join(BASE_DIR, slot["sig_file"])
            has_sig = os.path.exists(sig_path)
            lbl_sig = ttk.Label(
                self.scroll_frame,
                text="Trained" if has_sig else "Empty",
                foreground="green" if has_sig else "red"
            )
            lbl_sig.grid(row=r, column=1, padx=4, pady=3)

            btn_rec = ttk.Button(self.scroll_frame, text="Record Key", width=11, command=lambda s=slot, l=lbl_sig: self.start_recording(s, l))
            btn_rec.grid(row=r, column=2, padx=4, pady=3)

            lock_var = tk.StringVar(value=str(slot.get("lockout", 0.5)))
            ent_lock = ttk.Entry(self.scroll_frame, textvariable=lock_var, width=8)
            ent_lock.grid(row=r, column=3, padx=4, pady=3)
            lock_var.trace_add("write", lambda *_, i=idx, v=lock_var: self.update_lockout(i, v.get()))

            path_var = tk.StringVar(value=slot["audio_path"])
            ent_path = ttk.Entry(self.scroll_frame, textvariable=path_var, width=32)
            ent_path.grid(row=r, column=4, padx=4, pady=3)
            path_var.trace_add("write", lambda *_, i=idx, v=path_var: self.update_slot(i, "audio_path", v.get()))

            btn_browse = ttk.Button(self.scroll_frame, text="...", width=4, command=lambda v=path_var: self.browse_audio_file(v))
            btn_browse.grid(row=r, column=5, padx=2, pady=3)

            btn_test = ttk.Button(self.scroll_frame, text="Play", width=6, command=lambda p=path_var: self.trigger_playback(p.get()))
            btn_test.grid(row=r, column=6, padx=4, pady=3)

    def show_help_window(self):
        help_win = tk.Toplevel(self)
        help_win.title("Soundboard - Quick Start Guide")
        help_win.geometry("580x580")
        help_win.minsize(520, 480)

        txt_frame = ttk.Frame(help_win, padding=12)
        txt_frame.pack(fill="both", expand=True)

        title_lbl = ttk.Label(txt_frame, text="Soundcard Direct Soundboard Deck - User Guide", font=("Segoe UI", 11, "bold"))
        title_lbl.pack(anchor="w", pady=(0, 8))

        guide_text = (
            "1. HARDWARE SETUP & ROUTING:\n"
            " • Soundcard Input: Select your physical sound card/hardware microphone.\n"
            " • Headphones: Select your real headset/speakers (WASAPI recommended).\n"
            " • Broadcast (Cable): Select CABLE Input (VB-Audio Virtual Cable).\n\n"
            "2. TRAINING PHYSICAL BUTTONS & STOP RECORDING:\n"
            " • Click 'Record Key' on any slot (changes to 'PRESS KEY...').\n"
            " • Press the physical pad on your soundcard once to save its FFT fingerprint.\n"
            " • Click 'Stop Recording Sample' on the status bar if you want to cancel immediately.\n\n"
            "3. PRECISION NOISE GATE & LOCKOUT:\n"
            " • Watch the 'Live / Peak' meter while idle, and set Noise Gate slightly above idle noise "
            "   using the slider or 0.001 spinbox.\n"
            " • Short sounds (Claps, Dinks): Keep lockout at 0.5s.\n"
            " • Long sounds/Songs (3s+): Set lockout to 3.5s or 4.0s to prevent double triggers.\n\n"
            "4. MINIMIZE TO TASKBAR OR TRAY:\n"
            " • Use 'When Minimized' in the top-right to choose between normal Taskbar minimizing "
            "   or hiding into the Windows System Tray (click tray icon to restore).\n\n"
            "5. DISCORD / VOICE CHAT INTEGRATION:\n"
            " • Set Discord Input Device to 'CABLE Output (VB-Audio Virtual Cable)' and disable Krisp."
        )

        lbl_guide = ttk.Label(txt_frame, text=guide_text, font=("Segoe UI", 9), justify="left", wraplength=530)
        lbl_guide.pack(anchor="w", fill="both", expand=True, pady=(0, 10))

        btn_close = ttk.Button(txt_frame, text="Got It", command=help_win.destroy)
        btn_close.pack(anchor="e", pady=(4, 0))

    def update_lockout(self, index, val_str):
        try:
            val = max(0.1, float(val_str))
            self.config_data["slots"][index]["lockout"] = val
            self.save_config()
            self.load_all_signatures()
        except ValueError:
            pass

    def browse_audio_file(self, target_var):
        selected = filedialog.askopenfilename(
            title="Select Custom Sound File",
            filetypes=[
                ("All Supported Audio", "*.wav *.mp3 *.ogg *.opus *.flac"),
                ("OGG Files", "*.ogg *.opus"),
                ("MP3 & WAV Files", "*.mp3 *.wav"),
                ("FLAC Files", "*.flac"),
                ("All Files", "*.*")
            ]
        )
        if selected:
            if selected in self.router.cache:
                del self.router.cache[selected]
            target_var.set(selected)
            self.load_all_signatures()

    def update_slot(self, index, field, value):
        self.config_data["slots"][index][field] = value
        self.save_config()
        self.load_all_signatures()

    def on_threshold_slider(self, val):
        v = round(float(val), 3)
        self.threshold_var.set(v)
        self.config_data["threshold"] = v
        self.save_config()

    def on_threshold_spin(self):
        try:
            v = round(max(0.001, min(0.500, float(self.threshold_var.get()))), 3)
            self.threshold_var.set(v)
            self.config_data["threshold"] = v
            self.save_config()
        except ValueError:
            pass

    def on_match_change(self, val):
        v = float(val)
        self.lbl_match.config(text=f"{int(v*100)}%")
        self.config_data["match_threshold"] = round(v, 2)
        self.save_config()

    def refresh_devices(self):
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        input_names = []
        output_names = ["None (Disabled)"]

        saved_in = self.config_data.get("in_device", "")
        saved_mon = self.config_data.get("monitor_device", "")
        saved_broad = self.config_data.get("broadcast_device", "")

        idx_in = 0
        idx_mon = 0
        idx_broad = 0

        for i, d in enumerate(devices):
            api_name = hostapis[d['hostapi']]['name']
            if "WDM-KS" in api_name:
                continue
            tag = f"[{i}] {d['name']} ({api_name})"

            if d['max_input_channels'] > 0:
                input_names.append(tag)
                if saved_in and saved_in == tag:
                    idx_in = len(input_names) - 1

            if d['max_output_channels'] > 0:
                output_names.append(tag)
                if saved_mon and saved_mon == tag:
                    idx_mon = len(output_names) - 1
                if saved_broad and saved_broad == tag:
                    idx_broad = len(output_names) - 1

        self.cb_in['values'] = input_names
        self.cb_monitor['values'] = output_names
        self.cb_broadcast['values'] = output_names

        if input_names:
            self.cb_in.current(idx_in)
        if output_names:
            self.cb_monitor.current(idx_mon)
            self.cb_broadcast.current(idx_broad)

    def parse_device_id(self, combo):
        val = combo.get()
        if not val or val.startswith("None"):
            return None
        return int(val.split(']')[0].replace('[', ''))

    def _open_resilient_input_stream(self, preferred_dev_id, callback):
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        pref_info = devices[preferred_dev_id]
        base_name = pref_info['name'][:18].lower()

        candidates = [preferred_dev_id]
        for i, d in enumerate(devices):
            if i != preferred_dev_id and d['max_input_channels'] > 0:
                api_name = hostapis[d['hostapi']]['name']
                if "WDM-KS" not in api_name and base_name in d['name'].lower():
                    candidates.append(i)

        last_err = None
        for cid in candidates:
            d_info = devices[cid]
            default_fs = int(d_info['default_samplerate'])
            max_ch = max(1, min(2, int(d_info['max_input_channels'])))

            for fs in [default_fs, 44100, 48000]:
                for ch in [1, max_ch]:
                    try:
                        stream = sd.InputStream(device=cid, channels=ch, samplerate=fs, blocksize=0, callback=callback)
                        stream.start()
                        return stream, fs, cid
                    except Exception as e:
                        last_err = e

        raise RuntimeError(f"Could not open mic: {str(last_err)[:70]}")

    def trigger_playback(self, file_path):
        mon_id = self.parse_device_id(self.cb_monitor)
        broad_id = self.parse_device_id(self.cb_broadcast)
        self.router.play(file_path, mon_id, broad_id)
        name = os.path.basename(file_path) if file_path else "Stop"
        self.lbl_last_hit.config(text=f"Played: {name}", foreground="blue")

    def stop_recording_sample(self):
        """Immediately aborts an active key-recording session."""
        if self.is_recording_key:
            self.cancel_recording_flag = True

    def start_recording(self, slot, status_label):
        if self.is_recording_key:
            self.cancel_recording_flag = True
            time.sleep(0.05)

        if self.is_listening:
            self.toggle_listening()

        dev_id = self.parse_device_id(self.cb_in)
        if dev_id is None:
            messagebox.showwarning("Warning", "Select your Soundcard input device first.")
            return

        self.is_recording_key = True
        self.cancel_recording_flag = False
        self.active_rec_label = status_label
        self.btn_stop_rec.config(state="normal")

        status_label.config(text="PRESS KEY...", foreground="orange")
        self.lbl_status.config(text=f"Waiting for audio peak from {slot['name']}...", foreground="orange")
        threading.Thread(target=self._record_worker, args=(dev_id, slot, status_label), daemon=True).start()

    def _update_rms_meter(self, rms):
        if rms > self.peak_rms_seen:
            self.peak_rms_seen = rms
        self.lbl_live_rms.config(text=f"Live: {rms:.3f} | Peak: {self.peak_rms_seen:.3f}")

    def _record_worker(self, dev_id, slot, status_label):
        thresh = self.config_data["threshold"]
        accum = np.array([], dtype=np.float32)
        recorded_chunks = []
        pre_chunk = None
        is_capturing = False
        chunks_needed = 6  # 6 chunks of 50ms = 300ms total capture
        active_fs = SAMPLE_RATE

        def callback(indata, frames, time_info, status):
            nonlocal accum, is_capturing, pre_chunk
            mono = np.mean(indata, axis=1) if indata.shape[1] > 1 else indata[:, 0]
            accum = np.concatenate((accum, mono.copy()))
            chunk_len = int(active_fs * (CHUNK_MS / 1000.0))

            while len(accum) >= chunk_len:
                audio = accum[:chunk_len]
                accum = accum[chunk_len:]
                rms = float(np.sqrt(np.mean(audio**2)))
                self.after(0, lambda r=rms: self._update_rms_meter(r))

                if not is_capturing:
                    if rms > thresh:
                        is_capturing = True
                        if pre_chunk is not None:
                            recorded_chunks.append(pre_chunk)
                        recorded_chunks.append(audio)
                    else:
                        pre_chunk = audio
                else:
                    if len(recorded_chunks) < chunks_needed:
                        recorded_chunks.append(audio)

        stream = None
        try:
            stream, active_fs, used_id = self._open_resilient_input_stream(dev_id, callback)
            timeout = time.time() + 8.0
            while len(recorded_chunks) < chunks_needed and time.time() < timeout and not self.cancel_recording_flag:
                time.sleep(0.02)
        except Exception as e:
            self.after(0, lambda: status_label.config(text="Error", foreground="red"))
            self.after(0, lambda err=e: self.lbl_status.config(text=f"Error: {str(err)[:65]}", foreground="red"))
            self.is_recording_key = False
            self.after(0, lambda: self.btn_stop_rec.config(state="disabled"))
            return
        finally:
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

        self.is_recording_key = False
        self.after(0, lambda: self.btn_stop_rec.config(state="disabled"))

        sig_exists = os.path.exists(os.path.join(BASE_DIR, slot["sig_file"]))

        if self.cancel_recording_flag:
            self.after(0, lambda: status_label.config(
                text="Trained" if sig_exists else "Empty",
                foreground="green" if sig_exists else "red"
            ))
            self.after(0, lambda: self.lbl_status.config(text="Status: Recording Stopped by User", foreground="gray"))
            return

        if len(recorded_chunks) >= chunks_needed:
            raw_clip = np.concatenate(recorded_chunks)
            if active_fs != SAMPLE_RATE:
                target_len = int(len(raw_clip) * SAMPLE_RATE / active_fs)
                orig_idx = np.linspace(0, len(raw_clip), len(raw_clip), endpoint=False)
                new_idx = np.linspace(0, len(raw_clip), target_len, endpoint=False)
                raw_clip = np.interp(new_idx, orig_idx, raw_clip).astype(np.float32)

            filepath = os.path.join(BASE_DIR, slot["sig_file"])
            sf.write(filepath, raw_clip, SAMPLE_RATE)
            self.load_all_signatures()
            self.after(0, lambda: status_label.config(text="Trained", foreground="green"))
            self.after(0, lambda: self.lbl_status.config(text=f"Trained {slot['name']}!", foreground="green"))
        else:
            self.after(0, lambda: status_label.config(
                text="Trained" if sig_exists else "Empty",
                foreground="green" if sig_exists else "red"
            ))
            self.after(0, lambda: self.lbl_status.config(text="Training timed out (press button louder/lower gate).", foreground="red"))

    def load_all_signatures(self):
        self.signatures.clear()
        for slot in self.config_data["slots"]:
            fpath = os.path.join(BASE_DIR, slot["sig_file"])
            if os.path.exists(fpath):
                try:
                    data, sr = sf.read(fpath, dtype='float32')
                    if data.ndim > 1:
                        data = np.mean(data, axis=1)
                    feat = extract_fingerprint(data)
                    if feat is not None:
                        self.signatures[slot["name"]] = {
                            "vector": feat,
                            "path": slot["audio_path"],
                            "lockout": float(slot.get("lockout", 0.5))
                        }
                except Exception as e:
                    print(f"[SIG LOAD ERROR] {e}")

    def toggle_listening(self):
        if self.is_listening:
            self.is_listening = False
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
            self.btn_toggle.config(text="Start Listening")
            self.lbl_status.config(text="Status: Stopped", foreground="gray")
        else:
            dev_id = self.parse_device_id(self.cb_in)
            if dev_id is None:
                messagebox.showerror("Error", "Select a valid Soundcard input device.")
                return

            self.load_all_signatures()
            if not self.signatures:
                messagebox.showwarning("No Fingerprints", "Train at least one button before starting.")
                return

            self.config_data["in_device"] = self.cb_in.get()
            self.config_data["monitor_device"] = self.cb_monitor.get()
            self.config_data["broadcast_device"] = self.cb_broadcast.get()
            self.save_config()

            try:
                self.prev_chunk = None
                self.capture_buffer = []
                self.is_capturing_live = False
                self.waiting_for_silence = False
                self.silent_chunks_count = 0
                self.raw_accumulator = np.array([], dtype=np.float32)

                self.stream, self.input_fs, used_id = self._open_resilient_input_stream(
                    dev_id, self.audio_listener_callback
                )
                self.is_listening = True
                self.btn_toggle.config(text="Stop Listening")
                self.lbl_status.config(text=f"Status: Listening Active (Dev [{used_id}])", foreground="green")
            except Exception as e:
                messagebox.showerror("Stream Error", f"Failed to start stream:\n{e}")

    def audio_listener_callback(self, indata, frames, time_info, status):
        mono = np.mean(indata, axis=1) if indata.shape[1] > 1 else indata[:, 0]
        self.raw_accumulator = np.concatenate((self.raw_accumulator, mono.copy()))
        chunk_len = int(self.input_fs * (CHUNK_MS / 1000.0))

        while len(self.raw_accumulator) >= chunk_len:
            audio = self.raw_accumulator[:chunk_len]
            self.raw_accumulator = self.raw_accumulator[chunk_len:]
            self._process_50ms_chunk(audio)

    def _process_50ms_chunk(self, audio):
        now = time.time()
        rms = float(np.sqrt(np.mean(audio**2)))
        thresh = self.config_data["threshold"]
        self.after(0, lambda r=rms: self._update_rms_meter(r))

        if self.waiting_for_silence:
            if rms > thresh * 0.85:  # Hysteresis: require dropping below 85% of gate to count as silence
                self.silent_chunks_count = 0
            else:
                self.silent_chunks_count += 1

            time_elapsed = now - self.last_trigger_time
            if time_elapsed >= self.active_lockout_duration and self.silent_chunks_count >= SILENCE_CHUNKS_REQUIRED:
                self.waiting_for_silence = False
                self.silent_chunks_count = 0
                self.prev_chunk = audio.copy()
            return

        if not self.is_capturing_live:
            if rms > thresh:
                self.is_capturing_live = True
                self.capture_buffer = []
                if self.prev_chunk is not None:
                    self.capture_buffer.append(self.prev_chunk)
                self.capture_buffer.append(audio.copy())
            else:
                self.prev_chunk = audio.copy()
        else:
            self.capture_buffer.append(audio.copy())
            # Collect 6 chunks (300ms total including pre-chunk) for accurate spectral matching
            if len(self.capture_buffer) >= 6:
                self.is_capturing_live = False
                full_clip = np.concatenate(self.capture_buffer)
                self.capture_buffer = []
                self.prev_chunk = None

                # Verify sustained energy so tiny 5ms static pops don't trigger buttons
                active_frames = np.sum(np.abs(full_clip) > (thresh * 0.7))
                if active_frames < int(len(full_clip) * 0.08):
                    return

                if self.input_fs != SAMPLE_RATE:
                    target_len = int(len(full_clip) * SAMPLE_RATE / self.input_fs)
                    orig_idx = np.linspace(0, len(full_clip), len(full_clip), endpoint=False)
                    new_idx = np.linspace(0, len(full_clip), target_len, endpoint=False)
                    full_clip = np.interp(new_idx, orig_idx, full_clip).astype(np.float32)

                live_feat = extract_fingerprint(full_clip)
                if live_feat is None:
                    return

                best_score = -1.0
                second_best = -1.0
                best_match = None
                matched_name = ""

                for name, sig in self.signatures.items():
                    score = float(np.dot(live_feat, sig["vector"]))
                    if score > best_score:
                        second_best = best_score
                        best_score = score
                        best_match = sig
                        matched_name = name
                    elif score > second_best:
                        second_best = score

                min_score = self.config_data.get("match_threshold", 0.68)
                if best_match and best_score >= min_score:
                    self.last_trigger_time = now
                    self.active_lockout_duration = best_match.get("lockout", 0.5)
                    self.waiting_for_silence = True
                    self.silent_chunks_count = 0

                    target_path = best_match["path"]
                    self.trigger_playback(target_path)
                    self.after(0, lambda n=matched_name, s=best_score: self.lbl_last_hit.config(
                        text=f"Triggered: {n} ({int(s*100)}%)", foreground="green"
                    ))
                else:
                    self.last_trigger_time = now
                    self.active_lockout_duration = 0.25
                    self.waiting_for_silence = True
                    self.silent_chunks_count = 0
                    self.after(0, lambda n=matched_name, s=best_score: self.lbl_last_hit.config(
                        text=f"Ignored: closest was {n} ({int(max(0, s)*100)}%)", foreground="orange"
                    ))

if __name__ == "__main__":
    app = SoundcardDirectDeckApp()
    app.mainloop()
