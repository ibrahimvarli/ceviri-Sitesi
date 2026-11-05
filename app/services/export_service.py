from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from reportlab.lib.colors import Color
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.services.document_models import DocumentBlock, PDFPageAnalysis, PDFPageSpec


PRIMARY_COLOR = Color(0.09, 0.18, 0.33)
MUTED_COLOR = Color(0.42, 0.47, 0.56)
ACCENT_COLOR = Color(0.10, 0.56, 0.86)
SURFACE_COLOR = Color(0.96, 0.97, 0.99)
BODY_FONT_NAME = "PTS-Body"
BODY_FONT_BOLD_NAME = "PTS-Body-Bold"
MONO_FONT_NAME = "PTS-Mono"
FONT_CANDIDATES = [
    ("c:\\Windows\\Fonts\\segoeui.ttf", "c:\\Windows\\Fonts\\segoeuib.ttf"),
    ("c:\\Windows\\Fonts\\calibri.ttf", "c:\\Windows\\Fonts\\calibrib.ttf"),
    ("c:\\Windows\\Fonts\\arial.ttf", "c:\\Windows\\Fonts\\arialbd.ttf"),
]
MONO_FONT_CANDIDATES = [
    "c:\\Windows\\Fonts\\consola.ttf",
    "c:\\Windows\\Fonts\\cour.ttf",
]


@dataclass
class ColumnItem:
    text: str
    font_name: str
    font_size: float
    color: Color
    spacing_after: float


def export_translated_pages(
    original_filename: str,
    source_language: str,
    target_language: str,
    original_page_analyses: list[PDFPageAnalysis],
    translated_page_analyses: list[PDFPageAnalysis],
    page_specs: list[PDFPageSpec],
    export_folder: Path,
) -> str:
    export_folder.mkdir(parents=True, exist_ok=True)

    safe_stem = Path(original_filename).stem or "translation"
    export_filename = f"{safe_stem}-translated-{uuid4().hex[:8]}.pdf"
    export_path = export_folder / export_filename

    _register_fonts()
    pdf = canvas.Canvas(str(export_path))
    pdf.setTitle(f"{safe_stem} - translated")
    pdf.setAuthor("PDF Translate Studio")
    pdf.setSubject(f"{source_language} to {target_language} translated PDF")
    pdf.setPageCompression(1)

    total_pages = max(len(original_page_analyses), len(translated_page_analyses))

    for page_index in range(total_pages):
        spec = (
            page_specs[page_index]
            if page_index < len(page_specs)
            else PDFPageSpec(595, 842, 0)
        )
        width, height = _normalize_page_size(spec)
        original_analysis = (
            original_page_analyses[page_index]
            if page_index < len(original_page_analyses)
            else PDFPageAnalysis(blocks=[], page_text="")
        )
        translated_analysis = (
            translated_page_analyses[page_index]
            if page_index < len(translated_page_analyses)
            else PDFPageAnalysis(blocks=[], page_text="")
        )

        left_items = _build_column_items(
            original_analysis.blocks,
            empty_message="Bu sayfada orijinal metin bulunamadi.",
        )
        right_items = _build_column_items(
            translated_analysis.blocks,
            empty_message="Bu sayfada cevrilmis metin bulunamadi.",
        )
        page_number = page_index + 1
        continuation = 0

        while left_items or right_items:
            pdf.setPageSize((width, height))
            _draw_page_chrome(
                pdf=pdf,
                width=width,
                height=height,
                original_filename=original_filename,
                source_language=source_language,
                target_language=target_language,
                page_number=page_number,
                continuation=continuation,
            )
            left_items, right_items = _draw_two_column_body(
                pdf,
                width,
                height,
                left_items,
                right_items,
            )
            pdf.showPage()
            continuation += 1

    pdf.save()
    return export_filename


def _normalize_page_size(spec: PDFPageSpec) -> tuple[float, float]:
    width, height = spec.width, spec.height
    if spec.rotation in {90, 270}:
        width, height = height, width
    return max(width, 420), max(height, 595)


def _register_fonts() -> None:
    if BODY_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return

    regular_path, bold_path = _resolve_font_paths()
    pdfmetrics.registerFont(TTFont(BODY_FONT_NAME, regular_path))
    pdfmetrics.registerFont(TTFont(BODY_FONT_BOLD_NAME, bold_path))
    mono_path = _resolve_mono_font_path()
    pdfmetrics.registerFont(TTFont(MONO_FONT_NAME, mono_path))


def _resolve_font_paths() -> tuple[str, str]:
    for regular_path, bold_path in FONT_CANDIDATES:
        if Path(regular_path).exists() and Path(bold_path).exists():
            return regular_path, bold_path
    raise FileNotFoundError("Unicode destekli PDF fontu bulunamadi.")


def _resolve_mono_font_path() -> str:
    for font_path in MONO_FONT_CANDIDATES:
        if Path(font_path).exists():
            return font_path
    return _resolve_font_paths()[0]


def _build_column_items(
    blocks: list[DocumentBlock],
    *,
    empty_message: str,
) -> list[ColumnItem]:
    if not blocks:
        return [ColumnItem(empty_message, BODY_FONT_NAME, 10.5, MUTED_COLOR, 10)]

    items: list[ColumnItem] = []
    for block in blocks:
        items.extend(_convert_block_to_items(block))
    return items


def _convert_block_to_items(block: DocumentBlock) -> list[ColumnItem]:
    if block.kind == "heading":
        return [ColumnItem(block.text, BODY_FONT_BOLD_NAME, 13.5, PRIMARY_COLOR, 12)]

    if block.kind == "bullet":
        return [ColumnItem(block.text, BODY_FONT_NAME, 11, PRIMARY_COLOR, 10)]

    if block.kind == "footnote":
        return [ColumnItem(block.text, BODY_FONT_NAME, 9.2, MUTED_COLOR, 8)]

    if block.kind == "table":
        rows = block.columns or [[block.text]]
        row_texts = [" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows]
        return [ColumnItem("\n".join(row_texts), MONO_FONT_NAME, 9.5, PRIMARY_COLOR, 10)]

    return [ColumnItem(block.text, BODY_FONT_NAME, 10.8, PRIMARY_COLOR, 10)]


def _draw_page_chrome(
    *,
    pdf: canvas.Canvas,
    width: float,
    height: float,
    original_filename: str,
    source_language: str,
    target_language: str,
    page_number: int,
    continuation: int,
) -> None:
    pdf.setFillColor(PRIMARY_COLOR)
    pdf.setFont(BODY_FONT_BOLD_NAME, 16)
    title = f"Cevrilmis PDF - Sayfa {page_number}"
    if continuation:
        title += f" (devam {continuation})"
    pdf.drawString(48, height - 52, title)

    pdf.setStrokeColor(ACCENT_COLOR)
    pdf.setLineWidth(1.2)
    pdf.line(48, height - 64, width - 48, height - 64)

    pdf.setFillColor(MUTED_COLOR)
    pdf.setFont(BODY_FONT_NAME, 9)
    pdf.drawString(48, height - 80, f"Orijinal dosya: {original_filename}")
    pdf.drawRightString(
        width - 48,
        height - 80,
        f"Diller: {source_language} -> {target_language}",
    )

    pdf.drawString(48, 28, "PDF Translate Studio tarafindan olusturuldu")
    pdf.drawRightString(width - 48, 28, f"Sayfa {page_number}")


def _draw_two_column_body(
    pdf: canvas.Canvas,
    width: float,
    height: float,
    left_items: list[ColumnItem],
    right_items: list[ColumnItem],
) -> tuple[list[ColumnItem], list[ColumnItem]]:
    margin_x = 48
    gutter = 18
    top_y = height - 112
    bottom_y = 50
    column_width = (width - (margin_x * 2) - gutter) / 2
    left_x = margin_x
    right_x = margin_x + column_width + gutter

    _draw_column_header(pdf, left_x, top_y + 14, column_width, "Orijinal")
    _draw_column_header(pdf, right_x, top_y + 14, column_width, "Ceviri")

    left_remaining = _draw_column_items(
        pdf,
        left_x,
        top_y - 14,
        bottom_y,
        column_width,
        left_items,
    )
    right_remaining = _draw_column_items(
        pdf,
        right_x,
        top_y - 14,
        bottom_y,
        column_width,
        right_items,
    )

    return left_remaining, right_remaining


def _draw_column_header(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    title: str,
) -> None:
    pdf.setFillColor(SURFACE_COLOR)
    pdf.roundRect(x, y - 18, width, 20, 6, fill=1, stroke=0)
    pdf.setFillColor(ACCENT_COLOR)
    pdf.setFont(BODY_FONT_BOLD_NAME, 10)
    pdf.drawString(x + 8, y - 5, title)


def _draw_column_items(
    pdf: canvas.Canvas,
    x: float,
    start_y: float,
    bottom_y: float,
    column_width: float,
    items: list[ColumnItem],
) -> list[ColumnItem]:
    remaining_items = list(items)
    current_y = start_y

    while remaining_items:
        item = remaining_items[0]
        wrapped_lines = _wrap_column_item(item, column_width)
        required_height = (len(wrapped_lines) * (item.font_size + 3)) + item.spacing_after

        if current_y - required_height < bottom_y:
            break

        text_object = pdf.beginText(x, current_y)
        text_object.setFont(item.font_name, item.font_size)
        text_object.setFillColor(item.color)

        for wrapped_line in wrapped_lines:
            text_object.textLine(wrapped_line)
            current_y -= item.font_size + 3

        pdf.drawText(text_object)
        current_y -= item.spacing_after
        remaining_items.pop(0)

    return remaining_items


def _wrap_column_item(item: ColumnItem, column_width: float) -> list[str]:
    wrapped_lines: list[str] = []
    for paragraph in item.text.split("\n"):
        if not paragraph.strip():
            wrapped_lines.append("")
            continue
        wrapped = simpleSplit(paragraph, item.font_name, item.font_size, column_width)
        wrapped_lines.extend(wrapped or [""])
    return wrapped_lines or [""]
