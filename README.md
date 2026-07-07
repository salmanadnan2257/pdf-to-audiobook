# PDF to Audiobook

A desktop tool that takes a batch of PDFs, lets you check what will actually
be read aloud, and converts them to mp3 audiobooks with a real progress
queue and one-click playback.

## Why it exists

Reading long PDFs on a screen is tiring. This tool turns a PDF (or several
at once) into audio so it can be listened to instead, using a plain Tkinter
interface instead of a web app or a subscription reader.

## Features

- **Drag-and-drop batch queue**: drop PDFs onto the window (or use Add
  Files for a native multi-select dialog) to build a queue, remove items,
  or clear it. If the optional `tkinterdnd2` package isn't installed, the
  drop target is simply skipped and the app falls back to Add Files only,
  it does not crash.
- **Per-file and overall progress**: conversion runs one page at a time in
  a background thread, so the queue shows a real "Converting page N/M" per
  file, and an overall progress bar advances as each file in the batch
  finishes. The GUI stays responsive during conversion instead of freezing.
- **Text preview and page range**: double-click a queued file (or use
  Preview / Page Range) to see the extracted text for a chosen page range
  before converting, and to restrict conversion to that range instead of
  always processing the whole document.
- **Voice options that do something**: language and regional accent (gTTS
  top-level domain, e.g. UK vs Indian English) are real dropdowns, and a
  "slow speech" checkbox maps to gTTS's own rate control. gTTS has no
  volume parameter at all, so there is no volume control here; a fake one
  would just be misleading.
- **Playback**: a Play Selected Output button runs the converted mp3
  through the first available local player (`ffplay`, `mpv`, `afplay`, or
  `aplay`, checked in that order). If none of those are installed, the app
  says so and gives the file path instead of failing silently.
- **Command line, no GUI needed**: `converter.py` is a full CLI with the
  same language/accent/rate/page-range/playback options, for scripting or
  headless testing.

## Architecture

Two files, same split as before, extended rather than replaced:

- `converter.py`: all conversion logic and no GUI dependency.
  `get_page_count`, `extract_text_from_pdf` and `extract_pages_from_pdf`
  read a PDF (optionally restricted to a page range); `convert_pdf_to_audio`
  synthesizes speech **one page at a time**, calling an optional
  `progress_callback(done, total)` after each page, then concatenates the
  resulting mp3 fragments by raw byte concatenation into one output file.
  This is not a "proper" mux, but standalone mp3 frames decode correctly
  back to back, and it was verified against every player used in testing.
  `find_audio_player`/`play_audio` locate and invoke a local player.
  A full argparse CLI exposes all of this headless.
- `main.py`: the Tkinter GUI. A `QueueItem` holds one file's path, page
  count, chosen page range, status, and output path. Conversion runs on a
  background `threading.Thread`; progress messages flow back to the main
  thread through a `queue.Queue` that the Tk event loop polls every 100ms
  with `root.after`, which is what keeps the window responsive during
  network calls instead of freezing like the previous single-threaded
  version did.

Text extraction uses PyPDF2. Speech synthesis uses gTTS, which calls Google
Translate's public text-to-speech endpoint over HTTPS. **This means the
converter needs an internet connection to work; there is no offline TTS
fallback.** No API key is required, but it depends on that external service
being reachable and is subject to its rate limits.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Drag-and-drop needs `tkinterdnd2`, which is in `requirements.txt`. If it
fails to install on your platform (it bundles a native Tk extension), the
app still runs fine, just without the drop target.

No environment variables are read (see `.env.example`).

## Usage

GUI:

```bash
python3 main.py
```

Drop PDFs onto the window or click Add Files, optionally double-click a
file to preview its text and restrict the page range, pick a language and
accent, click Convert All, and watch the queue and overall progress bar.
Once a file shows "Done", select it and click Play Selected Output. Output
mp3s are saved next to each source PDF in a `tts_pdf` folder.

Command line (no display needed):

```bash
python3 converter.py path/to/file.pdf
# with accent, slow speech, a page range, and playback afterward
python3 converter.py path/to/file.pdf -t co.uk --slow --start-page 2 --end-page 5 --play
```

## Challenges

- **GUI and conversion logic were one file, in an earlier pass.** The
  original script did file extraction, TTS, and all the Tkinter widget
  wiring in a single `main.py` with a module-level global list of
  filenames. Resolution: split the conversion logic into `converter.py`
  with plain functions that take no GUI state, and gave it its own CLI
  entry point so it can run and be verified headless. This overhaul built
  on top of that split instead of collapsing it back together.

- **Blocking the Tk main loop during conversion.** The previous version
  called gTTS directly from the button handler, so the whole window froze
  during every network call, worse once batches got longer. Resolution:
  conversion now runs on a `threading.Thread`, with progress reported back
  through a `queue.Queue` polled by `root.after`, since touching Tk widgets
  directly from a worker thread is not safe.

- **gTTS has no built-in progress hook for a single synthesis call.**
  Calling `gTTS(text=...).save()` on a whole document is one opaque network
  request with no way to report partial progress. Resolution: split
  synthesis per page instead of per document, call the progress callback
  after each page, and concatenate the resulting mp3 byte streams into one
  file. Verified with `file` that a page-range conversion (pages 2-3 of a
  3-page test PDF) produces a smaller, still-valid MPEG audio file than a
  full conversion of the same PDF.

- **PyPDF2 returns `None` for pages it can't extract text from** (common
  for scanned or image-only pages), and concatenating `None` with a string
  raises a `TypeError`. Resolution: `converter.py` falls back to an empty
  string per page (`page.extract_text() or ""`), and raises a clear
  `ValueError` if every page in the selected range has no extractable
  text, rather than silently producing an empty or missing audio file.
  Verified against a deliberately blank test PDF, which raises the
  expected `ValueError` instead of crashing or hanging.

- **No local audio player is guaranteed to exist.** Python's standard
  library has no audio playback API, so Play Selected Output shells out to
  `ffplay`, `mpv`, `afplay`, or `aplay`, whichever is found first with
  `shutil.which`. On a machine with none of those installed this silently
  did nothing in an early draft. Resolution: `play_audio` returns a plain
  boolean the GUI checks, showing a clear "no player found, open this file
  yourself" message with the real path instead of failing quietly.

- **Rewriting the deep-dive diagram for the new architecture surfaced a
  stale assumption in the previous draft.** The old sequence diagram showed
  `main.py` calling `convert_pdf_to_audio` once per file synchronously; the
  new version calls it from a worker thread with a callback flowing back
  through a queue, which needed a third lifeline (the queue) in the diagram
  rather than just two. Missing that lifeline in the first redraw made the
  progress-callback arrows look like they went directly from `converter.py`
  back into Tkinter widgets, which is exactly the unsafe cross-thread
  widget access the code deliberately avoids. Resolution: added the queue
  as its own actor in the diagram so the arrows match what the code
  actually does.

## What I learned

- Splitting per-page synthesis instead of whole-document synthesis is what
  actually unlocks real progress reporting; there was no way to get
  meaningful progress out of a single black-box gTTS call.
- Raw mp3 concatenation (just writing each fragment's bytes one after
  another to the same file handle) is a legitimate, if slightly informal,
  way to join mp3 streams because each frame carries its own header; a
  "proper" solution would need an extra dependency like `pydub`/`ffmpeg`
  just to do the same thing more slowly.
- A `queue.Queue` polled with `root.after` is a clean, low-dependency way
  to get worker-thread progress into a Tkinter UI without needing to touch
  Tk widgets from any thread but the main one.

## What I'd do differently

- Use a proper audio container library (`pydub`, or shelling out to
  `ffmpeg -f concat`) instead of raw mp3 byte concatenation. It worked in
  every test here, but it is relying on mp3's frame independence rather
  than a documented guarantee.
- Show connection errors from gTTS in the GUI status label with more
  specificity (currently they land in the queue's Status column as
  "Failed: <exception text>", which is honest but not friendly).
- Add a real test suite (pytest) around `converter.py` with checked-in
  sample PDFs, instead of relying on manual verification with
  generated ones.
- Support an offline TTS engine (like `pyttsx3`) as a fallback when gTTS
  can't reach the network, since the current version is unusable offline
  no matter how good the queue and preview UI get.
