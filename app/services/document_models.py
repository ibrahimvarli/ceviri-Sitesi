from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class PDFPageSpec:
    width: float
    height: float
    rotation: int


@dataclass
class DocumentBlock:
    kind: str
    text: str
    font_size: float = 11.0
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    marker: str = ""
    columns: list[list[str]] = field(default_factory=list)

    def with_text(self, text: str) -> "DocumentBlock":
        return replace(self, text=text)


@dataclass
class PDFPageAnalysis:
    blocks: list[DocumentBlock]
    page_text: str


@dataclass
class PDFExtractionResult:
    pages: list[str]
    page_specs: list[PDFPageSpec]
    analyzed_pages: list[PDFPageAnalysis]
    page_count: int
    word_count: int
    char_count: int
