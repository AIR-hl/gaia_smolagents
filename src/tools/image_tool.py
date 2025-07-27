from typing import Optional
from smolagents import tool
import base64
import requests
import os
import textwrap
from src.tools.download_tool import download_file
from dotenv import load_dotenv

load_dotenv(override=True)

@tool
def image_parse_tool(file_path: str, question: Optional[str | None] = None) -> str:
    """
    Parse and analyze image content with an advanced VLM.
    This tool specializes in processing various image formats and can perform Visual Question Answering (VQA) when a specific question is provided.
    If no question is provided, it will provide a general description of the image.
    **Supported formats:**
    - Common images: .png, .jpg, .jpeg, .webp, .gif, .bmp, .tiff

    
    Args:
        file_path: The local path or url of the image file to be processed. Must be a valid image file.
        question: Optional question for visual question answering. When provided, the tool will analyze the image and provide a specific answer to the question based on visual content.
    """
    if file_path.startswith("http://") or file_path.startswith("https://"):
        try:
            result = download_file(file_path)
            file_path = result.split("Saved to: ")[1].split("\n")[0]
        except Exception as e:
            raise Exception(f"Error downloading file from {file_path}: {str(e)}")
            
    if not os.path.exists(file_path):
        return f"Image file not found: {file_path}"
    
    _, ext = os.path.splitext(file_path.lower())
    supported_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff']
    
    if ext not in supported_extensions:
        return f"Unsupported image format: {ext}. Supported formats: {', '.join(supported_extensions)}"

    try:
        img_type = "data:image/jpeg;base64," if ext in ['.jpg', '.jpeg'] else "data:image/png;base64,"
        with open(file_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")

        if question:
            prompt = f"""You are an expert for Visual Question Answering (VQA) task. 
Please analyze the image carefully and provide accurate caption and answer for the following question:
**Question:**
```
{question}
```

**Content Format Rules:**
For different content types, process them according to the following rules:
- Tables: Analyze the content and styling, return as well-structured HTML codes.
- Geometric Shapes: Generate vector graphic code (SVG).
- Complex Graphics: Provide extremely detailed description.
- General Images: Generate detailed and comprehensive caption.
- Math: Represent formulas in LaTex code.

**Output Format:**
## Image Caption:
[Provide an accurate caption of the image, dont miss any key information.]

## Answer
[Provide a accurate answer to the question based on the image content and above analysis]
"""
        else:
            prompt =f"""You are an expert for analyzing images. 
Please analyze the image carefully and provide accurate caption based on following rules:

**Content Format Rules:**
- Tables: Analyze the content and styling, return as well-structured HTML codes.
- Geometric Shapes: Generate vector graphic code (SVG).
- Complex Graphics: Provide extremely detailed description.
- General Images: Generate detailed and comprehensive caption.
- Math: Represent formulas in LaTex code.

**Output Format:**
## Image Caption:
[Provide an accurate caption of the image, dont miss any key information]
"""

        payload = {
            "model": "gpt-4o-0806",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"{img_type}{img_base64}"
                            }
                        }
                    ],
                },
            ],
            "max_tokens": 16384,
        }    
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
        }
        response = requests.post(os.getenv("OPENAI_BASE_URL"), headers=headers, json=payload)
        response.raise_for_status()
        
        response_json = response.json()
        if response_json.get("error"):
            raise Exception(response_json["error"])
            
        output = response_json["choices"][0]["message"]["content"]
        # The original had this replacement, I'll keep it.
        output = output.replace("[Submit Button for user to submit their answers.]", "")
        return output.strip()

    except Exception as e:
        return f"Error parsing image file {file_path}: {str(e)}"
