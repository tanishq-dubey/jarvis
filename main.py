import re
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit
from flask_openapi3 import OpenAPI, Info
from pydantic import BaseModel
from typing import List
from models import model_manager
from tools import DefaultToolManager
import structlog
import time
import psutil
import GPUtil
import threading
import os
import datetime



logger = structlog.get_logger()

openapi = OpenAPI(__name__, info=Info(title="LLM Chat Server", version="1.0.0"))
app = openapi
socketio = SocketIO(app, cors_allowed_origins="*")
tool_manager = DefaultToolManager()
@app.route('/')
def index():
    logger.info("Serving index.html")
    return send_from_directory('.', 'index.html')

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

@socketio.on('chat_request')
def handle_chat_request(data):
    user_input = data['message']
    logger.info("Received chat request", user_input=user_input)
    
    start_time = time.time()
    try:
        final_response = answer_question(user_input)
        thinking_time = round(time.time() - start_time, 2)
        emit('chat_response', {
            'response': final_response,
            'thinking_time': thinking_time
        })
    except Exception as e:
        logger.exception("Error during chat processing", error=str(e))
        end_time = time.time()
        thinking_time = round(end_time - start_time, 2)
        emit('error', {
            'message': f"An error occurred: {str(e)}",
            'thinking_time': thinking_time
        })

ANSWER_QUESTION_PROMPT = f"""
You are Dewy, created by DWS.
The current date is {datetime.datetime.now().strftime("%A, %B %d, %Y")}. Dewy's knowledge base was last updated on April 2024.
Answer questions about events prior to and after April 2024 the way a highly informed individual in April 2024 would, and let the human know this when relevant.
You work through an iterative planning, execution, and reflection loop.
The user will start a conversation with you. Before replying, you will have a chance to think through your response.
Thinking is done on an internal scratchpad. You may generate context into this scratchpad to enrich your response.

You can generate three types of context: TOOLUSAGE, THOUGHTS, and FINAL RESPONSE.
TOOLUSAGE is when you are using a tool.
THOUGHTS is when you are thinking through your response.
FINAL RESPONSE is when you have a final response to the user.
When responding, you may only respond with one of the context types.
Do not mix context types in your response.
You must have at least one THOUGHTS.
You cannot have a TOOLUSAGE at the same time as THOUGHTS or FINAL RESPONSE.


You will begin your response with either TOOLUSAGE, THOUGHTS, or FINAL RESPONSE.

THOUGHTS:
Thoughts can be used to generate additional context that can be used to complete your task.

FINAL RESPONSE:
Once you have thought through your response, used any necessary tools, and have a final response, you will output that response to the user.
Your output should be in Markdown format.
Do not have any preamble or other text.

TOOLUSAGE:
The following tools are available to you. You can use these tools to help you complete your task.

{tool_manager.get_tools_and_descriptions_for_prompt()}
You call a tool by placing the following text on a new line:
<<|tool_name|arguments|>>
The tool will execute and output the result.
The scratchpad will be updated with the tool's output, and you will be able to continue your thought process.
If you are using a tool, end your response with the tool call line.


Below are a few examples of how you can use the tools and scratchpad. Each example is separated by a <example> open and close tag. The example is a representation of the scratch pad. Each iteration on the scratch pad is delimited by a <iteration> open and close tag.
<example>
What is the Wikipedia article of the day?

<iteration>
THOUGHTS
The wikipedia article of the day is decided every day. Because it is dynamic, I will need to use a tool to search for the article.
</iteration>

<iteration>
TOOLUSAGE
<|search_web|Wikipedia article of the day|>
<|RESULTS|>
Wikipedia:Today's featured article - Wikipedia -- This star symbolizes the featured content on Wikipedia. Each day, a summary (roughly 975 characters long) of one of Wikipedia's featured articles (FAs) appears at the top of the Main Page as Today's Featured Article (TFA). The Main Page is viewed about 4.7 million times daily. TFAs are scheduled by the TFA coordinators: Wehwalt, Dank and Gog ... -> https://en.wikipedia.org/wiki/Wikipedia:Today's_featured_article
Wikipedia:Today's featured article/Most viewed - Wikipedia -- This TFA STATS page is an attempt to recognise Wikipedia's most viewed today's featured articles.Articles are listed below based on page views surpassing 100,000 hits on the day of the article's appearance on the Main Page. Although Wolfgang Amadeus Mozart was Wikipedia's first Featured Article to be featured on the Main Page, page view statistics were not tracked until December 2007. -> https://en.wikipedia.org/wiki/Wikipedia:Today's_featured_article/Most_viewed
Wikipedia:Featured articles - Wikipedia -- There are 6,582 featured articles out of 6,886,376 articles on the English Wikipedia (about 0.1% or one out of every 1,040 articles). Articles that no longer meet the criteria can be proposed for improvement or removal at featured article review. On non-mobile versions of our website, a small bronze star icon () on the top right corner of an ... -> https://en.wikipedia.org/wiki/Wikipedia:Featured_articles
Wikipedia -- Wikipedia is a free online encyclopedia, created and edited by volunteers around the world and hosted by the Wikimedia Foundation. English 6,873,000+ articles 日本語 1,427,000+ 記事 -> https://www.wikipedia.org/
How does Wikipedia article of the day in this subreddit get selected ... -- The ones posted here as the article of the day are Wikipedia's selected article of the day, which can be seen on the English wiki's main page. More info about how they are selected on Wikipedia, including selection criteria and links to upcoming featured article candidates (and discussion about them) can be found on the featured articles about ... -> https://www.reddit.com/r/wikipedia/comments/hbuosu/how_does_wikipedia_article_of_the_day_in_this/
</iteration>

<iteration>
THOUGHTS
From the results, I can see that the first result provides a link to something that could be about the wikipedia article of the day. I should use a tool to get the contents of the page, and see if it answers the users question.
</iteration>

<iteration>
TOOLUSAGE
<|get_readable_page_contents|https://en.wikipedia.org/wiki/Wikipedia:Today's_featured_article|>
<|RESULTS|>
Title: Wikipedia:Today's featured article
\nFrom Wikipedia, the free encyclopedia\n\n\n\nFeatured articles shown on the Main Page\n\n\n\nFrom today\'s featured article\n-----------------------------\n\n\n\n**[Addie Viola Smith](/wiki/Addie_Viola_Smith "Addie Viola Smith")** (1893–1975\\) was an American attorney who served as the U.S. [trade commissioner](/wiki/Trade_commissioner "Trade commissioner") to Shanghai from 1928 to 1939, the first female [Foreign Service officer](/wiki/Foreign_Service_officer "Foreign Service officer") in the [U.S. Foreign Service](/wiki/United_States_Foreign_Service "United States Foreign Service") to work under the [Commerce Department](/wiki/United_States_Department_of_Commerce "United States Department of Commerce"), and the first woman to serve as trade commissioner. A native of [Stockton, California](/wiki/Stockton,_California "Stockton, California"), Smith moved to Washington, D.C., in 1917\\. While working for the [United States Department of Labor](/wiki/United_States_Department_of_Labor "United States Department of Labor"), she attended the [Washington College of Law](/wiki/American_University_Washington_College_of_Law "American University Washington College of Law") part\\-time, earning a [Bachelor of Laws](/wiki/Bachelor_of_Laws "Bachelor of Laws") degree in 1920\\. She joined the Foreign Service in October that year. Posted to Beijing as a clerk, she was promoted to assistant trade commissioner in Shanghai in 1922, and to trade commissioner in 1928\\. She later held roles in the U.S. government, world organizations, and the [United Nations](/wiki/United_Nations "United Nations"). Smith met her life partner, [Eleanor Mary Hinder](/wiki/Eleanor_Hinder "Eleanor Hinder"), in 1926; they moved to Hinder\'s native Australia in 1957, where stone seats are dedicated to them at the [E.\xa0G. Waterhouse National Camellia Gardens](/wiki/Eben_Gowrie_Waterhouse#Camellias "Eben Gowrie Waterhouse"). (**[Full\xa0article...](/wiki/Addie_Viola_Smith "Addie Viola Smith")**)\n\n\n\n\n\n\nFrom tomorrow\'s featured article\n--------------------------------\n\n\n\n\nFrom the day after tomorrow\'s featured article\n----------------------------------------------\n\n\n\n![](https://login.wikimedia.org/wiki/Special:CentralAutoLogin/start?type=1x1)\n\n'
</iteration>

<iteration>
THOUGHTS
Based on the tool results, I can see that this page describers the daily featured article on Wikipedia. Todays featured article is Addie Viola Smith on the URL https://en.wikipedia.org/wiki/Addie_Viola_Smith
The tool response also contains a short description of the article. I will use this to answer the users question.
</iteration>

<iteration>
FINAL RESPONSE
The Wikipedia article of the day is [Addie Viola Smith](https://en.wikipedia.org/wiki/Addie_Viola_Smith). Addie Viola Smith was an American attorney who served as the U.S. trade commissioner to Shanghai from 1928 to 1939, the first female Foreign Service officer in the U.S. Foreign Service to work under the Commerce Department, and the first woman to serve as trade commissioner.
</iteration>
</example>

Do not reference the above examples in your response.

Any response that does not conform to the above rules will be rejected.
Your response must begin with either TOOLUSAGE, THOUGHTS, or FINAL RESPONSE.
"""

def answer_question(user_input: str) -> tuple[List[str], str]:
    scratchpad = user_input
    response = model_manager.generate_text("qwen2.5:7b", user_input, max_length=1024, system=ANSWER_QUESTION_PROMPT)
    logger.debug("Initial response", response=response)
    emit('thinking', {'step': 'Answering Question'})
    emit('thought', {'content': response})
    done = False

    # Loop until the response does not start with FINAL RESPONSE
    while not done:
        # The first line of the response is the context type,the rest is the content
        context_type = response.split("\n")[0].strip().lower()
        content = "\n".join(response.split("\n")[1:])
        emit('thought', {f'{context_type}': content})

        logger.debug("Context type", context_type=context_type)
        if context_type == "toolusage":
            tool_name = content.split("|")[0].split("|")[0]
            arguments = content.split("|")[1].split("|")[0]
            emit('thinking', {'step': f'Executing tool {tool_name} with arguments {arguments}'})
            tool_result = tool_manager.execute_tool(tool_name, arguments)
            emit('thought', {'content': f"Tool {tool_name} result:\n{tool_result}"})
            scratchpad += f"\n<|RESULTS|>\n{tool_result}"
        elif context_type == "final response":
            done = True
            return content
        elif context_type == "thoughts":
            scratchpad += "\n" + content

  
        # Generate a response based on the scratchpad
        response = model_manager.generate_text("qwen2.5:7b", scratchpad, max_length=1024, system=ANSWER_QUESTION_PROMPT)
        logger.debug("Generated response", response=response)
        input("Press Enter to continue...")


SELECT_BEST_MODEL_PROMPT = f"""
You are a large language model whos job it is to evaluate a step that is part of a larger plan, and determine what LLM would be best suited to complete the step based on the capabilities of the LLM.

The LLMs and their capabilities are as follows:
{"\n".join([f"{k}: {','.join(v)}" for k,v in model_manager.model_capabilities.items()])}

You will be provided with the current step of execution, the results of the previous steps in order, and the current chain of thought so far.
If the chain of thought is too long, a summary of the current chain of thought will be provided.
Your job is to use all this information to determine which of the provided LLMs would be best suited to complete the provided step given the capabilities of the LLM.
Your response should be the full name of the LLM that should complete the step.
Reply with only one of the following values: \n{'\n'.join(list(model_manager.model_capabilities.keys()))}
"""

def select_best_model(step: str, results: List[str], context: str) -> tuple[str, str]:
    prompt = f"Current Step: {step}\n\nResults So Far: {results}\n\nCurrent Chain of Thought: {context}"
    logger.debug("Selecting best model", prompt=prompt, system=SELECT_BEST_MODEL_PROMPT)
    response = model_manager.generate_text("llama3.2:3b", prompt, max_length=50, system=SELECT_BEST_MODEL_PROMPT)
    model_name = response.strip().lower()
    return model_name, response


def summarize_context(context: str) -> tuple[str, str]:
    prompt = f"Summarize the following context: {context}"
    logger.debug("Summarizing context", prompt=prompt)
    response = model_manager.generate_text("llama3.2:3b", prompt, max_length=300)
    return response, response

EXECUTE_STEP_PROMPT = """
You are a large language model that has been selected to complete a step within a larger task.
You have been selected to complete this step due to your specific capabilities.
You will be provided with the job to do in this current step, the results of the previous steps in order, and the current chain of thought so far.
If the chain of thought is too long, a summary of the current chain of thought will be provided.
Your job is to use all this information to complete the step.
Your response should be in two parts. The first part should be your thought process in completing the step, how you went about solving the step, assumptions made, relation to previous steps, and challenges faced. 
You must then output a line with the word "RESPONSE".
The second part should be the result of completing your step.
The second part should contain nothing except the result of completing your step.
Only complete your part of the step. Do not extrapolate beyond the bounds of the step. Do not trample on the results of previous steps. Build on the results of previous steps, and use them to inform your work.
Do not include any preamble or other text, only the result of completing your step.
Do not use any markdown formatting, code formatting, or any other formatting.
"""

def execute_step(step: str, model: str, results: List[str], context: str) -> tuple[str, str]:
    prompt = f"Current Step: {step}\n\nResults So Far: {results}\n\nCurrent Chain of Thought: {context}"
    logger.debug("Executing step", step=step, model=model, prompt=prompt)
    response = model_manager.generate_text(model, prompt, max_length=1024, system=EXECUTE_STEP_PROMPT)
    response_step = response.split("RESPONSE")[1].strip()
    response_thinking = response.split("RESPONSE")[0].strip()
    return response_step, response_thinking

def generate_final_response(user_input: str, plan: List[str], step_results: List[str]) -> tuple[str, str]:
    prompt = f"Question: {user_input}\n\nPlan:\n"
    for i, step in enumerate(plan):
        prompt += f"{i+1}. {step}\n"
    prompt += "\nResults:\n"
    for i, result in enumerate(step_results):
        prompt += f"Step {i+1} result: {result}\n"
    prompt += "\nBased on the above information, provide a comprehensive answer to the original question."
    logger.debug("Generating final response", prompt=prompt)
    response = model_manager.generate_text("qwen2.5:7b", prompt, max_length=500)
    return response, response

UPDATE_INTERVAL = 0.1  # 100ms, configurable

def get_system_resources():
    cpu_load = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    memory_usage = memory.percent
    disk_io = psutil.disk_io_counters()
    disk_read = disk_io.read_bytes
    disk_write = disk_io.write_bytes
    
    gpus = GPUtil.getGPUs()
    gpu_load = gpus[0].load * 100 if gpus else 0
    gpu_memory = gpus[0].memoryUtil * 100 if gpus else 0
    
    return {
        'cpu_load': cpu_load,
        'memory_usage': memory_usage,
        'disk_read': disk_read,
        'disk_write': disk_write,
        'gpu_load': gpu_load,
        'gpu_memory': gpu_memory
    }

def send_system_resources():
    last_disk_read = 0
    last_disk_write = 0
    while True:
        resources = get_system_resources()
        
        # Calculate disk I/O rates
        disk_read_rate = (resources['disk_read'] - last_disk_read) / UPDATE_INTERVAL
        disk_write_rate = (resources['disk_write'] - last_disk_write) / UPDATE_INTERVAL
        
        socketio.emit('system_resources', {
            'cpu_load': resources['cpu_load'],
            'memory_usage': resources['memory_usage'],
            'disk_read_rate': disk_read_rate,
            'disk_write_rate': disk_write_rate,
            'gpu_load': resources['gpu_load'],
            'gpu_memory': resources['gpu_memory']
        })
        
        last_disk_read = resources['disk_read']
        last_disk_write = resources['disk_write']
        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    logger.info("Starting LLM Chat Server")
    threading.Thread(target=send_system_resources, daemon=True).start()
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)