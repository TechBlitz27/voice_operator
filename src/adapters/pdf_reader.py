import pdfplumber
from typing import List
from src.core.interfaces.document import DocumentReader

class PDFReader(DocumentReader):
    """Production PDF text extraction adapter using pdfplumber."""

    def extract_text_chunks(self, file_path: str) -> List[str]:
        chunks: List[str] = []
        if not pdfplumber:
            raise ImportError("pdfplumber library not installed.")
            
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if not text:
                        continue
                    
                    # Split page text into paragraphs/lines
                    paragraphs = text.split("\n\n")
                    for p in paragraphs:
                        p_strip = p.strip()
                        if p_strip:
                            # Prepend page identifier metadata
                            chunks.append(p_strip)
                            
            return chunks
        except Exception as e:
            raise RuntimeError(f"Failed to read PDF document {file_path}: {e}")
