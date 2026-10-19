"""Step 3 and 4: parse with Docling. The OCR engine is selectable so engines can be benchmarked."""
from __future__ import annotations

from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (PdfPipelineOptions, RapidOcrOptions,
                                                TesseractCliOcrOptions)
from docling.document_converter import DocumentConverter, PdfFormatOption

ENGINES = ("rapidocr", "tesseract")
_cache: dict[str, DocumentConverter] = {}


def converter(engine: str) -> DocumentConverter:
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {ENGINES}")
    if engine not in _cache:
        opts = PdfPipelineOptions()
        opts.do_ocr = True
        opts.do_table_structure = True
        if engine == "rapidocr":
            opts.ocr_options = RapidOcrOptions()
        else:
            opts.ocr_options = TesseractCliOcrOptions(lang=["eng"])  # installer ships eng only; add fra/deu traineddata for multilingual
        _cache[engine] = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return _cache[engine]


def parse(path: Path, engine: str):
    """Returns the DoclingDocument."""
    return converter(engine).convert(str(path)).document
