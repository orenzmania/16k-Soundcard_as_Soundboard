# 16k-Soundcard-Customized-
A software to convert those cheap soundcards into a soundboard deck.
This is vibecoded, so expect it to NOT have any features, late updates, and the usual. Maybe bugfixes if i find them, but idk.
**ONLY SUPPORTS .WAV AND .MP3, CONVERT IF YOU HAVE .OGG, .M4A, ETC.** *some .ogg files might work, but others might not, hence the recommendation to just convert.

# PREREQUISITE
pip install pyinstaller sounddevice soundfile numpy

# COMPILING
pyinstaller --onefile --noconsole --clean --name "Soundcard-SoundboardDeck" deck_player.py

# HOW TO USE
### 1. HARDWARE SETUP & ROUTING:
• Soundcard Input: Select your physical F999 sound card microphone. (or any cheap soundcard)
• Headphones: Select your real headset/speakers (WASAPI recommended).
• Broadcast (Cable): Select CABLE Input (VB-Audio Virtual Cable).
**WASAPI IS RECOMMENDED AS FIRST CHOICE, IF ITS NOT WORKING CHANGE IT TO MME.**
WDM-KS is finicky and thus not recommended to use.
### 2. TRAINING PHYSICAL BUTTONS:
• Click 'Record Key' on any slot.
• The button will change to 'PRESS KEY...'.
• Press the physical pad on your F999 once. It will save a clean FFT fingerprint.
### 3. LOCKOUT SETTING (PREVENTING DOUBLE TRIGGERS):
• Short sounds (Claps, Dinks): Keep lockout at 0.5s.
• Long sounds/Songs (3s+): Set lockout to 3.5s or 4.0s so the script waits for the Soundcards's internal audio tail to finish before re-arming.
### 4. DISCORD / VOICE CHAT INTEGRATION:
• In Discord Voice Settings, set Input Device to 'CABLE Output (VB-Audio Virtual Cable)'.
• Turn off Discord's 'Krisp' noise suppression and 'Echo Cancellation' so short sound clips aren't mistakenly filtered out as background noise.
