from typing import Optional
from smolagents import tool
import textwrap
from src.utils import clean_references


@tool
def extract_zip_file(file_path: str, extract_dir: str = "downloads") -> str:
    """
    Extract and list contents of archive files (ZIP) to a specified directory.
    This tool specializes in processing compressed archive files, extracting their contents and providing a detailed listing of all extracted files for further processing.
    **Supported formats:**
    - ZIP archives: .zip

    
    Args:
        file_path: Path to the archive file to be extracted. Must be a valid ZIP file.
        extract_dir: Directory where files will be extracted. Defaults to "downloads". The directory will be created if it doesn't exist.
    """
    try:
        from .mdconvert import ZipConverter
    except ImportError:
        from src.tools.mdconvert import ZipConverter
    
    import os
    
    # Check if file exists
    if not os.path.exists(file_path):
        return f"Archive file not found: {file_path}"
    
    # Check file extension
    _, ext = os.path.splitext(file_path.lower())
    
    if ext != '.zip':
        return f"Unsupported archive format: {ext}. Currently supported: .zip"
    
    try:
        # Initialize converter with the specified extraction directory
        converter = ZipConverter(extract_dir=extract_dir)
        result = converter.convert(file_path, file_extension=ext)
        
        if result:            
            extracted_info = f"Archive Extraction Results:\n\n"
            extracted_info += f"**Source:** {file_path}\n"
            extracted_info += f"**Extraction Directory:** {extract_dir}\n\n"
            extracted_info += result.text_content
            
            return extracted_info
        else:
            return f"Cannot extract the archive file: {file_path}. The file might be corrupted, password-protected, or not a valid ZIP file."
    
    except Exception as e:
        return f"Error extracting archive file {file_path}: {str(e)}" 