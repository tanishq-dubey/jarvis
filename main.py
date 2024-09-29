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

    for iteration in range(max_retries):
        response = ollama.chat(model=PRIMARY_MODEL, messages=conversation_history, tools=tool_manager.get_tools_for_ollama_dict(), stream=False)
        assistant_message = response['message']
        
        conversation_history.append(assistant_message)
        emit('conversation_history', {'history': conversation_history})
        pprint.pp(assistant_message)

        if 'tool_calls' in assistant_message:
            emit('thought', {'type': 'decision', 'content': "Tool Call\n\n" + assistant_message['content']})
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

            reflection_prompt = "Reflect on the tool results. If there were any errors, propose multiple alternative approaches to solve the problem. If successful, consider if the result fully answers the user's query or if additional steps are needed."
            conversation_history.append({
                "role": "assistant",
                "content": reflection_prompt
            })
            emit('conversation_history', {'history': conversation_history})
        else:
            if "<answer>" in assistant_message['content'].lower():
                answer_content = re.search(r'<answer>(.*?)</answer>', assistant_message['content'], re.DOTALL)
                if answer_content:
                    final_answer = answer_content.group(1).strip()
                    emit('thought', {'type': 'answer', 'content': final_answer})
                    return final_answer
            else:
                emit('thought', {'type': 'decision', 'content': "Think/Plan/Decision/Action\n\n" + assistant_message['content']})
                reflection_prompt = "Your last response didn't provide a final answer. Please reflect on your current understanding of the problem and consider if you need to use any tools or if you can now provide a final answer. If you're ready to give a final answer, put your response in tags <answer></answer>"
                conversation_history.append({"role": "assistant", "content": reflection_prompt})
                emit('conversation_history', {'history': conversation_history})

    return f"Max iterations reached. Last response: {assistant_message['content']}"

ANSWER_QUESTION_PROMPT = f"""
The current date is {datetime.now().strftime("%A, %B %d, %Y")}, your knowledge cutoff was December 2023.
You are Dewey, an AI assistant with access to external tools and the ability to think through complex problems. Your role is to assist users by leveraging tools when necessary, thinking deeply about problems, and providing accurate and helpful information, all with a cheerful, but witty personality. Here are the tools available to you:

{tool_manager.get_tools_and_descriptions_for_prompt()}

When addressing a query, follow these steps:

1. Analyze: Thoroughly analyze the query and consider multiple approaches to solving it.

2. Plan: Develop a plan of action, considering whether you need to use any tools or if you can answer directly.

3. Execute: If you need to use a tool, call it as you would a function. If not, proceed with your reasoning.

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

Always explain your thought process, including your reasoning for each decision and how you arrived at your conclusions. If you're providing a final answer, put your response in tags <answer></answer>.

Remember, complex problems often require multiple steps and iterations. Don't hesitate to break down the problem, use tools multiple times, or explore different approaches to arrive at the best solution.
"""

PRIMARY_MODEL = "llama3.1:8b"

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