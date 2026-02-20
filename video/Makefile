.PHONY: studio render clips clips-narration clips-showcase clips-dry capture capture-darkmode check

studio:
	npx remotion studio

render:
	npx remotion render src/index.ts YapitTrailer out/trailer.mp4

clips:
	uv run generate_voice_clips.py

clips-narration:
	uv run generate_voice_clips.py --only narration

clips-showcase:
	uv run generate_voice_clips.py --only showcase

clips-dry:
	uv run generate_voice_clips.py --dry-run

capture:
	uv run capture_trailer.py --url "https://whatisintelligence.antikythera.org/chapter-01/" --light-mode

capture-darkmode:
	uv run capture_trailer.py --url "https://whatisintelligence.antikythera.org/chapter-01/" --light-mode --theme-cycle

check:
	npx tsc --noEmit && npx eslint src
