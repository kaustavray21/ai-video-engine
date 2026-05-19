import os
import re
import csv
import io
import logging
from dataclasses import dataclass
from typing import Optional

from apps.core.services.zip_extractor import FileEntry

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    success: bool
    text: str = ''
    error: str = ''
    skipped: bool = False


CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.vue', '.svelte',
    '.html', '.css', '.scss', '.sass',
    '.java', '.go', '.rs', '.cpp', '.c', '.h', '.cs', '.swift', '.kt', '.php', '.rb', '.dart',
    '.json', '.yaml', '.yml', '.toml', '.xml', '.env', '.sh', '.bash', '.zsh',
    '.dockerfile', '.makefile', '.mk', '.graphql', '.gql', '.sql',
}

SKIP_EXTENSIONS = {'.mp4', '.mp3', '.mov', '.avi', '.zip'}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}


class FileConverter:
    """
    Convert 30+ file types to plain text.

    Returns ConversionResult for each file. Skipped files (binaries,
    unsupported) have skipped=True but are not errors.
    """

    def convert(self, entry: FileEntry) -> ConversionResult:
        ext = entry.ext.lower()
        fname = os.path.basename(entry.abs_path)

        if ext in SKIP_EXTENSIONS:
            logger.debug(f'[FileConverter] {fname} — skipped (binary/archive)')
            return ConversionResult(success=True, skipped=True, text='')

        if ext == '.pdf':
            result = self._convert_pdf(entry)
        elif ext in ('.docx', '.doc'):
            result = self._convert_docx(entry)
        elif ext in ('.pptx', '.ppt'):
            result = self._convert_pptx(entry)
        elif ext in ('.txt', '.md'):
            result = self._read_utf8(entry)
        elif ext == '.rtf':
            result = self._convert_rtf(entry)
        elif ext in ('.xlsx', '.xls'):
            result = self._convert_xlsx(entry)
        elif ext == '.csv':
            result = self._convert_csv(entry)
        elif ext == '.ods':
            result = self._convert_ods(entry)
        elif ext == '.odp':
            result = self._convert_odp(entry)
        elif ext in CODE_EXTENSIONS:
            result = self._read_utf8(entry)
        elif ext in IMAGE_EXTENSIONS:
            result = self._convert_image(entry)
        elif ext == '.svg':
            result = self._convert_svg(entry)
        else:
            logger.debug(f'[FileConverter] {fname} — skipped (unsupported {ext})')
            return ConversionResult(success=True, skipped=True, text='')

        # Structured logging for the result
        if result.skipped:
            logger.info(f'[FileConverter] {ext} → {fname} skipped')
        elif result.success:
            logger.info(f'[FileConverter] {ext} → extracted {len(result.text):,} chars from {fname}')
        else:
            logger.warning(f'[FileConverter] {ext} → failed for {fname}: {result.error}')

        return result

    # ── PDF ──

    def _convert_pdf(self, entry: FileEntry) -> ConversionResult:
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(entry.abs_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return ConversionResult(success=True, text='\n'.join(text_parts))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── DOCX ──

    def _convert_docx(self, entry: FileEntry) -> ConversionResult:
        try:
            from docx import Document
            doc = Document(entry.abs_path)
            text = '\n'.join(p.text for p in doc.paragraphs)
            return ConversionResult(success=True, text=text)
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── PPTX ──

    def _convert_pptx(self, entry: FileEntry) -> ConversionResult:
        try:
            from pptx import Presentation
            prs = Presentation(entry.abs_path)
            text_parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, 'text') and shape.text.strip():
                        text_parts.append(shape.text)
            return ConversionResult(success=True, text='\n'.join(text_parts))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── RTF ──

    def _convert_rtf(self, entry: FileEntry) -> ConversionResult:
        try:
            from striprtf.striprtf import rtf_to_text
            with open(entry.abs_path, 'r', errors='replace') as f:
                raw = f.read()
            text = rtf_to_text(raw)
            return ConversionResult(success=True, text=text)
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── XLSX / XLS ──

    def _convert_xlsx(self, entry: FileEntry) -> ConversionResult:
        try:
            ext = os.path.splitext(entry.abs_path)[1].lower()
            rows = []

            if ext == '.xlsx':
                import openpyxl
                wb = openpyxl.load_workbook(entry.abs_path, read_only=True, data_only=True)
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    for row in ws.iter_rows(values_only=True):
                        # values_only=True → each cell is already the raw value
                        vals = [str(v) if v is not None else '' for v in row]
                        rows.append('\t'.join(vals))
                wb.close()
            else:
                import xlrd
                wb = xlrd.open_workbook(entry.abs_path)
                for sheet_name in wb.sheet_names():
                    ws = wb.sheet_by_name(sheet_name)
                    for rx in range(ws.nrows):
                        vals = [str(ws.cell_value(rx, cx)) if ws.cell_value(rx, cx) else '' for cx in range(ws.ncols)]
                        rows.append('\t'.join(vals))

            return ConversionResult(success=True, text='\n'.join(rows))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── CSV ──

    def _convert_csv(self, entry: FileEntry) -> ConversionResult:
        try:
            with open(entry.abs_path, 'r', errors='replace') as f:
                reader = csv.reader(f)
                rows = ['\t'.join(row) for row in reader]
            return ConversionResult(success=True, text='\n'.join(rows))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── ODS ──

    def _convert_ods(self, entry: FileEntry) -> ConversionResult:
        try:
            from odf.opendocument import load
            from odf.table import Table, TableRow, TableCell
            from odf.text import P
            doc = load(entry.abs_path)
            rows = []
            for table in doc.getElementsByType(Table):
                for row in table.getElementsByType(TableRow):
                    cells = []
                    for cell in row.getElementsByType(TableCell):
                        texts = [p.childRecursive() for p in cell.getElementsByType(P)]
                        cells.append(' '.join(''.join(t) for t in texts))
                    rows.append('\t'.join(cells))
            return ConversionResult(success=True, text='\n'.join(rows))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── ODP ──

    def _convert_odp(self, entry: FileEntry) -> ConversionResult:
        try:
            from odf.opendocument import load
            from odf.draw import Page
            from odf.text import P
            doc = load(entry.abs_path)
            text_parts = []
            for page in doc.getElementsByType(Page):
                for p in page.getElementsByType(P):
                    t = ''.join(p.childRecursive())
                    if t.strip():
                        text_parts.append(t)
            return ConversionResult(success=True, text='\n'.join(text_parts))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── UTF-8 (code / text / markup) ──

    def _read_utf8(self, entry: FileEntry) -> ConversionResult:
        try:
            with open(entry.abs_path, 'r', encoding='utf-8', errors='replace') as f:
                return ConversionResult(success=True, text=f.read())
        except Exception as e:
            return ConversionResult(success=False, error=str(e))

    # ── Image OCR (JPG / PNG) ──

    def _convert_image(self, entry: FileEntry) -> ConversionResult:
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(entry.abs_path)
            text = pytesseract.image_to_string(img)
            if text.strip():
                return ConversionResult(success=True, text=text)
            return ConversionResult(
                success=True, skipped=True,
                text=f'[Image: {os.path.basename(entry.abs_path)}]',
            )
        except Exception:
            logger.warning(f'OCR failed for {entry.abs_path}, using placeholder')
            return ConversionResult(
                success=True, skipped=True,
                text=f'[Image: {os.path.basename(entry.abs_path)}]',
            )

    # ── SVG ──

    def _convert_svg(self, entry: FileEntry) -> ConversionResult:
        try:
            import lxml.etree as ET
            tree = ET.parse(entry.abs_path)
            root = tree.getroot()
            texts = []
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    texts.append(elem.text.strip())
                if elem.tag == 'svg' and 'title' in elem.nsmap:
                    title = elem.find('.//svg:title', elem.nsmap)
                    if title is not None and title.text:
                        texts.append(title.text)
                if elem.tag == 'svg' and 'desc' in elem.nsmap:
                    desc = elem.find('.//svg:desc', elem.nsmap)
                    if desc is not None and desc.text:
                        texts.append(desc.text)
            for tag in ('{http://www.w3.org/2000/svg}title', '{http://www.w3.org/2000/svg}desc'):
                for el in root.iter(tag):
                    if el.text and el.text.strip():
                        texts.append(el.text.strip())
            return ConversionResult(success=True, text='\n'.join(texts))
        except Exception as e:
            return ConversionResult(success=False, error=str(e))
