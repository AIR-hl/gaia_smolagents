import copy
from datetime import datetime
import json
import logging
import re
from turtle import back
from typing import Literal, Optional, Tuple, List, Dict, Union
from typing_extensions import deprecated
from uuid import uuid4
from smolagents import Tool
import requests
from ddgs import DDGS
from urllib.parse import unquote


class DuckDuckGoSearchTool(Tool):
    name = "web_search_tool"
    description = (
        "Search the web using DuckDuckGo. Returns top search results with titles, links, and snippets. Supports time filtering for recent results.\n"
        "The output is a dictionary with the following fields: success, query, total_results, results[str].\n"
    )
    inputs = {
        "query": {
            "type": "string", 
            "description": "The search query to perform."
        },
        "timelimit": {
            "type": "string", 
            "description": (
                "Time filter: 'd' (1 day), 'w' (1 week), 'm' (1 month), 'y' (1 year), or custom range 'YYYY-MM-DD...YYYY-MM-DD'. Default: no time limit."
            ),
            "nullable": True,
        },
    }
    output_type = "any"

    def __init__(self, max_results=10, **kwargs):
        super().__init__()
        self.max_results = max_results
        self.backend=kwargs.get("backend", "duckduckgo")
        self.ddgs = DDGS()

    def _format_timelimit(self, timelimit: str | None) -> str | None:
        """Format timelimit string, replacing NOW with current date."""
        if timelimit:
            return timelimit.replace("NOW", datetime.now().strftime('%Y-%m-%d'))
        return timelimit

    def forward(self, query: str, timelimit: str | None = None) -> dict:
        """Search and return formatted results."""
        results_list, _ = self._search_internal(query, timelimit)
        
        if isinstance(results_list, str):  # Error message
            return {"success": False, "query": query, "total_results": 0, "results": [results_list]}
        
        formatted_results = []
        for idx, result in enumerate(results_list):
            formatted_results.append(f"{idx+1}. {result}")
        
        return {
            "success": True,
            "query": query,
            "total_results": len(formatted_results),
            "results": formatted_results
        }
    
    def _search_internal(self, query: str, timelimit: str | None = None) -> Tuple[Union[List[str], str], Dict[str, int]]:
        """Internal search method that returns raw results and mapping."""
        timelimit = self._format_timelimit(timelimit)
        
        try:
            results = self.ddgs.text(query, num_results=self.max_results, backend=self.backend, timelimit=timelimit, safesearch="off", region="wt-wt")
        except Exception as e:
            return f"Search failed: {str(e)}", {}
        
        if len(results) == 0:
            if timelimit:
                return f"No results found for query: '{query}' with time filter {timelimit}. Try a broader query.", {}
            else:
                return f"No results found for query: '{query}'. Try a different query.", {}
        
        postprocessed_results = []
        result_map = {}
        
        for idx, result in enumerate(results):
            snippet = result.get('body', '')
            # Clean up snippet
            snippet = re.sub(r'\n+', '; ', snippet)
            snippet = re.sub(r'\s+', ' ', snippet).strip()
            if len(snippet) > 250:
                truncated = snippet[:175]
                last_space = truncated.rfind(' ')
                if last_space > 0:
                    snippet = truncated[:last_space] + '...'
                else:
                    snippet = truncated + '...'
            formatted_result = f"[{result['title']}]({result['href']})\nSnippet: {snippet}"
            postprocessed_results.append(formatted_result)
            result_map[result['title']] = idx
            
        return postprocessed_results, result_map


class GoogleSearchTool(Tool):
    name = "web_search_tool"
    description = (
        "Search the web using Google. Returns top search results with titles, links, date published, source and snippets."
        "It supports time filtering and specific engine selection."
        "The output is a dictionary with the following fields: success, query, total_results, results."
    )
    inputs = {
        "query": {
            "type": "string", 
            "description": "The search query to perform."
        },
        "timelimit": {
            "type": "string", 
            "description": (
                "Time filter: 'd' (1 day), 'w' (1 week), 'm' (1 month), 'y' (1 year), or custom range 'YYYY-MM-DD...YYYY-MM-DD'. Default: no time limit."
            ),
            "nullable": True,
        },
    }
    output_type = "any"

    def __init__(self, max_results=10, **kwargs):
        super().__init__()
        import os
        self.organic_key = "organic_results"
        self.max_results = max_results
        self.api_key = os.getenv("SERPAPI_API_KEY")
        if self.api_key is None:
            raise ValueError("Missing SERPAPI_API_KEY environment variable.")

    def _format_timelimit(self, timelimit: str | None) -> str | None:
        """Format timelimit string, replacing NOW with current date."""
        if timelimit:
            return timelimit.replace("NOW", datetime.now().strftime('%Y-%m-%d'))
        return timelimit

    def _build_time_params(self, timelimit: str | None) -> Dict[str, str]:
        """Build time filter parameters for Google search."""
        params = {}
        if timelimit:
            match = re.match(r"(\d{4}-\d{2}-\d{2})\.\.\.(\d{4}-\d{2}-\d{2})", timelimit)
            if match:
                start_date = datetime.strptime(match.group(1), "%Y-%m-%d").strftime("%d/%m/%Y")
                end_date = datetime.strptime(match.group(2), "%Y-%m-%d").strftime("%d/%m/%Y")
                params["tbs"] = f"cdr:1,cd_min:{start_date},cd_max:{end_date}"
        return params

    def forward(self, query: str, timelimit: Optional[str | None] = None) -> dict:
        """Search and return formatted results."""
        results_list, _ = self._search_internal(query, timelimit)
        
        if isinstance(results_list, str):  # Error message
            return {"success": False, "query": query, "total_results": 0, "results": [results_list]}
        
        formatted_results = []
        for idx, result in enumerate(results_list):
            formatted_results.append(f"{idx+1}. {result}")
        
        return {
            "success": True,
            "query": query,
            "total_results": len(formatted_results),
            "results": formatted_results
        }

    def _search_internal(self, query: str, timelimit: Optional[str | None] = None) -> Tuple[Union[List[str], str], Dict[str, int]]:
        """Internal search method that returns raw results and mapping."""
        timelimit = self._format_timelimit(timelimit)
        
        params = {
            "q": query,
            "api_key": self.api_key,
            "engine": "google",
            "google_domain": "google.com",
            "safe": "off",
            "num": self.max_results,
        }
        
        # Add time filtering if specified
        time_params = self._build_time_params(timelimit)
        params.update(time_params)
        
        base_url = "https://serpapi.com/search.json"
        
        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            results = response.json()
        except requests.RequestException as e:
            return f"Search request failed: {str(e)}", {}
        except ValueError as e:
            return f"Failed to parse search results: {str(e)}", {}

        if self.organic_key not in results:
            if timelimit:
                return f"No results found for query: '{query}' with time filter {timelimit}. Try a broader query.", {}
            else:
                return f"No results found for query: '{query}'. Try a different query.", {}

        if len(results[self.organic_key]) == 0:
            if timelimit:
                return f"No results found for '{query}' with time filter {timelimit}. Try a broader query.", {}
            else:
                return f"No results found for '{query}'. Try a different query.", {}

        web_snippets = []
        result_map = {}
        
        for idx, page in enumerate(results[self.organic_key]):
            date_published = f"\nDate: {page['date']}" if "date" in page else ""
            source = f"\nSource: {page['source']}" if "source" in page else ""
            
            raw_snippet = page.get('snippet', '')
            if raw_snippet:
                cleaned_snippet = re.sub(r'\n+', '; ', raw_snippet)
                cleaned_snippet = re.sub(r'\s+', ' ', cleaned_snippet).strip()
                snippet = f"\nSnippet: {cleaned_snippet}"
            else:
                snippet = ""

            formatted_result = f"[{page['title']}]({unquote(page['link'])}){date_published}{source}{snippet}"
            web_snippets.append(formatted_result)
            result_map[page['title']] = idx
            
        return web_snippets, result_map

class BingSearchTool(Tool):
    name = "web_search_tool"
    description = (
        "Search the web using Bing via internal API. Returns top search results with titles, links, and snippets. "
        "Supports time filtering for recent results."
        "The output is a dictionary with the following fields: success, query, total_results, results."
    )
    inputs = {
        "query": {
            "type": "string", 
            "description": "The search query to perform."
        },
        "timelimit": {
            "type": "string", 
            "description": (
                "Time filter: 'd' (1 day), 'w' (1 week), 'm' (1 month), 'y' (1 year), "
                "or custom range 'YYYY-MM-DD...YYYY-MM-DD'. Default: no time limit."
            ),
            "nullable": True,
        },
    }
    output_type = "any"

    def __init__(self, max_results=10, **kwargs):
        super().__init__()
        self.max_results = max_results
        self.bing_url = "http://autobots-inner-search-dev.jd.local/api/bing_search"
        self.bing_header = {
            'Content-Type': 'application/json'
        }
        self.base_payload = {
            "use_llm": False,
            "model": "bing_search",
            "count": self.max_results,
            "parser_type": "bs4",
        }

    def _format_timelimit(self, timelimit: str | None) -> str | None:
        """Format timelimit string, replacing NOW with current date."""
        if timelimit:
            return timelimit.replace("NOW", datetime.now().strftime('%Y-%m-%d'))
        return timelimit

    def forward(self, query: str, timelimit: Optional[str | None] = None) -> dict:
        """Search and return formatted results."""
        results_list, _ = self._search_internal(query, timelimit)
        
        if isinstance(results_list, str):  # Error message
            return {
                "success": False,
                "query": query,
                "total_results": 0,
                "results": [results_list]
            }
        
        formatted_results = []
        for idx, result in enumerate(results_list):
            formatted_results.append(f"{idx+1}. {result}")
        
        # return "## Search Results\n\n" + "\n\n".join(formatted_results)
        return {
            "success": True,
            "query": query,
            "total_results": len(formatted_results),
            "results": formatted_results
        }
    
    def _search_internal(self, query: str, timelimit: Optional[str | None] = None) -> Tuple[Union[List[str], str], Dict[str, int]]:
        """Internal search method that returns raw results and mapping."""
        timelimit = self._format_timelimit(timelimit)
        
        # Prepare request payload
        request_body = copy.deepcopy(self.base_payload)
        request_body["query"] = query
        request_body["requestId"] = str(uuid4())
        
        try:
            response = requests.post(
                self.bing_url, 
                headers=self.bing_header, 
                data=json.dumps(request_body),
                timeout=10
            )
            response.raise_for_status()
            bing_results_list = response.json().get("data", [])
        except requests.RequestException as e:
            return f"Bing search request failed: {str(e)}", {}
        except (ValueError, KeyError) as e:
            return f"Failed to parse Bing search results: {str(e)}", {}
        
        if len(bing_results_list) == 0:
            if timelimit:
                return f"No results found for query: '{query}' with time filter {timelimit}. Try a broader query.", {}
            else:
                return f"No results found for query: '{query}'. Try a different query.", {}
        
        postprocessed_results = []
        result_map = {}
        
        for idx, result in enumerate(bing_results_list):
            # Extract and limit snippet length
            snippet = result.get('page_content', '')[:300]
            snippet = snippet.replace("  ", "")
            snippet = re.sub(r'\n+', '; ', snippet)
            snippet = re.sub(r'\s+', ' ', snippet)
            if len(result.get('page_content', '')) > 300:
                snippet += '...'
            
            formatted_result = f"[{result.get('name', 'Unknown Title')}]({result.get('source_url', '')})\nSnippet: {snippet}"
            postprocessed_results.append(formatted_result)
            result_map[result.get('name', f'result_{idx}')] = idx
            
        return postprocessed_results, result_map


@deprecated("Use IntegratedSearchTool_v2 instead")
class IntegratedSearchTool(Tool):
    name = "web_search_tool"
    description = (
        "Search the web using multiple search engines. "
        "Supports configurable engine selection and time filtering."
        "The output is a dictionary with the following fields: success, query, total_results, results."
    )
    inputs = {
        "query": {
            "type": "string", 
            "description": "The search query to perform."
        },
        "timelimit": {
            "type": "string", 
            "description": (
                "Time filter: 'd' (1 day), 'w' (1 week), 'm' (1 month), 'y' (1 year), or custom range 'YYYY-MM-DD...YYYY-MM-DD'. Default: no time limit."
            ),
            "nullable": True,
        },
    }
    output_type = "any"

    def __init__(self, search_engines: List[Literal["bing", "google", "duckduckgo", "yandex", "yahoo", "auto"]], **kwargs):
        super().__init__()
        self.engines_used = search_engines
        self.search_engines = []
        self.failed_engines = []
        
        if len(self.engines_used) == 0:
            self.engines_used = ["google"]

        for idx, engine in enumerate(self.engines_used):    
            # Initialize search engines with error handling
            if engine=="google":
                try:
                    self.google_search = GoogleSearchTool(max_results=kwargs.get(f"num{idx}", 10))
                    self.search_engines.append(("google", self.google_search))
                    logging.info("google search engine initialized successfully")
                except Exception as e:
                    self.failed_engines.append(("google", str(e)))
                    logging.warning(f"google search unavailable: {e}")
                    
            elif engine in ["duckduckgo", "yandex", "yahoo", "auto"]:
                try:
                    self.duckduckgo_search = DuckDuckGoSearchTool(backend=engine, max_results=kwargs.get(f"num{idx}", 10))
                    self.search_engines.append((engine, self.duckduckgo_search))
                    logging.info(f"{engine} search engine initialized successfully")
                except Exception as e:
                    self.failed_engines.append((engine, str(e)))
                    logging.warning(f"{engine} search unavailable: {e}")
                    
            elif engine=="bing":
                try:
                    self.bing_search = BingSearchTool(max_results=kwargs.get(f"num{idx}", 10))
                    self.search_engines.append((engine, self.bing_search))
                    logging.info(f"{engine} search engine initialized successfully")
                except Exception as e:
                    self.failed_engines.append((engine, str(e)))
                    logging.warning(f"{engine} search unavailable: {e}")             
        
        if not self.search_engines:
            failed_info = [f"{name}: {error}" for name, error in self.failed_engines]
            raise RuntimeError(f"No search engines could be initialized. Failed engines: {'; '.join(failed_info)}")
        
        logging.info(f"IntegratedSearchTool initialized with {len(self.search_engines)} engines: {[name for name, _ in self.search_engines]}")
            
    def forward(self, query: str, timelimit: Optional[str | None] = None) -> dict:
        """Search using multiple engines and combine results with interleaved merging."""
        if not self.search_engines:
            return {"success": False, "query": query, "total_results": 0, "results": ["No search engines available. Please check configuration."]}
        
        logging.info(f"Starting search for query: '{query}' using {len(self.search_engines)} engines")
        
        all_results = []
        all_maps = []
        engine_stats = []
        
        for engine_name, engine in self.search_engines:
            try:
                if timelimit is None:
                    results, result_map = engine._search_internal(query)
                else:
                    results, result_map = engine._search_internal(query, timelimit)
                if isinstance(results, list) and len(results) > 0:
                    all_results.append(results)
                    all_maps.append(result_map)
                    engine_stats.append(f"{engine_name}: {len(results)} results")
                    logging.info(f"{engine_name} search succeeded with {len(results)} results")
                else:
                    engine_stats.append(f"{engine_name}: 0 results")
                    logging.warning(f"{engine_name} search returned no results: {results}")
            except Exception as e:
                engine_stats.append(f"{engine_name}: failed ({str(e)[:50]}...)")
                logging.error(f"{engine_name} search failed: {e}")
        
        if not all_results:
            failed_summary = "; ".join(engine_stats)
            return {
                "success": False,
                "query": query,
                "total_results": 0,
                "results": [f"No results found for query: '{query}'. Engine status: {failed_summary}"]}
        
        # Combine results with interleaved merging
        combined_results = self._combine_multiple_results(all_results, all_maps)
        
        # Log merge statistics
        total_before_dedup = sum(len(results) for results in all_results)
        total_after_dedup = len(combined_results)
        success_engines = len(all_results)
        
        logging.info(f"Search completed. Engines: {success_engines}/{len(self.search_engines)} successful. "
                     f"Results: {total_before_dedup} → {total_after_dedup} (after deduplication)")
        
        return {
            "success": True,
            "query": query,
            "total_results": len(combined_results),
            "results": combined_results
        }
    
    def _combine_multiple_results(self, all_results: List[List[str]], all_maps: List[Dict[str, int]]) -> List[str]:
        """Combine and deduplicate results from multiple search engines with interleaved merging."""
        if not all_results:
            return []
        
        # Convert result_maps to sorted lists for consistent ordering
        sorted_results = []
        for results, result_map in zip(all_results, all_maps):
            # Sort by index to maintain original result order from each engine
            sorted_items = sorted(result_map.items(), key=lambda x: x[1])
            engine_results = [results[idx] for title, idx in sorted_items]
            sorted_results.append(engine_results)
        
        # Interleave results from different engines
        unique_results = []
        seen_titles = set()
        max_results = max(len(results) for results in sorted_results)
        
        for i in range(max_results):
            for engine_idx, engine_results in enumerate(sorted_results):
                if i < len(engine_results):
                    result = engine_results[i]
                    title = self._extract_title_from_result(result)
                    
                    if title not in seen_titles:
                        unique_results.append(result)
                        seen_titles.add(title)
        
        return unique_results
    
    def _extract_title_from_result(self, result: str) -> str:
        """Extract title from formatted result for deduplication."""
        import re
        # Match pattern [title](url) at the beginning of result
        match = re.match(r'\[([^\]]+)\]', result)
        if match:
            return match.group(1)
        return result[:50]
    
    def _combine_results(self, google_results: List[str], google_map: Dict[str, int], 
                        ddg_results: List[str], ddg_map: Dict[str, int]) -> List[str]:
        """Combine and deduplicate results from two search engines (legacy method)."""
        return self._combine_multiple_results([google_results, ddg_results], [google_map, ddg_map])
    
    def _format_results(self, results: List[str], query: str) -> dict:
        """Format results list with numbering."""
        formatted_results = []
        for idx, result in enumerate(results):
            formatted_results.append(f"{idx+1}. {result}")
        return {
            "success": True,
            "query": query,
            "total_results": len(formatted_results),
            "results": formatted_results
        }

class IntegratedSearchTool_v2(Tool):
    name = "web_search_tool"
    description = (
        "Search the web using integrated search engine. Use it just like using Google search.\n"
        "The output is a json dictionary with the following structure: {success, query, total_results, results: [{id, title, href, snippet}]}"
    )
    inputs = {
        "query": {
            "type": "string", 
            "description": "The search query to perform."
        },
        "num_results": {
            "type": "integer",
            "description": "The number of results per page. Default: 10.",
            "nullable": True,
        },
        "page": {
            "type": "integer",
            "description": "The page number to return. Default: 1.",
            "nullable": True,
        },
    }
    output_type = "any"

    def __init__(self):
        super().__init__()
        self.ddgs = DDGS()

    def forward(self, query: str, num_results: int | None = None, page: int | None = None) -> dict:
        """Search and return formatted results."""
        results_list, _ = self._search_internal(query, num_results, page)
        
        if isinstance(results_list, str):  # Error message
            return {"success": False, "query": query, "total_results": 0, "results": [results_list]}
        
        return {
            "success": True,
            "query": query,
            "total_results": len(results_list),
            "results": results_list
        }
    
    def _search_internal(self, query: str, num_results: int | None = None, page: int | None = 1) -> Tuple[Union[List[str], str], Dict[str, int]]:
        """Internal search method that returns raw results and mapping."""
        
        try:
            results = self.ddgs.text(query, max_results=num_results, page=page, backend="google, duckduckgo, yandex, bing, brave, yahoo, mojeek", safesearch="off", region="en-us")
        except Exception as e:
            return f"Search failed: {str(e)}", {}
        
        if len(results) == 0:
            return f"No results found for query: '{query}'. Try a different query.", {}
        
        postprocessed_results = []
        result_map = {}
        
        for idx, result in enumerate(results):
            snippet = result.get('body', '')
            # Clean up snippet
            snippet = re.sub(r'\n+', '; ', snippet)
            snippet = re.sub(r'\s+', ' ', snippet).strip()
            if len(snippet) > 225:
                truncated = snippet[:175]
                last_space = truncated.rfind(' ')
                if last_space > 0:
                    snippet = truncated[:last_space] + '...'
                else:
                    snippet = truncated + '...'
            result['id'] = idx
            result['snippet'] = snippet
            postprocessed_results.append(result)
            result_map[result['title']] = idx
            
        return postprocessed_results, result_map

if __name__ == "__main__":
    import os
    
    # Example usage - make sure to set SERPAPI_API_KEY environment variable if using Google search
    # os.environ["SERPAPI_API_KEY"] = "your_api_key_here"
    os.environ["SERPAPI_API_KEY"] = "6b053479779bb958a2f69ac373af45c60b26dcfb5946fb0ad62dca8dae491054"
    try:
        # Test with all available engines
        tool = IntegratedSearchTool(
            search_engines=["duckduckgo", "yahoo"], 
            num0=6,  
            num1=4, 
        )
        # tool = GoogleSearchTool(
        #     max_results=6,
        # )p
        query = "Hafnia genus Enterobacteriaceae taxonomy"
        result = tool(query)
        print("=== Integrated Search Results ===")
        print(result)
        
    except RuntimeError as e:
        print(f"Failed to initialize IntegratedSearchTool: {e}")
        print("Trying with DuckDuckGo only...")
        
        # Fallback to DuckDuckGo only (no API key required)
        tool = IntegratedSearchTool(search_engines=["duckduckgo"], num0=5)
        query = "artificial intelligence recent developments"
        result = tool(query)
        print("=== DuckDuckGo Search Results ===")
        print(result)