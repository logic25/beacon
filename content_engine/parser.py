"""
DOB Newsletter Email Parser

Parses DOB Buildings News emails and extracts updates.
"""

import re
import logging
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)


class DOBNewsletterParser:
    """Parse DOB Buildings News HTML emails"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def parse_email(self, html_content: str) -> Dict:
        """
        Parse DOB newsletter HTML email.
        
        Returns:
            {
                "newsletter_date": "2026-01-28",
                "updates": [
                    {
                        "title": "New Sidewalk Shed Rules",
                        "category": "Service Updates",
                        "summary": "...",
                        "source_url": "https://...",
                        "referenced_links": ["https://...", ...],
                        "full_content": "..."
                    }
                ]
            }
        """
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract newsletter date from subject or content
        newsletter_date = self._extract_date(soup)
        
        # Extract all sections
        updates = []
        
        # Service Updates section
        updates.extend(self._extract_section(soup, "Service Updates"))
        
        # Local Laws section
        updates.extend(self._extract_section(soup, "Local Laws"))
        
        # Buildings Bulletins section  
        updates.extend(self._extract_section(soup, "Buildings Bulletins"))
        
        # Hearings + Rules section
        updates.extend(self._extract_section(soup, "Hearings"))
        updates.extend(self._extract_section(soup, "Rules"))
        
        # Weather Advisories
        updates.extend(self._extract_section(soup, "Weather"))
        
        # Code Notes
        updates.extend(self._extract_section(soup, "Code Notes"))
        
        logger.info(f"Parsed {len(updates)} updates from DOB newsletter")
        
        return {
            "newsletter_date": newsletter_date,
            "updates": updates
        }
    
    def _extract_date(self, soup: BeautifulSoup) -> str:
        """Extract newsletter date"""
        # Look for date patterns in the HTML
        date_patterns = [
            r'(\w+ \d{1,2}, \d{4})',  # January 28, 2026
            r'(\d{1,2}/\d{1,2}/\d{4})',  # 01/28/2026
        ]
        
        text = soup.get_text()
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    date_str = match.group(1)
                    # Try to parse it
                    from dateutil import parser
                    date_obj = parser.parse(date_str)
                    return date_obj.strftime("%Y-%m-%d")
                except:
                    pass
        
        # Default to today if not found
        return datetime.now().strftime("%Y-%m-%d")
    
    def _extract_section(self, soup: BeautifulSoup, section_name: str) -> List[Dict]:
        """Extract updates from a specific section"""
        
        updates = []
        
        # Find section header
        # DOB newsletters use various formats, so we search flexibly
        section_patterns = [
            section_name,
            section_name.upper(),
            section_name.lower(),
        ]
        
        for pattern in section_patterns:
            # Find all headers that might be section titles
            headers = soup.find_all(['h2', 'h3', 'strong', 'b'])
            
            for header in headers:
                if pattern.lower() in header.get_text().lower():
                    # Found the section, extract items
                    items = self._extract_items_after_header(header)
                    
                    for item in items:
                        update = {
                            "title": item['title'],
                            "category": section_name,
                            "summary": item['summary'],
                            "source_url": item['link'],
                            "referenced_links": [],
                            "full_content": ""
                        }
                        
                        # Fetch the linked page content
                        if item['link']:
                            content, links = self._fetch_page_content(item['link'])
                            update['full_content'] = content
                            update['referenced_links'] = links
                        
                        updates.append(update)
                    
                    break
        
        return updates
    
    def _extract_items_after_header(self, header) -> List[Dict]:
        """Extract list items after a section header"""
        
        items = []
        
        # Navigate to next sibling elements
        current = header.find_next_sibling()
        
        while current and current.name not in ['h2', 'h3']:
            # Check if it's a list
            if current.name in ['ul', 'ol']:
                for li in current.find_all('li'):
                    item = self._parse_list_item(li)
                    if item:
                        items.append(item)
            
            # Check if it's a paragraph with a link
            elif current.name == 'p':
                link = current.find('a')
                if link:
                    items.append({
                        'title': link.get_text().strip(),
                        'summary': current.get_text().strip(),
                        'link': link.get('href', '')
                    })
            
            current = current.find_next_sibling()
        
        return items
    
    def _parse_list_item(self, li) -> Optional[Dict]:
        """Parse a single list item"""
        
        # Find link in list item
        link = li.find('a')
        
        if not link:
            return None
        
        title = link.get_text().strip()
        href = link.get('href', '')
        
        # Make absolute URL if relative
        if href and not href.startswith('http'):
            href = f"https://www1.nyc.gov{href}"
        
        # Get summary (text after the link)
        summary = li.get_text().strip()
        
        return {
            'title': title,
            'summary': summary,
            'link': href
        }
    
    def _fetch_page_content(self, url: str) -> tuple[str, List[str]]:
        """
        Fetch content from a linked page (1 level deep only).
        
        Returns:
            (content_text, referenced_links)
        """
        
        if not url or not url.startswith('http'):
            return "", []
        
        try:
            logger.info(f"Fetching content from: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(['script', 'style']):
                script.decompose()
            
            # Get text content
            content = soup.get_text(separator='\n', strip=True)
            
            # Extract referenced links (PDFs, related pages)
            referenced_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                
                # Make absolute
                if not href.startswith('http'):
                    href = f"https://www1.nyc.gov{href}"
                
                # Include PDFs and DOB pages
                if any(ext in href.lower() for ext in ['.pdf', '/buildings/', '/dob']):
                    referenced_links.append(href)
            
            # Remove duplicates
            referenced_links = list(set(referenced_links))
            
            logger.info(f"Fetched {len(content)} chars, found {len(referenced_links)} referenced links")
            
            return content[:5000], referenced_links  # Limit content length
            
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return "", []


# Email forwarding handler
def handle_forwarded_email(email_content: str) -> Dict:
    """
    Handle a forwarded DOB newsletter email.
    
    This would be called when an email is forwarded to
    beacon@greenlightexpediting.com
    
    Args:
        email_content: Raw email HTML content
        
    Returns:
        Parsed newsletter data
    """
    
    parser = DOBNewsletterParser()
    return parser.parse_email(email_content)


# Test function
def test_parser():
    """Test the parser with a sample"""
    
    sample_html = """
    <html>
    <body>
        <h1>Buildings News Update - January 28, 2026</h1>
        
        <h2>Service Updates</h2>
        <ul>
            <li><a href="https://www1.nyc.gov/site/buildings/news/sidewalk-shed-permits.page">
                New Sidewalk Shed Permit Rules: 90-Day Expiration
            </a> - Starting January 26, sidewalk shed permits expire every 90 days.</li>
            
            <li><a href="https://www1.nyc.gov/site/buildings/news/superintendent-limits.page">
                Construction Superintendent One-Site Limit (LL149)
            </a> - Superintendents can now only work at one site.</li>
        </ul>
        
        <h2>Local Laws</h2>
        <ul>
            <li><a href="https://www1.nyc.gov/site/buildings/news/ll-update.page">
                Local Law Updates
            </a> - New accessibility requirements.</li>
        </ul>
    </body>
    </html>
    """
    
    parser = DOBNewsletterParser()
    result = parser.parse_email(sample_html)
    
    print(f"Parsed {len(result['updates'])} updates:")
    for update in result['updates']:
        print(f"  - {update['title']} ({update['category']})")
        print(f"    URL: {update['source_url']}")
        print(f"    Referenced links: {len(update['referenced_links'])}")
        print()


if __name__ == "__main__":
    test_parser()
