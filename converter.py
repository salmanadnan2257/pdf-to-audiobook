"""Core PDF-to-audio conversion logic, kept separate from the GUI so it can
be tested and reused without a display.
"""
import os
import shutil
import subprocess

from PyPDF2 import PdfReader
from gtts import gTTS

# gTTS language codes worth exposing in a UI. Not exhaustive; gTTS supports
# many more (see gtts.lang.tts_langs()), this is a practical shortlist.
LANGUAGES = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Hindi": "hi",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese (Mandarin)": "zh-CN",
}

# gTTS top-level domains, which each carry a different regional accent for
# the same language (e.g. English read with a British vs Indian accent).
ACCENTS = {
    "Default (.com)": "com",
    "US (.com)": "com",
    "UK (.co.uk)": "co.uk",
    "Australia (.com.au)": "com.au",
    "India (.co.in)": "co.in",
    "Canada (.ca)": "ca",
    "Ireland (.ie)": "ie",
    "South Africa (.co.za)": "co.za",
}

# Players tried, in order, for local playback. Not every platform ships one
# of these, so `play_audio` reports honestly when none are found instead of
# pretending playback happened.
_PLAYER_COMMANDS = [
    ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpv", ["mpv", "--no-video", "--really-quiet"]),
    ("afplay", ["afplay"]),
    ("aplay", ["aplay", "-q"]),
]


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF."""
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        return len(reader.pages)


def extract_text_from_pdf(pdf_path: str, start_page: int = None, end_page: int = None) -> str:
    """Extract and concatenate the text of a page range in a PDF.

    `start_page`/`end_page` are 1-based and inclusive. Passing `None` for
    either extracts from the first/to the last page respectively.
    """
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        total = len(reader.pages)
        first = 1 if start_page is None else max(1, start_page)
        last = total if end_page is None else min(total, end_page)
        pages_text = []
        for i in range(first - 1, last):
            page_text = reader.pages[i].extract_text() or ""
            pages_text.append(page_text)
    return "\n".join(pages_text)


def extract_pages_from_pdf(pdf_path: str, start_page: int = None, end_page: int = None):
    """Like `extract_text_from_pdf`, but returns a list of per-page strings
    instead of one joined string, so callers can track progress page by
    page.
    """
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        total = len(reader.pages)
        first = 1 if start_page is None else max(1, start_page)
        last = total if end_page is None else min(total, end_page)
        return [reader.pages[i].extract_text() or "" for i in range(first - 1, last)]


def convert_pdf_to_audio(
    pdf_path: str,
    output_dir: str = None,
    lang: str = "en",
    tld: str = "com",
    slow: bool = False,
    start_page: int = None,
    end_page: int = None,
    progress_callback=None,
) -> str:
    """Extract the text from `pdf_path` and save it as an mp3.

    If `output_dir` is not given, a `tts_pdf` folder is created next to the
    source PDF. Returns the path to the saved mp3 file.

    `lang`/`tld` select gTTS's language and regional accent. `slow` maps to
    gTTS's own slow-speech flag, the closest thing it offers to a rate
    control (gTTS has no volume control at all, so there is no `volume`
    parameter here -- see README).

    Conversion runs one page at a time so `progress_callback(done, total)`
    can be called after each page, giving real per-file progress instead of
    a fake timer. The resulting per-page mp3 fragments are concatenated by
    plain byte concatenation, which decodes cleanly in every player tested
    (mp3 frames are self-contained) even though it is not a "proper" mux.
    """
    pages = extract_pages_from_pdf(pdf_path, start_page, end_page)
    non_empty_pages = [p for p in pages if p.strip()]
    if not non_empty_pages:
        raise ValueError(f"No extractable text found in '{pdf_path}' for the selected page range")

    pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
    if output_dir is None:
        output_dir = os.path.join(pdf_dir, "tts_pdf")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    save_path = os.path.join(output_dir, f"{base_name}_tts.mp3")

    total = len(pages)
    tmp_path = save_path + ".part"
    try:
        with open(tmp_path, "wb") as out:
            for i, page_text in enumerate(pages, start=1):
                if page_text.strip():
                    tts = gTTS(text=page_text, lang=lang, tld=tld, slow=slow)
                    tts.write_to_fp(out)
                if progress_callback is not None:
                    progress_callback(i, total)
        os.replace(tmp_path, save_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return save_path


def find_audio_player():
    """Return the (name, command) of the first available local audio player,
    or `None` if none of the ones this project knows about are installed.
    """
    for name, command in _PLAYER_COMMANDS:
        if shutil.which(command[0]):
            return name, command
    return None


def play_audio(path: str) -> bool:
    """Play `path` with the first available player, blocking until done.

    Returns `True` if a player was found and invoked, `False` if no known
    player is installed on this machine (caller should fall back to telling
    the user to open the file themselves).
    """
    found = find_audio_player()
    if found is None:
        return False
    _, command = found
    subprocess.run(command + [path], check=False)
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert a PDF's text to an mp3 audiobook (command line, no GUI)."
    )
    parser.add_argument("pdf", help="Path to the source PDF file")
    parser.add_argument(
        "-o", "--output-dir", default=None,
        help="Directory to save the mp3 in (default: <pdf folder>/tts_pdf)"
    )
    parser.add_argument(
        "-l", "--lang", default="en",
        help="gTTS language code (default: en)"
    )
    parser.add_argument(
        "-t", "--tld", default="com",
        help="gTTS top-level domain, selects regional accent (default: com)"
    )
    parser.add_argument(
        "--slow", action="store_true",
        help="Speak more slowly (gTTS's own rate control)"
    )
    parser.add_argument(
        "--start-page", type=int, default=None,
        help="First page to convert, 1-based (default: first page)"
    )
    parser.add_argument(
        "--end-page", type=int, default=None,
        help="Last page to convert, 1-based inclusive (default: last page)"
    )
    parser.add_argument(
        "--play", action="store_true",
        help="Play the resulting mp3 after conversion, if a local player is found"
    )
    args = parser.parse_args()

    def _print_progress(done, total):
        print(f"\rPage {done}/{total}", end="", flush=True)

    out_path = convert_pdf_to_audio(
        args.pdf, args.output_dir, args.lang, args.tld, args.slow,
        args.start_page, args.end_page, progress_callback=_print_progress,
    )
    print(f"\nSaved: {out_path}")

    if args.play:
        if not play_audio(out_path):
            print(f"No local audio player found (tried ffplay/mpv/afplay/aplay). Open '{out_path}' yourself.")
