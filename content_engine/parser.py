"""
DOB Newsletter Email Parser

Parses NYC DOB "Buildings News" / "My NYC.gov News" digest emails and extracts
the individual updates so the Content Intelligence engine can turn them into
content candidates.

These emails are GovDelivery-style HTML (nested tables, <font> tags, <hr>
separators) — NOT the idealized <h2>Service Updates</h2> + <ul> layout the
first version of this parser assumed. Story headlines are rendered as
<font style="font-size: 16pt"> elements:
  * color #003399  -> feature stories (the actual updates)
  * color #204496  -> section labels (Service Updates, Local Laws, Buildings
                      Bulletins, Hearings + Rules, Code Notes, etc.)
The masthead ("Buildings news") uses a much larger font (~43pt) and is skipped.

The primary extractor below walks the document in reading order, treating each
16pt heading as the start of a new update and everything up to the next heading
(or <hr>) as that update's body. If it finds nothing (e.g. a differently
formatted email), it falls back to the legacy header/list extractor.
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from bs4 import BeautifulSoup, NavigableString, Tag
import requests

logger = logging.getLogger(__name__)

# Heading font sizes (in pt). Story/section headings are ~16pt; the masthead is
# ~43pt and must be excluded.
_HEADING_MIN_PT = 14.0
_HEADING_MAX_PT = 26.0

# Boilerplate heading/title text we never want to emit as an update.
_SKIP_TITLES = {
    "buildings", "news", "buildings news", "dob now", "service notices",
    "forms", "bis", "codes", "jobs",
}


class DOBNewsletterParser:
    """Parse NYC DOB Buildings News HTML emails."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def parse_email(self, html_content: str, fetch_linked_pages: bool = False) -> Dict:
        """
        Parse a DOB newsletter HTML email into a list of updates.

        Args:
            html_content: raw HTML of the email.
            fetch_linked_pages: if True, fetch each update's primary link one
                level deep for extra context. Off by default because the
                newsletter links are opaque click-tracker redirects and the
                email body itself is already good source content.

        Returns:
            {
                "newsletter_date": "2026-07-02",
                "updates": [
                    {
                        "title": "...",
                        "category": "Service Updates",
                        "summary": "...",
                        "source_url": "https://...",
                        "referenced_links": [...],
                        "full_content": "..."
                    },
                    ...
                ]
            }
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        for tag in soup(['script', 'style']):
            tag.decompose()

        newsletter_date = self._extract_date(soup)

        # Primary: GovDelivery / real DOB newsletter format.
        updates = self._extract_govdelivery(soup)

        # Fallback: legacy idealized <h2>/<ul> format.
        if not updates:
            logger.info("GovDelivery extractor found nothing; trying legacy extractor")
            updates = self._extract_legacy(soup)

        # RESOLVE each story's links to their final URLs, but do NOT fetch and
        # concatenate the linked content into the story text. The sidebar sections
        # ("Buildings Bulletins", "Code Notes", "Service Updates") are lists of
        # links to DOB PDFs; the poller ingests each of those PDFs as its OWN clean
        # doc (email_poller._download_and_ingest_pdf). Previously we also fetched and
        # concatenated all of them into the section's full_content, producing a messy
        # multi-notice blob that DUPLICATED the clean per-PDF docs. Now we only
        # resolve the GovDelivery click-tracker URLs to their real destinations so
        # the poller can ingest each PDF cleanly, and leave the section text as its
        # own email blurb.
        if fetch_linked_pages:
            for u in updates:
                links = []
                if u.get('source_url'):
                    links.append(u['source_url'])
                for link in (u.get('referenced_links') or []):
                    if link not in links:
                        links.append(link)
                resolved = []
                for link in links[:8]:
                    final = self._resolve_url(link)
                    if final and final not in resolved:
                        resolved.append(final)
                if resolved:
                    u['source_url'] = resolved[0]
                    u['referenced_links'] = resolved

        logger.info(f"Parsed {len(updates)} updates from DOB newsletter (date={newsletter_date})")
        return {"newsletter_date": newsletter_date, "updates": updates}

    # ------------------------------------------------------------------
    # Date
    # ------------------------------------------------------------------
    def _extract_date(self, soup: BeautifulSoup) -> str:
        """Extract the newsletter date, tolerant of embedded whitespace."""
        # Collapse all whitespace (the email splits dates across lines/tabs,
        # e.g. "July 2,\n\t\t2026").
        text = ' '.join(soup.get_text(' ').split())

        patterns = [
            r'([A-Z][a-z]+\.?\s+\d{1,2},\s*\d{4})',   # July 2, 2026
            r'(\d{1,2}/\d{1,2}/\d{4})',                # 07/02/2026
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    from dateutil import parser as dateparser
                    return dateparser.parse(match.group(1)).strftime("%Y-%m-%d")
                except Exception:
                    continue
        return datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Primary extractor: real GovDelivery newsletter format
    # ------------------------------------------------------------------
    def _is_heading(self, tag: Tag) -> bool:
        """A <font> (or span) styled as a ~16pt section/story heading."""
        if not isinstance(tag, Tag):
            return False
        if tag.name not in ('font', 'span'):
            return False
        style = tag.get('style', '') or ''
        m = re.search(r'font-size:\s*([\d.]+)\s*pt', style)
        if not m:
            return False
        size = float(m.group(1))
        return _HEADING_MIN_PT <= size <= _HEADING_MAX_PT

    def _tokenize(self, root: Tag) -> List[tuple]:
        """Walk the tree in reading order into a flat token stream.

        Tokens: ('head', title) | ('text', str) | ('link', text, href) | ('hr',)
        Heading and anchor inner text is captured once (we don't recurse into
        them) to avoid duplication.
        """
        tokens: List[tuple] = []

        def walk(node: Tag):
            for child in node.children:
                if isinstance(child, NavigableString):
                    s = ' '.join(str(child).split())
                    if s:
                        tokens.append(('text', s))
                elif isinstance(child, Tag):
                    if self._is_heading(child):
                        title = ' '.join(child.get_text(' ', strip=True).split())
                        tokens.append(('head', title))
                    elif child.name == 'hr':
                        tokens.append(('hr',))
                    elif child.name == 'a':
                        txt = ' '.join(child.get_text(' ', strip=True).split())
                        href = child.get('href', '') or ''
                        tokens.append(('link', txt, href))
                        if txt:
                            tokens.append(('text', txt))
                    elif child.name in ('img', 'br'):
                        continue
                    else:
                        walk(child)

        walk(root)
        return tokens

    def _extract_govdelivery(self, soup: BeautifulSoup) -> List[Dict]:
        root = soup.body or soup
        tokens = self._tokenize(root)

        raw: List[Dict] = []
        cur: Optional[Dict] = None

        def flush():
            nonlocal cur
            if cur is not None:
                raw.append(cur)
                cur = None

        for tok in tokens:
            kind = tok[0]
            if kind == 'head':
                title = tok[1].strip()
                flush()
                if not title or title.lower() in _SKIP_TITLES or len(title) < 3:
                    cur = None
                    continue
                cur = {'title': title, 'summary_parts': [], 'links': []}
            elif kind == 'hr':
                flush()
            elif kind == 'text':
                if cur is not None:
                    cur['summary_parts'].append(tok[1])
            elif kind == 'link':
                if cur is not None and tok[2]:
                    cur['links'].append((tok[1], tok[2]))
        flush()

        updates: List[Dict] = []
        for item in raw:
            summary = ' '.join(' '.join(item['summary_parts']).split())
            # Drop empty / pure-boilerplate blocks.
            if len(summary) < 40:
                continue
            if self._is_boilerplate(item['title'], summary):
                continue
            source_url = item['links'][0][1] if item['links'] else ''
            updates.append({
                "title": item['title'],
                "category": self._classify(item['title'], summary),
                "summary": summary[:1200],
                "source_url": source_url,
                "referenced_links": [href for _, href in item['links'][:8]],
                "full_content": summary,
            })
        return updates

    @staticmethod
    def _is_boilerplate(title: str, summary: str) -> bool:
        t = f"{title} {summary}".lower()
        markers = (
            "unsubscribe", "manage your subscription", "update your preferences",
            "this email was sent", "govdelivery", "privacy policy",
        )
        return any(m in t for m in markers)

    @staticmethod
    def _classify(title: str, summary: str = "") -> str:
        """Map a heading to one of the categories bot_v2 knows how to ingest."""
        t = f"{title} {summary}".lower()
        if "local law" in t:
            return "Local Laws"
        if "code note" in t:
            return "Code Notes"
        if "bulletin" in t and "enforcement" not in t:
            return "Buildings Bulletins"
        if "hearing" in t or ("rule" in t and "rules" in title.lower()):
            return "Hearings"
        if any(w in t for w in ("weather advisor", "hurricane", "storm",
                                 "heat wave", "extreme heat", "snow", "blizzard",
                                 "flooding", "coastal storm")):
            return "Weather"
        return "Service Updates"

    # ------------------------------------------------------------------
    # Fallback extractor: legacy idealized <h2>/<ul> format
    # ------------------------------------------------------------------
    _LEGACY_SECTIONS = [
        "Service Updates", "Local Laws", "Buildings Bulletins",
        "Hearings", "Rules", "Weather", "Code Notes",
    ]

    def _extract_legacy(self, soup: BeautifulSoup) -> List[Dict]:
        updates: List[Dict] = []
        for section in self._LEGACY_SECTIONS:
            updates.extend(self._extract_section(soup, section))
        return updates

    def _extract_section(self, soup: BeautifulSoup, section_name: str) -> List[Dict]:
        updates = []
        headers = soup.find_all(['h2', 'h3', 'strong', 'b'])
        for header in headers:
            if section_name.lower() in header.get_text().lower():
                for item in self._extract_items_after_header(header):
                    updates.append({
                        "title": item['title'],
                        "category": section_name,
                        "summary": item['summary'],
                        "source_url": item['link'],
                        "referenced_links": [],
                        "full_content": item['summary'],
                    })
                break
        return updates

    def _extract_items_after_header(self, header) -> List[Dict]:
        items = []
        current = header.find_next_sibling()
        while current and current.name not in ['h2', 'h3']:
            if current.name in ['ul', 'ol']:
                for li in current.find_all('li'):
                    item = self._parse_list_item(li)
                    if item:
                        items.append(item)
            elif current.name == 'p':
                link = current.find('a')
                if link:
                    items.append({
                        'title': link.get_text().strip(),
                        'summary': current.get_text().strip(),
                        'link': link.get('href', ''),
                    })
            current = current.find_next_sibling()
        return items

    def _parse_list_item(self, li) -> Optional[Dict]:
        link = li.find('a')
        if not link:
            return None
        href = link.get('href', '')
        if href and not href.startswith('http'):
            href = f"https://www.nyc.gov{href}"
        return {
            'title': link.get_text().strip(),
            'summary': li.get_text().strip(),
            'link': href,
        }

    # ------------------------------------------------------------------
    # Optional linked-page enrichment
    # ------------------------------------------------------------------
    def _resolve_url(self, url: str) -> str:
        """Follow redirects (GovDelivery click-trackers) and return the final URL,
        without downloading the body. Returns '' on failure."""
        if not url or not url.startswith('http'):
            return url or ''
        try:
            r = self.session.get(url, timeout=10, stream=True, allow_redirects=True)
            final = str(r.url or url)
            r.close()
            return final
        except Exception as e:
            logger.warning(f"Could not resolve {url}: {e}")
            return ''

    def _fetch_page_content(self, url: str) -> Tuple[str, List[str]]:
        if not url or not url.startswith('http'):
            return "", []
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            # DOB service-notice links are GovDelivery trackers that redirect to a
            # PDF. Parsing PDF bytes as HTML yields binary garbage, so detect a PDF
            # response (by content-type or the post-redirect URL) and extract its
            # text with PyMuPDF instead.
            ctype = response.headers.get('content-type', '').lower()
            final_url = str(getattr(response, 'url', '') or url).lower()
            if 'pdf' in ctype or final_url.endswith('.pdf'):
                try:
                    import fitz  # PyMuPDF
                    parts = []
                    with fitz.open(stream=response.content, filetype='pdf') as doc:
                        for page in doc:
                            parts.append(page.get_text())
                    return "\n".join(parts).strip()[:5000], []
                except Exception as e:
                    logger.warning(f"PDF extract failed for {url}: {e}")
                    return "", []

            soup = BeautifulSoup(response.content, 'html.parser')
            for script in soup(['script', 'style']):
                script.decompose()
            content = soup.get_text(separator='\n', strip=True)
            referenced_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if not href.startswith('http'):
                    href = f"https://www.nyc.gov{href}"
                if any(ext in href.lower() for ext in ['.pdf', '/buildings/', '/dob']):
                    referenced_links.append(href)
            return content[:5000], list(set(referenced_links))
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return "", []


# Email forwarding handler
def handle_forwarded_email(email_content: str) -> Dict:
    """Handle a forwarded DOB newsletter email."""
    return DOBNewsletterParser().parse_email(email_content)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: python parser.py <newsletter.html>")
        raise SystemExit(1)
    result = DOBNewsletterParser().parse_email(open(path, encoding='utf-8').read())
    print(f"newsletter_date: {result['newsletter_date']}")
    print(f"updates: {len(result['updates'])}\n")
    for u in result['updates']:
        print(f"- [{u['category']}] {u['title']}")
        print(f"    {u['summary'][:120]}...")
        print(f"    url: {u['source_url'][:70]}")
