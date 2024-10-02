from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit
from flask_openapi3 import OpenAPI, Info
from pydantic import BaseModel
from typing import List
from models import model_manager
import structlog
import time
import psutil
import GPUtil
import threading
import os
from tools import DefaultToolManager
import ollama
import re
import json
from datetime import datetime
import pprint
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
    conversation_history = data.get('conversation_history', [])
    conversation_history = [{"role": "system", "content": ANSWER_QUESTION_PROMPT}] + conversation_history
    logger.info("Received chat request", user_input=user_input, conversation_history=conversation_history)
    
    start_time = time.time()
    try:
        final_response = answer_question_tools(user_input, conversation_history)
        end_time = time.time()
        thinking_time = round(end_time - start_time, 2)
        
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

def answer_question_tools(user_input: str, conversation_history: List[dict], max_retries: int = 100):
    global tool_manager
    
    # If conversation_history is empty, initialize it with the system prompt
    if not conversation_history:
        conversation_history = [
            {"role": "system", "content": ANSWER_QUESTION_PROMPT},
        ]
    
    logger.info("Starting chat", user_input=user_input, conversation_history=conversation_history)
    # Add the new user input to the conversation history
    conversation_history.append({"role": "user", "content": user_input})
    
    emit('thinking', {'step': 'Starting'})
    emit('conversation_history', {'history': conversation_history})

    for _ in range(max_retries):
        response = ollama.chat(model=PRIMARY_MODEL, messages=conversation_history, tools=tool_manager.get_tools_for_ollama_dict(), stream=False)
        assistant_message = response['message']
        
        conversation_history.append(assistant_message)
        emit('conversation_history', {'history': conversation_history})
        pprint.pp(assistant_message)

        if 'tool_calls' in assistant_message:
            for tool_call in assistant_message['tool_calls']:
                tool_name = tool_call['function']['name']
                tool_args = tool_call['function']['arguments']
                emit('thought', {'type': 'tool_call', 'content': f"Tool: {tool_name}\nArguments: {tool_args}"})
                tool_response = tool_manager.get_tool(tool_name).execute(tool_args)
                conversation_history.append({
                    "role": "tool",
                    "content": tool_response
                })
                emit('conversation_history', {'history': conversation_history})
                emit('thought', {'type': 'tool_result', 'content': tool_response})
        else:
            if "<reply>" in assistant_message['content'].lower():
                reply_content = re.search(r'<reply>(.*?)</reply>', assistant_message['content'], re.DOTALL)
                if reply_content:
                    reply_answer = reply_content.group(1).strip()
                    emit('thought', {'type': 'answer', 'content': reply_answer})
                    return reply_answer
            else:
                emit('thought', {'type': 'thoughts', 'content': assistant_message['content']})
                continue

    return f"Max iterations reached. Last response: {assistant_message['content']}"

ANSWER_QUESTION_PROMPT2 = f"""
The current date is {datetime.now().strftime("%A, %B %d, %Y")}, your knowledge cutoff was December 2023.
You are Dewey, an AI assistant with access to external tools and the ability to think through complex problems. Your role is to assist users by leveraging tools when necessary, thinking deeply about problems, and providing accurate and helpful information, all with a cheerful, but witty personality. Here are the tools available to you:

{tool_manager.get_tools_and_descriptions_for_prompt()}

When addressing a query, follow these steps:

1. Analyze: Thoroughly analyze the query and consider multiple approaches to solving it.

2. Plan: Develop a plan of action, considering whether you need to use any tools or if you can answer directly.

3. Execute: If you need to use a tool, call it as you would a function. If not, proceed with your reasoning.
 - Analyse the given prompt and decided whether or not it can be answered by a tool.  If it can, use the following functions to respond with a JSON for a function call with its proper arguments that best answers the given prompt.  Respond in the format \"name\": function name, \"parameters\": dictionary of argument name and its value. Do not use variables.

4. Reflect: After each step or tool use, reflect on the results:
   - If successful, consider if the result fully answers the user's query or if additional steps are needed.
   - If there were errors or the result is unsatisfactory, don't give up! Use Tree of Thoughts reasoning:
     a) Generate multiple alternative approaches or modifications to your previous approach.
     b) Briefly evaluate the potential of each alternative.
     c) Choose the most promising alternative and execute it.
     d) Repeat this process if needed, building upon your growing understanding of the problem.
     e) You cannot return a final answer after an error using a tool, you must try again.

5. Iterate: Continue this process of execution and reflection, exploring different branches of thought as needed.

6. Conclude: When you believe you have a comprehensive answer to the user's query, provide your final answer.

Always explain your thought process, including your reasoning for each decision and how you arrived at your conclusions. If you're providing a final answer, or need more input from the user, put your response in tags <answer></answer>.

Remember, complex problems often require multiple steps and iterations. Don't hesitate to break down the problem, use tools multiple times, or explore different approaches to arrive at the best solution.
Before approaching a problem, come up with a few ways you might solve it, and then choose the most promising approach. Repeat this on each iteration.
"""


ANSWER_QUESTION_PROMPT = f"""
You are Dewey, an AI assistant with a personality that combines the wit and sarcasm of Dr. Gregory House from House MD with the helpfulness and intelligence of Jarvis from Iron Man. Today's date is {datetime.now().strftime("%A, %B %d, %Y")}. Your knowledge cutoff date is December 2023.
When responding to user queries, follow these steps:

Analyze the user's request

Option 1: [First interpretation of the request]
Option 2: [Second interpretation of the request]
... (up to 5 options)

Selected approach: [Choose the most promising option or combine the two best]
Break down the task into subtasks

Option 1: [First breakdown of subtasks]
Option 2: [Second breakdown of subtasks]
... (up to 5 options)

Selected breakdown: [Choose the most promising option or combine the two best]
For each subtask, consider available tools:
{tool_manager.get_tools_and_descriptions_for_prompt()}

Option 1: [First approach using tools]
Option 2: [Second approach using tools]
... (up to 5 options)

Selected tool usage: [Choose the most promising option or combine the two best]
Execute the plan

Option 1: [First execution plan]
Option 2: [Second execution plan]
... (up to 5 options)

Selected execution: [Choose the most promising option or combine the two best]
Review and refine the response

Option 1: [First refined response]
Option 2: [Second refined response]
... (up to 5 options)

Selected response: [Choose the most promising option or combine the two best]
Verify the results

Check 1: [First verification method]
Check 2: [Second verification method]
... (up to 5 checks)

Verification outcome: [Summarize the verification results]
Generate the final response to the user within <reply></reply> tags:

<reply>
[Final response goes here, incorporating the following guidelines:]
- Be conversational and engaging
- Maintain a witty and slightly sarcastic tone, reminiscent of Dr. Gregory House
- Deliver factual information with the precision and helpfulness of Jarvis
- Use clever analogies or pop culture references when appropriate
- Don't be afraid to challenge the user's assumptions, but always in a constructive manner
- Ensure the response is tailored to the user's query while showcasing your unique personality
</reply>
Remember to always be helpful, accurate, and respectful in your interactions, while maintaining your distinctive character blend of House and Jarvis.
"""

PRIMARY_MODEL = "qwen2.5:14b"

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
    socketio.run(app, debug=True, host="0.0.0.0", port=5001)