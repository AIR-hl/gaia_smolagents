import mimetypes
from datetime import datetime
import os
from pathlib import Path
import threading
from typing import Optional
from urllib.parse import urlparse
from smolagents import tool
import requests
from requests.adapters import HTTPAdapter, Retry
import textwrap

_thread_local = threading.local()

def get_link_pool():
    """Get the link pool for the current thread."""
    return getattr(_thread_local, 'link_pool', None)

def set_link_pool(link_pool):
    """Set the link pool for the current thread."""
    _thread_local.link_pool = link_pool


@tool
def download_file(url: str) -> dict:
    """
    Download file from URL with intelligent format detection and error handling. It supports a wide range of file formats and saves them locally for further processing.
    The output is a dictionary with the following fields: success, file_path, file_size, file_type.
    
    Args:
        url: The URL of the file to download. Can be:
             - Direct file URLs: "https://example.com/document.pdf"
             - arXiv abstract URLs: "https://arxiv.org/abs/2301.12345" (auto-converted to PDF)
             - Encoded links: "link-abc123" (resolved from link pool)
    
    Returns:
        A dictionary with the following fields: success, file_path, file_size, file_type.
    """
    # Configuration
    ALLOWED_EXTS = {".xlsx", ".pptx", ".wav", ".mp3", ".m4a", ".png", ".jpg", ".jpeg", 
                    ".docx", ".pdf", ".html", ".htm", ".txt", ".md", ".json", ".xml", 
                    ".csv", ".zip", ".tar", ".gz", ".webp", "webm"}
    DOWNLOAD_DIR = Path("./downloads")
    TIMEOUT = 30.0
    MAX_RETRIES = 2
    
    try:
        # Handle encoded links
        link_pool=get_link_pool()
        if url.startswith("link-") and link_pool is not None:
            decoded_url = link_pool.decode_url(url[5:])  # Remove 'link-' prefix
            if decoded_url:
                url = decoded_url
            else:
                return {
                    "success":False,
                    "error":f"Invalid encoded link '{url}' - unable to decode URL"
                }
        
        # Special handling for arXiv URLs
        if "arxiv" in url.lower():
            if "/abs/" in url:
                url = url.replace("/abs/", "/pdf/") + ".pdf"
            elif url.endswith("/abs"):
                url = url.replace("/abs", "/pdf.pdf")
        
        # Set up session with retry logic
        session = requests.Session()
        retries = Retry(
            total=MAX_RETRIES,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
        )
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.mount("https://", HTTPAdapter(max_retries=retries))
        
        # Download the file
        response = session.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()
        
        # Determine filename
        if response.headers.get("content-disposition"):
            filename = _get_filename_from_header(response.headers.get("content-disposition"))
        else:
            path = urlparse(url).path
            filename = os.path.basename(path)
        if not filename:
            filename = f"downloaded_{datetime.now().strftime('%Y%m%d_%H%M%S')}.file"
        # Validate file extension
        ext = Path(filename).suffix.lower()
        if not ext:
            # Try to guess extension from content type
            guessed_ext = mimetypes.guess_extension(response.headers.get("content-type", ""))
            if guessed_ext:
                ext = guessed_ext.lower()
                filename += ext        
        # Ensure download directory exists
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        
        # Handle filename conflicts
        dest = DOWNLOAD_DIR / filename
        counter = 1
        original_stem = dest.stem
        while dest.exists():
            dest = DOWNLOAD_DIR / f"{original_stem}_{counter}{ext}"
            counter += 1
        
        # Download and save file
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = dest.stat().st_size
        return {
            "success":True,
            "file_path":str(dest),
            "file_size":file_size,
            "file_type":ext
        }
        
    except requests.exceptions.Timeout:
        return {
            "success":False,
            "error":f"Download timed out after {TIMEOUT} seconds for URL: {url}"
        }
    except requests.exceptions.HTTPError as e:
        return {
            "success":False,
            "error":f"HTTP {e.response.status_code} - {e.response.reason} for URL: {url}"
        }
    except requests.exceptions.RequestException as e:
        return {
            "success":False,
            "error":f"Network error occurred while downloading from {url}: {str(e)}"
        }
    except Exception as e:
        return {
            "success":False,
            "error":f"Unexpected error during download from {url}: {str(e)}"
        }


def _get_filename_from_header(content_disposition: Optional[str]) -> Optional[str]:
    """Extract filename from Content-Disposition header."""
    if not content_disposition:
        return None
    
    parts = content_disposition.split(";")
    for part in parts:
        part = part.strip()
        if part.lower().startswith("filename="):
            filename = part.partition("=")[2].strip('"\' ')
            return filename
    return None