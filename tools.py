import subprocess
import tempfile
import time
import json
import requests
from markdownify import markdownify as md
from readability.readability import Document
import duckduckgo_search
import datetime
import random
import math
import re
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import ollama
import os

class Tool:
    def __init__(self, name: str, description: str, arguments: dict, returns: str):
        self.name = name
        self.description = description
        self.arguments = arguments
        self.returns = returns

    def execute(self, arguments: dict) -> str:
        pass


class ToolManager:
    def __init__(self):
        self.tools = []

    def add_tool(self, tool: Tool):
        self.tools.append(tool)

    def get_tool(self, name: str) -> Tool:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def get_tools_and_descriptions_for_prompt(self):
        return "\n".join([f"{tool.name}: {tool.description}" for tool in self.tools])

    def get_tools_for_ollama_dict(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments,
                },
            }
            for tool in self.tools
        ]


class DefaultToolManager(ToolManager):
    def __init__(self):
        super().__init__()
        self.add_tool(SearchTool())
        self.add_tool(GetReadablePageContentsTool())
        self.add_tool(CalculatorTool())
        self.add_tool(PythonCodeTool())
        self.add_tool(DateTimeTool())
        self.add_tool(RandomNumberTool())
        self.add_tool(RegexTool())
        self.add_tool(Base64Tool())
        self.add_tool(SimpleChartTool())
        self.add_tool(LLAVAImageAnalysisTool())


class SearchTool(Tool):
    def __init__(self):
        super().__init__(
            "search_web",
            "Search the internet for information",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
            },
            "results:list[string]",
        )

    def execute(self, arg: dict) -> str:
        try:
            res = duckduckgo_search.DDGS().text(arg["query"], max_results=5)
            return "\n\n".join([f"{r['title']}\n{r['body']}\n{r['href']}" for r in res])
        except Exception as e:
            return f"Error searching the web: {str(e)}"


def get_readable_page_contents(url: str) -> str:
    try:
        response = requests.get(url)
        response.raise_for_status()
        doc = Document(response.content)
        content = doc.summary()
        return md(content)
    except Exception as e:
        return f"Error fetching readable content: {str(e)}"


class GetReadablePageContentsTool(Tool):
    def __init__(self):
        super().__init__(
            "get_readable_page_contents",
            "Get the contents of a web page in a readable format",
            {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The url of the web page"}
                },
            },
            "contents:string",
        )

    def execute(self, arg: dict) -> str:
        return get_readable_page_contents(arg["url"])


class CalculatorTool(Tool):
    def __init__(self):
        super().__init__(
            "calculator",
            "Perform a calculation using python's eval function",
            {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate, should be a python mathematical expression",
                    }
                },
            },
            "result:string",
        )

    def execute(self, arg: dict) -> str:
        try:
            return str(eval(arg["expression"]))
        except Exception as e:
            return f"Error executing code: {str(e)}"


class PythonCodeTool(Tool):
    def __init__(self):
        super().__init__(
            "python_code",
            "Execute python code using a temporary file and a subprocess. You must print results to stdout.",
            {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The python code to execute, can be multiline",
                    }
                },
            },
            "result:string",
        )

    def execute(self, arg: dict) -> str:
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".py", mode="w", delete=False
            ) as temp_file:
                temp_file.write(arg["code"])
                temp_file.flush()

                start_time = time.time()
                process = subprocess.Popen(
                    ["python", temp_file.name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, stderr = process.communicate(timeout=10)  # 10 second timeout
                end_time = time.time()
                execution_time = end_time - start_time

                result = {
                    "stdout": stdout,
                    "stderr": stderr,
                    "return_value": process.returncode,
                    "execution_time": execution_time,
                }

        except subprocess.TimeoutExpired:
            process.kill()
            return "Error: Code execution timed out after 10 seconds"
        except Exception as e:
            return f"Error executing code: {str(e)}"

        return "\n".join([f"{k}:\n{v}" for k, v in result.items()])


class DateTimeTool(Tool):
    def __init__(self):
        super().__init__(
            "get_current_datetime",
            "Get the current date and time",
            {"type": "object", "properties": {}},
            "datetime:string"
        )

    def execute(self, arg: dict) -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RandomNumberTool(Tool):
    def __init__(self):
        super().__init__(
            "generate_random_number",
            "Generate a random number within a given range",
            {
                "type": "object",
                "properties": {
                    "min": {"type": "number", "description": "The minimum value"},
                    "max": {"type": "number", "description": "The maximum value"}
                }
            },
            "random_number:number"
        )

    def execute(self, arg: dict) -> str:
        return str(random.uniform(arg["min"], arg["max"]))


class RegexTool(Tool):
    def __init__(self):
        super().__init__(
            "regex_match",
            "Perform a regex match on a given text",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to search in"},
                    "pattern": {"type": "string", "description": "The regex pattern to match"}
                }
            },
            "matches:list[string]"
        )

    def execute(self, arg: dict) -> str:
        matches = re.findall(arg["pattern"], arg["text"])
        return json.dumps(matches)


class Base64Tool(Tool):
    def __init__(self):
        super().__init__(
            "base64_encode_decode",
            "Encode or decode a string using Base64",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["encode", "decode"], "description": "Whether to encode or decode"},
                    "text": {"type": "string", "description": "The text to encode or decode"}
                }
            },
            "result:string"
        )

    def execute(self, arg: dict) -> str:
        if arg["action"] == "encode":
            return base64.b64encode(arg["text"].encode()).decode()
        elif arg["action"] == "decode":
            return base64.b64decode(arg["text"].encode()).decode()
        else:
            return "Invalid action. Use 'encode' or 'decode'."


class SimpleChartTool(Tool):
    def __init__(self):
        super().__init__(
            "generate_simple_chart",
            "Generate a simple bar chart image",
            {
                "type": "object",
                "properties": {
                    "data": {"type": "array", "items": {"type": "number"}, "description": "List of numerical values for the chart"},
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels for each bar"}
                }
            },
            "image_base64:string"
        )

    def execute(self, arg: dict) -> str:
        data = arg["data"]
        labels = arg["labels"]
        
        # Create a simple bar chart
        width, height = 400, 300
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        # Draw bars
        max_value = max(data)
        bar_width = width // (len(data) + 1)
        for i, value in enumerate(data):
            bar_height = (value / max_value) * (height - 50)
            left = (i + 1) * bar_width
            draw.rectangle([left, height - bar_height, left + bar_width, height], fill='blue')
        
        # Add labels
        font = ImageFont.load_default()
        for i, label in enumerate(labels):
            left = (i + 1) * bar_width + bar_width // 2
            draw.text((left, height - 20), label, fill='black', anchor='ms', font=font)
        
        # Convert to base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return img_str


class LLAVAImageAnalysisTool(Tool):
    def __init__(self):
        super().__init__(
            "analyze_image",
            "Analyze an image using the LLAVA model",
            {
                "type": "object",
                "properties": {
                    "image_base64": {"type": "string", "description": "Base64 encoded image"},
                    "question": {"type": "string", "description": "Question about the image"}
                }
            },
            "analysis:string"
        )

    def execute(self, arg: dict) -> str:
        try:
            # Decode base64 image
            image_data = base64.b64decode(arg["image_base64"])
            image = Image.open(BytesIO(image_data))

            # Save image to a temporary file
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                image.save(temp_file, format="PNG")
                temp_file_path = temp_file.name

            # Call LLAVA model
            response = ollama.chat(
                model="llava:7b",
                messages=[
                    {
                        "role": "user",
                        "content": arg["question"],
                        "images": [temp_file_path]
                    }
                ]
            )

            # Clean up temporary file
            os.remove(temp_file_path)

            # Unload LLAVA model
            ollama.delete("llava:7b")

            return response['message']['content']
        except Exception as e:
            return f"Error analyzing image: {str(e)}"