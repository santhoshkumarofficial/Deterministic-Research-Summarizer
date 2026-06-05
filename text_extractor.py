import pdfplumber
import fitz
import pytesseract
import pandas as pd
import json
import os
import re
import io
import hashlib
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
import shutil

tesseract_path = shutil.which("tesseract") or r'C:\Program Files\Tesseract-OCR\tesseract.exe'
pytesseract.pytesseract.tesseract_cmd = tesseract_path

import tempfile

FIGURES_DIR = os.path.join(os.path.dirname(__file__), "data", "figures")
PAPERS_DIR  = os.path.join(os.path.dirname(__file__), "data", "papers")

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(PAPERS_DIR,  exist_ok=True)



@dataclass
class FigureSchema:
    figure_id:    str
    page_number:  int
    bounding_box: dict

    caption_text:       str  = ""
    caption_claim:      str  = ""
    figure_number_raw:  str  = ""

    ocr_raw_text:             str  = ""
    x_axis_label:             str  = ""
    y_axis_label:             str  = ""
    x_tick_values:            list = field(default_factory=list)
    y_tick_values:            list = field(default_factory=list)
    legend_items:             list = field(default_factory=list)
    numeric_values_in_figure: list = field(default_factory=list)

    figure_type:         str  = ""
    primary_insight:     str  = ""
    comparison_entities: list = field(default_factory=list)
    performance_range:   dict = field(default_factory=dict)
    trend_direction:     str  = ""

    extraction_confidence: str  = ""
    integrity_status:      str  = ""
    integrity_flags:       list = field(default_factory=list)
    figure_hash:           str  = ""
    extraction_timestamp:  str  = ""



class CaptionExtractor:

    CAPTION_PATTERNS = [
        r'(Fig(?:ure)?\.?\s*\d+[a-z]?)\s*[:\.\-]?\s*(.*)',
        r'(FIGURE\s*\d+[a-z]?)\s*[:\.\-]?\s*(.*)',
    ]

    def extract_caption(self, page: fitz.Page, fig_bbox: fitz.Rect) -> dict:
        result = {"caption_text": "", "figure_number_raw": "", "caption_claim": ""}

        search_zones = [
            fitz.Rect(fig_bbox.x0 - 20, fig_bbox.y1,      fig_bbox.x1 + 20, fig_bbox.y1 + 100),
            fitz.Rect(fig_bbox.x0 - 20, fig_bbox.y0 - 60, fig_bbox.x1 + 20, fig_bbox.y0),
        ]

        all_blocks = page.get_text("blocks")

        for zone in search_zones:
            for block in all_blocks:
                bx0, by0, bx1, by1, text = block[:5]
                if not text.strip():
                    continue
                if fitz.Rect(bx0, by0, bx1, by1).intersects(zone):
                    for pattern in self.CAPTION_PATTERNS:
                        match = re.search(pattern, text.strip(), re.IGNORECASE | re.DOTALL)
                        if match:
                            result["figure_number_raw"] = match.group(1).strip()
                            result["caption_text"]      = text.strip()
                            result["caption_claim"]     = self._extract_claim(match.group(2).strip())
                            return result

        for zone in search_zones:
            for block in all_blocks:
                bx0, by0, bx1, by1, text = block[:5]
                if fitz.Rect(bx0, by0, bx1, by1).intersects(zone) and text.strip():
                    result["caption_text"]  = text.strip()[:300]
                    result["caption_claim"] = self._extract_claim(text.strip())
                    break

        return result

    def _extract_claim(self, caption_body: str) -> str:
        if not caption_body:
            return ""
        sentences = re.split(r'(?<=[.!?])\s+', caption_body)
        claim_keywords = [
            'accuracy', 'performance', 'comparison', 'result', 'show',
            'demonstrate', 'achieve', 'outperform', 'loss', 'precision',
            'recall', 'f1', 'error', 'training', 'evaluation',
            'proposed', 'versus', 'vs'
        ]
        for sent in sentences:
            if any(kw in sent.lower() for kw in claim_keywords):
                return sent.strip()
        return sentences[0].strip() if sentences else caption_body[:200]



class FigureOCRExtractor:

    NUMERIC_PATTERN = re.compile(r'\b\d+(?:\.\d+)?(?:%|k|K|M|B)?\b')

    X_AXIS_KEYWORDS = ['epoch', 'iteration', 'step', 'model', 'method',
                       'class', 'category', 'dataset', 'layer', 'sample']
    Y_AXIS_KEYWORDS = ['accuracy', 'loss', 'precision', 'recall', 'f1',
                       'score', 'rate', 'value', 'error', 'perplexity', '%']

    def extract_from_image(self, img: Image.Image) -> dict:
        processed = self._preprocess(img)
        try:
            ocr_data  = pytesseract.image_to_data(
                processed, output_type=pytesseract.Output.DICT,
                config='--psm 11 --oem 3'
            )
            full_text = pytesseract.image_to_string(processed, config='--psm 6')
        except Exception as e:
            return self._empty(f"OCR failed: {e}")

        return {
            "ocr_raw_text":             full_text.strip(),
            "x_axis_label":             self._detect_x_axis(img, ocr_data, full_text),
            "y_axis_label":             self._detect_y_axis(img, ocr_data, full_text),
            "x_tick_values":            self._extract_ticks(img, ocr_data, axis='x'),
            "y_tick_values":            self._extract_ticks(img, ocr_data, axis='y'),
            "legend_items":             self._extract_legend(ocr_data, full_text),
            "numeric_values_in_figure": self._extract_numerics(full_text),
        }

    def _preprocess(self, img: Image.Image) -> Image.Image:
        img_gray  = img.convert('L')
        enhancer  = ImageEnhance.Contrast(img_gray)
        img_c     = enhancer.enhance(2.0)
        img_sharp = img_c.filter(ImageFilter.SHARPEN)
        w, h      = img_sharp.size
        if w < 400:
            scale     = 400 / w
            img_sharp = img_sharp.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        return img_sharp

    def _detect_x_axis(self, img, ocr_data, full_text) -> str:
        w, h     = img.size
        words    = ocr_data.get('text', [])
        tops     = ocr_data.get('top', [])
        confs    = ocr_data.get('conf', [])
        bottom_w = [words[i].lower() for i in range(len(words))
                    if words[i].strip() and tops[i] > h * 0.75 and int(confs[i]) > 30]
        for kw in self.X_AXIS_KEYWORDS:
            for w_item in bottom_w:
                if kw in w_item:
                    return kw.capitalize()
        return ' '.join(bottom_w[:3]).strip() if bottom_w else ""

    def _detect_y_axis(self, img, ocr_data, full_text) -> str:
        w, h   = img.size
        words  = ocr_data.get('text', [])
        lefts  = ocr_data.get('left', [])
        confs  = ocr_data.get('conf', [])
        left_w = [words[i].lower() for i in range(len(words))
                  if words[i].strip() and lefts[i] < w * 0.2 and int(confs[i]) > 30]
        for kw in self.Y_AXIS_KEYWORDS:
            for w_item in left_w:
                if kw in w_item:
                    return kw.capitalize()
        for kw in self.Y_AXIS_KEYWORDS:
            if kw in full_text.lower():
                return kw.capitalize()
        return ""

    def _extract_ticks(self, img, ocr_data, axis: str) -> list:
        w, h  = img.size
        words = ocr_data.get('text', [])
        lefts = ocr_data.get('left', [])
        tops  = ocr_data.get('top', [])
        confs = ocr_data.get('conf', [])
        ticks = []
        seen  = set()
        for i in range(len(words)):
            word = words[i].strip()
            if not word or int(confs[i]) < 20:
                continue
            is_tick = bool(re.match(r'^[\d\.\%\-]+$', word)) or len(word) <= 15
            if axis == 'y' and lefts[i] < w * 0.2 and is_tick and word not in seen:
                ticks.append(word); seen.add(word)
            elif axis == 'x' and tops[i] > h * 0.7 and is_tick and word not in seen:
                ticks.append(word); seen.add(word)
        return ticks[:15]

    def _extract_legend(self, ocr_data, full_text) -> list:
        known = ['proposed', 'baseline', 'resnet', 'bert', 'vgg', 'model a',
                 'model b', 'train', 'test', 'val', 'validation', 'deepgram',
                 'whisper', 'our method']
        found = [kw.title() for kw in known if kw in full_text.lower()]
        for line in full_text.split('\n'):
            line = line.strip()
            if 3 <= len(line) <= 25 and '(' not in line and '=' not in line:
                if re.search(r'[A-Z][a-z]', line) and line not in found:
                    found.append(line)
        return found[:8]

    def _extract_numerics(self, text: str) -> list:
        return list(set(self.NUMERIC_PATTERN.findall(text)))[:20]

    def _empty(self, reason: str) -> dict:
        return {"ocr_raw_text": reason, "x_axis_label": "", "y_axis_label": "",
                "x_tick_values": [], "y_tick_values": [],
                "legend_items": [], "numeric_values_in_figure": []}



class FigureSemanticAnalyzer:

    def analyze(self, schema: FigureSchema, img: Image.Image) -> FigureSchema:
        schema.figure_type         = self._classify(schema, img)
        schema.comparison_entities = self._entities(schema)
        schema.performance_range   = self._perf_range(schema)
        schema.trend_direction     = self._trend(schema)
        schema.primary_insight     = self._insight(schema)
        return schema

    def _classify(self, schema: FigureSchema, img: Image.Image) -> str:
        combined = (schema.caption_text + " " + schema.caption_claim + " " +
                    schema.ocr_raw_text).lower()
        rules = [
            (['confusion matrix', 'confusion'],                  'confusion_matrix'),
            (['roc curve', 'roc-auc', 'auc'],                    'roc_curve'),
            (['training loss', 'val loss', 'loss curve',
              'learning curve', 'convergence'],                   'line_chart_loss'),
            (['accuracy over', 'precision-recall',
              'f1 over epoch', 'vs epoch'],                       'line_chart_metric'),
            (['comparison', 'vs', 'versus', 'baseline',
              'benchmark', 'bar chart'],                          'bar_chart'),
            (['scatter', 'distribution', 'cluster'],              'scatter_plot'),
            (['architecture', 'framework', 'pipeline',
              'flow', 'diagram', 'overview', 'system'],           'architecture_diagram'),
            (['attention', 'heatmap', 'heat map',
              'visualization', 'feature map'],                    'heatmap'),
        ]
        for keywords, fig_type in rules:
            if any(kw in combined for kw in keywords):
                return fig_type
        img_arr = np.array(img.convert('RGB'))
        if len(np.unique(img_arr.reshape(-1, 3), axis=0)) < 500:
            return 'diagram_or_simple_graphic'
        return 'other'

    def _entities(self, schema: FigureSchema) -> list:
        entities = set(schema.legend_items)
        model_patterns = [
            r'\b(BERT|GPT|T5|ResNet|VGG|LSTM|CNN|RNN|Transformer|Whisper|'
            r'Gemma|LLaMA|Deepgram|BART|XLNet|RoBERTa|EfficientNet|'
            r'Inception|MobileNet|DenseNet|AlexNet|ViT)\b',
            r'\bproposed (?:model|method|system|approach)\b',
            r'\bbaseline\b',
        ]
        combined = schema.caption_text + " " + schema.ocr_raw_text
        for pat in model_patterns:
            for m in re.findall(pat, combined, re.IGNORECASE):
                entities.add(m.strip())
        return list(entities)[:8]

    def _perf_range(self, schema: FigureSchema) -> dict:
        nums = []
        for v in schema.numeric_values_in_figure:
            try:
                nums.append(float(v.replace('%', '').replace('k', '000').replace('K', '000')))
            except ValueError:
                continue
        if not nums:
            return {}
        combined = schema.caption_text + " " + schema.ocr_raw_text
        unit = ("%"          if '%' in schema.ocr_raw_text or 'accuracy' in combined.lower()
                else "loss_value" if 'loss' in combined.lower()
                else "seconds"    if 'time' in combined.lower() or 'second' in combined.lower()
                else "")
        return {"min": round(min(nums), 4), "max": round(max(nums), 4),
                "unit": unit, "count": len(nums)}

    def _trend(self, schema: FigureSchema) -> str:
        if schema.figure_type in ['architecture_diagram', 'confusion_matrix',
                                   'bar_chart', 'heatmap']:
            return "N/A"
        combined = schema.caption_text.lower() + " " + schema.caption_claim.lower()
        if any(k in combined for k in ['decreas', 'reduc', 'drop', 'fall', 'lower']):
            return "decreasing"
        if any(k in combined for k in ['increas', 'improv', 'rise', 'higher', 'better']):
            return "increasing"
        if any(k in combined for k in ['stable', 'converge', 'plateau', 'consistent']):
            return "stable"
        if 'loss' in schema.figure_type:
            return "decreasing"
        return "undetected"

    def _insight(self, schema: FigureSchema) -> str:
        type_desc = {
            "bar_chart":            "compares performance",
            "line_chart_loss":      "shows training loss progression",
            "line_chart_metric":    "tracks metric over training",
            "confusion_matrix":     "shows classification results per class",
            "scatter_plot":         "shows data distribution",
            "roc_curve":            "shows ROC-AUC performance",
            "heatmap":              "visualizes attention or feature distribution",
            "architecture_diagram": "illustrates system architecture",
        }.get(schema.figure_type, "presents results")

        parts = [f"{schema.figure_number_raw or 'This figure'} {type_desc}"]

        if schema.comparison_entities:
            parts.append(f"for {', '.join(schema.comparison_entities[:3])}")
        if schema.y_axis_label:
            parts.append(f"(Y-axis: {schema.y_axis_label})")
        if schema.performance_range:
            r = schema.performance_range
            parts.append(f"with values ranging from {r['min']}{r.get('unit','')} "
                         f"to {r['max']}{r.get('unit','')}")
        if schema.caption_claim:
            parts.append(f"— {schema.caption_claim}")
        elif schema.trend_direction not in ['N/A', 'undetected', '']:
            parts.append(f"showing a {schema.trend_direction} trend")

        return " ".join(parts).strip()



class FigureAuditEngine:

    REQUIRED  = ['caption_text', 'figure_type', 'primary_insight']
    IMPORTANT = ['x_axis_label', 'y_axis_label', 'numeric_values_in_figure']

    def audit(self, schema: FigureSchema) -> FigureSchema:
        flags = []
        for f in self.REQUIRED:
            if not getattr(schema, f):
                flags.append(f"MISSING_REQUIRED: {f}")
        for f in self.IMPORTANT:
            v = getattr(schema, f)
            if not v or (isinstance(v, list) and not v):
                flags.append(f"MISSING_IMPORTANT: {f}")
        if not schema.comparison_entities and schema.figure_type == 'bar_chart':
            flags.append("MISSING: comparison_entities for bar_chart")

        schema.integrity_flags = flags
        if not flags:
            schema.integrity_status      = "COMPLETE"
            schema.extraction_confidence = "HIGH"
        elif len(flags) <= 2:
            schema.integrity_status      = "PARTIAL"
            schema.extraction_confidence = "MEDIUM"
        else:
            schema.integrity_status      = "FLAGGED"
            schema.extraction_confidence = "LOW"
        return schema



class FigureIntelligenceModule:

    MIN_W = 80
    MIN_H = 80

    def __init__(self, output_dir: str = "extracted_figures"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "images"), exist_ok=True)
        self._caption  = CaptionExtractor()
        self._ocr      = FigureOCRExtractor()
        self._semantic = FigureSemanticAnalyzer()
        self._audit    = FigureAuditEngine()

    def extract_all_figures(self, pdf_path: str) -> list:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc     = fitz.open(pdf_path)
        schemas = []

        for page_num in range(len(doc)):
            page      = doc[page_num]
            page_figs = self._process_page(page, page_num + 1)
            schemas.extend(page_figs)

        doc.close()
        return schemas

    def _process_page(self, page: fitz.Page, page_num: int) -> list:
        schemas   = []
        processed = set()

        for s in self._extract_by_captions(page, page_num):
            key = (round(s.bounding_box['x0']), round(s.bounding_box['y0']))
            processed.add(key)
            schemas.append(s)

        for img_info in page.get_images(full=True):
            try:
                s = self._from_xref(page, img_info[0], page_num, len(schemas))
                if s:
                    key = (round(s.bounding_box['x0']), round(s.bounding_box['y0']))
                    if key not in processed:
                        processed.add(key)
                        schemas.append(s)
            except Exception:
                pass

        for region in self._drawing_regions(page):
            key = (round(region.x0), round(region.y0))
            if key not in processed:
                processed.add(key)
                try:
                    s = self._from_drawing(page, region, page_num, len(schemas))
                    if s:
                        schemas.append(s)
                except Exception:
                    pass

        return schemas

    def _extract_by_captions(self, page: fitz.Page, page_num: int) -> list:
        CAPTION_RE = re.compile(r'(Fig(?:ure)?\.?\s*\d+[a-z]?)\s*[:\.\-]', re.IGNORECASE)
        page_w     = page.rect.width
        schemas    = []

        captions = []
        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text = block[:5]
            if CAPTION_RE.search(text.strip()):
                captions.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                                  "text": text.strip()})

        for idx, cap in enumerate(captions):
            fig_y_end   = cap["y0"] - 5
            fig_y_start = max(0, captions[idx-1]["y1"] + 5) if idx > 0 else max(0, fig_y_end - 250)
            fig_rect    = fitz.Rect(40, fig_y_start, page_w - 40, fig_y_end)

            if fig_rect.height < self.MIN_H:
                continue

            try:
                pix       = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fig_rect)
                img_bytes = pix.tobytes("png")
                img       = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            except Exception:
                continue

            schema              = self._build_schema(page, img, img_bytes, fig_rect, page_num, idx)
            schema.caption_text = cap["text"]
            m = CAPTION_RE.search(cap["text"])
            if m:
                schema.figure_number_raw = m.group(1)
                schema.caption_claim     = self._caption._extract_claim(cap["text"][m.end():].strip())

            schema = self._semantic.analyze(schema, img)
            schema = self._audit.audit(schema)
            schemas.append(schema)

        return schemas

    def _from_xref(self, page, xref, page_num, idx) -> Optional[FigureSchema]:
        rects = page.get_image_rects(xref)
        if not rects:
            return None
        bbox = rects[0]
        if bbox.width < self.MIN_W or bbox.height < self.MIN_H:
            return None
        img_data  = page.parent.extract_image(xref)
        if not img_data:
            return None
        img_bytes = img_data["image"]
        img       = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        return self._build_schema(page, img, img_bytes, bbox, page_num, idx)

    def _from_drawing(self, page, region, page_num, idx) -> Optional[FigureSchema]:
        pix       = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=region)
        img_bytes = pix.tobytes("png")
        img       = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        if img.size[0] < self.MIN_W or img.size[1] < self.MIN_H:
            return None
        return self._build_schema(page, img, img_bytes, region, page_num, idx)

    def _drawing_regions(self, page: fitz.Page) -> list:
        regions = []
        for d in page.get_drawings():
            rect = d.get('rect')
            if not rect:
                continue
            r = fitz.Rect(rect)
            if r.width > self.MIN_W and r.height > self.MIN_H:
                merged = False
                for i, existing in enumerate(regions):
                    if existing.intersects(r):
                        regions[i] = existing | r
                        merged = True
                        break
                if not merged:
                    regions.append(r)
        return [r for r in regions if r.width > self.MIN_W and r.height > self.MIN_H]

    def _build_schema(self, page, img, img_bytes, bbox, page_num, idx) -> FigureSchema:
        fig_id = f"Fig_p{page_num}_{idx + 1}"
        schema = FigureSchema(
            figure_id            = fig_id,
            page_number          = page_num,
            bounding_box         = {"x0": round(bbox.x0, 2), "y0": round(bbox.y0, 2),
                                     "x1": round(bbox.x1, 2), "y1": round(bbox.y1, 2)},
            figure_hash          = hashlib.sha256(img_bytes).hexdigest()[:16],
            extraction_timestamp = datetime.now().isoformat()
        )

        cap_data                 = self._caption.extract_caption(page, bbox)
        schema.caption_text      = cap_data["caption_text"]
        schema.caption_claim     = cap_data["caption_claim"]
        schema.figure_number_raw = cap_data["figure_number_raw"] or fig_id

        ocr                             = self._ocr.extract_from_image(img)
        schema.ocr_raw_text             = ocr["ocr_raw_text"]
        schema.x_axis_label             = ocr["x_axis_label"]
        schema.y_axis_label             = ocr["y_axis_label"]
        schema.x_tick_values            = ocr["x_tick_values"]
        schema.y_tick_values            = ocr["y_tick_values"]
        schema.legend_items             = ocr["legend_items"]
        schema.numeric_values_in_figure = ocr["numeric_values_in_figure"]

        schema = self._semantic.analyze(schema, img)
        schema = self._audit.audit(schema)

        img.save(os.path.join(self.output_dir, "images", f"{fig_id}.png"))
        return schema

    def print_audit_report(self, schemas: list):
        icons = {"COMPLETE": "✅", "PARTIAL": "⚠️ ", "FLAGGED": "❌"}
        print("\n" + "═" * 70)
        print("  FIGURE INTELLIGENCE AUDIT REPORT")
        print("═" * 70)
        print(f"  {'Fig ID':<18} {'Type':<22} {'Insight Preview':<22} Status")
        print("─" * 70)
        for s in schemas:
            icon    = icons.get(s.integrity_status, "?")
            preview = (s.primary_insight[:19] + "...") if len(s.primary_insight) > 22 else s.primary_insight
            print(f"  {s.figure_id:<18} {s.figure_type[:20]:<22} {preview:<22} {icon} {s.integrity_status}")
        total    = len(schemas)
        complete = sum(1 for s in schemas if s.integrity_status == "COMPLETE")
        print("═" * 70)
        print(f"  Completeness Ratio: {complete}/{total} "
              f"({(complete/total*100) if total else 0:.1f}%)")
        print("═" * 70)



def extract_text(pdf_path):
    print("\n[TEXT] Starting text extraction...")
    results = []

    doc         = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"[TEXT] Total pages found: {total_pages}")

    for page_num in range(total_pages):
        page     = doc[page_num]
        page_no  = page_num + 1

        plain_text = page.get_text("text").strip()
        if not plain_text:
            print(f"[TEXT] Page {page_no}: empty or no text layer")
            continue

        spans = []
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:          
                continue
            for line in block.get("lines", []):
                line_text  = ""
                line_sizes = []
                line_flags = []
                bbox       = line.get("bbox", (0, 0, 0, 0))
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if t:
                        line_text  += t + " "
                        line_sizes.append(span.get("size", 0))
                        line_flags.append(span.get("flags", 0))
                line_text = line_text.strip()
                if line_text:
                    avg_size  = sum(line_sizes) / len(line_sizes) if line_sizes else 0
                    # flags bit 4 = bold, bit 1 = italic
                    is_bold   = any(f & 16 for f in line_flags)
                    spans.append({
                        "text":    line_text,
                        "size":    round(avg_size, 2),
                        "bold":    is_bold,
                        "x0":      round(bbox[0], 1),
                        "y0":      round(bbox[1], 1),
                    })

        results.append({
            "page":  page_no,
            "text":  plain_text,
            "spans": spans,          
        })
        print(f"[TEXT] Page {page_no}: {len(plain_text)} chars, {len(spans)} spans extracted")

    doc.close()
    print(f"[TEXT] Done. {len(results)} pages had text.\n")
    return results



def extract_tables(pdf_path):
    results     = []
    table_count = 0

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if not tables:
                continue

            print(f"[TABLES] Page {i+1}: {len(tables)} table(s) found")
            for j, table in enumerate(tables):
                cleaned = [
                    [cell if cell is not None else "" for cell in row]
                    for row in table if any(cell for cell in row)
                ]
                if len(cleaned) < 2:
                    continue
                try:
                    df = pd.DataFrame(cleaned[1:], columns=cleaned[0])
                except Exception:
                    df = pd.DataFrame(cleaned)

                table_count += 1
                results.append({
                    "page": i + 1, "table_index": j + 1,
                    "dataframe": df, "raw": cleaned
                })
                print(f"[TABLES]   Table {j+1}: "
                      f"{len(df)} rows × {len(df.columns)} cols | "
                      f"Columns: {list(df.columns)}")

    print(f"[TABLES] Done. {table_count} total tables extracted.\n")
    return results



def extract_figures(pdf_path, paper_id):
    print("[FIGURES] Starting intelligent figure extraction...")

    output_dir = os.path.join(FIGURES_DIR, paper_id)
    module     = FigureIntelligenceModule(output_dir=output_dir)
    schemas    = module.extract_all_figures(pdf_path)
    module.print_audit_report(schemas)

    results = []
    for schema in schemas:
        results.append({
            "page":         schema.page_number,
            "figure_index": int(schema.figure_id.split("_")[-1]),
            "path":         os.path.join(output_dir, "images", f"{schema.figure_id}.png"),
            "width":        round(schema.bounding_box["x1"] - schema.bounding_box["x0"]),
            "height":       round(schema.bounding_box["y1"] - schema.bounding_box["y0"]),

            "figure_type":       schema.figure_type,
            "caption":           schema.caption_text,
            "caption_claim":     schema.caption_claim,
            "primary_insight":   schema.primary_insight,
            "x_axis_label":      schema.x_axis_label,
            "y_axis_label":      schema.y_axis_label,
            "x_tick_values":     schema.x_tick_values,
            "y_tick_values":     schema.y_tick_values,
            "legend_items":      schema.legend_items,
            "numeric_values":    schema.numeric_values_in_figure,
            "comparison_models": schema.comparison_entities,
            "performance_range": schema.performance_range,
            "trend_direction":   schema.trend_direction,

            "integrity_status": schema.integrity_status,
            "integrity_flags":  schema.integrity_flags,
            "confidence":       schema.extraction_confidence,
            "figure_hash":      schema.figure_hash,
        })

    print(f"[FIGURES] Done. {len(results)} figures extracted with insights.\n")
    return results



def extract_numbers(text_results):
    print("[NUMBERS] Extracting all numerical values from text...")

    pattern = r"""
        \d{1,3}(?:,\d{3})*(?:\.\d+)?%?  |
        \d+\.\d+%?                        |
        \d+e[-+]?\d+                      |
        \d+%                              |
        \d+
    """

    all_numbers = []
    seen        = set()

    for page_data in text_results:
        page = page_data["page"]
        text = page_data["text"]           
        for match in re.finditer(pattern, text, re.VERBOSE | re.IGNORECASE):
            raw     = match.group().strip()
            start   = max(0, match.start() - 30)
            end     = min(len(text), match.end() + 30)
            context = text[start:end].replace("\n", " ")
            key     = f"{raw}_{page}"
            if key not in seen:
                seen.add(key)
                all_numbers.append({"raw": raw, "page": page, "context": context})

    print(f"[NUMBERS] Done. {len(all_numbers)} unique numerical values found.\n")
    return all_numbers



SECTION_KEYWORDS = [
    "abstract", "introduction", "related work", "background",
    "literature", "methodology", "method", "approach", "model",
    "experiment", "evaluation", "results", "discussion",
    "conclusion", "future work", "references", "acknowledgement",
    "acknowledgments",
]

_KW_PATTERNS = [
    re.compile(r'(?<!\w)' + re.escape(kw) + r'(?!\w)', re.IGNORECASE)
    for kw in SECTION_KEYWORDS
]

_NUMBERED_HEADING = re.compile(r'^\d+[\.\d]*\s+\w+')

HEADING_RATIO = 1.15


def _compute_body_font_size(text_results: list) -> float:
   
    all_sizes = []
    for page_data in text_results:
        for span in page_data.get("spans", []):
            s = span.get("size", 0)
            if s > 0:
                all_sizes.append(s)
    if not all_sizes:
        return 10.0
    all_sizes.sort()
    mid = len(all_sizes) // 2
    return all_sizes[mid]


def _matches_keyword(line_lower: str) -> bool:
    for pat in _KW_PATTERNS:
        if pat.search(line_lower):
            return True
    return False


def _is_section_heading(span: dict, body_size: float) -> bool:
   
    text       = span["text"].strip()
    word_count = len(text.split())

    if word_count == 0 or word_count > 8:
        return False

    is_large = span["size"] >= body_size * HEADING_RATIO
    is_bold  = span["bold"]
    if not (is_large or is_bold):
        return False

    text_lower = text.lower()
    if _matches_keyword(text_lower):
        return True
    if _NUMBERED_HEADING.match(text.strip()):
        return True
    if text.isupper() and word_count <= 6:
        return True

    return False


def detect_sections(text_results: list) -> list:
    print("[SECTIONS] Detecting sections (font-aware mode)...")

    body_size = _compute_body_font_size(text_results)
    print(f"[SECTIONS] Body font size (median): {body_size:.2f}pt")

    sections = []
    current  = {"heading": "preamble", "page": 1, "lines": []}

    for page_data in text_results:
        page_no = page_data["page"]
        spans   = page_data.get("spans", [])

        for span in spans:
            text = span["text"].strip()
            if not text:
                continue

            if _is_section_heading(span, body_size):
                if current["lines"]:
                    current["text"] = " ".join(current["lines"])
                    sections.append(current)
                current = {"heading": text, "page": page_no, "lines": []}
                print(f"[SECTIONS]   Found: '{text}' "
                      f"(size={span['size']:.1f}pt, bold={span['bold']}) "
                      f"on page {page_no}")
            else:
                current["lines"].append(text)

    if current["lines"]:
        current["text"] = " ".join(current["lines"])
        sections.append(current)

    deduped = []
    for sec in sections:
        if deduped and deduped[-1]["heading"].lower() == sec["heading"].lower() \
                   and sec["page"] == deduped[-1]["page"]:
            deduped[-1]["text"] = (deduped[-1]["text"] + " " + sec.get("text", "")).strip()
        else:
            deduped.append(sec)

    print(f"[SECTIONS] Done. {len(deduped)} sections detected.\n")
    return deduped



def save_to_json(paper_id, text_results, table_results,
                 figure_results, number_results, section_results):
    print("[JSON] Building unified JSON...")

    pages_out = [{"page": p["page"], "text": p["text"]} for p in text_results]

    tables_out = []
    for t in table_results:
        tables_out.append({
            "page":        t["page"],
            "table_index": t["table_index"],
            "columns":     list(t["dataframe"].columns),
            "rows":        t["dataframe"].values.tolist(),
            "raw":         t["raw"]
        })

    unified = {
        "paper_id": paper_id,
        "sections": section_results,
        "pages":    pages_out,
        "tables":   tables_out,
        "figures":  figure_results,
        "numbers":  number_results,
        "stats": {
            "total_pages":    len(text_results),
            "total_tables":   len(table_results),
            "total_figures":  len(figure_results),
            "total_numbers":  len(number_results),
            "total_sections": len(section_results),
        }
    }

    output_path = os.path.join(PAPERS_DIR, f"{paper_id}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(unified, f, indent=2, ensure_ascii=False)

    print(f"[JSON] Saved to: {output_path}\n")
    return output_path, unified



def extract_paper(pdf_path):
    print("=" * 55)
    print("RESEARCH PAPER EXTRACTION PIPELINE")
    print("=" * 55)
    print(f"File: {pdf_path}\n")

    paper_id = Path(pdf_path).stem.replace(" ", "_").lower()
    print(f"Paper ID: {paper_id}\n")

    text_results    = extract_text(pdf_path)
    table_results   = extract_tables(pdf_path)
    figure_results  = extract_figures(pdf_path, paper_id)
    number_results  = extract_numbers(text_results)
    section_results = detect_sections(text_results)

    json_path, unified = save_to_json(
        paper_id, text_results, table_results,
        figure_results, number_results, section_results
    )

    print("=" * 55)
    print("EXTRACTION COMPLETE — SUMMARY")
    print("=" * 55)
    print(f"Pages extracted   : {unified['stats']['total_pages']}")
    print(f"Sections found    : {unified['stats']['total_sections']}")
    print(f"Tables found      : {unified['stats']['total_tables']}")
    print(f"Figures saved     : {unified['stats']['total_figures']}")
    print(f"Numbers captured  : {unified['stats']['total_numbers']}")
    print(f"JSON saved to     : {json_path}")
    print("=" * 55)

    return unified


if __name__ == "__main__":
    PDF_PATH = r"C:\projects\research_ai\sample.pdf"
    result   = extract_paper(PDF_PATH)