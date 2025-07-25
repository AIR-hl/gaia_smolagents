from typing import Optional
from smolagents import tool
import textwrap
from src.utils import clean_references


@tool
def pdb_parse_tool(file_path: str) -> str:
    """
    Parse and analyze local scientific data files with specialized processing for molecular and structural data.
    This tool specializes in processing scientific file formats commonly used in research and analysis.
    **Supported formats:**
    - Protein structures: .pdb (Protein Data Bank files)
    
    
    Args:
        file_path: Local path to the scientific file to be processed. Must be a valid scientific data file.
    """
    try:
        from .mdconvert import PDBConverter
    except ImportError:
        from src.tools.mdconvert import PDBConverter
    
    import os
    
    # Check if file exists
    if not os.path.exists(file_path):
        return f"Scientific file not found: {file_path}"
    
    # Check file extension
    _, ext = os.path.splitext(file_path.lower())
    
    if ext == '.pdb':
        converter = PDBConverter()
        file_type = "Protein Data Bank (PDB)"
    else:
        return f"Unsupported scientific file format: {ext}. Currently supported: .pdb"
    
    try:
        result = converter.convert(file_path, file_extension=ext)
        
        if result:
            # Handle both DocumentConverterResult and string returns from PDBConverter
            if isinstance(result, str):
                # PDBConverter returns error messages as strings
                return result
            elif hasattr(result, 'text_content'):
                content = result.text_content
            else:
                content = str(result)

            analysis_content = f"{file_type} Structure Analysis:\n\n{content}"
            return analysis_content
        else:
            return f"Cannot parse the scientific file: {file_path}. The file might be corrupted or contain invalid molecular data."
    
    except Exception as e:
        return f"Error parsing scientific file {file_path}: {str(e)}" 