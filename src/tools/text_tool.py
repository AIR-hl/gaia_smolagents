from typing import Optional
from smolagents import tool
import textwrap
from src.utils import clean_references
from src.tools.download_tool import download_file
import os

@tool
def text_parse_tool(file_path: str) -> str:
    """
    A powerful general tool for parsing text-based files with various formats.
    **Supported formats:**
    - Plain text: .txt
    - Markdown: .md, .markdown
    - Structured data formats: .json, .csv, .jsonld, .jsonl
    - Subtitle files: .srt, .vtt
    - Other text-based formats: .log, .conf, .cfg, .ini, .yaml, .xml, .py, .js, .cpp, .java, etc.
    
    Args:
        file_path: The local path or url of the text file to be processed. Must be a valid text file.
    """
    try:
        from .mdconvert import MarkdownConverter, PlainTextConverter
    except ImportError:
        from src.tools.mdconvert import MarkdownConverter, PlainTextConverter
    
    if file_path.startswith("http://") or file_path.startswith("https://"):
        try:
            result=download_file(file_path)
            file_path=result.split("Saved to: ")[1].split("\n")[0]
        except Exception as e:
            raise Exception(f"Error downloading file from {file_path}: {str(e)}") 
    # Use PlainTextConverter for text files
    converter = PlainTextConverter()
    
    # Determine file extension
    _, ext = os.path.splitext(file_path.lower())
    
    # Check if it's a supported text format
    supported_extensions = ['', '.txt', '.md', '.markdown', '.json', '.csv', '.srt', '.log', '.conf', '.cfg', '.ini', '.yaml', '.yml', '.xml', '.vtt', '.jsonld', '.jsonl','.py', 'js', 'cpp','java','.c']
    if ext not in supported_extensions:
        return f"Unsupported text file format: {ext}. Supported formats: {', '.join(supported_extensions)}"
    
    try:
        result = converter.convert(file_path, file_extension=ext)
        if result:
            content = clean_references(result.text_content)
            return f"# Text File Content:\n\n{content}"
        else:
            return f"Cannot parse the text file: {file_path}. Please check if the file exists and is readable."
    
    except Exception as e:
        return f"Error parsing text file {file_path}: {str(e)}" 
    

if __name__ == "__main__":
    print(text_parse_tool("downloads/piIOFzskMWE.en.srt"))
    # print(parse_text_file("data/gaia/2023/validation/8d46b8d6-b38a-47ff-ac74-cda14cf2d19b.csv"))