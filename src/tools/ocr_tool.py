import base64
import requests
import os
import textwrap
from smolagents import tool
from src.tools.download_tool import download_file

@tool
def ocr_tool(file_path: str) -> str:
    """
    Extracts text from an image file using Optical Character Recognition (OCR).
    This tool specializes in processing various image formats and extracting textual content.
    **Supported formats:**
    - Common images: .png, .jpg, .jpeg, .webp, .gif, .bmp, .tiff

    Args:
        file_path: The local path or url of the image file to be processed. Must be a valid image file.
    
    Returns:
        The extracted text from the image.
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

        prompt = textwrap.dedent(f"""
You are a powerful OCR assistant, accuracy is the most important. Please carefully analyze and accurately extract the text, tables or formulas in the picture.\n
You can use HTML code to represent the tables, LaTex code to represent the formulas. Note: DO NOT add any redundant description.\n
If there is no such text content, only return: "There isn't any text in the picture".
""")
        payload = {
            "model": "Doubao-1.5-vision-pro-32k",
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
            "max_tokens": 4096,
        }    
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
        }
        response = requests.post(os.getenv("OPENAI_BASE_URL"), headers=headers, json=payload)
        response.raise_for_status() # Raise an exception for bad status codes
        
        response_json = response.json()
        if response_json.get("error"):
            raise Exception(response_json["error"])
            
        ocr_result = response_json["choices"][0]["message"]["content"]
        return ocr_result

    except Exception as e:
        return f"Error performing OCR on image file {file_path}: {str(e)}"


if __name__ == "__main__":
    print(ocr_tool("data/gaia/2023/validation/366e2f2b-8632-4ef2-81eb-bc3877489217.png"))