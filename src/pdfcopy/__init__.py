"""Copy continuous paragraphs from any PDF."""

from pdfcopy.extract import ExtractResult, extract, extract_text
from pdfcopy.writeback import fix_pdf

__all__ = ["ExtractResult", "extract", "extract_text", "fix_pdf"]
__version__ = "0.1.2"
