from abc import ABC, abstractmethod
from typing import List

class DocumentReader(ABC):
    """Interface for extracting text content from physical files."""

    @abstractmethod
    def extract_text_chunks(self, file_path: str) -> List[str]:
        """Extracts text from a physical document as a list of readable blocks (e.g. paragraphs).

        Args:
            file_path: Absolute or relative path to the target document.

        Returns:
            A list of strings representing the document contents chunked by semantic sections.
        """
        pass
