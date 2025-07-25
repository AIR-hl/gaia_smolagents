from typing import Optional
from smolagents import tool
import textwrap
from src.utils import clean_references
import asyncio
from crawl4ai import AsyncWebCrawler, CacheMode, DefaultMarkdownGenerator, PruningContentFilter
from crawl4ai.async_configs import CrawlerRunConfig

@tool
def html_parse_tool(file_path: str) -> str:
    """
    Parse and extract content from local HTML file and return the cleaned HTML content. For online HTML files, use `visit_webpage` tool OR download the file first.
    This tool specializes in processing local HTML file, using advanced content extraction algorithms. 
    **Supported formats:**
    - HTML files: .html, .htm
    
    Args:
        file_path: Local path to the HTML file to be processed. Must be a valid HTML file.
    """
    try:
        from .mdconvert import HtmlConverter
    except ImportError:
        from src.tools.mdconvert import HtmlConverter
    
    import os
    if file_path.startswith("http://") or file_path.startswith("https://"):
        from .crawler_tool import CrawlWebpageTool
        return CrawlWebpageTool().forward(file_path)
    # Check if file exists
    if not os.path.exists(file_path):
        return f"HTML file not found: {file_path}"
    
    # Check file extension
    _, ext = os.path.splitext(file_path.lower())
    supported_extensions = ['.html', '.htm']
    
    if ext not in supported_extensions:
        return f"Unsupported file format: {ext}. Supported formats: {', '.join(supported_extensions)}"
    
    try:
        file_abs_path=os.path.abspath(file_path)
        result=None
        async def crawl_local_file():
            nonlocal result
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, capture_console_messages=True, markdown_generator=DefaultMarkdownGenerator(content_filter=PruningContentFilter(threshold=0.25, threshold_type="dynamic")))

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=f"file://{file_abs_path}", config=config)
                if result.success:
                    result=result.fit_html
                else:
                    raise Exception(f"Failed to crawl local file: {result.error_message}")
        
        asyncio.run(crawl_local_file())
        
        if result:

            content = clean_references(result)            
            final_content = f"## HTML File Content Analysis:\n\n{content}"
            
            return final_content
        else:
            return f"Cannot parse the HTML file: {file_path}. The file might be corrupted or contain no readable content."
    
    except Exception as e:
        return f"Error parsing HTML file {file_path}: {str(e)}"

if __name__ == "__main__":
    print(html_parse_tool("downloads/4123.html"))