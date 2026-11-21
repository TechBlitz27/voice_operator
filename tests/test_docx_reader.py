import os
import pytest
import docx
from src.adapters.docx_reader import DOCXReader

def test_docx_reader_ignores_empty_paragraphs(tmp_path):
    """Verifies that empty paragraphs in Word documents are ignored during text chunking."""
    doc_path = os.path.join(tmp_path, "test_empty.docx")
    
    doc = docx.Document()
    doc.add_paragraph("First paragraph text.")
    doc.add_paragraph("")  # Empty paragraph
    doc.add_paragraph("Second paragraph text.")
    doc.save(doc_path)
    
    reader = DOCXReader()
    chunks = reader.extract_text_chunks(doc_path)
    
    assert len(chunks) == 2
    assert chunks[0] == "First paragraph text."
    assert chunks[1] == "Second paragraph text."


def test_docx_reader_preserves_unicode_and_ordering(tmp_path):
    """Verifies that paragraphs containing Unicode characters are correctly extracted in order."""
    doc_path = os.path.join(tmp_path, "test_unicode.docx")
    
    unicode_paragraphs = [
        "नमस्ते, आप कैसे हैं?",  # Hindi
        "café formatting",         # Accented
        "こんにちは"               # Japanese
    ]
    
    doc = docx.Document()
    for p in unicode_paragraphs:
        doc.add_paragraph(p)
    doc.save(doc_path)
    
    reader = DOCXReader()
    chunks = reader.extract_text_chunks(doc_path)
    
    assert len(chunks) == 3
    assert chunks[0] == unicode_paragraphs[0]
    assert chunks[1] == unicode_paragraphs[1]
    assert chunks[2] == unicode_paragraphs[2]


def test_docx_reader_missing_file():
    """Verifies that loading a nonexistent file raises RuntimeError."""
    reader = DOCXReader()
    with pytest.raises(RuntimeError):
        reader.extract_text_chunks("nonexistent_word_doc.docx")
