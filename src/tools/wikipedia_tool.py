from smolagents import Tool
from typing import Optional
import requests
import re
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
import threading

# 使用线程本地存储来获取link_pool
_thread_local = threading.local()

def get_link_pool():
    """Get the link pool for the current thread."""
    return getattr(_thread_local, 'link_pool', None)

def set_link_pool(link_pool):
    """Set the link pool for the current thread."""
    _thread_local.link_pool = link_pool

class WikiSearchTool(Tool):
    name = "wiki_search_tool"
    description = (
        "Search Wikipedia for articles with optional year filtering, returns article titles, summaries, and links.\n"
        "The output is a dictionary with the following fields: success, query, total_results, results[].\n"
    )
    inputs = {
        "query": {
            "type": "string", 
            "description": "The Wikipedia search query."
        },
        "filter_year": {
            "type": "string", 
            "description": "Filter results by year (YYYY format). Will prioritize articles created or modified in that year.",
            "nullable": True,
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5).",
            "nullable": True,
        }
    }
    output_type = "any"
    
    def __init__(self):
        super().__init__()
        
    def forward(self, query: str, filter_year: Optional[str] = None, limit: Optional[int] = 5) -> dict:
        """Search Wikipedia and return formatted results with optional year filtering."""
        
        # If year is specified, add it to the search query
        search_query = query
        if filter_year:
            search_query = f"{query} {filter_year}"
        
        base_url = "https://en.wikipedia.org/w/api.php"
        
        # Handle None limit
        result_limit = limit if limit is not None else 5
        
        # First, search for articles
        search_params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": search_query,
            "srlimit": result_limit * 2,  # Get more results to filter
            "srprop": "timestamp|snippet|size"
        }
        
        try:
            response = requests.get(base_url, params=search_params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if 'error' in data:
                error_info = data['error']
                return {"success": False, "query": query, "total_results": 0, "results": [f"Wikipedia API error: {error_info.get('code', 'unknown')} - {error_info.get('info', 'unknown')}"]}

            search_results = data.get("query", {}).get("search", [])
            
            if not search_results:
                return {"success": False, "query": query, "total_results": 0, "results": [f"No Wikipedia articles found for: {query}"]}
            
            # Filter by year if specified
            if filter_year:
                filtered_results = []
                for result in search_results:
                    timestamp = result.get("timestamp", "")
                    if timestamp.startswith(filter_year):
                        filtered_results.append(result)
                
                # If no exact year matches, fall back to all results
                if not filtered_results:
                    filtered_results = search_results
                    
                search_results = filtered_results[:limit]
            else:
                search_results = search_results[:limit]
            
            # Get detailed info for each result
            titles = [result["title"] for result in search_results]
            info_params = {
                "action": "query",
                "format": "json",
                "prop": "extracts|info",
                "exintro": True,
                "explaintext": True,
                "titles": "|".join(titles),
                "redirects": 1,
                "inprop": "url"
            }
            
            info_response = requests.get(base_url, params=info_params, timeout=10)
            info_response.raise_for_status()
            info_data = info_response.json()
            
            pages = info_data.get("query", {}).get("pages", {})
            results = []
            
            for result in search_results:
                title = result["title"]
                snippet = result.get("snippet", "")
                timestamp = result.get("timestamp", "")
                
                # Find corresponding page info
                page_info = None
                for page_id, page_data in pages.items():
                    if page_data.get("title") == title:
                        page_info = page_data
                        break
                
                if page_info:
                    extract = page_info.get("extract", snippet)
                    page_url = page_info.get("fullurl", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}")
                else:
                    extract = snippet
                    page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                
                # Clean up the extract
                truncated_extract = extract[:400]
                cleaned_extract = re.sub(r'\n+', '; ', truncated_extract)
                cleaned_extract = re.sub(r'\s+', ' ', cleaned_extract).strip()
                cleaned_extract = re.sub(r'<[^>]+>', '', cleaned_extract)  # Remove HTML tags
                
                year_info = ""
                if timestamp:
                    year_info = f" (Last modified: {timestamp[:4]})"
                
                result_text = f"[{title}]({page_url}){year_info}\nSummary: {cleaned_extract}{'...' if len(extract) > 400 else ''}"
                results.append(result_text)

            if results:
                formatted_results = []
                for idx, result in enumerate(results):
                    formatted_results.append(f"{idx+1}. {result}")
                
                header = f"## Wikipedia Search Results for '{query}'"
                if filter_year:
                    header += f" (filtered by year {filter_year})"
                
                return {"success": True, "query": query, "total_results": len(formatted_results), "results": formatted_results}
            
            return {"success": False, "query": query, "total_results": 0, "results": [f"No Wikipedia articles found for: {query}"]}
            
        except requests.Timeout:
            raise TimeoutError("Wikipedia request timed out. Please try again.")
        except requests.RequestException as e:
            raise requests.RequestException(f"Network error: {str(e)}")
        except Exception as e:
            raise Exception(f"Wikipedia search error: {str(e)}")


class WikiPageTool(Tool):
    name = "visit_wiki_page"
    description = (
        "A intelligent tool for accessing and getting the clean content of a Wikipedia page from given URL.\n"
        "The content will be formatted to markdown-like format, and all media items(images, videos, audio) will be preserved, and exclude References, See Also, Notes, Bibliography, etc. sections."
    )
    inputs = {
        "url": {
            "type": "string", 
            "description": "The Wikipedia URL to retrieve (e.g., 'https://en.wikipedia.org/wiki/Python_(programming_language)' or 'https://en.wikipedia.org/wiki/Machine_learning')."
        },
        "include_media": {
            "type": "boolean",
            "description": "Whether to include media elements href(images, videos) in the output (default: True).",
            "nullable": True,
        }
    }
    output_type = "string"
    
    def __init__(self):
        super().__init__()
        
    def forward(self, url: str, include_media: Optional[bool] = True) -> str:
        """Retrieve full Wikipedia page content with media and encoded links."""
        base_url = "https://en.wikipedia.org/w/api.php"
        link_pool = get_link_pool()
        if url.startswith('link-') and link_pool is not None:
            actual_url = link_pool.decode_url(url[5:])  # Remove 'link-' prefix
            if actual_url:
                url = actual_url
                
        # Extract page title from URL
        try:
            if '/wiki/' in url:
                title = url.split('/wiki/')[-1]
                title = title.replace('_', ' ')
                # URL decode the title
                import urllib.parse
                title = urllib.parse.unquote(title)
            else:
                return f"Invalid Wikipedia URL format: {url}"
        except Exception as e:
            return f"Error parsing Wikipedia URL: {str(e)}"
        
        # Get page content in HTML format
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "text|displaytitle|categories",
            "disableeditsection": True,
            "disabletoc": True
        }
        
        try:
            response = requests.get(base_url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            if 'error' in data:
                error_info = data['error']
                return f"Wikipedia API error: {error_info.get('code', 'unknown')} - {error_info.get('info', 'unknown')}"

            parse_data = data.get("parse", {})
            html_content = parse_data.get("text", {}).get("*", "")
            display_title = parse_data.get("displaytitle", title)
            
            if not html_content:
                return f"No content found for Wikipedia page: {url}"
            
            # Parse HTML content
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove references, see also sections and everything after them
            self._remove_sections_and_below(soup, [
                'references', 'References', 'REFERENCES',
                'see_also', 'See_also', 'SEE_ALSO',
                'notes', 'Notes', 'NOTES',
                'bibliography', 'Bibliography', 'BIBLIOGRAPHY',
                'external_links', 'External_links', 'EXTERNAL_LINKS',
                'further_reading', 'Further_reading', 'FURTHER_READING'
            ])
            
            # Remove reference links [1], [2], etc.
            for ref_link in soup.find_all('sup', class_='reference'):
                ref_link.decompose()
            
            # Remove edit links
            for edit_link in soup.find_all('span', class_='mw-editsection'):
                edit_link.decompose()
            
            # Handle hyperlinks based on include_media setting
            for link in soup.find_all('a'):
                if isinstance(link, Tag) and link.get('href'):
                    # Check if link contains media elements
                    contains_media = bool(link.find_all(['img', 'video', 'audio', 'source']))
                    
                    if include_media and contains_media:
                        # Preserve media links when include_media=True
                        continue
                    else:
                        # Remove non-media links and replace with text content
                        link_text = link.get_text()
                        if link_text.strip():
                            link.replace_with(NavigableString(link_text))
                        else:
                            link.decompose()
            
            if include_media:
                # Process and fix URLs for all media elements
                for media in soup.find_all(['img', 'video', 'audio', 'source']):
                    if not isinstance(media, Tag):
                        continue
                    
                    # Fix src attributes
                    src = media.get('src')
                    if src and isinstance(src, str):
                        if src.startswith('//'):
                            media['src'] = f"https:{src}"
                        elif src.startswith('/'):
                            media['src'] = f"https://en.wikipedia.org{src}"
                        elif src.startswith('//upload.wikimedia.org/'):
                            media['src'] = f"https:{src}"
                    
                    # Fix srcset attributes for responsive images
                    srcset = media.get('srcset')
                    if srcset and isinstance(srcset, str):
                        fixed_srcset = []
                        for src_item in srcset.split(','):
                            src_item = src_item.strip()
                            if src_item.startswith('//'):
                                fixed_srcset.append(f"https:{src_item}")
                            elif src_item.startswith('/'):
                                fixed_srcset.append(f"https://en.wikipedia.org{src_item}")
                            else:
                                fixed_srcset.append(src_item)
                        media['srcset'] = ', '.join(fixed_srcset)
                    
                    # Fix poster attribute for videos
                    poster = media.get('poster')
                    if poster and isinstance(poster, str):
                        if poster.startswith('//'):
                            media['poster'] = f"https:{poster}"
                        elif poster.startswith('/'):
                            media['poster'] = f"https://en.wikipedia.org{poster}"
                
                # Also fix URLs for media links
                for media_link in soup.find_all('a'):
                    if isinstance(media_link, Tag) and media_link.get('href'):
                        # Check if this is a media-related link
                        href = media_link.get('href')
                        if href and isinstance(href, str):
                            if href.startswith('//'):
                                media_link['href'] = f"https:{href}"
                            elif href.startswith('/'):
                                media_link['href'] = f"https://en.wikipedia.org{href}"
            else:
                # Remove all media elements
                for media in soup.find_all(['img', 'video', 'audio', 'source', 'figure']):
                    media.decompose()
            
            # Convert to markdown-like format
            content = self._html_to_markdown(soup)
            
            # Add page header
            header = f"# {display_title}\n\n**Source:** {url}\n\n"
            
            return header + content
            
        except requests.Timeout:
            return "Wikipedia request timed out. Please try again."
        except requests.RequestException as e:
            return f"Network error: {str(e)}"
        except Exception as e:
            return f"Wikipedia page retrieval error for {url}: {str(e)}"
    
    def _remove_sections_and_below(self, soup: BeautifulSoup, section_names: list) -> None:
        """Remove specified sections and everything below them."""
        # Find all elements in the soup
        all_elements = list(soup.find_all())
        
        # Look for section headings that match our target names
        for i, element in enumerate(all_elements):
            if isinstance(element, Tag) and element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                heading_text = element.get_text().strip().lower()
                heading_id_attr = element.get('id', '')
                heading_id = heading_id_attr.lower() if isinstance(heading_id_attr, str) else ''
                
                # Check if this heading matches any of our target sections
                for section_name in section_names:
                    target_name = section_name.lower().replace('_', ' ')
                    if (heading_text == target_name or 
                        heading_text == target_name.replace(' ', '') or
                        target_name in heading_text or
                        target_name in heading_id):
                        
                        # Remove this heading and everything after it
                        elements_to_remove = all_elements[i:]
                        for elem in elements_to_remove:
                            if hasattr(elem, 'decompose'):
                                elem.decompose()
                        return  # Stop after finding the first matching section
        
        # Also look for span elements with matching IDs (Wikipedia sometimes uses these)
        for span in soup.find_all('span', {'id': True}):
            if isinstance(span, Tag):
                span_id_attr = span.get('id', '')
                span_id = span_id_attr.lower() if isinstance(span_id_attr, str) else ''
                for section_name in section_names:
                    target_name = section_name.lower().replace('_', '')
                    if target_name in span_id:
                        # Find the parent heading and remove from there
                        parent = span.parent
                        while parent and (not isinstance(parent, Tag) or parent.name not in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                            parent = parent.parent
                        if parent and isinstance(parent, Tag):
                            # Remove parent heading and everything after it
                            current = parent
                            while current:
                                next_sibling = current.next_sibling
                                if hasattr(current, 'decompose'):
                                    current.decompose()
                                current = next_sibling
                            return
    
    def _html_to_markdown(self, soup: BeautifulSoup) -> str:
        """Convert HTML content to markdown-like format, preserving media links."""
        result = []
        
        for element in soup.descendants:
            if isinstance(element, Tag) and element.name:
                if element.name == 'h1':
                    result.append(f"\n\n# {element.get_text().strip()}\n")
                elif element.name == 'h2':
                    result.append(f"\n\n## {element.get_text().strip()}\n")
                elif element.name == 'h3':
                    result.append(f"\n\n### {element.get_text().strip()}\n")
                elif element.name == 'h4':
                    result.append(f"\n\n#### {element.get_text().strip()}\n")
                elif element.name == 'p':
                    text = element.get_text().strip()
                    if text:
                        result.append(f"{text}\n")
                elif element.name == 'a':
                    # Handle preserved media links - extract and show media only
                    href = element.get('href')
                    if href and isinstance(href, str):
                        # Check if this link contains media elements
                        media_elements = element.find_all(['img', 'video', 'audio'])
                        if media_elements:
                            # Extract media elements without the link wrapper
                            for media in media_elements:
                                if isinstance(media, Tag):
                                    if media.name == 'img':
                                        alt_text = media.get('alt', 'Image')
                                        if not isinstance(alt_text, str):
                                            alt_text = 'Image'
                                        src = media.get('src', '')
                                        if isinstance(src, str) and src:
                                            result.append(f"\n![{alt_text}]({src})\n")
                                    elif media.name == 'video':
                                        src = media.get('src', '')
                                        if isinstance(src, str) and src:
                                            result.append(f"\n[Video: {src}]\n")
                                    elif media.name == 'audio':
                                        src = media.get('src', '')
                                        if isinstance(src, str) and src:
                                            result.append(f"\n[Audio: {src}]\n")
                elif element.name == 'img':
                    # Handle standalone images (not within links)
                    if not element.find_parent('a'):
                        alt_text = element.get('alt', 'Image')
                        if not isinstance(alt_text, str):
                            alt_text = 'Image'
                        src = element.get('src', '')
                        if isinstance(src, str) and src:
                            result.append(f"\n![{alt_text}]({src})\n")
                elif element.name == 'video':
                    # Handle standalone videos (not within links)
                    if not element.find_parent('a'):
                        src = element.get('src', '')
                        if isinstance(src, str) and src:
                            result.append(f"\n[Video: {src}]\n")
                elif element.name == 'audio':
                    # Handle standalone audio (not within links)
                    if not element.find_parent('a'):
                        src = element.get('src', '')
                        if isinstance(src, str) and src:
                            result.append(f"\n[Audio: {src}]\n")
                elif element.name == 'ul':
                    # Handle lists
                    continue
                elif element.name == 'li':
                    text = element.get_text().strip()
                    if text:
                        result.append(f"- {text}\n")
                elif element.name == 'table':
                    # Simple table representation
                    result.append("\n[Table content - see original page for full table]\n")
                elif element.name in ['strong', 'b']:
                    text = element.get_text().strip()
                    if text:
                        result.append(f"**{text}**")
                elif element.name in ['em', 'i']:
                    text = element.get_text().strip()
                    if text:
                        result.append(f"*{text}*")
        
        # Join and clean up
        content = ''.join(result)
        content = re.sub(r'\n{3,}', '\n\n', content)  # Remove excessive newlines
        content = re.sub(r'[ \t]+', ' ', content)  # Clean up whitespace
        
        return content.strip()


# Unit Tests
if __name__ == "__main__":
    import unittest
    from unittest.mock import Mock, patch
    
    class TestWikipediaTools(unittest.TestCase):
        
        def setUp(self):
            self.search_tool = WikiSearchTool()
            self.page_tool = WikiPageTool()
            
        def test_search_tool_basic_search(self):
            """Test basic Wikipedia search functionality"""
            # Mock the requests.get call
            with patch('requests.get') as mock_get:
                # Mock search response
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {
                    "query": {
                        "search": [
                            {
                                "title": "Test Article",
                                "snippet": "Test snippet",
                                "timestamp": "2024-01-01T00:00:00Z"
                            }
                        ]
                    }
                }
                
                # Mock detailed info response
                mock_info_response = Mock()
                mock_info_response.raise_for_status.return_value = None
                mock_info_response.json.return_value = {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "Test Article",
                                "extract": "Test extract content",
                                "fullurl": "https://en.wikipedia.org/wiki/Test_Article"
                            }
                        }
                    }
                }
                
                mock_get.side_effect = [mock_response, mock_info_response]
                
                result = self.search_tool.forward("test query")
                self.assertIn("Test Article", result)
                self.assertIn("Test extract content", result)
                
        def test_search_tool_with_year_filter(self):
            """Test Wikipedia search with year filtering"""
            with patch('requests.get') as mock_get:
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {
                    "query": {
                        "search": [
                            {
                                "title": "Test Article 2020",
                                "snippet": "Test snippet from 2020",
                                "timestamp": "2020-01-01T00:00:00Z"
                            }
                        ]
                    }
                }
                
                mock_info_response = Mock()
                mock_info_response.raise_for_status.return_value = None
                mock_info_response.json.return_value = {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "Test Article 2020",
                                "extract": "Test extract from 2020",
                                "fullurl": "https://en.wikipedia.org/wiki/Test_Article_2020"
                            }
                        }
                    }
                }
                
                mock_get.side_effect = [mock_response, mock_info_response]
                
                result = self.search_tool.forward("test query", filter_year="2020")
                self.assertIn("2020", result)
                self.assertIn("Test Article 2020", result)
        
        def test_search_tool_error_handling(self):
            """Test error handling in Wikipedia search"""
            with patch('requests.get') as mock_get:
                mock_response = Mock()
                mock_response.raise_for_status.side_effect = requests.RequestException("Network error")
                mock_get.return_value = mock_response
                
                result = self.search_tool.forward("test query")
                self.assertIn("Network error", result)
                
        def test_page_tool_url_parsing(self):
            """Test URL parsing in WikiPageTool"""
            test_cases = [
                ("https://en.wikipedia.org/wiki/Python_(programming_language)", "Python (programming language)"),
                ("https://en.wikipedia.org/wiki/Machine_learning", "Machine learning"),
                ("https://en.wikipedia.org/wiki/Artificial_intelligence", "Artificial intelligence"),
            ]
            
            for url, expected_title in test_cases:
                # Extract title using the same logic as in the tool
                if '/wiki/' in url:
                    title = url.split('/wiki/')[-1]
                    title = title.replace('_', ' ')
                    import urllib.parse
                    title = urllib.parse.unquote(title)
                    self.assertEqual(title, expected_title)
                    
        def test_page_tool_invalid_url(self):
            """Test invalid URL handling"""
            result = self.page_tool.forward("https://invalid-url.com")
            self.assertIn("Invalid Wikipedia URL format", result)
            
        def test_page_tool_basic_functionality(self):
            """Test basic page retrieval functionality"""
            with patch('requests.get') as mock_get:
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {
                    "parse": {
                        "text": {
                            "*": "<div><p>Test content</p></div>"
                        },
                        "displaytitle": "Test Article"
                    }
                }
                mock_get.return_value = mock_response
                
                # Mock link pool
                mock_link_pool = Mock()
                mock_link_pool.encode_url.return_value = "test123"
                set_link_pool(mock_link_pool)
                
                result = self.page_tool.forward("https://en.wikipedia.org/wiki/Test_Article")
                self.assertIn("Test Article", result)
                self.assertIn("Test content", result)
                
        def test_page_tool_with_media_disabled(self):
            """Test page retrieval with media disabled"""
            with patch('requests.get') as mock_get:
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {
                    "parse": {
                        "text": {
                            "*": "<div><p>Test content</p><img src='test.jpg' alt='test'></div>"
                        },
                        "displaytitle": "Test Article"
                    }
                }
                mock_get.return_value = mock_response
                
                result = self.page_tool.forward("https://en.wikipedia.org/wiki/Test_Article", include_media=False)
                self.assertIn("Test Article", result)
                self.assertIn("Test content", result)
                # Media should be removed when include_media=False
                
        def test_page_tool_api_error(self):
            """Test API error handling"""
            with patch('requests.get') as mock_get:
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = {
                    "error": {
                        "code": "missingtitle",
                        "info": "The page you specified doesn't exist."
                    }
                }
                mock_get.return_value = mock_response
                
                result = self.page_tool.forward("https://en.wikipedia.org/wiki/Nonexistent_Article")
                self.assertIn("Wikipedia API error", result)
                self.assertIn("missingtitle", result)
                
        def test_link_pool_functions(self):
            """Test link pool utility functions"""
            # Test set_link_pool and get_link_pool
            test_pool = Mock()
            set_link_pool(test_pool)
            retrieved_pool = get_link_pool()
            self.assertEqual(test_pool, retrieved_pool)
            
            # Test with None
            set_link_pool(None)
            retrieved_pool = get_link_pool()
            self.assertIsNone(retrieved_pool)
            
    # Run the tests
    unittest.main(verbosity=2)