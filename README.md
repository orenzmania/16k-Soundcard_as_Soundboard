# 16k-Soundcard-Customized-
A software to convert those cheap soundcards into a soundboard deck.
This is vibecoded, so expect it to NOT have any features, late updates, and the usual. Maybe bugfixes if i find them, but idk.
ONLY SUPPORTS .WAV AND .MP3, CONVERT IF YOU HAVE .OGG, .M4A, ETC.

1. HARDWARE SETUP & ROUTING:
• F999 Input: Select your physical F999 sound card microphone. (or any cheap soundcard)
• Headphones: Select your real headset/speakers (WASAPI recommended).
• Broadcast (Cable): Select CABLE Input (VB-Audio Virtual Cable).
2. TRAINING PHYSICAL BUTTONS:
• Click 'Record Key' on any slot.
• The button will change to 'PRESS KEY...'.
• Press the physical pad on your F999 once. It will save a clean FFT fingerprint.
3. LOCKOUT SETTING (PREVENTING DOUBLE TRIGGERS):
• Short sounds (Claps, Dinks): Keep lockout at 0.5s.
• Long sounds/Songs (3s+): Set lockout to 3.5s or 4.0s so the script waits for the F999's internal audio tail to finish before re-arming.
4. DISCORD / VOICE CHAT INTEGRATION:
• In Discord Voice Settings, set Input Device to 'CABLE Output (VB-Audio Virtual Cable)'.
• Turn off Discord's 'Krisp' noise suppression and 'Echo Cancellation' so short sound clips aren't mistakenly filtered out as background noise.
