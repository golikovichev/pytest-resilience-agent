# Demo video credits

## Background music

- File: `technology_dreams.mp3`
- Source: royalty-free instrumental track from a free music library
- License: permits commercial use and redistribution; no track-level
  attribution required by the originating library

If you want to swap the music in your own fork, drop a replacement mp3 in
this folder and update `build_video.sh` (or the equivalent ffmpeg call) to
point at the new filename. Keep the `-stream_loop -1` flag so the audio
loops cleanly to fit the 180 s video duration.

## Slides

- Source: PIL-rendered PNGs from `videos/slides/make_slides.py`
- Fonts: Inter (SIL Open Font License) and Segoe UI / Consolas as fallbacks
- Palette: dark navy background, ember-orange accents, indigo highlights;
  full hex values live in the slide generator script

## Subtitles

- `videos/subtitles.srt` is the source of truth
- `videos/subtitles.ass` is the libass-rendered version with `PlayResY=1080`
  so the captions read at the correct size at 1080p playback
