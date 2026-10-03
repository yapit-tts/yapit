# Yapit

Free, open-source text-to-speech: listen to documents, web pages and text with natural-sounding voices. Yapit turns a web page, PDF, EPUB, image or markdown into a document you can read and play back.

- App: https://yapit.md
- Source: https://github.com/yapit-tts/yapit
- CLI: https://github.com/yapit-tts/yapit-cli, prints any of the inputs above as clean markdown

## Shared documents as markdown

A shared document at `https://yapit.md/listen/<id>` answers a request with `Accept: text/markdown` with its markdown. `https://yapit.md/listen/<id>/md` gives the same to any client, and `/listen/<id>/md-annotated` keeps the TTS annotations (`<yap-speak>`, `<yap-show>`, `<yap-cap>`). A document its owner has not shared answers 404 to anyone else.
