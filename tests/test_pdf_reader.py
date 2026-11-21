import pytest
from unittest.mock import MagicMock, patch
from src.adapters.pdf_reader import PDFReader

def test_pdf_reader_extracts_text_chunks():
    """Verifies that PDF page text is correctly split into paragraphs and ordered."""
    reader = PDFReader()
    
    # Mock PDF structure
    mock_pdf = MagicMock()
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "This is paragraph 1.\n\nThis is paragraph 2."
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "This is page 2 paragraph."
    mock_pdf.pages = [mock_page1, mock_page2]
    
    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf
        chunks = reader.extract_text_chunks("mocked_doc.pdf")
        
        assert len(chunks) == 3
        assert chunks[0] == "This is paragraph 1."
        assert chunks[1] == "This is paragraph 2."
        assert chunks[2] == "This is page 2 paragraph."


def test_pdf_reader_empty_document():
    """Verifies that an empty PDF page with no extractable text returns empty chunks."""
    reader = PDFReader()
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = None  # Scanned or blank page
    mock_pdf.pages = [mock_page]
    
    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf
        chunks = reader.extract_text_chunks("blank.pdf")
        assert len(chunks) == 0


def test_pdf_reader_missing_file():
    """Verifies that attempting to load a nonexistent file path raises RuntimeError."""
    reader = PDFReader()
    with pytest.raises(RuntimeError):
        reader.extract_text_chunks("nonexistent_file_xyz.pdf")
