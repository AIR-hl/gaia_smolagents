import json
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from smolagents import Tool
from dataclasses import dataclass
from bs4 import BeautifulSoup
import re
from urllib.parse import urlencode, quote_plus
import time

@dataclass
class ArxivSearchResult:
    title: str
    authors: List[str]
    # abstract: str
    arxiv_id: str
    pdf_url: str
    abs_url: str
    subjects: List[str]
    submitted_date: str
    announced_date: Optional[str] = None
    doi: Optional[str] = None
    journal_ref: Optional[str] = None
    comments: Optional[str] = None

class ArxivWebSearchTool(Tool):    
    name = "arxiv_search_tool"
    description = (
        "Performs advanced search on ArXiv, it's same as the website and better than external API.\n"
        "Supports all advanced search features including field-specific searches, date filtering and subject classification\n"
        "The output is a dictionary with the following fields: success, query, search_url, total_results, results[dict].\n"
    )
    inputs = {
        'query': {
            "description": "The search query (keywords, paper title, author name, etc.)",
            "type": "string",
        },
        'search_field': {
            "description": "Field to search in. Options: 'all', 'title', 'author', 'abstract', 'comments', 'journal_ref', 'paper_id', Default: 'all'",
            "type": "string",
            "nullable": True,
        },
        'subject_classifications': {
            "description": "List of subject classifications. Options: 'computer_science', 'economics', 'eess', 'mathematics', 'physics', 'q_biology', 'q_finance', 'statistics', Default: None",
            "type": "array",
            "nullable": True,
        },
        'physics_archives': {
            "description": "Physics subcategory when physics is selected. Options: 'all', 'astro-ph', 'cond-mat', 'gr-qc', 'hep-ex', 'hep-lat', 'hep-ph', 'hep-th', 'math-ph', 'nlin', 'nucl-ex', 'nucl-th', 'physics', 'quant-ph'",
            "type": "string",
            "nullable": True,
        },
        'timelimit': {
            "description": "Time filter for the search. Can be a specific year (e.g., '2022'), a date range (e.g., '2022-06-01...2022-06-30'), or an open-ended range (e.g., '2022-06-01...' or '...2022-06-01').",
            "type": "string",
            "nullable": True,
        },
        'max_results': {
            "description": "Maximum number of results to return (25, 50, 100, 200)",
            "type": "integer",
            "nullable": True,
        },
    }
    output_type = "any"
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://arxiv.org/search/advanced"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # Subject classification mapping (using actual form field names)
        self.subject_classifications = {
            'computer_science': 'Computer Science',
            'economics': 'Economics',
            'eess': 'Electrical Engineering and Systems Science',
            'mathematics': 'Mathematics', 
            'physics': 'Physics',
            'q_biology': 'Quantitative Biology',
            'q_finance': 'Quantitative Finance',
            'statistics': 'Statistics'
        }
        
        # Valid search fields from the actual form
        self.search_fields = [
            'title', 'author', 'abstract', 'comments', 'journal_ref', 
            'acm_class', 'msc_class', 'report_num', 'paper_id', 
            'cross_list_category', 'doi', 'orcid', 'author_id', 'all'
        ]
        
        # Physics archives subcategories
        self.physics_archives = [
            'all', 'astro-ph', 'cond-mat', 'gr-qc', 'hep-ex', 'hep-lat',
            'hep-ph', 'hep-th', 'math-ph', 'nlin', 'nucl-ex', 'nucl-th',
            'physics', 'quant-ph'
        ]
    
    def forward(
        self,
        query: str,
        search_field: str = "all",
        subject_classifications: Optional[List[str]] = None,
        physics_archives: str = "all",
        timelimit: Optional[str] = None,
        max_results: int = 25,
    ) -> dict | str:
        try:
            # Clear any accumulated cookies or state that might interfere with requests
            self.session.cookies.clear()

            date_filter = 'all_dates'
            date_year = None
            date_from = None
            date_to = None

            if timelimit:
                if re.fullmatch(r'\d{4}', timelimit):
                    date_filter = 'specific_year'
                    date_year = timelimit
                elif '...' in timelimit:
                    parts = timelimit.split('...')
                    start = parts[0].strip() if parts[0] else None
                    end = parts[1].strip() if parts[1] else None
                    if start or end:
                        date_filter = 'date_range'
                        date_from = start
                        date_to = end

            # Validate date_filter parameters to avoid malformed queries
            if date_filter == 'specific_year' and not date_year:
                # Fallback to all dates if specific year is not provided
                date_filter = 'all_dates'
            if date_filter == 'date_range' and not (date_from or date_to):
                date_filter = 'all_dates'

            # Ensure search_field is valid; otherwise default to 'all'
            if search_field not in self.search_fields:
                search_field = 'all'

            # Build search URL
            search_url = self._build_search_url(
                query=query,
                search_field=search_field,
                subject_classifications=subject_classifications,
                physics_archives=physics_archives,
                date_filter=date_filter,
                date_year=date_year,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
            )
            
            # Perform search
            response = self.session.get(search_url, timeout=30)
            response.raise_for_status()
            
            # Parse results
            results = self._parse_search_results(response.text)
            
            # Format output
            return self._format_results(results, query, search_url)
            
        except Exception as e:
            # return f"Search Error: {str(e)}"
            return "Sorry, this query returned no results. Please try again with different conditions."
    
    def _build_search_url(
        self,
        query: str,
        search_field: str,
        subject_classifications: Optional[List[str]],
        physics_archives: str,
        date_filter: str,
        date_year: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
        max_results: int,
    ) -> str:
        """Build the ArXiv advanced search URL with all parameters"""
        
        # Start with the base advanced search parameters
        params = [
            ('advanced', ''),
            ('terms-0-operator', 'AND'),
            ('terms-0-term', query),
            ('terms-0-field', search_field),
            ('classification-include_cross_list', "include"),
            ('date-filter_by', date_filter)
        ]

        # Add subject classifications
        if subject_classifications:
            for subject in subject_classifications:
                if subject in self.subject_classifications:
                    params.append((f'classification-{subject}', 'y'))
            # Physics archives only make sense if physics is selected
            if 'physics' in subject_classifications:
                params.append(('classification-physics_archives', physics_archives))
        else:
            # If no subject specified but user provided physics archive, include default
            if physics_archives != 'all':
                params.append(('classification-physics_archives', physics_archives))
        
        if date_filter == 'specific_year' and date_year:
            params.append(('date-year', date_year))
        elif date_filter == 'date_range':
            if date_from:
                params.append(('date-from_date', date_from))
            if date_to:
                params.append(('date-to_date', date_to))
        
        # Add date-date_type immediately after date parameters to match ArXiv order
        if date_filter in ['specific_year', 'date_range']:
            params.append(('date-date_type', 'submitted_date_first'))
        
        # Add display options
        params.append(('abstracts', 'hide'))
        
        # Validate and adjust max_results to ArXiv accepted values
        valid_sizes = [25, 50, 100, 200]
        if max_results not in valid_sizes:
            # Find the closest valid size
            adjusted_size = min(valid_sizes, key=lambda x: abs(x - max_results))
        else:
            adjusted_size = max_results
        params.append(('size', str(adjusted_size)))
        
        # Always add order parameter (empty string for relevance)
        sort_param = ""
        params.append(('order', sort_param))
        
        # Add optional parameters only when needed
        # if include_older_versions:
        #     params.append(('include_older_versions', 'y'))
        
        return f"{self.base_url}?{urlencode(params, quote_via=quote_plus)}"
    
    # def _get_sort_parameter(self, sort_by: str) -> str:
    #     """Convert sort option to ArXiv parameter format"""
    #     sort_mapping = {
    #         'relevance': '',  # No order parameter for relevance
    #         'announced_date_desc': '-announced_date_first',
    #         'announced_date_asc': 'announced_date_first', 
    #         'submitted_date_desc': '-submitted_date_first',
    #         'submitted_date_asc': 'submitted_date_first'
    #     }
    #     return sort_mapping.get(sort_by, '')
    
    def _parse_search_results(self, html_content: str) -> List[ArxivSearchResult]:
        """Parse search results from ArXiv HTML page"""
        soup = BeautifulSoup(html_content, 'html.parser')
        results = []
        
        # Find all search result items
        result_items = soup.find_all('li', class_='arxiv-result')
        
        for item in result_items:
            try:
                result = self._parse_single_result(item)
                if result:
                    results.append(result)
            except Exception as e:
                continue  # Skip problematic results
        
        return results
    
    def _get_accurate_submission_date(self, abs_url: str) -> str:
        """Get accurate submission date from paper's detailed page"""
        try:
            # Request the paper's detailed page
            response = self.session.get(abs_url, timeout=10)
            response.raise_for_status()
            
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the submission history section
            submission_history = soup.find('h2', string='Submission history')
            if not submission_history:
                return ""
            
            # The submission history structure is more complex than expected
            # We need to collect all text after the h2 and look for the first date
            
            # Get the parent container of the submission history
            parent = submission_history.parent
            if parent:
                # Get all text content after the submission history h2
                submission_history_index = list(parent.children).index(submission_history)
                remaining_content = list(parent.children)[submission_history_index + 1:]
                
                # Collect all text from these elements
                full_text = ""
                for element in remaining_content:
                    if hasattr(element, 'get_text'):
                        full_text += element.get_text() + " "
                    elif isinstance(element, str):
                        full_text += element + " "
                
                # Look for the first date pattern in the combined text
                # Pattern: "Fri, 8 Dec 2023 15:35:24 UTC" or similar
                date_match = re.search(r'(\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+UTC)', full_text)
                if date_match:
                    return date_match.group(1)
            
            # Alternative approach: look for any element containing submission date pattern
            # This searches the entire page for patterns like "[v1] Mon, 7 Jul 2025 16:13:13 UTC"
            page_text = soup.get_text()
            # Look for version indicators followed by date
            version_date_match = re.search(r'\[v\d+\]\s*(\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+UTC)', page_text)
            if version_date_match:
                return version_date_match.group(1)
                
            # Final fallback: look for any UTC date in the page
            date_match = re.search(r'(\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+UTC)', page_text)
            if date_match:
                return date_match.group(1)
            
            return ""
            
        except Exception as e:
            # If anything goes wrong, return empty string and fall back to search page parsing
            return ""
    
    def _parse_single_result(self, item) -> Optional[ArxivSearchResult]:
        """Parse a single search result item"""
        try:
            # Extract title
            title_elem = item.find('p', class_='title')
            if not title_elem:
                return None
            title = title_elem.get_text().strip()
            
            # Extract authors
            authors_elem = item.find('p', class_='authors')
            authors = []
            if authors_elem:
                author_links = authors_elem.find_all('a')
                authors = [link.get_text().strip() for link in author_links]
            
            # Extract ArXiv ID and URLs
            list_title = item.find('p', class_='list-title')
            arxiv_id = ""
            abs_url = ""
            pdf_url = ""
            
            if list_title:
                arxiv_link = list_title.find('a')
                if arxiv_link:
                    href = arxiv_link.get('href', '')
                    if href.startswith('http'):
                        abs_url = href
                    else:
                        abs_url = "https://arxiv.org" + href
                    arxiv_id = abs_url.split('/')[-1] if abs_url else ""
                    pdf_url = abs_url.replace('/abs/', '/pdf/') + '.pdf' if abs_url else ""
            
            # Extract abstract
            abstract_elem = item.find('span', class_='abstract-full') or item.find('p', class_='abstract')
            abstract = ""
            if abstract_elem:
                abstract = abstract_elem.get_text().strip()
                # Clean up abstract
                abstract = re.sub(r'\s+', ' ', abstract)
                if abstract.startswith('Abstract:'):
                    abstract = abstract[9:].strip()
            
            # Extract subjects
            subjects_elem = item.find('div', class_='tags')
            subjects = []
            if subjects_elem:
                subject_spans = subjects_elem.find_all('span', class_='tag')
                subjects = [span.get_text().strip() for span in subject_spans]
            
            # Get accurate submission date from paper's detailed page
            submitted_date = ""
            announced_date = None
            
            if abs_url:
                submitted_date = self._get_accurate_submission_date(abs_url)
            
            # Fallback: Extract from search results page if detailed page fails
            if not submitted_date:
                submitted_elem = item.find('p', class_='is-size-7')
                if submitted_elem:
                    date_text = submitted_elem.get_text()
                    # Extract dates using regex
                    submitted_match = re.search(r'Submitted[^;]*?(\d{1,2}\s+\w+\s+\d{4})', date_text)
                    if submitted_match:
                        submitted_date = submitted_match.group(1)
                    
                    announced_match = re.search(r'originally announced[^;]*?(\d{1,2}\s+\w+\s+\d{4})', date_text)
                    if announced_match:
                        announced_date = announced_match.group(1)
            
            # Extract additional metadata
            comments_elem = item.find('p', class_='comments')
            comments = comments_elem.get_text().strip() if comments_elem else None
            
            doi_elem = item.find('p', class_='doi')
            doi = None
            if doi_elem:
                doi_link = doi_elem.find('a')
                if doi_link:
                    doi = doi_link.get_text().strip()
            
            journal_elem = item.find('p', class_='journal-ref')
            journal_ref = journal_elem.get_text().strip() if journal_elem else None
            
            return ArxivSearchResult(
                title=title,
                authors=authors,
                # abstract=abstract,
                arxiv_id=arxiv_id,
                pdf_url=pdf_url,
                abs_url=abs_url,
                subjects=subjects,
                submitted_date=submitted_date,
                announced_date=announced_date,
                doi=doi,
                journal_ref=journal_ref,
                comments=comments
            )
            
        except Exception as e:
            return None
    
    def _format_results(self, results: List[ArxivSearchResult], query: str, search_url: str) -> dict:
        """Format search results as JSON string"""
        formatted_results = []
        
        for result in results:
            formatted_result = {
                "title": result.title,
                "authors": result.authors,
                # "abstract": result.abstract,
                "arxiv_id": result.arxiv_id,
                "pdf_url": result.pdf_url,
                "abs_url": result.abs_url,
                "subjects": result.subjects,
                "submitted_date": result.submitted_date,
            }
            
            # Add optional fields if they exist
            if result.announced_date:
                formatted_result["announced_date"] = result.announced_date
            if result.doi:
                formatted_result["doi"] = result.doi
            if result.journal_ref:
                formatted_result["journal_ref"] = result.journal_ref
            if result.comments:
                formatted_result["comments"] = result.comments
                
            formatted_results.append(formatted_result)
        
        return {
            "success": True,
            "query": query,
            "search_url": search_url,
            "total_results": len(formatted_results),
            "results": formatted_results
        }

# Test functions
def test_arxiv_web_search():
    """Test the ArXiv web search tool"""
    tool = ArxivWebSearchTool()
    
    # print("=== Basic search test ===")
    # result = tool(
    #     query="transformer neural network",
    #     max_results=3
    # )
    # print(result)
    # time.sleep(5)
    # print("\n=== Field-specific search test ===")
    # result = tool(
    #     query="AI governance",
    #     search_field="title",
    #     max_results=3
    # )
    # print(result)
    # time.sleep(5)
    print("\n=== Date range search test ===")
    result = tool(
        query="deep learning",
        timelimit="2023-01-01...2023-12-31",
        max_results=3
    )
    print(result)
    # time.sleep(5)        
    # print("\n=== Subject classification test ===")
    # result = tool(
    #     query="machine learning",
    #     subject_classifications=["cs"],
    #     max_results=3
    # )
    # print(result)

if __name__ == "__main__":
    test_arxiv_web_search() 