import duckduckgo_search
import requests
from readability.readability import Document
from markdownify import markdownify as md
import subprocess
import time
import tempfile

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
        return [{'type': 'function', 'function': {'name': tool.name, 'description': tool.description, 'parameters': tool.arguments}} for tool in self.tools]
    

class DefaultToolManager(ToolManager):
    def __init__(self):
        super().__init__()
        self.add_tool(SearchTool())
        self.add_tool(GetReadablePageContentsTool())
        self.add_tool(CalculatorTool())
        self.add_tool(PythonCodeTool())


class SearchTool(Tool):
    def __init__(self):
        super().__init__("search_web", "Search the internet for information", {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'The search query'}}}, "results:list[string]")

    def execute(self, arg: dict) -> str:
        res = duckduckgo_search.DDGS().text(arg['query'], max_results=5)
        return '\n\n'.join([f"{r['title']}\n{r['body']}\n{r['href']}" for r in res])
    

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
        super().__init__("get_readable_page_contents", "Get the contents of a web page in a readable format", {'type': 'object', 'properties': {'url': {'type': 'string', 'description': 'The url of the web page'}}}, "contents:string")

    def execute(self, arg: dict) -> str:
        return get_readable_page_contents(arg['url'])


class CalculatorTool(Tool):
    def __init__(self):
        super().__init__("calculator", "Perform a calculation", {'type': 'object', 'properties': {'expression': {'type': 'string', 'description': 'The mathematical expression to evaluate, should be a python mathematical expression'}}}, "result:string")

    def execute(self, arg: dict) -> str:
        p = PythonCodeTool()
        return p.execute({'code': arg['expression']})

class PythonCodeTool(Tool):
    def __init__(self):
        super().__init__("python_code", "Execute python code", 
                         {'type': 'object', 'properties': {'code': {'type': 'string', 'description': 'The python code to execute, can be multiline'}}}, 
                         "result:string")

    def execute(self, arg: dict) -> str:
        try:
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as temp_file:
                temp_file.write(arg['code'])
                temp_file.flush()

                start_time = time.time()
                process = subprocess.Popen(['python', temp_file.name], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE, 
                                           text=True)
                stdout, stderr = process.communicate(timeout=10)  # 10 second timeout
                end_time = time.time()
                execution_time = end_time - start_time

                result = {
                    'stdout': stdout,
                    'stderr': stderr,
                    'return_value': process.returncode,
                    'execution_time': execution_time
                }

        except subprocess.TimeoutExpired:
            process.kill()
            return "Error: Code execution timed out after 10 seconds"
        except Exception as e:
            return f"Error executing code: {str(e)}"
        
        return '\n'.join([f"{k}: {v}" for k, v in result.items()])