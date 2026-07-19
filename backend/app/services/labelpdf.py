"""Label sheet PDF rendering (reportlab, A4 portrait).

label_positions is a PURE layout function (unit-tested directly): sheet slots
are filled left-to-right, top-to-bottom, with skip_first leading positions left
empty (partially used sheet) and automatic page breaks past cols*rows.
All template dimensions are mm with y measured FROM THE TOP of the page;
render_batch_pdf converts to reportlab's bottom-left origin at draw time.
"""

from dataclasses import dataclass

import qrcode
import qrcode.constants
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdf_canvas

from app.models.labels import LabelTemplate

_PAD_MM = 2.0  # inner padding between label edge, QR and text
_TAG_FONT = ("Helvetica-Bold", 9)
_NAME_FONT = ("Helvetica", 7)
_CRUMB_FONT = ("Helvetica", 5.5)


@dataclass(frozen=True)
class LabelSpec:
    """One sticker's content: QR payload + human-readable lines."""

    tag: str
    qr_payload: str
    name: str | None = None
    breadcrumb: str | None = None


def label_positions(
    template: LabelTemplate, count: int, skip_first: int = 0
) -> list[tuple[int, int, int, float, float]]:
    """(page, col, row, x_mm, y_mm) of each label's top-left corner, in print
    order. Pages are 0-based; x/y are offsets from the page's top-left."""
    per_page = template.cols * template.rows
    positions: list[tuple[int, int, int, float, float]] = []
    for i in range(count):
        slot = skip_first + i
        page, index = divmod(slot, per_page)
        row, col = divmod(index, template.cols)
        x_mm = template.margin_left_mm + col * (template.label_w_mm + template.gutter_x_mm)
        y_mm = template.margin_top_mm + row * (template.label_h_mm + template.gutter_y_mm)
        positions.append((page, col, row, x_mm, y_mm))
    return positions


def _qr_image(payload: str) -> ImageReader:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=4,  # QR-spec quiet zone (4 modules) — matters on small stickers
        box_size=8,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").get_image()
    return ImageReader(img)


def _ellipsize(text: str, font: str, size: float, max_width_pt: float) -> str:
    """Trim with a trailing ellipsis to fit max_width_pt (empty when nothing fits)."""
    if stringWidth(text, font, size) <= max_width_pt:
        return text
    while text and stringWidth(text + "…", font, size) > max_width_pt:
        text = text[:-1]
    return text + "…" if text else ""


def render_batch_pdf(
    template: LabelTemplate, labels: list[LabelSpec], path: str, skip_first: int = 0
) -> None:
    """Render the sheet(s) to `path`: QR at template.qr_size_mm on the left of
    each label, tag text next to it, optional name/breadcrumb (per the
    template's show_* flags) ellipsized to the remaining width."""
    page_size = (template.page_w_mm * mm, template.page_h_mm * mm)
    canv = pdf_canvas.Canvas(path, pagesize=page_size)

    qr_side = min(
        template.qr_size_mm, template.label_h_mm - 2 * _PAD_MM, template.label_w_mm - 2 * _PAD_MM
    )
    current_page = 0
    for spec, (page, _col, _row, x_mm, y_mm) in zip(
        labels, label_positions(template, len(labels), skip_first)
    ):
        while page > current_page:
            canv.showPage()
            current_page += 1

        # Label frame in points, bottom-left origin.
        left = x_mm * mm
        top = (template.page_h_mm - y_mm) * mm
        bottom = top - template.label_h_mm * mm

        qr_pt = qr_side * mm
        qr_x = left + _PAD_MM * mm
        qr_y = bottom + (template.label_h_mm * mm - qr_pt) / 2  # vertically centered
        canv.drawImage(_qr_image(spec.qr_payload), qr_x, qr_y, qr_pt, qr_pt)

        text_x = qr_x + qr_pt + _PAD_MM * mm
        text_width = left + (template.label_w_mm - _PAD_MM) * mm - text_x

        lines: list[tuple[str, tuple[str, float]]] = [(spec.tag, _TAG_FONT)]
        if template.show_name and spec.name:
            lines.append((spec.name, _NAME_FONT))
        if template.show_breadcrumb and spec.breadcrumb:
            lines.append((spec.breadcrumb, _CRUMB_FONT))

        line_heights = [size * 1.35 for _, (_, size) in lines]
        block_h = sum(line_heights)
        cursor = bottom + (template.label_h_mm * mm + block_h) / 2  # block centered
        for (text, (font, size)), line_h in zip(lines, line_heights):
            cursor -= line_h
            canv.setFont(font, size)
            canv.drawString(text_x, cursor, _ellipsize(text, font, size, text_width))

    canv.showPage()
    canv.save()
