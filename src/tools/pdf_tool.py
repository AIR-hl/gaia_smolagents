from typing import Optional
import pymupdf4llm
from smolagents import tool
import textwrap
from src.tools.download_tool import download_file
from src.utils import clean_references


@tool
def pdf_parse_tool(file_path: str, pages: Optional[list[int] | None] = None, extrct_images: Optional[bool] = True) -> str:
    """
    Parse and extract text or image content from local PDF file with advanced extraction capabilities.
    This tool specializes in processing PDF documents, preserving table structures and formatting where possible.
    
    Args:
        file_path: Local path to the PDF file to be processed. Must be a valid PDF file.
        pages: Optional, List of page numbers to extract, e.g [1,2,3]. If None, all pages will be extracted. Default is None.
        extrct_images: Optional, Whether to extract images / graphics from the PDF file. Default is True.
    """
    import os
    
    if file_path.startswith("http://") or file_path.startswith("https://"):
        try:
            result=download_file(file_path)
            file_path=result.split("Saved to: ")[1].split("\n")[0]
        except Exception as e:
            return f"Error downloading file from {file_path}: {str(e)}"
    
    # Check if file exists and has correct extension
    if not os.path.exists(file_path):
        return f"PDF file not found: {file_path}"
    
    _, ext = os.path.splitext(file_path.lower())
    if ext != '.pdf':
        return f"Invalid file format: {ext}. This tool only supports PDF files (.pdf)"
    
    try:
        file_name = os.path.splitext(os.path.basename(file_path))[0]

        if not extrct_images:
            write_images = False
            image_path = ""
        else:
            if not os.path.exists(f"downloads/{file_name}"):
                os.makedirs(f"downloads/{file_name}")
            image_path = f"downloads/{file_name}"
            write_images = True
        search_pages=[n-1 for n in pages] if pages else None
        content=pymupdf4llm.to_markdown(file_path, image_path=image_path,table_strategy="lines", pages=search_pages, write_images=write_images)
        if content:
            content = clean_references(content)
            import fitz
            def get_pdf_page_count(filepath):
                doc = fitz.open(filepath)
                return doc.page_count
            page_count = get_pdf_page_count(file_path)
            
            content = textwrap.dedent(f"""
# PDF Content Analysis:
## MetaData:
- page_count: {page_count}
{f"- images save dir: `downloads/{file_name}/`" if write_images and len(os.listdir(f"downloads/{file_name}")) != 0 else "No images extracted"}

## {f'Pages {pages}' if pages else 'All Pages'} Content:

{content}
""").strip()
            return content
        else:
            raise Exception(f"Cannot parse the PDF file. The file might be corrupted, password-protected, or image format.")
    
    except Exception as e:
        return f"Error parsing PDF file {file_path}: {str(e)}"

if __name__ == "__main__":
    print(pdf_parse_tool("downloads/2206.11922v7.pdf", extrct_images=True))