# PDF to Audiobook

A small desktop tool that takes one or more PDFs, pulls out the text, and
saves each one as an mp3 you can listen to instead of read.

## Why it exists

Reading long PDFs on a screen is tiring. This tool turns a PDF into audio so
it can be listened to instead, using a plain Tkinter file picker instead of a
web app or a subscription reader.

## Features

- Pick one or more PDF files through a native file dialog, or add more to an
  existing selection.
- Extracts text from every page of each PDF and joins it into one document.
- Converts the extracted text to speech and saves it as an mp3 next to the
  source PDF, inside a `tts_pdf` folder.
- Also works from the command line with no GUI, for scripting or testing.

## Architecture

Two files:

- `converter.py`: all the conversion logic (`extract_text_from_pdf`,
  `convert_pdf_to_audio`) with no GUI dependency, plus a small argparse CLI so
  it can be run and tested headless.
- `main.py`: the Tkinter GUI (Select Files, Add Files, Convert buttons and a
  status label) that calls into `converter.py`.

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

No environment variables are read (see `.env.example`).

## Usage

GUI:

```bash
python3 main.py
```

Select one or more PDFs, click Convert, and find the mp3s in a `tts_pdf`
folder next to each source PDF.

Command line (no display needed):

```bash
python3 converter.py path/to/file.pdf
# or with a custom output directory and language
python3 converter.py path/to/file.pdf -o path/to/output_folder -l en
```

## Challenges

- **GUI and conversion logic were one file.** The original script did file
  extraction, TTS, and all the Tkinter widget wiring in a single `main.py`
  with a module-level global list of filenames. That made it impossible to
  test the conversion step without opening a window. Resolution: split the
  conversion logic into `converter.py` with two plain functions
  (`extract_text_from_pdf`, `convert_pdf_to_audio`) that take no GUI state,
  and gave it its own CLI entry point so it can run and be verified headless.

- **PyPDF2 returns `None` for pages it can't extract text from** (common for
  scanned or image-only pages), and concatenating `None` with a string raises
  a `TypeError`. Resolution: `converter.py` falls back to an empty string per
  page (`page.extract_text() or ""`) so a single bad page doesn't crash the
  whole batch, and raises a clear `ValueError` if a PDF has no extractable
  text at all rather than silently producing an empty audio file.

- **Path handling used string splitting instead of `os.path`.** The original
  built the output folder and filename by splitting on `'/'`
  (`filename.split('/')[:-1]`), which only works on POSIX paths and breaks on
  Windows. Resolution: rewritten with `os.path.dirname`, `os.path.basename`,
  `os.path.splitext`, and `os.makedirs(exist_ok=True)`, which is also simpler
  than the original's open-to-check-then-mkdir pattern.

- **Directory creation raced its own existence check.** The original tried to
  `open(dir, 'r')` to see if the output folder existed, and created it only in
  the `FileNotFoundError` handler, silently swallowing `PermissionError`
  instead of surfacing it. Resolution: `os.makedirs(output_dir,
  exist_ok=True)` does this in one call with no race and no silent failure
  mode.

- **No sample input shipped with the project**, so there was nothing to
  verify the conversion against without opening the GUI and picking a real
  file by hand. Resolution: verified the CLI path end to end against a
  generated one-line test PDF (see Setup/Usage above); this produced a real
  playable mp3, confirmed with `file` reporting valid MPEG audio.

- **External TTS dependency isn't obvious from the GUI.** Nothing in the
  interface tells the user that Convert needs internet access, so a failure
  on a machine with no network looks like a bug rather than a connectivity
  issue. Resolution documented here rather than fixed in code, since the
  fix (a clear error message on connection failure) would go beyond the
  batching change already made to `convert_pdf_to_tts`.

- **A `\\` line break inside a bare TikZ node broke the deep-dive PDF's
  build.** While diagramming the `main.py` → `converter.py` call in
  `docs/explainers/deep-dive.pdf`, a sequence-diagram node label used
  `{calls\\convert\_pdf\_to\_audio()}` without an `align=center` option,
  which `pdflatex` rejected with "Something's wrong--perhaps a missing
  \item" because a manual line break needs a multi-line text mode to land
  in. Resolution: added `align=center` to that node's options, which is
  also what every other multi-line node in the diagram already used.

## What I learned

- Splitting GUI event handlers from the underlying work makes headless
  testing possible, and it's a small refactor once you see the seam (any
  function that doesn't touch a widget can move out).
- `PyPDF2.PdfReader.extract_text()` returning `None` instead of an empty
  string on a bad page is an easy default to miss and an easy crash to cause;
  it's worth handling explicitly instead of assuming extraction always
  returns a string.
- `os.path` functions replace manual `split('/')` path handling with code
  that is both shorter and portable across operating systems.

## What I'd do differently

- Show connection errors from gTTS in the GUI status label instead of only
  printing to the console, so a failed conversion because of no internet
  access looks different from a failed conversion because of a bad PDF.
- Run conversion on a background thread; right now `convert_pdf_to_tts`
  blocks the Tkinter main loop while gTTS makes network calls, so the window
  is unresponsive during a multi-file conversion.
- Add a real test suite (pytest) around `converter.py` with a checked-in
  sample PDF, instead of relying on manual verification.
- Support an offline TTS engine (like `pyttsx3`) as a fallback when gTTS
  can't reach the network, since the current version is unusable offline.
