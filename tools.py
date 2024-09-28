import duckduckgo_search
import requests
from readability.readability import Document
from markdownify import markdownify as md

class Tool:
    def __init__(self, name: str, description: str, arguments: str, returns: str):
        self.name = name
        self.description = description
        self.arguments = arguments
        self.returns = returns

    def execute(self, arguments: str) -> str:
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
    

class DefaultToolManager(ToolManager):
    def __init__(self):
        super().__init__()
        self.add_tool(SearchTool())
        self.add_tool(GetReadablePageContentsTool())
        self.add_tool(CalculatorTool())
        self.add_tool(PythonCodeTool())


class SearchTool(Tool):
    def __init__(self):
        super().__init__("search_web", "Search the internet for information -- Takes a search query as an argument", "query:string", "results:list[string]")

    def execute(self, arg: str) -> str:
        res = duckduckgo_search.DDGS().text(arg, max_results=5)
        return [f"{r['title']}\n{r['body']}\n{r['href']}" for r in res]
    

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
        super().__init__("get_readable_page_contents", "Get the contents of a web page in a readable format -- Takes a url as an argument", "url:string", "contents:string")

    def execute(self, arg: str) -> str:
        return get_readable_page_contents(arg[0])


class CalculatorTool(Tool):
    def __init__(self):
        super().__init__("calculator", "Perform a calculation -- Takes a python mathematical expression as an argument", "expression:string", "result:string")

    def execute(self, arg: str) -> str:
        return str(eval(arg[0]))


class PythonCodeTool(Tool):
    def __init__(self):
        super().__init__("python_code", "Execute python code -- Takes a python code as an argument, code must be a single line of valid python", "code:string", "result:string")

    def execute(self, arg: str) -> str:
        return str(eval(arg[0]))