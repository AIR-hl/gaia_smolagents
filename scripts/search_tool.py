from datetime import datetime
from smolagents import Tool


class DuckDuckGoSearchTool(Tool):
    name = "web_search"
    description = """Performs a web search using DuckDuckGo search engine and returns the top search results. This tool functions similarly to Google search and supports time-based filtering for more targeted results."""
    inputs = {"query": {"type": "string", "description": "The search query to perform."},
              "timelimit":{"type":"string", "description":"Specifies the time frame for search results. Accepts short formats: 'd' (1 day), 'w' (1 week), 'm' (1 month), 'y' (1 year) to indicate results within the past period. For a custom range, use the format 'YYYY-MM-DD...YYYY-MM-DD' or 'YYYY-MM-DD...NOW'. Defaults to None (no time restriction).",
                        "nullable": True,}}
    output_type = "string"

    def __init__(self, max_results=10, **kwargs):
        super().__init__()
        self.max_results = max_results
        try:
            from duckduckgo_search import DDGS
        except ImportError as e:
            raise ImportError(
                "You must install package `duckduckgo_search` to run this tool: for instance run `pip install duckduckgo-search`."
            ) from e
        self.ddgs = DDGS(**kwargs)

    def forward(self, query: str, timelimit: str=None) -> str:
        if timelimit:
            timelimit.replace("NOW", datetime.now().strftime('%Y-%m-%d'))
        results = self.ddgs.text(query, max_results=self.max_results, timelimit=timelimit)
        if len(results) == 0:
            raise Exception("No results found! Try a less restrictive/shorter query.")
        postprocessed_results = [f"[{result['title']}]({result['href']})\n{result['body']}" for result in results]
        return "## Search Results\n\n" + "\n\n".join(postprocessed_results)
    

if __name__=="__main__":
    tool=DuckDuckGoSearchTool()
    result=tool.forward("Who is the president of the USA?")
    print(result)