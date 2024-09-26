from flask import Flask, send_from_directory
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



logger = structlog.get_logger()

openapi = OpenAPI(__name__, info=Info(title="LLM Chat Server", version="1.0.0"))
app = openapi
socketio = SocketIO(app, cors_allowed_origins="*")

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
    full_context = ""
    try:
        # Step 1: Generate a plan using the initial LLM
        emit('thinking', {'step': 'Generating plan'})
        plan, plan_generation = generate_plan(user_input)
        full_context += f"Plan Thinking:\n{plan_generation}"
        full_context += f"Plan:\n{plan}"
        emit('thought', {'content': f"Plan Thinking:\n{plan_generation}"})
        emit('thought', {'content': f"Plan:\n{plan}"})

        if plan[0].strip().lower() == "direct_answer":
            final_response = plan[1]
            thinking_time = round(time.time() - start_time, 2)
            emit('chat_response', {
                'response': final_response,
                'thinking_time': thinking_time
            })
            return
        
        # Step 2: Execute each step of the plan
        step_results = []
        for i, step in enumerate(plan):
            emit('thinking', {'step': f'Executing step {i+1}'})
            while True:
                best_model, model_selection = select_best_model(step, step_results, full_context)
                if best_model in model_manager.model_capabilities:
                    break
                logger.warning(f"Selected model {best_model} is not in the list of available models. Retrying...")
            emit('thought', {'content': f"Selected model for step {i+1}:\n{model_selection}"})
            # summary, summary_generation = summarize_context(f"Plan: {plan}\n\nSteps: {step_results}")
            # emit('thought', {'content': f"Context summary:\n{summary_generation}"})
            step_result, step_execution = execute_step(step, best_model, step_results, full_context)
            emit('thought', {'content': f"Step {i+1} result:\n{step_execution}"})
            emit('thought', {'content': f"Result {i+1}:\n{step_result}"})
            step_results.append(step_result)
            full_context += f"Step {i+1} result:\n{step_execution}"
        
        # Step 3: Generate final response
        emit('thinking', {'step': 'Generating final response'})
        final_response, final_generation = generate_final_response(user_input, plan, step_results)
        emit('thought', {'content': f"Final response generation:\n{final_generation}"})
        
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

PLAN_GENERATE_PROMPT = """
You are building a "chain of thought" workflow for a series of LLMs to complete a task provided by a user.
Your first task is to "think" through the problem provided by the user. Probe what it would take to complete the task, see if there are hidden nuances, what constrains might be relevant, how to be efficient.
This thinking should set question the premise of the task, and sets the scene for a plan of attack to be created.
Verbalize your thoughts out loud, allow the user to see your thought process. This thought process will also be used as context for processing the generated plan.
This thought process should mimic the process of a human, and not be a simple list of steps, but should be a narrative of thought that a human would have.
Each step in the formulated plan is a step that a seperate LLM will complete. The LLM that will complete the step will be selected based on the scope of the step and the capabilities of the available models.
There are models that are good at coding and math, and there are models that are good at reasoning and planning. Some models that are generalists, multilingual, or conversational. And even some that are vision models.
Use this context of the possible models to shape each step such that a LLM can complete the step given the step and some context.
Steps should follow a logical "chain of thought" in order to best complete the overall task.
Steps should be self contained and be designed such that the results of one step can be passed on to the next step.
Steps should be phrased in such a way that it acts as a prompt or instruction to the LLM that will complete the step.
Each step will return a result, and a thought process. The thought process is extremely important, it is the "chain of thought" that the LLM went through to complete the step. This thought process is critical for the next step in the plan.
Consider how results from one step can be combined with results from another step and consider how the chain of thought from one step can inform the next step when designing each step.
Try and minimize the number of steps required to complete the task since running a lot of steps is expensive. 
Your output should be your thought process, followed by a single line titled "STEPS", followed by each step to take, one step per line.
Do not add any sort of markdown formatting, code formatting, or any other formatting.
Do not add any preamble, postamble, or other text, only the thought process and the steps.

Consider the following example:

Prompt: Write a program to reverse a string, then output ASCII block art of that reversed string. Do this in python.

So there are two parts to this task. First, we need to reverse the input string. Then we need to print the ASCII block art for each character in the reversed string.
We should be able to reverse the string using either a simple loop, or a python slice. Slicing is simpler, so we should use that.
For the ASCII block art, the challenge is in creating a mapping between each character and its block art representation. There are a few ways to go about this:
 - Find a library that converts text to block art
 - Create our own mapping from characters to block art
 - Create a procedurally generated mapping from characters to block art
Procedural generation could be done with an algorithm, but coming up with a good algorithm could be challenging.
Generating a dictionary could be a good approach, but there are 26 letters in the alphabet, and 10 digits, so we would need 36 different outputs for the block art.
We should search for a library that already does this, import it, and call it on the result of the string reversal. We would also need to tell the user to install the library.

We're now ready to create our plan.

STEPS
1. Write a function that takes a string and reverses it.
2. Write a function that takes a string and returns the ASCII block art for each character in the string, this must be done using a library.
3. Combine the two functions into a single program.

---

Now you try.
"""
_REMINADER_PT ="""
Each task you create should be should be self contained and be designed such that the results of one step can be passed on to the next step. 
Try and minimize the number of steps required to complete the task. 
Output only a numbered list of steps, each step should be a seperate line.
Do not output any preamble or other text, only the list of steps.
If you think a task can be completed by a single step, then you can output a single step. 
If you can directly answer the question, you must begin your response with a single line containing the text "DIRECT_ANSWER" and then provide the answer to the question on the next line.

Here are some samples:

Input: Write a program to reverse a string, then output the ASCII art of that reversed string. Do this in python.
Steps:
1. Define a template for a program that prints the ASCII art of the reversed string.
2. Fill in the logic to reverse the string.
3. Fill in the logic to print the ASCII art of the reversed string.
4. Output the final program.

Input: What are the oceans of the world?
Steps:
1. Use the encyclopedia tool to get the page on the oceans of the world, parse, and output the results.

Input: What is the perfect gas law?
Steps:
DIRECT_ANSWER
The perfect gas law is the equation of state of a hypothetical ideal gas. The formula is $$PV = nRT$$ where P is pressure, V is volume, n is the number of moles, R is the ideal gas constant, and T is temperature.
"""

def generate_plan(user_input: str) -> tuple[List[str], str]:
    logger.debug("Generating plan", prompt=user_input, system=PLAN_GENERATE_PROMPT)
    response = model_manager.generate_text("qwen2.5:7b", user_input, max_length=1024, system=PLAN_GENERATE_PROMPT)
    plan = response.split("STEPS")[1].strip()
    response_no_steps = response.split("STEPS")[0].strip()
    return [step.strip() for step in plan.split("\n") if step.strip()], response_no_steps


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