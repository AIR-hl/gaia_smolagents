import asyncio
import hashlib
import json
import re
import time
import os
import threading
from datetime import datetime
from typing import List, Optional, Union, Dict, Any
import requests
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from src.utils import is_download_link
from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter, BrowserConfig

from smolagents import Tool

from src.tools.download_tool import download_file
from src.utils import clean_references


# 使用线程本地存储来避免全局变量竞争
_thread_local = threading.local()


def set_crawler_and_link_pool(crawler, link_pool):
    """Set the crawler and link pool for the current thread."""
    _thread_local.crawler = crawler
    _thread_local.link_pool = link_pool


def get_crawler() -> Optional['SimpleCrawler']:
    """Get the crawler for the current thread."""
    return getattr(_thread_local, 'crawler', None)


def get_link_pool() -> Optional['LinkPool']:
    """Get the link pool for the current thread."""
    return getattr(_thread_local, 'link_pool', None)


class CrawlWebpageTool(Tool):
    name = "visit_webpage"
    description = (
        "Access and get formatted content from webpage. You can use this to get cleaned markdown or HTML with orginal layout format.\n"
        "It's ideal for comprehensive content analysis and following links within web documents.\n"
        "But for online files with specific format(.pdf, .xlsx, etc.), you should use corresponding parsing tool to get the content."  
    )
    inputs = {
        "url": {
            "type": "string",
            "description": "The URL of the webpage to visit."
        },
        "return_markdown":{
            "type": "boolean",
            "description": "Whether to return the cleaned markdown content. If False, the cleaned HTML content with original format will be returned. Default is True.",
            "nullable": True,
        }
    }
    output_type = "string"

    def forward(self, url: str, return_markdown: Optional[bool | None]=True) -> str:
        crawler = get_crawler()
        link_pool = get_link_pool()
        
        if crawler is None:
            return "Error: Crawler not initialized. Please set up crawler first."
        
        try:
            # Decode the URL if it's an encoded link
            if url.startswith('link-') and link_pool is not None:
                actual_url = link_pool.decode_url(url[5:])  # Remove 'link-' prefix
                if actual_url:
                    url = actual_url
            
            # Check if this URL was visited recently
            header = crawler._check_history(url)
            
            # Crawl the page
            if return_markdown:
                content = crawler.crawl_page(url)
                content = clean_references(content)
            else:
                content = crawler.crawl_page(url, return_html=True)
            # Encode any new links found in the content
            if link_pool is not None:
                content = link_pool.encode_markdown(content)
                
            return header + content
        except Exception as e:
            return f"Error reading webpage '{url}': {str(e)}"


class CrawlerArchiveWebpageTool(Tool):
    name = "visit_archived_webpage"
    description = (
        "Access and get formatted content of archived webpage from the Wayback Machine.\n"
        "This tool searches the Internet Archive's Wayback Machine to find and retrieve archived versions of web pages from specific dates. "
        "If the exact date is not available, it returns the closest available archive. "
        "It's invaluable for accessing historical content, researching changes over time, or recovering deleted content."
    )
    
    inputs = {
        "url": {
            "type": "string", 
            "description": "The original URL to search for in archives. Should be complete URL with protocol (http:// or https://)"
        },
        "date": {
            "type": "string",
            "description": "Target archive date in YYYYMMDD format. Examples: '20200315' for March 15, 2020, '20081231' for December 31, 2008"
        }
    }
    output_type = "string"

    def forward(self, url: str, date: str) -> str:
        """
        Retrieve historical web content from the Wayback Machine archive for a specific date.
        
        Args:
            url: The original URL to search for in archives. Should be complete URL
                 with protocol (http:// or https://)
            date: Target archive date in YYYYMMDD format. Examples:
                  - "20200315" for March 15, 2020
                  - "20081231" for December 31, 2008
                  - "20150701" for July 1, 2015
        
        Returns:
            Formatted content from the archived webpage with snapshot date information.
            If exact date not available, returns closest available archive.
            Returns error message if no archives exist for the URL.
        """
        # Input validation
        if not url or not isinstance(url, str):
            return "Error: URL must be a non-empty string"
        
        if not (url.startswith('http://') or url.startswith('https://')):
            return "Error: URL must start with http:// or https://"
        
        if not date or not isinstance(date, str):
            return "Error: Date must be a non-empty string"
        
        # Validate date format (YYYYMMDD)
        if not re.match(r'^\d{8}$', date):
            return "Error: Date must be in YYYYMMDD format (e.g., '20200315')"
        
        # Additional date validation - check if it's a valid date
        try:
            datetime.strptime(date, '%Y%m%d')
        except ValueError:
            return f"Error: '{date}' is not a valid date. Use YYYYMMDD format with valid day/month."
        
        crawler = get_crawler()
        link_pool = get_link_pool()
        
        if crawler is None:
            return "Error: Crawler not initialized. Please set up crawler first."
        
        try:
            # Search for archived versions
            no_timestamp_url = f"https://archive.org/wayback/available?url={url}"
            archive_url = no_timestamp_url + f"&timestamp={date}"
            
            response = requests.get(archive_url, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            
            response_notimestamp = requests.get(no_timestamp_url, timeout=30)
            response_notimestamp.raise_for_status()
            response_notimestamp_data = response_notimestamp.json()
            
            closest = None
            if "archived_snapshots" in response_data and "closest" in response_data["archived_snapshots"]:
                closest = response_data["archived_snapshots"]["closest"]
            elif "archived_snapshots" in response_notimestamp_data and "closest" in response_notimestamp_data["archived_snapshots"]:
                closest = response_notimestamp_data["archived_snapshots"]["closest"]
            
            if not closest:
                return f"No archived version found for '{url}' in the Wayback Machine. The URL may not have been archived or may not exist."
            
            target_url = closest["url"]
            archive_date = closest["timestamp"][:8]
            
            # Crawl the archived page
            content = crawler.crawl_page(target_url)
            
            # Check if crawling was successful
            if not content or content.startswith("Error"):
                return f"Error retrieving archived content from '{target_url}': {content}"
            
            # Encode any links found in the archived content
            if link_pool is not None:
                content = link_pool.encode_markdown(content)
            
            return f"Web archive for '{url}', snapshot from {archive_date}:\n\n{content}"
            
        except requests.exceptions.Timeout:
            return f"Error: Request to Wayback Machine timed out. Please try again."
        except requests.exceptions.HTTPError as e:
            return f"Error: HTTP {e.response.status_code} from Wayback Machine API. Please try again later."
        except requests.exceptions.RequestException as e:
            return f"Error: Network issue accessing Wayback Machine: {str(e)}"
        except ValueError as e:
            return f"Error: Invalid response from Wayback Machine API: {str(e)}"
        except Exception as e:
            return f"Error accessing archived webpage for '{url}' from date '{date}': {str(e)}"


class LinkPool:
    """
    A URL encoding/decoding manager that converts URLs to short, manageable identifiers.
    """
    def __init__(self, prefix_length=8):
        # mapping from short_id to full URL
        self._id_to_url: dict[str, str] = {}
        # mapping from full URL to short_id (for fast lookup)
        self._url_to_id: dict[str, str] = {}
        self.prefix_length = prefix_length

    def _generate_id(self, url: str) -> str:
        # create a deterministic short id using hash
        full_hash = hashlib.md5(url.encode()).hexdigest()
        short_id = full_hash[:self.prefix_length]
        
        # handle collision (unlikely but possible)
        counter = 0
        while short_id in self._id_to_url and self._id_to_url[short_id] != url:
            counter += 1
            short_id = full_hash[:self.prefix_length-2] + f"{counter:02d}"
        
        return short_id

    def encode_url(self, url: str) -> str:
        """
        Convert a URL to a short identifier. If the URL is already encoded, return the existing ID.
        """
        if url in self._url_to_id:
            return self._url_to_id[url]
        
        sid = self._generate_id(url)
        self._id_to_url[sid] = url
        self._url_to_id[url] = sid
        return sid

    def decode_url(self, sid: str) -> str:
        """
        Convert a short identifier back to the original URL.
        """
        return self._id_to_url.get(sid, "")

    def encode_html(self, html: str, tag='a', attr='href', placeholder_fmt='[link-{}]') -> str:
        """
        Parse HTML, replace each URL in specified tag/attribute with a placeholder containing its short id.
        Returns modified HTML.
        """
        soup = BeautifulSoup(html, 'html.parser')
        for element in soup.find_all(tag):
            if isinstance(element, Tag):  # Type check to ensure it's a Tag
                url = element.get(attr)
                if url and isinstance(url, str):  # Type check for url
                    sid = self.encode_url(url)
                    element[attr] = placeholder_fmt.format(sid)
        return str(soup)

    def encode_markdown(self, markdown: str, placeholder_fmt='link-{}') -> str:
        """
        Replace Markdown links (inline), including optional titles, with placeholders.
        Format: [text](link-sid, "title").
        """
        result = markdown
        # Inline links: [text](url "optional title")
        pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)(?:\s+\"([^\"]*)\")?\)")
        def repl(match):
            text, url, title = match.group(1), match.group(2), match.group(3)
            sid = self.encode_url(url)
            link_ref = placeholder_fmt.format(sid)
            if title:
                return f"[{text}]({link_ref}, \"{title}\")"
            return f"[{text}]({link_ref})"
        result = pattern.sub(repl, result)
        return result

    def save_pool(self, filepath: str) -> None:
        """
        Save the link pool mapping to a JSON file.
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self._id_to_url, f, ensure_ascii=False, indent=2)

    def load_pool(self, filepath: str) -> None:
        """
        Load the link pool mapping from a JSON file.
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            self._id_to_url = json.load(f)
        self._url_to_id = {url: sid for sid, url in self._id_to_url.items()}


class SimpleCrawler:
    '''
    A simple web crawler for extracting and formatting web content.
    '''
    def __init__(self, threshold: float=0.33, link_pool: Optional[LinkPool]=None):
        self.history = []
        self.md_generator = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=threshold, threshold_type="dynamic")
        )
        load_more_js = [
            "window.scrollTo(0, document.body.scrollHeight);",
            # The "More" link at page bottom
            "document.querySelector('a.morelink')?.click();"  
        ]
        self.run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            markdown_generator=self.md_generator,
            locale='en-US',
            scroll_delay=0.5,
            js_code=load_more_js,
            timezone_id="America/New_York",
        )
        self.link_pool = link_pool
    
    def _pre_visit(self, url):
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i][0] == url:
                return f"You previously visited this page {round(time.time() - self.history[i][1])} seconds ago.\n"
        return ""

    def _to_contents(self, query: str, snippets: List):
        web_snippets = []
        idx = 1
        for search_info in snippets:
            redacted_version = f"{idx}. [{search_info['title']}]({search_info['link']})" + \
                            f"{search_info['date']}{search_info['source']}\n{self._pre_visit(search_info['link'])}{search_info['snippet']}"
            redacted_version = redacted_version.replace("Your browser can't play this video.", "")
            web_snippets.append(redacted_version)
            idx += 1
        
        content = (
            f"A Google search for '{query}' found {len(web_snippets)} results:\n\n## Web Results\n"
            + "\n\n".join(web_snippets)
        )
        return content

    def _check_history(self, url_or_query):
        header = ''
        for i in range(len(self.history) - 2, -1, -1):  # Start from the second last
            if self.history[i][0] == url_or_query:
                header += f"NOTICE: You previously visited this page {round(time.time() - self.history[i][1])} seconds ago.\n---\n"
                return header
        self.history.append((url_or_query, time.time()))
        return header
    
    async def _crawl_page(self, url, return_html: bool=False):
        try:
            # Use a simplified approach to avoid complex async generator issues
            async with AsyncWebCrawler() as crawler:
                # Try to get the result directly
                
                if url.endswith(('.aspx', '.asp', '.php', '.jsp')):
                    load_more_js = [
                        "window.scrollTo(0, document.body.scrollHeight);",
                        # The "More" link at page bottom
                        "document.querySelector('a.morelink')?.click();"  
                    ]
                    result = await crawler.arun(
                        url=url,
                        config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, js_code=load_more_js)
                    )
                    if hasattr(result, 'error_message') and result.error_message:
                        if is_download_link(url):
                            download_result=download_file(url)
                            if download_result['success']:
                                return "The URL is seems a download link, so I have downloaded the file and returned the path. \n" + download_result['file_path']
                            else:
                                return download_result['error']
                        else:
                            return result.error_message
                    if return_html:
                        return result.html
                    else:
                        return result.markdown
                else:
                    result = await crawler.arun(
                        url=url,
                        config=self.run_config
                    )
                    if hasattr(result, 'error_message') and result.error_message:
                        if is_download_link(url):
                            download_result=download_file(url)
                            if download_result['success']:
                                return "The URL is seems a download link, the file has been downloaded and saved at: \n" + download_result['file_path']
                            else:
                                return download_result['error']
                        else:
                            return result.error_message                   
                    if return_html:
                        return result.fit_html
                    else:
                        return result.markdown.fit_markdown
        except Exception as e:
            # Fallback to Jina reader if crawl4ai fails
            try:
                return self._read_page(url)
            except Exception as fallback_error:
                return f"Error crawling page: {str(e)}\nFallback error: {str(fallback_error)}"
        
    def _read_page(self, url):
        jina_url = f'https://r.jina.ai/{url}'
        headers = {
            'Authorization': f'Bearer {os.getenv("JINA_API_KEY")}',
            'X-Engine': 'direct',
            'X-Return-Format': 'text',
            'X-Timeout': '10',
            'X-Token-Budget': '50000'
        }
        response = requests.get(jina_url, headers=headers)
        return response.text

    def crawl_page(self, url, return_html: bool=False):
        header = self._check_history(url)
        pages = asyncio.run(self._crawl_page(url=url, return_html=return_html))
        return header + pages


if __name__ == "__main__":
    crawler = SimpleCrawler()
    url = "https://arxiv.org/ps/2001.01780"
    result=crawler.crawl_page(url, return_html=False)
    print(result)