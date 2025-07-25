from typing import Optional
from smolagents import tool
import textwrap
from src.tools.mdconvert import XlsxConverter
from src.utils import clean_references
from src.tools.download_tool import download_file
import os
@tool
def doc_parse_tool(file_path: str) -> str:
    """
    Parse and extract content from Microsoft Office documents including `Word`, `Excel`, and `PowerPoint` files.
    This tool specializes in processing document formats while preserving structure, formatting, and multimedia elements.    
    **Supported formats:**
    - Excel spreadsheets:  .xls, .xlsx,    
    - Word documents: .doc, .docx
    - PowerPoint presentations: .ppt, .pptx

    Args:
        file_path: The local path or url of the document file to be processed. Must be a valid DOCX or PPTX file.
    """
    try:
        from .mdconvert import DocxConverter, PptxConverter
    except ImportError:
        from src.tools.mdconvert import DocxConverter, PptxConverter
    

    if file_path.startswith("http://") or file_path.startswith("https://"):
        try:
            result=download_file(file_path)
            file_path=result.split("Saved to: ")[1].split("\n")[0]
        except Exception as e:
            raise Exception(f"Error downloading file from {file_path}: {str(e)}") 
    
    # Check if file exists
    if not os.path.exists(file_path):
        return f"Document file not found: {file_path}"
    
    # Check file extension and select appropriate converter
    _, ext = os.path.splitext(file_path.lower())
    
    if ext == '.docx' or ext == '.doc':
        converter = DocxConverter()
        doc_type = "Word Document"
    elif ext == '.pptx' or ext == '.ppt':
        converter = PptxConverter()
        doc_type = "PowerPoint Presentation"
    elif ext == '.xlsx' or ext == '.xls':
        converter = XlsxConverter()
        doc_type = "Excel Spreadsheet"
    else:
        return f"Unsupported document format: {ext}. Supported formats: .docx, .doc, .pptx, .ppt, .xlsx, .xls"
    
    try:
        result = converter.convert(file_path, file_extension=ext)
        
        if result:
            content = clean_references(result.text_content)
            content = f"# {doc_type} Content Analysis:\n\n{content}"
            
            return content
        else:
            return f"Cannot parse the document file: {file_path}. The file might be corrupted, password-protected, or empty."
    
    except Exception as e:
        return f"Error parsing document file {file_path}: {str(e)}" 

if __name__ == "__main__":
    print(doc_parse_tool("data/gaia/2023/validation/a3fbeb63-0e8c-4a11-bff6-0e3b484c3e9c.pptx"))