import docx
from typing import List
from src.core.interfaces.document import DocumentReader

class DOCXReader(DocumentReader):
    """Production Microsoft Word DOCX text extraction adapter using python-docx."""

    def extract_text_chunks(self, file_path: str) -> List[str]:
        chunks: List[str] = []
        try:
            doc = docx.Document(file_path)
            for p in doc.paragraphs:
                text_strip = p.text.strip()
                if text_strip:
                    chunks.append(text_strip)
            return chunks
        except Exception as e:
            raise RuntimeError(f"Failed to read DOCX document {file_path}: {e}")
