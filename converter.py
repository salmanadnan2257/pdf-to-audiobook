"""Core PDF-to-audio conversion logic, kept separate from the GUI so it can
be tested and reused without a display.
"""
import os

from PyPDF2 import PdfReader
from gtts import gTTS


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract and concatenate the text of every page in a PDF."""
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        pages_text = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            pages_text.append(page_text)
    return "\n".join(pages_text)


def convert_pdf_to_audio(pdf_path: str, output_dir: str = None, lang: str = "en") -> str:
    """Extract the text from `pdf_path` and save it as an mp3.

    If `output_dir` is not given, a `tts_pdf` folder is created next to the
    source PDF. Returns the path to the saved mp3 file.
    """
    text = extract_text_from_pdf(pdf_path)
    if not text.strip():
        raise ValueError(f"No extractable text found in '{pdf_path}'")

    pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
    if output_dir is None:
        output_dir = os.path.join(pdf_dir, "tts_pdf")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    save_path = os.path.join(output_dir, f"{base_name}_tts.mp3")

    tts = gTTS(text=text, lang=lang)
    tts.save(save_path)
    return save_path


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
    args = parser.parse_args()

    out_path = convert_pdf_to_audio(args.pdf, args.output_dir, args.lang)
    print(f"Saved: {out_path}")
