
from smolagents import Tool
from smolagents.models import Model


class FileParseTool(Tool):
    name = "file_parse_tool"
    description = """Use this tool to extract and convert the content of a file into markdown-formatted text. 
It supports a wide range of file types as followed:
- Documents: .pdf, .docx, .html, .htm, .xlsx, .pptx
- Audio: .wav, .mp3, .m4a, .flac
- Images: .png, .jpg
- Other: All standard text-based file formats (e.g., .txt, .md, .json, etc.)

Optionally, you can provide a specific question about the file (such as for images or audio); the tool will then return an analysis or answer based on the question. 
If no question is provided, the tool simply extracts and returns the file's conten informationt."""

    inputs = {
        "file_path": {
            "description": "The path to the file you want to process. The file must have a valid extension such as '.pdf', '.png', etc.",
            "type": "string",
        },
        "question": {
            "description": "[Optional] A specific question you want to ask about the image. Providing this will return an analysis based on your question. Leave this empty to simply extract the content from the image without extra analysis.",
            "type": "string",
            "nullable": True,
        }
    }
    output_type = "string"

    def __init__(self, text_limit: int = 100000):
        super().__init__()
        self.text_limit = text_limit
        try:
            from .mdconvert import MarkdownConverter
        except ImportError:
            from scripts.mdconvert import MarkdownConverter

        self.md_converter = MarkdownConverter()

    def forward(self, file_path, question: str | None = None) -> str:        
        result = self.md_converter.convert(source=file_path, question=question)
        if result:
            return result.text_content
        else:
            return "Cannot parse the current file or url"


if __name__ == "__main__":
    from smolagents import OpenAIServerModel

    model = OpenAIServerModel(
        api_base="http://gpt-proxy.jd.com/v1",
        api_key="64268e2b-188f-4e86-9b2a-8542ba3849c8",
        model_id="gpt-4.1",
    )

    document_inspection_tool = FileParserTool(200000)
    txt = document_inspection_tool.forward("/Users/xushiyue.6/Downloads/f47aa748-a344-4854-97bd-6352e473b810_capture.jpg", "OpenAI 有哪些模型")
    print(txt)
