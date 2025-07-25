import re
import threading
from typing import Any, Optional
from smolagents import tool
import textwrap
from src.tools.crawler_tool import LinkPool

_thread_local = threading.local()
# Global link pool instance for the @tool function
_global_link_pool = None


def set_link_pool(link_pool):
    """Set the global link pool for the final_answer tool."""
    global _global_link_pool
    _global_link_pool = link_pool

def get_link_pool() -> Optional['LinkPool']:
    """Get the link pool for the current thread."""
    return getattr(_thread_local, 'link_pool', None)

@tool
def final_answer(answer: str) -> Any:
    """
    Provides a final answer to the given problem.
    
    Args:
        answer: The final answer to the problem. Can include text, numbers, URLs, or any other relevant information.
    
    Returns:
        The processed final answer with decoded links, ready for presentation to the user.
    """
    if not isinstance(answer, str):
        return str(answer)
    link_pool = get_link_pool()
    if link_pool is None:
        return answer

    def replace_link(match):
        url = match.group(0)
        if link_pool is not None:
            decoded_url = link_pool.decode_url(url[5:])  # Remove 'link-' prefix
            return decoded_url
        return url

    pattern = r'link-\d+'
    return re.sub(pattern, replace_link, answer)