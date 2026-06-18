"""
Core PPTX template engine.

Scan for {...} placeholders, then fill them with generated content
while preserving all original formatting (fonts, colors, sizes).
"""
import os
import re
from io import BytesIO
from typing import Dict, List, Optional
from zipfile import ZipFile

from lxml import etree

# ── OOXML namespaces ──────────────────────────────────────────────────────────
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "dsp": "http://schemas.microsoft.com/office/drawing/2008/diagram",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}

PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")


class PPTCore:
    """Template-based PPTX engine: scan placeholders, fill with content."""

    # ══════════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════════════

    def list_templates(self, file_path: str) -> list:
        """
        Parse a multi-slide PPTX and return one TemplateInfo dict per slide.
        Each entry contains template_id, template_name, and its placeholders.
        """
        from models.schemas import TemplateInfo

        templates = []
        with ZipFile(file_path, "r") as pptx:
            slide_paths = self._sorted(pptx, "ppt/slides/slide", ".xml")

            for slide_idx, sp in enumerate(slide_paths, start=1):
                tree = etree.fromstring(pptx.read(sp))

                # Extract title: first text box's first non-empty paragraph
                title = self._extract_slide_title(tree, slide_idx)

                # Scan placeholders on this slide only
                items = []
                counter = 0
                counter = self._scan_text_boxes(tree, slide_idx, items, counter)
                counter = self._scan_tables(tree, slide_idx, items, counter)

                # Also scan notes if present
                notes_path = sp.replace("slides/slide", "notesSlides/notesSlide")
                if notes_path in pptx.namelist():
                    counter = self._scan_notes(pptx, notes_path, slide_idx, items, counter)

                unique = list(dict.fromkeys(i["name"] for i in items))
                templates.append(
                    TemplateInfo(
                        template_id=slide_idx,
                        template_name=title,
                        placeholders=unique,
                    ).model_dump()
                )

        return templates

    def _extract_slide_title(self, tree, slide_idx: int) -> str:
        """Extract a human-readable title from a slide (first text box text)."""
        # Try all text boxes, pick the first non-empty paragraph as title
        for tb in tree.xpath(".//p:txBody", namespaces=NS):
            for para in tb.xpath(".//a:p", namespaces=NS):
                runs = para.xpath(".//a:r", namespaces=NS)
                merged = ""
                for r in runs:
                    t = r.xpath("./a:t", namespaces=NS)
                    if t and t[0].text:
                        merged += t[0].text
                merged = merged.strip()
                if merged and not PLACEHOLDER_RE.fullmatch(merged):
                    return merged
        return f"Slide {slide_idx}"

    def export_single_slide(self, file_path: str, template_id,
                            content_map: Dict[str, str],
                            font_config: Dict = None) -> bytes:
        """
        Open the built-in PPTX, delete all slides except those specified,
        replace placeholders, and return the resulting PPTX as bytes.

        template_id can be an int (single slide) or a list of ints (multiple slides).
        """
        # Normalize slide indices to a list
        if isinstance(template_id, int):
            keep_indices = [template_id]
        else:
            keep_indices = list(template_id)

        scan = self.scan_placeholders(file_path)
        details = [d for d in scan["details"] if d["slide_index"] in keep_indices]

        with ZipFile(file_path, "r") as src:
            slide_paths = self._sorted(src, "ppt/slides/slide", ".xml")
            rels_paths = self._sorted(src, "ppt/slides/_rels/slide", ".xml.rels")

            # Determine which slide files to keep/remove
            keep_slides = {f"ppt/slides/slide{idx}.xml" for idx in keep_indices}
            keep_rels_set = {f"ppt/slides/_rels/slide{idx}.xml.rels" for idx in keep_indices}

            # Build set of files to remove (other slides + their rels)
            remove_files = set()
            for sp in slide_paths:
                if sp not in keep_slides:
                    remove_files.add(sp)
            for rp in rels_paths:
                if rp not in keep_rels_set:
                    remove_files.add(rp)

            # Parse presentation.xml to strip removed slide references
            pres_path = "ppt/presentation.xml"
            pres_tree = etree.fromstring(src.read(pres_path))
            sld_id_lst = pres_tree.xpath("//p:sldIdLst", namespaces=NS)
            if sld_id_lst:
                # Get relationship IDs for all slides
                pres_rels_path = "ppt/_rels/presentation.xml.rels"
                pres_rels_tree = etree.fromstring(src.read(pres_rels_path))
                slide_rids = {}
                for rel in pres_rels_tree.xpath(
                    "//pkg:Relationship[@Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide']",
                    namespaces=NS
                ):
                    target = rel.get("Target", "")
                    rid = rel.get("Id", "")
                    if target.startswith("slides/slide"):
                        try:
                            idx = int(target.replace("slides/slide", "").replace(".xml", ""))
                            slide_rids[idx] = rid
                        except ValueError:
                            pass

                keep_rids = {slide_rids[idx] for idx in keep_indices if idx in slide_rids}
                for sld_id in list(sld_id_lst[0]):
                    if sld_id.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") not in keep_rids:
                        sld_id_lst[0].remove(sld_id)

                modified = {pres_path: etree.tostring(pres_tree, xml_declaration=True,
                                                       encoding="UTF-8", standalone=True)}

                # Fill placeholders on each kept slide
                for idx in keep_indices:
                    keep_slide = f"ppt/slides/slide{idx}.xml"
                    slide_details = [d for d in details if d["slide_index"] == idx]
                    if slide_details and keep_slide in slide_paths:
                        slide_tree = etree.fromstring(src.read(keep_slide))
                        if self._fill_slide(slide_tree, slide_details, content_map):
                            modified[keep_slide] = etree.tostring(slide_tree, xml_declaration=True,
                                                                   encoding="UTF-8", standalone=True)

                    # Also handle notes for this slide
                    notes_path = keep_slide.replace("slides/slide", "notesSlides/notesSlide")
                    note_items = [d for d in slide_details if d["container_type"] == "notes"]
                    if note_items and notes_path in src.namelist():
                        notes_tree = etree.fromstring(src.read(notes_path))
                        if self._fill_notes(notes_tree, note_items, content_map):
                            modified[notes_path] = etree.tostring(notes_tree, xml_declaration=True,
                                                                   encoding="UTF-8", standalone=True)

                # Repack, skipping removed files
                buf = BytesIO()
                with ZipFile(buf, "w") as dst:
                    for entry in src.infolist():
                        if entry.filename in remove_files:
                            continue
                        if entry.filename in modified:
                            dst.writestr(entry, modified[entry.filename])
                        else:
                            dst.writestr(entry, src.read(entry.filename))
                return buf.getvalue()

        # Fallback: return original if something went wrong
        with open(file_path, "rb") as f:
            return f.read()

    def scan_placeholders(self, file_path: str) -> dict:
        """
        Walk every slide / table / notes / SmartArt and collect paragraphs
        whose merged text contains ``{...}`` patterns.

        Returns a dict matching ScanResult schema.
        """
        from models.schemas import PlaceholderInfo, SlidePlaceholderGroup, ScanResult

        all_items: List[PlaceholderInfo] = []
        counter = 0

        with ZipFile(file_path, "r") as pptx:
            slide_paths = self._sorted(pptx, "ppt/slides/slide", ".xml")

            for slide_idx, sp in enumerate(slide_paths, start=1):
                tree = etree.fromstring(pptx.read(sp))
                counter = self._scan_text_boxes(tree, slide_idx, all_items, counter)
                counter = self._scan_tables(tree, slide_idx, all_items, counter)

                notes_path = sp.replace("slides/slide", "notesSlides/notesSlide")
                if notes_path in pptx.namelist():
                    counter = self._scan_notes(pptx, notes_path, slide_idx, all_items, counter)

            counter = self._scan_smartart(pptx, all_items, counter)

        unique = list(dict.fromkeys(i["name"] for i in all_items))
        groups: Dict[int, list] = {}
        for i in all_items:
            groups.setdefault(i["slide_index"], []).append(i)

        result = ScanResult(
            total_placeholders=len(all_items),
            unique_placeholders=unique,
            details=all_items,
            slides=[
                SlidePlaceholderGroup(slide_index=idx, placeholders=items)
                for idx, items in sorted(groups.items())
            ],
        )
        return result.model_dump()

    def fill_template(self, file_path: str, content_map: Dict[str, str],
                      output_path: Optional[str] = None) -> str:
        """
        Replace every ``{Name}`` in the template with values from *content_map*,
        preserving all original formatting.  Writes to *output_path* and returns it.
        """
        if output_path is None:
            base, ext = os.path.splitext(file_path)
            output_path = f"{base}_filled{ext}"

        scan = self.scan_placeholders(file_path)
        details = scan["details"]

        with ZipFile(file_path, "r") as src:
            modified: Dict[str, bytes] = {}

            slide_paths = self._sorted(src, "ppt/slides/slide", ".xml")
            notes_paths = self._sorted(src, "ppt/notesSlides/notesSlide", ".xml")
            diagram_paths = sorted(
                n for n in src.namelist()
                if n.startswith("ppt/diagrams/") and n.endswith(".xml")
            )

            # Group items by slide
            by_slide: Dict[int, list] = {}
            for d in details:
                by_slide.setdefault(d["slide_index"], []).append(d)

            # ── Slides ────────────────────────────────────────────────────────
            for idx, sp in enumerate(slide_paths, start=1):
                items = [i for i in by_slide.get(idx, []) if i["container_type"] != "notes"]
                if not items:
                    continue
                tree = etree.fromstring(src.read(sp))
                if self._fill_slide(tree, items, content_map):
                    modified[sp] = etree.tostring(tree, xml_declaration=True,
                                                   encoding="UTF-8", standalone=True)

            # ── Notes ─────────────────────────────────────────────────────────
            for idx, np_ in enumerate(notes_paths, start=1):
                items = [i for i in by_slide.get(idx, []) if i["container_type"] == "notes"]
                if not items:
                    continue
                tree = etree.fromstring(src.read(np_))
                if self._fill_notes(tree, items, content_map):
                    modified[np_] = etree.tostring(tree, xml_declaration=True,
                                                    encoding="UTF-8", standalone=True)

            # ── SmartArt ──────────────────────────────────────────────────────
            smartart = [i for i in details if i["container_type"] == "smartart"]
            if smartart:
                for dp in diagram_paths:
                    d_items = [i for i in smartart if i.get("xpath", "") == dp]
                    if not d_items:
                        continue
                    tree = etree.fromstring(src.read(dp))
                    if self._fill_smartart(tree, d_items, content_map):
                        modified[dp] = etree.tostring(tree, xml_declaration=True,
                                                       encoding="UTF-8", standalone=True)

            # ── Repack ────────────────────────────────────────────────────────
            self._repack(src, output_path, modified)

        return output_path

    def fill_to_bytes(self, file_path: str, content_map: Dict[str, str]) -> bytes:
        """Same as fill_template but returns raw bytes for HTTP streaming."""
        path = self.fill_template(file_path, content_map)
        with open(path, "rb") as f:
            data = f.read()
        if os.path.exists(path):
            os.remove(path)
        return data

    # ══════════════════════════════════════════════════════════════════════════
    #  SCAN HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _scan_text_boxes(self, tree, slide_idx, items, counter):
        for tb_idx, tb in enumerate(tree.xpath(".//p:txBody", namespaces=NS), start=1):
            for p_idx, para in enumerate(tb.xpath(".//a:p", namespaces=NS)):
                counter = self._check_para(para, slide_idx, "text_box", items, counter,
                                           text_box_index=tb_idx, paragraph_index=p_idx)
        return counter

    def _scan_tables(self, tree, slide_idx, items, counter):
        for tbl_idx, tbl in enumerate(tree.xpath(".//a:tbl", namespaces=NS), start=1):
            for row_idx, row in enumerate(tbl.xpath(".//a:tr", namespaces=NS)):
                for cell_idx, cell in enumerate(row.xpath(".//a:tc", namespaces=NS)):
                    for p_idx, para in enumerate(cell.xpath(".//a:p", namespaces=NS)):
                        counter = self._check_para(
                            para, slide_idx, "table_cell", items, counter,
                            table_index=tbl_idx, row_index=row_idx,
                            cell_index=cell_idx, paragraph_index=p_idx,
                        )
        return counter

    def _scan_notes(self, pptx, path, slide_idx, items, counter):
        tree = etree.fromstring(pptx.read(path))
        for p_idx, para in enumerate(tree.xpath(".//a:p", namespaces=NS)):
            counter = self._check_para(para, slide_idx, "notes", items, counter,
                                       paragraph_index=p_idx)
        return counter

    def _scan_smartart(self, pptx, items, counter):
        drawings = sorted(
            n for n in pptx.namelist()
            if n.startswith("ppt/diagrams/drawing") and n.endswith(".xml")
        )
        for dp in drawings:
            m = re.search(r"drawing(\d+)\.xml", dp)
            if not m:
                continue
            tree = etree.fromstring(pptx.read(dp))
            shapes = tree.xpath(".//dsp:sp[.//dsp:txBody]", namespaces=NS)
            for shape_idx, shape in enumerate(shapes):
                for tb_idx, tb in enumerate(shape.xpath(".//dsp:txBody", namespaces=NS)):
                    for p_idx, para in enumerate(tb.xpath(".//a:p", namespaces=NS)):
                        counter = self._check_para(
                            para, int(m.group(1)), "smartart", items, counter,
                            text_box_index=tb_idx, paragraph_index=p_idx,
                            extra_xpath=dp,
                        )
        return counter

    def _check_para(self, para, slide_idx, container_type, items, counter, **kw):
        runs = para.xpath(".//a:r", namespaces=NS)
        info = self._process_runs(runs)
        found = PLACEHOLDER_RE.findall(info["merged_text"])
        if not found:
            return counter
        for name in dict.fromkeys(found):
            counter += 1
            items.append({
                "name": name,
                "slide_index": slide_idx,
                "container_type": container_type,
                "text_box_index": kw.get("text_box_index"),
                "paragraph_index": kw.get("paragraph_index", 0),
                "table_index": kw.get("table_index"),
                "row_index": kw.get("row_index"),
                "cell_index": kw.get("cell_index"),
                "paragraph_text": info["merged_text"],
                "run_texts": info["run_texts"],
                "run_styles": info["run_styles"],
                "run_lengths": info["run_lengths"],
                "xpath": kw.get("extra_xpath", ""),
            })
        return counter

    # ══════════════════════════════════════════════════════════════════════════
    #  FILL HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _fill_slide(self, tree, items, cmap) -> bool:
        changed = False
        for item in items:
            ct = item["container_type"]
            if ct == "text_box":
                changed |= self._fill_text_box(tree, item, cmap)
            elif ct == "table_cell":
                changed |= self._fill_table_cell(tree, item, cmap)
        return changed

    def _fill_text_box(self, tree, item, cmap) -> bool:
        boxes = tree.xpath(".//p:txBody", namespaces=NS)
        tb_idx = item.get("text_box_index")
        if tb_idx is None or tb_idx > len(boxes):
            return False
        para = self._nth_para(boxes[tb_idx - 1], item["paragraph_index"])
        return self._do_fill(para, item, cmap) if para is not None else False

    def _fill_table_cell(self, tree, item, cmap) -> bool:
        tables = tree.xpath(".//a:tbl", namespaces=NS)
        ti = item.get("table_index")
        ri = item.get("row_index")
        ci = item.get("cell_index")
        if not ti or ti > len(tables):
            return False
        rows = tables[ti - 1].xpath(".//a:tr", namespaces=NS)
        if ri is None or ri >= len(rows):
            return False
        cells = rows[ri].xpath(".//a:tc", namespaces=NS)
        if ci is None or ci >= len(cells):
            return False
        para = self._nth_para(cells[ci], item["paragraph_index"])
        return self._do_fill(para, item, cmap) if para is not None else False

    def _fill_notes(self, tree, items, cmap) -> bool:
        changed = False
        for item in items:
            paras = tree.xpath(".//a:p", namespaces=NS)
            pi = item["paragraph_index"]
            if pi < len(paras):
                changed |= self._do_fill(paras[pi], item, cmap)
        return changed

    def _fill_smartart(self, tree, items, cmap) -> bool:
        changed = False
        all_tbs = tree.xpath(".//dsp:txBody", namespaces=NS)
        for item in items:
            tb_idx = item.get("text_box_index")
            if tb_idx is None or tb_idx > len(all_tbs):
                continue
            para = self._nth_para(all_tbs[tb_idx - 1], item["paragraph_index"])
            if para is not None:
                changed |= self._do_fill(para, item, cmap)
        return changed

    def _do_fill(self, para, item, cmap) -> bool:
        """Replace placeholders in merged text, then redistribute across runs."""
        new_text = item["paragraph_text"]
        for name, value in sorted(cmap.items(), key=lambda kv: len(kv[0]), reverse=True):
            new_text = new_text.replace(f"{{{name}}}", value)
        if new_text == item["paragraph_text"]:
            return False
        runs = para.xpath(".//a:r", namespaces=NS)
        if not runs:
            return False
        self._intelligent_distribute(runs, new_text, item["run_texts"], item["run_lengths"])
        return True

    # ══════════════════════════════════════════════════════════════════════════
    #  RUN PROCESSING  (faithful port from reference pipeline)
    # ══════════════════════════════════════════════════════════════════════════

    def _process_runs(self, runs) -> dict:
        merged, texts, styles, lengths = "", [], [], []
        for r in runs:
            t = r.xpath("./a:t", namespaces=NS)
            txt = t[0].text if t and t[0].text is not None else ""
            merged += txt
            texts.append(txt)
            lengths.append(len(txt))
            styles.append(self._extract_style(r))
        return {"merged_text": merged, "run_texts": texts,
                "run_styles": styles, "run_lengths": lengths}

    def _extract_style(self, run) -> dict:
        s = {}
        rpr = run.xpath("./a:rPr", namespaces=NS)
        if not rpr:
            return s
        rpr = rpr[0]
        for attr in ("sz", "b", "i", "u", "strike"):
            v = rpr.get(attr)
            if v is not None:
                s[attr] = v
        latin = rpr.xpath("./a:latin", namespaces=NS)
        if latin:
            s["font_family"] = latin[0].get("typeface")
        fill = rpr.xpath("./a:solidFill/a:srgbClr", namespaces=NS)
        if fill:
            s["color"] = fill[0].get("val")
        return s

    # ══════════════════════════════════════════════════════════════════════════
    #  INTELLIGENT TEXT DISTRIBUTION  (faithful port from reference pipeline)
    # ══════════════════════════════════════════════════════════════════════════

    def _intelligent_distribute(self, runs, new_text, orig_texts, orig_lengths):
        if not runs:
            return
        if not orig_texts or len(orig_texts) != len(runs):
            self._simple_dist(runs, new_text)
            return

        meaningful = [(i, l) for i, l in enumerate(orig_lengths) if l > 0]
        total = sum(l for _, l in meaningful)
        if total == 0:
            self._simple_dist(runs, new_text)
            return

        chars = list(new_text)
        ci = 0

        for ri, run in enumerate(runs):
            t_nodes = run.xpath("./a:t", namespaces=NS)
            if not t_nodes:
                continue
            orig_len = orig_lengths[ri] if ri < len(orig_lengths) else 0

            if orig_len == 0:
                ot = orig_texts[ri] if ri < len(orig_texts) else ""
                if ot and not ot.strip():
                    if ci < len(chars) and chars[ci] == " ":
                        t_nodes[0].text = " "; ci += 1
                    else:
                        t_nodes[0].text = ""
                else:
                    t_nodes[0].text = ""
                continue

            if ri == len(runs) - 1:
                t_nodes[0].text = "".join(chars[ci:])
            else:
                proportion = orig_len / total
                target = max(1, int(len(new_text) * proportion))
                chunk, taken = "", 0
                while taken < target and ci < len(chars):
                    chunk += chars[ci]; taken += 1; ci += 1
                    if taken >= target and ci < len(chars):
                        if chars[ci - 1] != " " and chars[ci] != " ":
                            while ci < len(chars) and chars[ci] != " " and taken < target * 1.5:
                                chunk += chars[ci]; taken += 1; ci += 1
                        break
                t_nodes[0].text = chunk

    def _simple_dist(self, runs, new_text):
        for i, r in enumerate(runs):
            t = r.xpath("./a:t", namespaces=NS)
            if t:
                t[0].text = new_text if i == 0 else ""

    # ══════════════════════════════════════════════════════════════════════════
    #  REPACK
    # ══════════════════════════════════════════════════════════════════════════

    def _repack(self, src: ZipFile, output: str, modified: Dict[str, bytes]):
        with ZipFile(output, "w") as dst:
            for entry in src.infolist():
                if entry.filename in modified:
                    dst.writestr(entry, modified[entry.filename])
                else:
                    dst.writestr(entry, src.read(entry.filename))

    # ══════════════════════════════════════════════════════════════════════════
    #  UTILITIES
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _sorted(pptx: ZipFile, prefix: str, suffix: str) -> List[str]:
        return sorted(n for n in pptx.namelist() if n.startswith(prefix) and n.endswith(suffix))

    @staticmethod
    def _nth_para(container, idx: int):
        paras = container.xpath(".//a:p", namespaces=NS)
        return paras[idx] if idx < len(paras) else None
