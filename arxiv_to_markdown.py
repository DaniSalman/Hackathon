"""
arxiv_to_markdown.py - convert an arXiv paper's HTML version into Markdown without losing content.

Deterministic: no ML, no LLM. Same HTML in -> same Markdown out.
Dependencies: requests, beautifulsoup4  (pip install requests beautifulsoup4)

arXiv's HTML pages are produced by LaTeXML. Every formula is a <math> element whose
`alttext` attribute holds the original LaTeX, so formulas are recovered exactly rather
than reconstructed from rendered output.

Output conventions
  - Inline math: $...$        Display math: $$...$$   Equation numbers follow: $$...$$ (3)
  - Figures/images: replaced by their captions, as  > **Figure 1:** caption text
  - Tables: Markdown tables. Merged cells are expanded into a regular grid: a rowspan's value
    repeats in each row it covers, a colspan's extra columns stay empty, and group headers are
    merged into one header row ("Group / Column"). Nested tables are flattened.
  - Display math with bare line breaks is wrapped in aligned/gathered; colour commands are stripped
  - Footnotes: GFM footnotes [^1] with definitions at the end
  - Literal "$" and HTML-like "<tag" in text are backslash-escaped so they can't be
    misread as math/HTML; "*" and "_" are left as-is to keep the text verbatim

Usage
  from arxiv_to_markdown import arxiv_to_markdown
  result = arxiv_to_markdown("1706.03762v7")          # writes 1706.03762v7.md
  print(result.report.summary())

  python arxiv_to_markdown.py 1706.03762v7 -o attention.md
  python arxiv_to_markdown.py --html-file saved_page.html -o paper.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import CData, Comment, Declaration, Doctype, ProcessingInstruction

__all__ = [
    "arxiv_to_markdown",
    "html_to_markdown",
    "fetch_arxiv_html",
    "normalize_arxiv_id",
    "ConversionResult",
    "ConversionReport",
    "ArxivError",
    "NoHTMLVersionError",
    "ConversionIncompleteError",
]

ARXIV_HTML_URL = "https://arxiv.org/html/{}"
USER_AGENT = "arxiv-to-markdown/1.0 (research tool; python-requests)"


# --------------------------------------------------------------------------- errors


class ArxivError(Exception):
    """Network or arXiv-side failure."""


class NoHTMLVersionError(ArxivError):
    """The paper has no HTML version on arXiv (LaTeXML could not convert it)."""


class ConversionIncompleteError(Exception):
    """Raised in strict mode when the completeness checks fail."""


# --------------------------------------------------------------------------- results


@dataclass
class ConversionReport:
    source: str = ""
    math_total: int = 0
    math_emitted: int = 0
    math_inside_images: int = 0
    math_without_latex: int = 0
    images_total: int = 0
    images_covered_by_caption: int = 0
    images_without_caption: int = 0
    words_inside_images: int = 0
    captions: int = 0
    footnotes: int = 0
    tables_markdown: int = 0
    equations_numbered: int = 0
    latex_errors_in_source: int = 0
    source_words: int = 0
    missing_words: list = field(default_factory=list)  # [(word, count)]
    warnings: list = field(default_factory=list)

    @property
    def math_missing(self) -> int:
        return self.math_total - self.math_emitted - self.math_inside_images

    @property
    def word_coverage(self) -> float:
        if not self.source_words:
            return 1.0
        return 1.0 - sum(c for _, c in self.missing_words) / self.source_words

    @property
    def ok(self) -> bool:
        return self.math_missing == 0 and not self.missing_words

    def summary(self) -> str:
        lines = [
            f"Source: {self.source}",
            f"Formulas: {self.math_emitted}/{self.math_total} written"
            + (f" ({self.math_inside_images} were labels inside images)" if self.math_inside_images else ""),
            f"Text coverage: {self.word_coverage:.4%} of {self.source_words} words",
            f"Captions: {self.captions} | images replaced by captions: {self.images_covered_by_caption}"
            f" | uncaptioned images: {self.images_without_caption}",
            f"Tables: {self.tables_markdown}"
            f" | footnotes: {self.footnotes} | numbered equations: {self.equations_numbered}",
        ]
        if self.missing_words:
            lines.append("Words not found in output: " + ", ".join(f"{w}x{c}" for w, c in self.missing_words[:20]))
        lines += [f"Warning: {w}" for w in self.warnings]
        lines.append("Status: COMPLETE" if self.ok else "Status: CHECK WARNINGS")
        return "\n".join(lines)


@dataclass
class ConversionResult:
    markdown: str
    report: ConversionReport
    path: str | None = None


# --------------------------------------------------------------------------- fetching

_NEW_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_OLD_ID = re.compile(r"([a-z][a-z\-]*(?:\.[A-Z]{2})?/\d{7})(v\d+)?")


def normalize_arxiv_id(ref: str) -> str:
    """Accepts '1706.03762', '1706.03762v7', 'arXiv:1706.03762', or any arxiv.org URL."""
    ref = re.sub(r"^\s*arxiv:\s*", "", ref.strip(), flags=re.I)
    m = _NEW_ID.search(ref) or _OLD_ID.search(ref)
    if not m:
        raise ValueError(f"Not a recognizable arXiv id: {ref!r}")
    return m.group(1) + (m.group(2) or "")


def _decode(resp: requests.Response) -> str:
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.content.decode(resp.apparent_encoding or "utf-8", errors="replace")


def fetch_arxiv_html(paper_id: str, timeout: float = 30.0, retries: int = 3) -> tuple[str, str]:
    """Returns (html, final_url). Raises NoHTMLVersionError if arXiv has no HTML version."""
    pid = normalize_arxiv_id(paper_id)
    url = ARXIV_HTML_URL.format(pid)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 404:
            raise NoHTMLVersionError(f"arXiv has no HTML version of {pid} ({url} returned 404).")
        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = ArxivError(f"HTTP {resp.status_code} from {url}")
            wait = resp.headers.get("Retry-After", "")
            time.sleep(int(wait) if wait.isdigit() else 2 ** attempt)
            continue
        resp.raise_for_status()
        page = _decode(resp)
        if "ltx_document" not in page:
            raise NoHTMLVersionError(
                f"{resp.url} is not a LaTeXML paper page; arXiv could not produce an HTML version of {pid}."
            )
        return page, resp.url
    raise ArxivError(f"Could not fetch {url} after {retries} attempts: {last_err}")


# --------------------------------------------------------------------------- constants

_MS, _ME, _HB = "", "", ""  # math-token start/end, hard line break
_TO, _TC = "", ""  # "<" and ">" of real HTML tags inside HTML-fallback tables
_TOKEN = re.compile(_MS + r"(\d+)" + _ME)
_SKIP_STRINGS = (Comment, CData, Declaration, Doctype, ProcessingInstruction)

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "caption", "dd", "details", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul",
}
# LaTeXML renders some blocks as <span> when they sit in inline context; classes catch those.
_BLOCK_CLASSES = {
    "ltx_para", "ltx_p", "ltx_listing", "ltx_listingline", "ltx_tabular", "ltx_eqn_table",
    "ltx_eqn_div", "ltx_equationgroup", "ltx_theorem", "ltx_proof", "ltx_figure", "ltx_table",
    "ltx_float", "ltx_caption", "ltx_itemize", "ltx_enumerate", "ltx_description", "ltx_item",
    "ltx_bibliography", "ltx_biblist", "ltx_bibitem", "ltx_abstract", "ltx_authors", "ltx_creator",
    "ltx_quote", "ltx_flex_figure", "ltx_flex_cell", "ltx_block", "ltx_logical-block",
}
_DROP_TAGS = ["script", "style", "noscript", "template", "button", "input", "select", "textarea",
              "nav", "iframe", "head", "meta", "link"]
_DROP_CLASSES = {"ltx_note_type", "ltx_listing_data", "ltx_page_navbar", "ltx_page_header",
                 "ltx_page_footer", "ltx_rdf"}
_VISUAL_TAGS = ["img", "svg", "picture", "canvas", "video", "audio", "object", "embed"]
_PRESERVE_WS = {"html", "body", "article", "section", "div", "span", "p", "pre", "textarea", "code",
                "td", "th", "li", "dd", "dt", "figure", "figcaption", "a", "em", "b", "i", "strong",
                "cite", "sup", "sub", "tt"}
_STRUCTURAL_MARKS = ["ltx_note_mark", "ltx_tag_note", "ltx_note_type"]
_GENERIC_ALTS = {"", "refer to caption", "image", "figure", "graphic"}
_BULLETS = set("•∙◦▪▫‣⁃–—-∗*·○●■□►▸➢➤✓✔")

_LEVEL_BY_CLASS = {
    "ltx_title_document": 1, "ltx_title_part": 2, "ltx_title_chapter": 2, "ltx_title_section": 2,
    "ltx_title_appendix": 2, "ltx_title_bibliography": 2, "ltx_title_abstract": 2,
    "ltx_title_acknowledgements": 2, "ltx_title_index": 2, "ltx_title_glossary": 2,
    "ltx_title_subsection": 3, "ltx_title_subsubsection": 4, "ltx_title_paragraph": 5,
    "ltx_title_subparagraph": 6,
}

_TEX_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%[^\n]*(?:\n[ \t]*)?")
_WS = re.compile(r"[ \t\n\r\f\v\xa0 -   　]+")


# --------------------------------------------------------------------------- helpers


def _cls(el) -> set:
    c = el.get("class") if isinstance(el, Tag) else None
    if not c:
        return set()
    return set(c.split()) if isinstance(c, str) else set(c)


_TEX_COLOR = re.compile(r"\\(?:text)?color(?:\[[^\]]*\])?\{[^{}]*\}\s*")


def _clean_tex(tex: str) -> str:
    # LaTeXML wraps long alttext with "%\n" (a LaTeX comment); drop comments, then join lines.
    tex = _TEX_COMMENT.sub(r"\1", tex)
    # Colour switches are presentation only: "{\color[rgb]{.7,0,0}x}" -> "{x}"
    tex = _TEX_COLOR.sub("", tex)
    return re.sub(r"\s*\n\s*", " ", tex).strip()


def _wrap_multiline(tex: str) -> str:
    """Display math with a bare top-level "\\\\" (LaTeXML drops the split/align wrapper) is not valid
    outside an environment; wrap it so the line breaks render."""
    depth, top_break, top_amp, i = 0, False, False, 0
    while i < len(tex):
        ch = tex[i]
        if ch == "\\":
            m = re.match(r"\\(begin|end)\{[^}]*\}", tex[i:])
            if m:
                depth += 1 if m.group(1) == "begin" else -1
                i += m.end()
                continue
            if tex[i + 1:i + 2] == "\\":
                top_break = top_break or depth == 0
                i += 2
                continue
            i += 2  # any other escape, e.g. \{ \& \,
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "&" and depth == 0:
            top_amp = True
        i += 1
    if not top_break:
        return tex
    env = "aligned" if top_amp else "gathered"
    return f"\\begin{{{env}}} {tex} \\end{{{env}}}"


_TEX_TEXT_ESCAPES = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
                     "#": r"\#", "_": r"\_", "%": r"\%", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _tex_escape_text(s: str) -> str:
    """Escape plain text for use inside \\text{...}."""
    return re.sub(r"[\\{}$&#_%~^]", lambda m: _TEX_TEXT_ESCAPES[m.group(0)], s)


_REL_OPS = re.compile(
    r"^(=|<|>|\+|-|\*|/|,|:|;|\\(leq?|geq?|neq?|ne|approx|equiv|sim|simeq|cong|propto|to|rightarrow|"
    r"leftarrow|Rightarrow|Leftarrow|iff|implies|mapsto|in|notin|subset|subseteq|supset|supseteq|ll|gg|"
    r"pm|mp|times|cdot|div|coloneqq|eqqcolon|triangleq|doteq|prec|succ|preceq|succeq|perp|mid)\b)")


def _joins_tightly(left: str, right: str) -> bool:
    strip = lambda s: re.sub(r"^(\s*\\(displaystyle|textstyle)\s*)+", "", s).strip()
    l, r = strip(left), strip(right)
    return (not l or not r or bool(_REL_OPS.match(r))
            or bool(re.search(r"(=|<|>|\+|-|,|\\(leq?|geq?|neq?|approx|equiv|to|in|times|cdot))\s*$", l))
            or r.startswith(("&", "\\\\")))


def _pipe_safe(tex: str) -> str:
    # A bare "|" would split a Markdown table cell; \vert / \Vert render identically.
    # Add a separating space only before a letter, so "$|x|$" never ends in "\vert $".
    tex = re.sub(r"\\\|(?=[A-Za-z])", r"\\Vert ", tex).replace("\\|", "\\Vert")
    return re.sub(r"\|(?=[A-Za-z])", r"\\vert ", tex).replace("|", "\\vert")


def _protect_line(line: str) -> str:
    """Escape text that would otherwise turn a paragraph line into Markdown structure."""
    s = line.lstrip()
    if not s:
        return s
    if re.match(r"(#{1,6}|[-+*])(\s|$)", s) or s[0] in ">|" or s.startswith(("```", "~~~")):
        return "\\" + s
    m = re.match(r"(\d{1,9})([.)])(\s|$)", s)
    if m:
        return m.group(1) + "\\" + s[len(m.group(1)):]
    compact = s.replace(" ", "")
    if len(compact) >= 3 and len(set(compact)) == 1 and compact[0] in "=-*_":
        return "\\" + s
    return s


def _protect_lines(text: str) -> str:
    return "\n".join(_protect_line(l) for l in text.split("\n"))


def _is_plain_paragraph(block: str) -> bool:
    if block.startswith(("#", ">", "|", "- ", "* ", "+ ", "$$", "```", "~~~", "<table", "[^")):
        return False
    return not re.match(r"\d+[.)](\s|$)", block)


def _indent_item(marker: str, body: str) -> str:
    lines = body.split("\n") if body else [""]
    pad = " " * (len(marker) + 1)
    first = f"{marker} {lines[0]}" if lines[0] else marker
    return "\n".join([first] + [(pad + l) if l.strip() else "" for l in lines[1:]])


def _fence(text: str) -> str:
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    f = "`" * max(3, longest + 1)
    return f"{f}\n{text}\n{f}"


def _split_ws(s: str) -> tuple[str, str, str]:
    m = re.match(r"^([\s" + _HB + r"]*)(.*?)([\s" + _HB + r"]*)$", s, re.S)
    return m.group(1), m.group(2), m.group(3)


def _wrap(s: str, mark: str) -> str:
    lead, core, trail = _split_ws(s)
    if not core or "*" in core:
        return s
    return f"{lead}{mark}{core}{mark}{trail}"


def _wrap_code(s: str) -> str:
    lead, core, trail = _split_ws(s)
    if not core:
        return s
    core = core.replace("\\<", "<").replace("\\$", "$")  # backslash escapes are literal in code spans
    longest = max((len(r) for r in re.findall(r"`+", core)), default=0)
    f = "`" * (longest + 1)
    pad = " " if core.startswith("`") or core.endswith("`") else ""
    return f"{lead}{f}{pad}{core}{pad}{f}{trail}"


def _url_escape(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


# --------------------------------------------------------------------------- converter


class _Converter:
    def __init__(self, base_url: str = ""):
        self.base_url = base_url
        self.maths: list[tuple[str, bool]] = []
        self.emitted: set[int] = set()
        self.in_visual: set[int] = set()
        self.footnotes: list[tuple[str, str]] = []
        self._fn_index: list[tuple[str, str, bool]] = []  # (label, original mark, in title/authors)
        self._html_cells = False  # True while rendering cells of an HTML-fallback table
        self._in_cell = False  # True while rendering any table cell
        self.report = ConversionReport(source=base_url)
        self._block_memo: dict[int, bool] = {}

    # ---- entry point
    def convert(self, page: str) -> tuple[str, ConversionReport]:
        # BeautifulSoup collapses whitespace-only text nodes outside these tags; keeping them
        # preserves indentation in code listings (LaTeXML puts leading spaces in their own spans).
        soup = BeautifulSoup(page, "html.parser", preserve_whitespace_tags=_PRESERVE_WS)
        root = (soup.find("article", class_="ltx_document") or soup.find(class_="ltx_document")
                or soup.find(class_="ltx_page_content") or soup.body or soup)
        self._prepare(root)
        blocks = self.render_children(root)
        md = "\n\n".join(b for b in blocks if b.strip())
        if self.footnotes:
            md += "\n\n" + "\n\n".join(self._footnote_def(l, b) for l, b in self.footnotes)
        self._check_words(md)
        md = re.sub(_ME + _MS, _ME + " " + _MS, md)  # keep "$a$ $b$" from fusing into "$a$$b$"
        md = self._restore(md)
        md = md.replace(_HB, "  \n").strip("\n") + "\n"
        self._finish_report()
        return md, self.report

    # ---- preparation: drop chrome, tokenize math, count source words
    def _prepare(self, root: Tag) -> None:
        for t in root.find_all(_DROP_TAGS):
            if not t.decomposed:
                t.decompose()
        for t in root.find_all(lambda x: bool(_cls(x) & _DROP_CLASSES) or x.has_attr("hidden")):
            if not t.decomposed:
                t.decompose()
        for m in root.find_all("math"):
            tex = m.get("alttext")
            if tex is None:
                ann = m.find("annotation", attrs={"encoding": re.compile(r"tex", re.I)})
                if ann is not None:
                    tex = ann.get_text()
                else:
                    tex = m.get_text(" ")
                    self.report.math_without_latex += 1
            idx = len(self.maths)
            self.maths.append((_clean_tex(tex), m.get("display") == "block"))
            if m.find_parent(_VISUAL_TAGS) is not None:
                self.in_visual.add(idx)
            m.replace_with(NavigableString(f"{_MS}{idx}{_ME}"))
        # LaTeXML sometimes emits math-mode material as text ("ltx_markedasmath"); keep it as math.
        for s in root.find_all(class_="ltx_markedasmath"):
            if s.find_parent(class_="ltx_markedasmath") is not None:
                continue  # its text is taken by the outer one
            def absorb(mm):
                self.emitted.add(int(mm.group(1)))
                return self.maths[int(mm.group(1))][0]
            txt = _TOKEN.sub(absorb, s.get_text(""))
            tex = txt.strip() if re.fullmatch(r"[\w\s.,:;+\-=()\[\]/']*", txt) else "\\text{" + _tex_escape_text(txt) + "}"
            idx = len(self.maths)
            self.maths.append((tex, False))
            s.replace_with(NavigableString(f"{_MS}{idx}{_ME}"))
        self.report.latex_errors_in_source = len(root.select(".ltx_ERROR"))

        # Source text for the completeness check. Inline pieces are joined without spaces
        # (so "L<span>a</span>TeX" counts as one word); block, note and <br> boundaries get a space.
        src_parts, vis_parts = [], []
        prev_unit = None
        for node in root.descendants:
            if isinstance(node, Tag):
                if node.name == "br":
                    src_parts.append(" ")
                continue
            if isinstance(node, _SKIP_STRINGS) or not isinstance(node, NavigableString):
                continue
            if node.find_parent(class_=_STRUCTURAL_MARKS) is not None:
                continue
            text = _TOKEN.sub(" ", str(node))
            if node.find_parent(_VISUAL_TAGS) is not None:
                vis_parts.append(" " + text)
                continue
            unit = node.find_parent(lambda t: self._is_note(t) or self._is_block(t))
            if unit is not prev_unit:
                src_parts.append(" ")
                prev_unit = unit
            src_parts.append(text)
        src = Counter(re.findall(r"\w+", "".join(src_parts)))
        vis = Counter(re.findall(r"\w+", "".join(vis_parts)))
        self._src_joined = re.sub(r"\W+", "", "".join(src_parts))
        self._src_words = src
        self.report.source_words = sum(src.values())
        self.report.words_inside_images = sum(vis.values())

    # ---- block/inline classification
    def _is_note(self, el: Tag) -> bool:
        return "ltx_note" in _cls(el)

    def _is_block(self, el: Tag) -> bool:
        key = id(el)
        if key in self._block_memo:
            return self._block_memo[key]
        if self._is_note(el) or el.name in _VISUAL_TAGS:
            res = False
        elif el.name in _BLOCK_TAGS or _cls(el) & _BLOCK_CLASSES:
            res = True
        else:
            res = any(isinstance(c, Tag) and self._is_block(c) for c in el.children)
        self._block_memo[key] = res
        return res

    # ---- text
    @staticmethod
    def _text(raw: str) -> str:
        raw = raw.replace("$", "\\$")
        return re.sub(r"<(?=[A-Za-z/!?])", r"\\<", raw)

    @staticmethod
    def _finish_inline(s: str) -> str:
        s = s.replace("​", "").replace("\xad", "").replace("﻿", "")
        s = _WS.sub(" ", s)
        s = re.sub(r" ?" + _HB + r"[ " + _HB + r"]*", _HB, s)
        s = s.strip(" " + _HB)
        s = re.sub(r" (\[\^\d+\])", r"\1", s)  # "Vaswani [^1]" -> "Vaswani[^1]"
        return s.replace(_HB, "  \n")

    # ---- block rendering
    def render_children(self, el: Tag) -> list[str]:
        out: list[str] = []
        buf: list[str] = []
        runin: str | None = None

        def emit(blocks: list[str]) -> None:
            nonlocal runin
            blocks = [b for b in blocks if b and b.strip()]
            if not blocks:
                return
            if runin is not None:
                if _is_plain_paragraph(blocks[0]):
                    blocks = [runin + " " + blocks[0]] + blocks[1:]
                else:
                    blocks = [runin] + blocks
                runin = None
            out.extend(blocks)

        def flush() -> None:
            if buf:
                txt = self._finish_inline("".join(buf))
                buf.clear()
                if txt:  # table cells are inline context: no block-level escaping needed
                    emit([txt if self._in_cell else _protect_lines(txt)])

        for child in list(el.children):
            if isinstance(child, _SKIP_STRINGS):
                continue
            if isinstance(child, NavigableString):
                buf.append(self._text(str(child)))
            elif isinstance(child, Tag):
                if self._is_block(child):
                    flush()
                    if child.name in ("h1", "h2", "h3", "h4", "h5", "h6") and "ltx_runin" in _cls(child):
                        if runin is not None:
                            out.append(runin)
                        txt = self._finish_inline(self._inline_children(child, plain=True)).replace("  \n", " ")
                        runin = txt if (not txt or "*" in txt) else f"**{txt}**"
                        continue
                    emit(self.render_block(child))
                else:
                    buf.append(self.inline(child))
        flush()
        if runin:
            out.append(runin)
        return out

    def render_block(self, el: Tag) -> list[str]:
        name, cls = el.name, _cls(el)
        if name in _VISUAL_TAGS:
            v = self._visual(el)
            return [v] if v else []
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return self._heading(el)
        if "ltx_eqn_table" in cls or (name == "table" and cls & {"ltx_equation", "ltx_equationgroup"}):
            return self._equation_table(el)
        if "ltx_eqn_div" in cls:
            return self._equation_div(el)
        if "ltx_tabular" in cls or name == "table":
            return self._table(el)
        if "ltx_listing" in cls:
            return self._listing(el)
        if name == "pre":
            return self._pre(el)
        if name in ("ul", "ol") or cls & {"ltx_itemize", "ltx_enumerate", "ltx_biblist"}:
            return self._list(el)
        if name == "dl" or "ltx_description" in cls:
            return self._dl(el)
        if name == "figcaption" or "ltx_caption" in cls:
            return self._caption(el)
        if name == "blockquote" or "ltx_quote" in cls:
            body = "\n\n".join(self.render_children(el))
            return ["\n".join(("> " + l) if l else ">" for l in body.split("\n"))] if body else []
        if name == "hr":
            return ["---"]
        return self.render_children(el)

    # ---- inline rendering
    def _inline_children(self, el: Tag, plain: bool = False) -> str:
        return "".join(self._inline_node(c, plain) for c in el.children)

    def _inline_node(self, c, plain: bool) -> str:
        if isinstance(c, _SKIP_STRINGS):
            return ""
        if isinstance(c, NavigableString):
            return self._text(str(c))
        if isinstance(c, Tag):
            if self._is_block(c):  # block inside inline context: keep content, flatten breaks
                return _HB.join(self.render_block(c))
            return self.inline(c, plain)
        return ""

    def inline(self, el: Tag, plain: bool = False) -> str:
        name, cls = el.name, _cls(el)
        if name in _VISUAL_TAGS:
            return self._visual(el)
        if self._is_note(el):
            return self._footnote(el)
        if name == "br":
            return _HB
        if name == "a":
            return self._link(el, plain)
        content = self._inline_children(el, plain)
        if plain:
            return content
        code = name in ("code", "tt", "kbd", "samp") or "ltx_font_typewriter" in cls
        bold = name in ("b", "strong") or "ltx_font_bold" in cls
        italic = name in ("i", "em") or bool(cls & {"ltx_font_italic", "ltx_font_slanted"})
        if cls & {"ltx_author_notes", "ltx_contact"}:  # keep "Name" and "email" apart
            content = f" {content} "
        if self._html_cells:  # inside an HTML table Markdown isn't rendered: emit real tags
            for tag, on in (("code", code), ("i", italic), ("b", bold), (name, name in ("sup", "sub"))):
                if on and content.strip():
                    lead, core, trail = _split_ws(content)
                    content = f"{lead}{_TO}{tag}{_TC}{core}{_TO}/{tag}{_TC}{trail}"
            return content
        if code:
            return _wrap_code(content)
        if name in ("sup", "sub") and content.strip():
            return f"<{name}>{content}</{name}>"
        if bold and italic:
            return _wrap(content, "***")
        if bold:
            return _wrap(content, "**")
        if italic:
            return _wrap(content, "*")
        return content

    def _link(self, a: Tag, plain: bool) -> str:
        text = self._inline_children(a, plain)
        href = (a.get("href") or "").strip()
        if plain or not href or href.startswith(("#", "javascript:", "data:", "mailto:")):
            return text  # mailto links are often empty ("mailto:"); the address is the link text
        url = urljoin(self.base_url, href) if self.base_url else href
        if self.base_url and urldefrag(url)[0].rstrip("/") == urldefrag(self.base_url)[0].rstrip("/"):
            return text  # link into this same paper
        lead, core, trail = _split_ws(text)
        if self._html_cells:
            href_attr = _url_escape(url).replace('"', "%22")
            return f'{lead}{_TO}a href="{href_attr}"{_TC}{core or url}{_TO}/a{_TC}{trail}'
        plain_core = core.replace("\\<", "<").replace("\\$", "$")
        if not core or plain_core in (href, url):
            return f"{lead}<{_url_escape(url)}>{trail}"
        core = core.replace("[", "\\[").replace("]", "\\]")
        return f"{lead}[{core}]({_url_escape(url)}){trail}"

    def _visual(self, el: Tag) -> str:
        self.report.images_total += 1
        for fig in el.find_parents("figure"):
            if fig.find("figcaption") is not None or fig.find(class_="ltx_caption") is not None:
                self.report.images_covered_by_caption += 1
                return ""
        self.report.images_without_caption += 1
        alt = (el.get("alt") or "").strip()
        if alt and alt.lower() not in _GENERIC_ALTS:
            return alt if alt.startswith("[") else f"[Image: {alt}]"
        return "[Image]"

    # ---- footnotes
    def _footnote(self, note: Tag) -> str:
        mark_el = next((c for c in note.children if isinstance(c, Tag) and "ltx_note_mark" in _cls(c)), None)
        mark = mark_el.get_text(strip=True) if mark_el else ""
        content = note.find(class_="ltx_note_content")
        if content is None:
            if mark_el is not None:
                mark_el.extract()
            content = note
        for t in content.find_all(class_=_STRUCTURAL_MARKS):
            if t.find_parent(class_="ltx_note") is note:
                t.decompose()
        body = "\n\n".join(self.render_children(content)).strip()
        front = note.find_parent(class_=["ltx_authors", "ltx_title_document"]) is not None
        if not body:
            # An empty note is a repeated marker (\footnotemark) pointing at an earlier footnote:
            # reuse the footnote with the same mark, else the first one in the title/author block.
            target = next((lab for lab, mk, fr in self._fn_index if mark and mk == mark), None)
            if target is None and front:
                target = next((lab for lab, mk, fr in self._fn_index if fr), None)
            if target is not None:
                return f"[^{target}]"
            return f"<sup>{mark}</sup>" if mark else ""
        label = str(len(self.footnotes) + 1)
        self.footnotes.append((label, body))
        self._fn_index.append((label, mark, front))
        self.report.footnotes += 1
        return f"[^{label}]"

    @staticmethod
    def _footnote_def(label: str, body: str) -> str:
        lines = body.split("\n") if body else [""]
        return "\n".join([f"[^{label}]: {lines[0]}"] + [("    " + l) if l.strip() else "" for l in lines[1:]])

    # ---- headings and captions
    def _heading(self, el: Tag) -> list[str]:
        txt = self._finish_inline(self._inline_children(el, plain=True)).replace("  \n", " ")
        if not txt:
            return []
        cls = _cls(el)
        level = next((v for k, v in _LEVEL_BY_CLASS.items() if k in cls), None)
        if level is None:
            level = min(max(int(el.name[1]), 2), 6)
        return ["#" * level + " " + txt]

    def _caption(self, el: Tag) -> list[str]:
        self.report.captions += 1
        tag = el.find(class_=re.compile(r"^ltx_tag_(figure|table|float)$")) or el.find(class_="ltx_tag")
        tag_txt = ""
        if tag is not None:
            tag_txt = self._finish_inline(self.inline(tag, plain=True))
            tag.extract()
        body = "\n".join(self.render_children(el)).strip()
        head = f"**{tag_txt}**" if tag_txt and "*" not in tag_txt else tag_txt
        text = (head + " " + body).strip() if head else body
        return ["\n".join(("> " + l) if l.strip() else ">" for l in text.split("\n"))] if text else []

    # ---- equations
    def _segments(self, raw: str) -> list[tuple[str, str]]:
        segs: list[tuple[str, str]] = []
        for part in re.split("(" + _MS + r"\d+" + _ME + ")", raw):
            m = _TOKEN.fullmatch(part)
            if m:
                idx = int(m.group(1))
                self.emitted.add(idx)
                tex = self.maths[idx][0]
                if not tex:
                    continue
                if segs and segs[-1][0] == "math":
                    segs[-1] = ("math", segs[-1][1] + " " + tex)
                else:
                    segs.append(("math", tex))
            else:
                t = self._finish_inline(part)
                if t:
                    segs.append(("text", t.replace("  \n", " ")))
        return segs

    @staticmethod
    def _seg_line(segs: list[tuple[str, str]]) -> str:
        """One equation row -> a single $$...$$; words inside the row become \\text{...}."""
        if not any(k == "math" for k, _ in segs):
            return " ".join(v for _, v in segs)
        parts, notes = [], []
        for k, v in segs:
            if k == "math":
                parts.append(v)
                continue
            notes += re.findall(r"\[\^[^\]]+\]", v)  # footnote refs must stay outside the math
            v = re.sub(r"\[\^[^\]]+\]", "", v).replace("\\<", "<").replace("\\$", "$")
            if v.strip():
                parts.append("\\text{ " + _tex_escape_text(v.strip()) + " }")
        return "$$" + _wrap_multiline(" ".join(parts)) + "$$" + "".join(notes)

    def _equation_table(self, el: Tag) -> list[str]:
        def owner(node):
            return node.find_parent(lambda t: t.name == "table" or bool(_cls(t) & {"ltx_tabular", "ltx_eqn_table"}))

        rows = [r for r in el.find_all(lambda t: t.name == "tr" or "ltx_eqn_row" in _cls(t)) if owner(r) is el]
        if not rows:
            return self.render_children(el)
        parsed = []  # (segments, number, rowspan)
        for r in rows:
            segs, number, span = [], "", 1
            for cell in r.children:
                if not isinstance(cell, Tag):
                    continue
                ccls = _cls(cell)
                if cell.name not in ("td", "th") and "ltx_eqn_cell" not in ccls:
                    continue
                if "ltx_eqn_eqno" in ccls:
                    number = self._finish_inline(self._inline_children(cell, plain=True))
                    span = int(cell.get("rowspan") or 1) if str(cell.get("rowspan") or "1").isdigit() else 1
                    continue
                if any(re.fullmatch(r"ltx_eqn_\w+_pad(left|right)", c) for c in ccls):
                    continue
                for k, s in enumerate(self._segments(self._inline_children(cell, plain=True))):
                    if segs and segs[-1][0] == s[0] == "math":
                        # Joining two alignment columns: "a" + "=b" stays tight; columns that
                        # don't meet at an operator (cases: value | condition) get a \quad.
                        joiner = " " if k > 0 or _joins_tightly(segs[-1][1], s[1]) else " \\quad "
                        segs[-1] = ("math", segs[-1][1] + joiner + s[1])
                    else:
                        segs.append(s)
            parsed.append((segs, number, span))

        lines: list[str] = []
        i = 0
        while i < len(parsed):
            segs, number, span = parsed[i]
            group = parsed[i:i + max(span, 1)] if number else [parsed[i]]
            group_lines = [self._seg_line(g[0]) for g in group]
            if number:
                self.report.equations_numbered += 1
                group_lines[-1] = (group_lines[-1] + " " + number).strip()
            lines.extend(l for l in group_lines if l)
            i += len(group)
        return ["\n\n".join(lines)] if lines else []

    def _equation_div(self, el: Tag) -> list[str]:
        if any(isinstance(c, Tag) and "ltx_eqn_div" in _cls(c) for c in el.descendants):
            return self.render_children(el)
        tags = [t for t in el.find_all(class_="ltx_tag_equation")]
        number = " ".join(self._finish_inline(self.inline(t, plain=True)) for t in tags)
        for t in tags:
            t.extract()
        line = self._seg_line(self._segments(self._inline_children(el, plain=True)))
        if number:
            self.report.equations_numbered += 1
            line = (line + " " + number).strip()
        return [line] if line else []

    # ---- tables
    def _table(self, el: Tag) -> list[str]:
        def owner(node):
            return node.find_parent(lambda t: t.name == "table" or "ltx_tabular" in _cls(t))

        def span_of(cell, attr):
            v = str(cell.get(attr) or "")
            if v.isdigit():
                return int(v)
            m = next((re.fullmatch(rf"ltx_{attr}_(\d+)", c) for c in _cls(cell) if c.startswith(f"ltx_{attr}_")), None)
            return int(m.group(1)) if m else 1

        rows = []
        for r in el.find_all(lambda t: t.name == "tr" or "ltx_tr" in _cls(t)):
            if owner(r) is not el:
                continue
            cells = [c for c in r.children if isinstance(c, Tag) and (c.name in ("td", "th") or _cls(c) & {"ltx_td", "ltx_th"})]
            parent = r.parent
            in_head = parent is not None and (parent.name == "thead" or "ltx_thead" in _cls(parent))
            rows.append((cells, in_head))
        rows = [(c, h) for c, h in rows if c]
        if not rows:
            return self.render_children(el)

        if self._in_cell:
            # A table nested inside a cell (e.g. a two-line "Active / Params" label): flatten it to
            # one text line per row; a pipe table cannot live inside a pipe-table cell.
            lines = []
            for cells, _ in rows:
                parts = [re.sub(r"\s+", " ", " ".join(self.render_children(c))).strip() for c in cells]
                line = " ".join(p for p in parts if p)
                if line:
                    lines.append(line)
            return ["  \n".join(lines)] if lines else []

        head_rows = sum(1 for _, h in rows if h)

        # Render every cell exactly once (rendering registers footnotes and counts images).
        saved = self._in_cell
        self._in_cell = True
        try:
            text = {}
            for cells, _ in rows:
                for c in cells:  # keep in-cell line breaks as "  \n", flatten anything else
                    t = "  \n".join(self.render_children(c)).replace("  \n", _HB)
                    text[id(c)] = re.sub(r"\s*\n\s*", " ", t).replace(_HB, "  \n").strip()
        finally:
            self._in_cell = saved
        if not any(_TOKEN.sub("", t).strip() or _TOKEN.search(t) for t in text.values()):
            return []  # layout-only table with no content (e.g. a spacer)

        self.report.tables_markdown += 1

        # Expand colspan/rowspan into a rectangular grid of (cell, kind): kind is "own" for the cell's
        # first slot, "col" for the extra slots of a colspan, "row" for the extra slots of a rowspan.
        carry: dict[int, list] = {}  # column -> [rows still to fill, cell, is_colspan_slot]
        grid = []
        for cells, _ in rows:
            row: list = []

            def take_carry():
                while len(row) in carry:
                    entry = carry[len(row)]
                    row.append((entry[1], "col" if entry[2] else "row"))
                    entry[0] -= 1
                    if entry[0] <= 0:
                        del carry[len(row) - 1]

            for c in cells:
                take_carry()
                cs, rs = span_of(c, "colspan"), span_of(c, "rowspan")
                for k in range(cs):
                    if rs > 1:
                        carry[len(row)] = [rs - 1, c, k > 0]
                    row.append((c, "own" if k == 0 else "col"))
            take_carry()
            grid.append(row)
        ncols = max(len(r) for r in grid)
        for r in grid:
            r.extend([(None, "pad")] * (ncols - len(r)))

        # Header rows: <thead> rows if present, otherwise row 0 (plus the next row when row 0 is a
        # group-header row, i.e. it has merged cells).
        if head_rows:
            nhead = head_rows
        else:
            first = rows[0][0]
            nhead = max([span_of(c, "rowspan") for c in first]
                        + [2 if any(span_of(c, "colspan") > 1 for c in first) else 1])
        nhead = max(1, min(nhead, len(grid) - 1 if len(grid) > 1 else 1))

        def md_text(txt: str) -> str:
            return self._restore(txt.replace("  \n", "<br>").replace("|", "\\|"), table=True)

        def head_label(col: int) -> str:
            parts: list[str] = []
            for r in grid[:nhead]:
                c = r[col][0]
                t = text[id(c)].strip() if c is not None else ""
                if t and (not parts or parts[-1] != t):
                    parts.append(t)
            return " / ".join(parts)  # "Accuracy / MNLI": group header + column header

        def align(col: int) -> str:
            for r in grid:
                c, kind = r[col]
                if c is not None and kind == "own":
                    cc = _cls(c)
                    if "ltx_align_center" in cc:
                        return ":---:"
                    if "ltx_align_right" in cc:
                        return "---:"
                    if "ltx_align_left" in cc:
                        return ":---"
            return "---"

        lines = ["| " + " | ".join(md_text(head_label(k)) for k in range(ncols)) + " |",
                 "| " + " | ".join(align(k) for k in range(ncols)) + " |"]
        for r in grid[nhead:]:
            # a colspan's extra slots stay empty; a rowspan's value repeats so every row is self-contained
            vals = [md_text(text[id(c)]) if c is not None and kind != "col" else "" for c, kind in r]
            lines.append("| " + " | ".join(vals) + " |")
        return ["\n".join(lines)]

    # ---- lists
    def _list(self, el: Tag) -> list[str]:
        ordered = el.name == "ol" or "ltx_enumerate" in _cls(el)
        items = [c for c in el.children if isinstance(c, Tag) and (c.name == "li" or _cls(c) & {"ltx_item", "ltx_bibitem"})]
        if not items:
            return self.render_children(el)
        start = int(el.get("start")) if str(el.get("start") or "").isdigit() else 1
        rendered, loose = [], False
        for n, li in enumerate(items):
            tag = next((c for c in li.children if isinstance(c, Tag) and "ltx_tag" in _cls(c)), None)
            marker_txt = None
            if tag is not None:
                marker_txt = self._finish_inline(self.inline(tag, plain=True)).replace("  \n", " ")
                tag.extract()
            blocks = self.render_children(li)
            loose = loose or len(blocks) > 1
            body = "\n\n".join(blocks)
            if not marker_txt:
                marker = f"{start + n}." if ordered else "-"
            elif len(marker_txt) == 1 and marker_txt in _BULLETS:
                marker = "-"
            elif re.fullmatch(r"\d{1,9}[.)]", marker_txt):
                marker = marker_txt
            else:
                marker = "-"
                body = f"{marker_txt} {body}".rstrip() if not body.startswith(("$$", "|", "```", "<table")) else f"{marker_txt}\n\n{body}"
            rendered.append(_indent_item(marker, body))
        return [("\n\n" if loose else "\n").join(rendered)]

    def _dl(self, el: Tag) -> list[str]:
        items, term = [], None
        for c in el.children:
            if not isinstance(c, Tag):
                continue
            if c.name == "dt":
                if term is not None:
                    items.append(f"- **{term}**" if "*" not in term else f"- {term}")
                term = self._finish_inline(self._inline_children(c, plain=True)).replace("  \n", " ")
            elif c.name == "dd":
                body = "\n\n".join(self.render_children(c))
                head = (f"**{term}**" if "*" not in term else term) if term else ""
                items.append(_indent_item("-", (head + " " + body).strip()))
                term = None
        if term is not None:
            items.append(f"- **{term}**" if "*" not in term else f"- {term}")
        return ["\n".join(items)] if items else []

    # ---- listings and preformatted text
    def _listing(self, el: Tag) -> list[str]:
        lines = [l for l in el.find_all(class_="ltx_listingline")
                 if l.find_parent(class_="ltx_listing") is el]
        if not lines:
            return self.render_children(el)
        if not any(_TOKEN.search(l.get_text()) for l in lines):  # source code: keep verbatim
            raw = []
            for l in lines:
                tag = next((c for c in l.children if isinstance(c, Tag) and "ltx_tag" in _cls(c)), None)
                num = tag.extract().get_text("").strip() if tag is not None else ""
                code = l.get_text("").replace("\xa0", " ").strip("\n").rstrip()
                raw.append(f"{num} {code}".rstrip() if num else code)
            while raw and not raw[0].strip():
                raw.pop(0)
            while raw and not raw[-1].strip():
                raw.pop()
            return [_fence("\n".join(raw))] if raw else []
        parsed = []  # algorithm with math: keep line numbers, indentation and formulas
        for l in lines:
            tag = next((c for c in l.children if isinstance(c, Tag) and "ltx_tag" in _cls(c)), None)
            tag_txt = ""
            if tag is not None:
                tag_txt = self._finish_inline(self.inline(tag, plain=True))
                tag.extract()
            raw = self._inline_children(l).replace("\t", "    ")
            lead = len(raw) - len(raw.lstrip(" \xa0\n"))
            lead = len(raw[:lead].replace("\n", ""))
            body = self._finish_inline(raw).replace("  \n", " ")
            if tag_txt or body:
                parsed.append((tag_txt, lead, body))
        if not parsed:
            return []
        base = min(p[1] for p in parsed if p[2]) if any(p[2] for p in parsed) else 0
        out = []
        for tag_txt, lead, body in parsed:
            indent = "\xa0" * max(lead - base, 0)
            line = (f"{tag_txt} " if tag_txt else "") + indent + body
            out.append(_protect_line(line) if not tag_txt else line)
        return ["  \n".join(out)]

    def _pre(self, el: Tag) -> list[str]:
        txt = el.get_text("").replace("\xa0", " ")
        txt = txt[1:] if txt.startswith("\n") else txt
        txt = txt.rstrip()
        return [_fence(txt)] if txt else []

    # ---- math restoration and checks
    def _restore(self, s: str, table: bool = False) -> str:
        def rep(m):
            idx = int(m.group(1))
            self.emitted.add(idx)
            tex, display = self.maths[idx]
            if not tex:
                return ""
            if table:
                tex = _pipe_safe(tex)
            return f"$${_wrap_multiline(tex)}$$" if display else f"${tex}$"
        # "$x$2" / "3$x$" are not parsed as math by most renderers (pandoc, GitHub): add a space.
        s = re.sub(r"(?<=\d)(?=" + _MS + ")", " ", s)
        s = re.sub("(" + _ME + r")(?=\d)", r"\1 ", s)
        return _TOKEN.sub(rep, s)

    def _check_words(self, md: str) -> None:
        text = re.sub(r"</?su[bp]>|\[\^\d+\]:?", "", _TOKEN.sub(" ", md))
        missing = self._src_words - Counter(re.findall(r"\w+", text))
        # Formatting can split a word ("n<em>it</em>n" -> "n*it*n"); a word only counts as
        # missing if its letters also occur fewer times in the output than in the source.
        out_joined = re.sub(r"\W+", "", text)
        self.report.missing_words = [
            (w, c) for w, c in missing.most_common()
            if out_joined.count(w) < self._src_joined.count(w)
        ]

    def _finish_report(self) -> None:
        r = self.report
        r.math_total = len(self.maths)
        r.math_emitted = len(self.emitted - self.in_visual)
        r.math_inside_images = len(self.in_visual - self.emitted)
        if r.math_missing:
            r.warnings.append(f"{r.math_missing} formulas were not written to the output.")
        if r.math_without_latex:
            r.warnings.append(f"{r.math_without_latex} formulas had no LaTeX source; their rendered text was used.")
        if r.latex_errors_in_source:
            r.warnings.append(f"The arXiv HTML itself contains {r.latex_errors_in_source} unconverted LaTeX "
                              "commands (shown as raw text, as on arXiv).")
        if r.words_inside_images:
            r.warnings.append(f"{r.words_inside_images} words are labels drawn inside images/diagrams; "
                              "images are replaced by captions, so these labels are not included.")
        if r.missing_words:
            r.warnings.append(f"{sum(c for _, c in r.missing_words)} source words are missing from the output.")


# --------------------------------------------------------------------------- public API


def html_to_markdown(page: str, base_url: str = "") -> tuple[str, ConversionReport]:
    """Convert LaTeXML/arXiv HTML to Markdown. Returns (markdown, report)."""
    return _Converter(base_url).convert(page)


def arxiv_to_markdown(
    paper_id: str,
    output_path: str | os.PathLike | None = None,
    *,
    write: bool = True,
    strict: bool = False,
    timeout: float = 30.0,
    html: str | None = None,
) -> ConversionResult:
    """
    Fetch https://arxiv.org/html/<paper_id> and convert the whole paper to Markdown.

    paper_id     '1706.03762', '1706.03762v7', 'arXiv:1706.03762' or any arxiv.org URL.
                 Pin a version (v7) for reproducible output.
    output_path  Where to write the .md file (default: '<paper_id>.md'). Ignored if write=False.
    strict       Raise ConversionIncompleteError if any formula or source word is missing.
    html         Already-downloaded page HTML (skips the network request).

    Raises NoHTMLVersionError if arXiv has no HTML version of the paper.
    """
    pid = normalize_arxiv_id(paper_id)
    if html is None:
        html, url = fetch_arxiv_html(pid, timeout=timeout)
    else:
        url = ARXIV_HTML_URL.format(pid)
    md, report = html_to_markdown(html, base_url=url)
    if strict and not report.ok:
        raise ConversionIncompleteError(report.summary())
    path = None
    if write:
        path = os.fspath(output_path) if output_path else pid.replace("/", "_") + ".md"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
    return ConversionResult(markdown=md, report=report, path=path)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert an arXiv paper's HTML version to Markdown.")
    ap.add_argument("paper_id", nargs="?", help="arXiv id or URL, e.g. 1706.03762v7")
    ap.add_argument("-o", "--output", help="output .md path (default: <id>.md)")
    ap.add_argument("--html-file", help="convert a saved HTML page instead of downloading")
    ap.add_argument("--strict", action="store_true", help="fail if anything is missing")
    args = ap.parse_args(argv)
    try:
        if args.html_file:
            with open(args.html_file, encoding="utf-8") as f:
                page = f.read()
            try:
                base = ARXIV_HTML_URL.format(normalize_arxiv_id(args.paper_id)) if args.paper_id else ""
            except ValueError:
                base = ""
            md, report = html_to_markdown(page, base_url=base)
            if args.strict and not report.ok:
                raise ConversionIncompleteError(report.summary())
            out = args.output or os.path.splitext(args.html_file)[0] + ".md"
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
        elif args.paper_id:
            res = arxiv_to_markdown(args.paper_id, args.output, strict=args.strict)
            report, out = res.report, res.path
        else:
            ap.error("give a paper id or --html-file")
            return 2
    except (ArxivError, ConversionIncompleteError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(report.summary())
    print(f"Wrote {out}")
    return 0 if report.ok else 3


if __name__ == "__main__":
    sys.exit(_main())
