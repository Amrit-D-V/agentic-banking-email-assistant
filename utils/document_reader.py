import io
import logging
import shutil
from pathlib import Path
from typing import List

import pypdf
from PIL import Image, ImageOps, UnidentifiedImageError

from config.settings import settings

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".csv", ".log", ".md", ".json", ".eml"}
MAX_CHARS = 20000

try:
    import pytesseract

    OCR_AVAILABLE = shutil.which("tesseract") is not None
except ImportError:
    pytesseract = None
    OCR_AVAILABLE = False


def ocr_image(img: Image.Image) -> str:
    if not OCR_AVAILABLE:
        return "[OCR unavailable: install tesseract-ocr to read image attachments]"
    img = ImageOps.exif_transpose(img).convert("L")
    if min(img.size) < 1000:
        scale = 1000 / min(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return pytesseract.image_to_string(img, lang=settings.OCR_LANGUAGES).strip()


def extract_text_from_pdf(pdf_path: str) -> str:
    path = Path(pdf_path)
    if not path.exists():
        return f"[Error: PDF file {path.name} does not exist]"
    pages: List[str] = []
    try:
        reader = pypdf.PdfReader(str(path))
        for idx, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if not text:
                ocr_parts = []
                for image in page.images:
                    try:
                        ocr_parts.append(ocr_image(Image.open(io.BytesIO(image.data))))
                    except Exception as e:
                        log.warning("OCR failed on %s page %d: %s", path.name, idx, e)
                text = "\n".join(p for p in ocr_parts if p)
                if text:
                    text = f"[OCR]\n{text}"
            if text:
                pages.append(f"--- Page {idx} ---\n{text}")
        return "\n\n".join(pages)
    except Exception as e:
        return f"[Error reading PDF {path.name}: {e}]"


def extract_text_from_image(image_path: str) -> str:
    try:
        with Image.open(image_path) as img:
            frames = []
            for i in range(getattr(img, "n_frames", 1)):
                img.seek(i)
                frames.append(ocr_image(img.copy()))
            return "\n".join(f for f in frames if f)
    except UnidentifiedImageError:
        return f"[Unsupported or corrupt image: {Path(image_path).name}]"


def extract_text_from_attachment(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        return f"[Attachment not found: {path.name}]"
    try:
        head = path.read_bytes()[:8]
        if head.startswith(b"%PDF") or path.suffix.lower() == ".pdf":
            text = extract_text_from_pdf(str(path))
        elif path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
        else:
            try:
                Image.open(path).verify()
                text = extract_text_from_image(str(path))
            except (UnidentifiedImageError, OSError):
                text = f"[Unsupported attachment type: {path.suffix or 'unknown'}]"
    except Exception as e:
        text = f"[Error reading attachment {path.name}: {e}]"
    return text[:MAX_CHARS]
