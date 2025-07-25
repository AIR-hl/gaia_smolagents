from datetime import datetime
import glob
import hashlib
import re
import textwrap
import time
from typing import Optional
from dotenv import load_dotenv
import requests
from smolagents import Tool
import os
import shutil
import zipfile
from src.tools.download_tool import download_file
from src.utils import clean_references
import pymupdf4llm

load_dotenv()

class PDFParseTool(Tool):
    name = "pdf_parse_tool"
    description = (
        "Parse and extract text or image content from PDF file with advanced VLM or traditional parsing library."
        "The `traditional` mode is better for tables and images extraction, the `VLM` mode is better for complex format and math formulas, etc.\n"
        "The output is a dictionary with the following fields: success, extract_dir, markdown_path, images_dir."
        # "You'd better set `page_range` to parse the page seperately when using the VLM mode, otherwise the parsing time will be very long.\n"
    )
    inputs = {
        "file_path": {
            "type": "string", 
            "description": "The local path or url to the PDF file to be parsed."
        },
        "page_range":{
            "type":"string",
            "description":"The page range to parse, e.g. \"1-10\", \"1,3-6\". If not provided, all pages will be parsed.",
            "nullable":True
        },
        "use_vlm":{
            "type":"boolean",
            "description":"If False, use traditional pdf parsing library to parse the file, Default is False.",
            "nullable":True
        }
    }

    output_type="any"

    def __init__(self, output_dir="downloads", **kwargs):
        super().__init__(**kwargs)
        self.token = os.getenv("MINERU_API_TOKEN")
        self.base_url=os.getenv("MINERU_BASE_URL")
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {self.token}"
        }
        self.output_dir=output_dir

    def forward(self, file_path:str , page_range: Optional[str] = None, use_vlm:Optional[bool]=False)->dict:
        if file_path.startswith("http://") or file_path.startswith("https://"):
            result=download_file(file_path)
            if result["success"]:
                file_path=result["file_path"]
            else:
                raise Exception(f"Error downloading file from {file_path}: {result['error']}")        
        
        if use_vlm:
            upload_result=self._upload_file(file_path, page_range)
            remote_url=self._query_state(upload_result["id"])
            result=self._fetch_result(remote_url, upload_result["file_name"].split(".")[0])
            if result["success"]:
                return result
            else:
                raise Exception(f"Error parsing file with VLM model: {result['error']}")
        else:
            result=self._pymupdf_parse(file_path, page_range)   
            if result["success"]:
                return result
            else:
                raise Exception(f"Error parsing file with pymupdf: {result['error']}")


    def _upload_file(self, file_path, page_ranges):
        if not os.path.exists(file_path):
            raise ValueError(f"The file does not exist -> {file_path}")
        if page_ranges is None:
            file_name=os.path.basename(file_path)
        else:
            file_name=f"{os.path.basename(file_path).split('.')[0]}_{datetime.now().strftime('%H%M%S')}.pdf"
        apply_url = f"{self.base_url}/file-urls/batch"
        body={
            "enable_formula": True,
            "language": "auto",
            "enable_table": True,
            "files": [
                {
                    "name": file_name,
                    "data_id": hashlib.md5(file_name.encode()).hexdigest(),
                    "is_ocr":True
                } if page_ranges is None else {
                    "name": file_name,
                    "data_id": hashlib.md5(file_name.encode()).hexdigest(),
                    "page_ranges":page_ranges,
                    "is_ocr":True
                }
            ],
            "model_version":"v2",
            "formats":["markdown"]
        }
        try:
            response = requests.post(apply_url,headers=self.headers,json=body)
            if response.status_code == 200:
                result = response.json()
                if result["code"] == 0:
                    batch_id = result["data"]["batch_id"]
                    urls = result["data"]["file_urls"]
                    with open(file_path, 'rb') as f:
                        res_upload = requests.put(urls[0], data=f)
                        if res_upload.status_code == 200:
                            return {"id":batch_id,"file_name":file_name}
                        else:
                            raise Exception(f"{urls[0]} upload failed")
                else:
                    raise Exception(f'apply upload url failed,reason:{result["msg"]}')
            else:
                raise Exception(f'apply upload url failed,reason:{response}')
        except Exception as err:
            raise err


    def _query_state(self, batch_id):
        query_url=f"{self.base_url}/extract-results/batch/{batch_id}"
        time.sleep(30)
        for _ in range(10):
            response=requests.get(query_url,headers=self.headers)
            if response.status_code == 200:
                result=response.json()
                if result["code"] == 0:
                    extract_data = result["data"]["extract_result"][0]
                    state = extract_data.get("state")
                    if state == "done":                
                        return extract_data.get("full_zip_url")
                    elif state != "failed":
                        time.sleep(60)
                    else:
                        raise Exception(f'File parsed failed -> {extract_data.get("err_msg")}')   
                else:
                    raise Exception(f"query state failed,reason:{result['msg']}")
            else:
                raise Exception(f"query state failed,reason:{response.text}")
        raise TimeoutError(f"query state failed,reason:timeout")
    
    def _fetch_result(self, remote_url:str, file_name:str):    
        try:
            response = requests.get(remote_url)
            if response.status_code != 200:
                raise Exception(f"Failed to download ZIP file: {response.status_code}")
            
            zip_path = os.path.join(self.output_dir, f"{file_name}_temp.zip")
            with open(zip_path, 'wb') as f:
                f.write(response.content)
            
            extract_dir = os.path.join(self.output_dir, file_name)
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            os.remove(zip_path)
            pattern = r'(!\[.*?\]\()(images/[^\)]+)(\))'
           

            def replace_match(match):
                prefix = match.group(1)
                img_path = match.group(2)
                suffix = match.group(3)
                return f"{prefix}{extract_dir.rstrip('/') + '/' if extract_dir else ''}{img_path}{suffix}"
                        
            with open(os.path.join(extract_dir, "full.md"), "r") as f:
                content=f.read()
                content=clean_references(content)
            
            with open(os.path.join(extract_dir, "content.md"), "w") as f:
                f.write(re.sub(pattern, replace_match, content))
            os.remove(os.path.join(extract_dir, "full.md"))

            json_files = glob.glob(os.path.join(extract_dir, "*.json"))            
            for file_path in json_files:
                os.remove(file_path)
        
            return {
                "success":True,
                "extract_dir":str(extract_dir),
                "markdown_path":str(os.path.join(extract_dir, "content.md")),
                "images_dir":str(os.path.join(extract_dir, "images"))
            }
            
        except Exception as err:
            raise err

    def _pymupdf_parse(self, file_path, page_range)->dict:
        page_range=self._parse_pages(page_range)
        file_name=os.path.basename(file_path).split(".")[0]
        import fitz
        def get_pdf_page_count(filepath):
            doc = fitz.open(filepath)
            return doc.page_count
        page_count = get_pdf_page_count(file_path)        
        extract_dir=f"{self.output_dir}/{file_name}_{datetime.now().strftime('%H%M%S')}"
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)
        image_path = f"{extract_dir}/images"
        search_pages=[n-1 for n in range(1,page_count+1) if n in page_range] if page_range else None
        content=pymupdf4llm.to_markdown(file_path, image_path=image_path,table_strategy="lines", pages=search_pages, write_images=True)
        if content:
            content = clean_references(content)
            content = textwrap.dedent(f"""
# PDF Content Analysis:
## MetaData:
- page_count: {page_count}
{f"- images save dir: `{image_path}/`" if len(os.listdir(image_path)) != 0 else "No images extracted"}

## {f'Pages {page_range}' if page_range else 'All Pages'} Content:

{content}
""").strip()
            with open(os.path.join(extract_dir, "content.md"), "w") as f:
                f.write(clean_references(content))
            return {
                "success":True,
                "extract_dir":str(extract_dir),
                "markdown_path":str(os.path.join(extract_dir, "content.md")),
                "images_dir":str(os.path.join(extract_dir, "images"))
            }
        else:
            return {
                "success":False,
                "error":"No content extracted"
            }
    def _parse_pages(self, page_str):
        if not page_str or not page_str.strip():
            return []
        
        pages = set()
        
        parts = page_str.split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
                
            if '-' in part:
                range_parts = part.split('-')
                if len(range_parts) == 2:
                    try:
                        start = int(range_parts[0].strip())
                        end = int(range_parts[1].strip())
                        if start <= end:
                            pages.update(range(start, end + 1))
                    except ValueError:
                        continue
            else:
                try:
                    page_num = int(part)
                    pages.add(page_num)
                except ValueError:
                    continue
        
        return sorted(list(pages))
if __name__ == "__main__":
    tool=PDFParseTool(output_dir="downloads")
    result=tool.forward("downloads/finding_nemo_-_species_identification_information.pdf", page_range="1,3-6", use_vlm=True)
    print(result)