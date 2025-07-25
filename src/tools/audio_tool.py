from typing import Optional
from smolagents import tool
import textwrap
from src.tools.download_tool import download_file

@tool
def audio_parse_tool(file_path: str) -> str:
    """
    Parse and transcribe audio files with advanced OpenAI Whisper model.
    This tool specializes in processing various audio formats and can extract both metadata and speech content through transcription.
    **Supported formats:**
    - Uncompressed audio: .wav
    - Compressed audio: .mp3, .m4a, .flac
    
    Args:
        file_path: The local path or url of the audio file to be processed. Must be a valid audio file.
    """
    from .mdconvert import WavConverter, Mp3Converter
    
    import os
    if file_path.startswith("http://") or file_path.startswith("https://"):
        try:
            result=download_file(file_path)
            file_path=result.split("Saved to: ")[1].split("\n")[0]
        except Exception as e:
            raise Exception(f"Error downloading file from {file_path}: {str(e)}") 
    # Check if file exists
    if not os.path.exists(file_path):
        return f"Audio file not found: {file_path}"
    
    # Check file extension and select appropriate converter
    _, ext = os.path.splitext(file_path.lower())
    
    if ext == '.wav':
        converter = WavConverter()
    elif ext in ['.mp3', '.m4a', '.flac']:
        converter = Mp3Converter()
    else:
        return f"Unsupported audio format: {ext}. Supported formats: .wav, .mp3, .m4a, .flac"
    
    try:
        result = converter.convert(file_path, file_extension=ext)
        
        if result:
            return result.text_content
        else:
            return f"Cannot parse the audio file: {file_path}. The file might be corrupted or contain no speech content."
    
    except Exception as e:
        return f"Error parsing audio file {file_path}: {str(e)}" 

if __name__ == "__main__":
    print(audio_parse_tool("data/gaia/2023/validation/2b3ef98c-cc05-450b-a719-711aee40ac65.wav"))