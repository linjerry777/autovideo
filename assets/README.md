# Audio Assets

Drop royalty-free MP3 files into the appropriate folders. The pipeline picks one at random per video and mixes it with the voice.

## Music (BGM under voice)

`audio_generator.py` reads `news.json["items"][i]["emotion"]` and picks from the matching folder. Fallback chain: `<emotion>/` → `generic/` → no BGM.

```
assets/music/
├─ surprise/    # 驚訝風 — twist reveals, pop hits
├─ fear/        # 緊張感 — minor key, low strings
├─ joy/         # 輕快 — upbeat, major key
├─ curiosity/   # 神秘 — ambient, building
├─ anger/       # 強烈節奏 — bass-heavy, urgent
└─ generic/     # fallback when emotion folder is empty
```

**Recommended sources:** YouTube Audio Library (free, commercial-safe), Pixabay Music, Free Music Archive.

**Format:** MP3, 30-90s loops work best (BGM gets looped to match voice length).

**Volume:** Music gets ducked to ~-12dB under the voice automatically (sidechaincompress).

## SFX (Hook attention-grabber)

Plays right before the first spoken word. ~0.3-0.5 seconds.

```
assets/sfx/hook/
├─ whoosh.mp3
├─ ding.mp3
├─ alert.mp3
└─ ...   # any number of files; pipeline picks one at random
```

**Recommended sources:** Pixabay (sfx category), Freesound.org (CC0 licensed).

**Format:** MP3, < 1 second.
