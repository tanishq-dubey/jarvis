import configparser
import json
import os
import pprint
import queue
import random
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from typing import List, Optional
import enum

import GPUtil
import ollama
import psutil
import structlog
import logging
from flask import Flask, g, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from pydantic import BaseModel
from werkzeug.utils import secure_filename
import base64

from models import model_manager
from tools import DefaultToolManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
logger = structlog.get_logger()
# Configuration setup
CONFIG_FILE = "config.ini"

# Add this near the top of the file, after imports
processing_thread = None
processing_thread_started = False

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_IMAGE_SIZE = 1 * 1024 * 1024  # 1MB


def create_default_config():
    config = configparser.ConfigParser()
    config["DEFAULT"] = {
        "AdminKey": secrets.token_urlsafe(32),
        "DatabasePath": "llm_chat_server.db",
    }
    config["SERVER_FEATURES"] = {
        "EnableFrontend": "false",
        "EnableChatEndpoints": "false",
        "EnableAPIEndpoints": "true",
    }
    config["MODEL"] = {"PrimaryModel": "qwen2.5:14b"}
    config["PERFORMANCE"] = {"UpdateInterval": "0.1"}
    with open(CONFIG_FILE, "w") as configfile:
        config.write(configfile)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_default_config()

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


config = load_config()
ADMIN_KEY = config["DEFAULT"]["AdminKey"]
DATABASE = config["DEFAULT"]["DatabasePath"]
ENABLE_FRONTEND = config["SERVER_FEATURES"].getboolean("EnableFrontend")
ENABLE_CHAT_ENDPOINTS = config["SERVER_FEATURES"].getboolean("EnableChatEndpoints")
ENABLE_API_ENDPOINTS = config["SERVER_FEATURES"].getboolean("EnableAPIEndpoints")
PRIMARY_MODEL = config["MODEL"]["PrimaryModel"]
UPDATE_INTERVAL = config["PERFORMANCE"].getfloat("UpdateInterval")

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

tool_manager = DefaultToolManager()


# Database setup
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


class QueryStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"


def init_db():
    with app.app_context():
        db = get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS Keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                api_key TEXT NOT NULL UNIQUE
            );
        """)
        db.execute('''
            CREATE TABLE IF NOT EXISTS Queries (
                id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                query TEXT NOT NULL,
                api_key_id INTEGER,
                status TEXT NOT NULL,
                conversation_history TEXT,
                FOREIGN KEY (api_key_id) REFERENCES Keys (id)
            )
        ''')
        db.commit()


# Create a schema.sql file with the following content:
"""
CREATE TABLE IF NOT EXISTS Keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    api_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Queries (
    id TEXT PRIMARY KEY,
    ip TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    query TEXT NOT NULL,
    api_key_id INTEGER,
    status TEXT NOT NULL,
    conversation_history TEXT,
    FOREIGN KEY (api_key_id) REFERENCES Keys (id)
);
"""


def validate_api_key(api_key):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM Keys WHERE api_key = ?", (api_key,))
    result = cursor.fetchone()
    return result[0] if result else None


@app.route("/")
def index():
    if ENABLE_FRONTEND:
        logger.info("Serving index.html")
        return send_from_directory(".", "index.html")
    else:
        return jsonify({"error": "Frontend is disabled"}), 404


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


@socketio.on("chat_request")
def handle_chat_request(data):
    if not ENABLE_CHAT_ENDPOINTS:
        emit("error", {"message": "Chat endpoints are disabled"})
        return

    user_input = data["message"]
    conversation_history = data.get("conversation_history", [])
    conversation_history = [
        {"role": "system", "content": ANSWER_QUESTION_PROMPT}
    ] + conversation_history
    logger.info(
        "Received chat request",
        user_input=user_input,
        conversation_history=conversation_history,
    )

    start_time = time.time()
    try:
        final_response = answer_question_tools(user_input, conversation_history)
        end_time = time.time()
        thinking_time = round(end_time - start_time, 2)

        emit(
            "chat_response",
            {"response": final_response, "thinking_time": thinking_time},
        )
    except Exception as e:
        logger.exception("Error during chat processing", error=str(e))
        end_time = time.time()
        thinking_time = round(end_time - start_time, 2)
        emit(
            "error",
            {"message": f"An error occurred: {str(e)}", "thinking_time": thinking_time},
        )


def answer_question_tools(
    user_input: str, conversation_history: List[dict], max_retries: int = 100
):
    global tool_manager

    # If conversation_history is empty, initialize it with the system prompt
    if not conversation_history:
        conversation_history = [
            {"role": "system", "content": ANSWER_QUESTION_PROMPT},
        ]

    logger.info(
        "Starting chat",
        user_input=user_input,
        conversation_history=conversation_history,
    )
    # Add the new user input to the conversation history
    conversation_history.append({"role": "user", "content": user_input})

    emit("thinking", {"step": "Starting"})
    emit("conversation_history", {"history": conversation_history})

    last_thought_content = None

    for _ in range(max_retries):
        response = ollama.chat(
            model=PRIMARY_MODEL,
            messages=conversation_history,
            tools=tool_manager.get_tools_for_ollama_dict(),
            stream=False,
        )
        assistant_message = response["message"]

        conversation_history.append(assistant_message)
        emit("conversation_history", {"history": conversation_history})
        pprint.pp(assistant_message)

        if "tool_calls" in assistant_message:
            for tool_call in assistant_message["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                emit(
                    "thought",
                    {
                        "type": "tool_call",
                        "content": f"Tool: {tool_name}\nArguments: {tool_args}",
                    },
                )
                tool_response = tool_manager.get_tool(tool_name).execute(tool_args)
                conversation_history.append({"role": "tool", "content": tool_response})
                emit("conversation_history", {"history": conversation_history})
                emit("thought", {"type": "tool_result", "content": tool_response})
        else:
            if "<reply>" in assistant_message["content"].lower():
                reply_content = re.search(
                    r"<reply>(.*?)</reply>", assistant_message["content"], re.DOTALL
                )
                if reply_content:
                    reply_answer = reply_content.group(1).strip()
                    emit("thought", {"type": "answer", "content": reply_answer})
                    return reply_answer
            else:
                current_thought_content = assistant_message["content"].strip()
                emit(
                    "thought", {"type": "thoughts", "content": current_thought_content}
                )

                # Check for two consecutive thoughts, with the second being empty
                if last_thought_content and not current_thought_content:
                    emit("thought", {"type": "answer", "content": last_thought_content})
                    return last_thought_content

                last_thought_content = current_thought_content
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
        "cpu_load": cpu_load,
        "memory_usage": memory_usage,
        "disk_read": disk_read,
        "disk_write": disk_write,
        "gpu_load": gpu_load,
        "gpu_memory": gpu_memory,
    }


def send_system_resources():
    last_disk_read = 0
    last_disk_write = 0
    while True:
        resources = get_system_resources()

        # Calculate disk I/O rates
        disk_read_rate = (resources["disk_read"] - last_disk_read) / UPDATE_INTERVAL
        disk_write_rate = (resources["disk_write"] - last_disk_write) / UPDATE_INTERVAL

        socketio.emit(
            "system_resources",
            {
                "cpu_load": resources["cpu_load"],
                "memory_usage": resources["memory_usage"],
                "disk_read_rate": disk_read_rate,
                "disk_write_rate": disk_write_rate,
                "gpu_load": resources["gpu_load"],
                "gpu_memory": resources["gpu_memory"],
            },
        )

        last_disk_read = resources["disk_read"]
        last_disk_write = resources["disk_write"]
        time.sleep(UPDATE_INTERVAL)


class QueryRequest(BaseModel):
    message: str


class QueryResponse(BaseModel):
    query_id: str


class QueryStatusResponse(BaseModel):
    status: str
    conversation_history: Optional[List[dict]]


@app.post(
    "/api/v1/query"
)
def api_query():
    """
    Submit a new query to the LLM Chat Server.

    This endpoint requires authentication via an API key.

    Sample cURL:
    curl -X POST http://localhost:5001/api/v1/query \
         -H "Content-Type: application/json" \
         -H "X-API-Key: your-api-key" \
         -d '{"message": "What is the capital of France?"}'
    """
    if not ENABLE_API_ENDPOINTS:
        return jsonify({"error": "API endpoints are disabled"}), 404

    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({"error": "API key is required"}), 401

    api_key_id = validate_api_key(api_key)
    if not api_key_id:
        return jsonify({"error": "Invalid API key"}), 401

    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "Invalid request body"}), 400

    user_input = data['message']
    query_id = str(uuid.uuid4())

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO Queries (id, ip, query, api_key_id, status) VALUES (?, ?, ?, ?, ?)",
            (query_id, request.remote_addr, user_input, api_key_id, QueryStatus.QUEUED.value)
        )
        db.commit()
        logger.info(f"Added new query to database: {query_id}")

        return jsonify({"query_id": query_id})
    except Exception as e:
        logger.exception(f"Error during API query processing: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.get(
    "/api/v1/query_status/<string:query_id>"
)
def get_query_status(query_id: str):
    """
    Get the status of a submitted query.

    This endpoint requires authentication via an API key.

    Sample cURL:
    curl -X GET http://localhost:5001/api/v1/query_status/query-id-here \
         -H "X-API-Key: your-api-key"
    """
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({"error": "API key is required"}), 401

    api_key_id = validate_api_key(api_key)
    if not api_key_id:
        return jsonify({"error": "Invalid API key"}), 401

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT status, conversation_history FROM Queries WHERE id = ?", (query_id,))
        result = cursor.fetchone()

        if result is None:
            return jsonify({"error": "Query not found"}), 404

        status, conversation_history = result

        response = {"status": status}
        if status == QueryStatus.DONE.value:
            response["conversation_history"] = json.loads(conversation_history)

        return jsonify(response)
    except Exception as e:
        logger.exception("Error retrieving query status", error=str(e))
        return jsonify({"error": str(e)}), 500


def answer_question_tools_api(
    user_input: str, conversation_history: List[dict], max_retries: int = 100
):
    global tool_manager

    if not conversation_history:
        conversation_history = [
            {"role": "system", "content": ANSWER_QUESTION_PROMPT},
        ]

    logger.info(
        "Starting API chat",
        user_input=user_input,
        conversation_history=conversation_history,
    )
    conversation_history.append({"role": "user", "content": user_input})

    last_thought_content = None

    for _ in range(max_retries):
        response = ollama.chat(
            model=PRIMARY_MODEL,
            messages=conversation_history,
            tools=tool_manager.get_tools_for_ollama_dict(),
            stream=False,
        )
        logger.info(f"API       Response: {response}")
        assistant_message = response["message"]

        conversation_history.append(assistant_message)

        if "tool_calls" in assistant_message:
            for tool_call in assistant_message["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                if tool_name is not None and tool_args is not None:
                    tool_response = tool_manager.get_tool(tool_name).execute(tool_args)
                    conversation_history.append({"role": "tool", "content": tool_response})
                    logger.info(f"API Tool response: {tool_response}")
                else:
                    logger.warning(f"Skipping tool call due to missing tool name or arguments: {tool_call}")
        else:
            if "<reply>" in assistant_message["content"].lower():
                reply_content = re.search(
                    r"<reply>(.*?)</reply>", assistant_message["content"], re.DOTALL
                )
                if reply_content:
                    reply_answer = reply_content.group(1).strip()
                    conversation_history.append(
                        {"role": "assistant", "content": reply_answer}
                    )
                    return conversation_history
            else:
                current_thought_content = assistant_message["content"].strip()

                if last_thought_content and not current_thought_content:
                    conversation_history.append(
                        {"role": "assistant", "content": last_thought_content}
                    )
                    return conversation_history

                last_thought_content = current_thought_content
                continue

    conversation_history.append(
        {
            "role": "assistant",
            "content": f"Max iterations reached. Last response: {assistant_message['content']}",
        }
    )
    return conversation_history


def process_queries():
    logger.info("Query processing thread started")
    with app.app_context():
        while True:
            try:
                db = get_db()
                cursor = db.cursor()
                
                # First, check if there are any PROCESSING queries
                cursor.execute(
                    "SELECT id FROM Queries WHERE status = ? LIMIT 1",
                    (QueryStatus.PROCESSING.value,)
                )
                processing_query = cursor.fetchone()
                if processing_query:
                    logger.info(f"Found processing query: {processing_query[0]}. Waiting...")
                    db.commit()
                    time.sleep(10)
                    continue

                # If no PROCESSING queries, get the oldest QUEUED query
                cursor.execute(
                    "SELECT id, query FROM Queries WHERE status = ? ORDER BY timestamp ASC LIMIT 1",
                    (QueryStatus.QUEUED.value,)
                )
                result = cursor.fetchone()

                if result:
                    query_id, user_input = result
                    logger.info(f"Processing query: {query_id}")
                    
                    # Update status to PROCESSING
                    cursor.execute(
                        "UPDATE Queries SET status = ? WHERE id = ?",
                        (QueryStatus.PROCESSING.value, query_id)
                    )
                    db.commit()
                    logger.info(f"Updated query {query_id} status to PROCESSING")

                    # Fetch conversation history if it exists
                    cursor.execute("SELECT conversation_history FROM Queries WHERE id = ?", (query_id,))
                    conversation_history_result = cursor.fetchone()
                    
                    if conversation_history_result and conversation_history_result[0]:
                        conversation_history = json.loads(conversation_history_result[0])
                    else:
                        conversation_history = [{"role": "system", "content": ANSWER_QUESTION_PROMPT}]
                    
                    logger.info(f"Starting answer_question_tools_api for query {query_id}")
                    final_conversation_history = answer_question_tools_api(user_input, conversation_history)
                    logger.info(f"Finished answer_question_tools_api for query {query_id}")

                    # Update with final result and set status to DONE
                    db.execute("BEGIN TRANSACTION")
                    cursor.execute(
                        "UPDATE Queries SET conversation_history = ?, status = ? WHERE id = ?",
                        (json.dumps(final_conversation_history), QueryStatus.DONE.value, query_id)
                    )
                    db.commit()
                    logger.info(f"Updated query {query_id} status to DONE")
                else:
                    logger.info("No queued queries found. Waiting...")
                    time.sleep(5)  # Wait for 5 seconds before checking again if no queries are found
            except Exception as e:
                logger.exception(f"Error processing query: {str(e)}")
                time.sleep(1)  # Wait for 1 second before retrying in case of an error


# Admin endpoint for generating API keys
class GenerateKeyRequest(BaseModel):
    username: str


class GenerateKeyResponse(BaseModel):
    username: str
    api_key: str


@app.post(
    "/admin/generate_key"
)
def generate_api_key():
    """
    Generate a new API key for a user.

    This endpoint requires authentication via an admin key.

    Sample cURL:
    curl -X POST http://localhost:5001/admin/generate_key \
         -H "Content-Type: application/json" \
         -H "X-Admin-Key: your-admin-key" \
         -d '{"username": "new_user"}'
    """
    admin_key = request.headers.get("X-Admin-Key")
    if not admin_key or admin_key != ADMIN_KEY:
        return jsonify({"error": "Invalid admin key"}), 401

    data = request.get_json()
    if not data or 'username' not in data:
        return jsonify({"error": "Invalid request body"}), 400

    username = data['username']
    api_key = secrets.token_urlsafe(32)

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO Keys (username, api_key) VALUES (?, ?)", (username, api_key)
        )
        db.commit()
        return jsonify({"username": username, "api_key": api_key})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400
    except Exception as e:
        logger.exception("Error generating API key", error=str(e))
        return jsonify({"error": str(e)}), 500


def start_processing_thread():
    global processing_thread, processing_thread_started
    if not processing_thread_started:
        processing_thread = threading.Thread(target=process_queries, daemon=True)
        processing_thread.start()
        processing_thread_started = True
        logger.info("Query processing thread started")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.post("/api/v1/query_with_image")
def api_query_with_image():
    """
    Submit a new query to the LLM Chat Server with an optional image.

    This endpoint requires authentication via an API key.

    Sample cURL:
    curl -X POST http://localhost:5001/api/v1/query_with_image \
         -H "X-API-Key: your-api-key" \
         -F "message=What's in this image?" \
         -F "image=@path/to/your/image.jpg"
    """
    if not ENABLE_API_ENDPOINTS:
        return jsonify({"error": "API endpoints are disabled"}), 404

    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({"error": "API key is required"}), 401

    api_key_id = validate_api_key(api_key)
    if not api_key_id:
        return jsonify({"error": "Invalid API key"}), 401

    if 'message' not in request.form:
        return jsonify({"error": "Message is required"}), 400

    user_input = request.form['message']
    query_id = str(uuid.uuid4())

    image_base64 = None
    if 'image' in request.files:
        file = request.files['image']
        if file and allowed_file(file.filename):
            if file.content_length > MAX_IMAGE_SIZE:
                return jsonify({"error": "Image size exceeds 1MB limit"}), 400
            
            # Read and encode the image
            image_data = file.read()
            image_base64 = base64.b64encode(image_data).decode('utf-8')

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO Queries (id, ip, query, api_key_id, status) VALUES (?, ?, ?, ?, ?)",
            (query_id, request.remote_addr, user_input, api_key_id, QueryStatus.QUEUED.value)
        )
        db.commit()
        logger.info(f"Added new query with image to database: {query_id}")

        # If there's an image, add it to the conversation history
        if image_base64:
            conversation_history = [
                {"role": "system", "content": ANSWER_QUESTION_PROMPT},
                {"role": "user", "content": f"[An image was uploaded with this message] {user_input}"},
                {"role": "system", "content": f"An image was uploaded. You can analyze it using the analyze_image tool with the following base64 string: {image_base64}"}
            ]
            cursor.execute(
                "UPDATE Queries SET conversation_history = ? WHERE id = ?",
                (json.dumps(conversation_history), query_id)
            )
            db.commit()

        return jsonify({"query_id": query_id})
    except Exception as e:
        logger.exception(f"Error during API query processing with image: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Replace the if __main__ block with this:
if __name__ == "__main__":
    logger.info("Starting LLM Chat Server")
    init_db()  # Initialize the database

    if ENABLE_FRONTEND or ENABLE_CHAT_ENDPOINTS:
        threading.Thread(target=send_system_resources, daemon=True).start()
        logger.info("System resources thread started")

    if ENABLE_API_ENDPOINTS:
        start_processing_thread()

    logger.info("Starting Flask application")
    socketio.run(app, debug=True, host="0.0.0.0", port=5001)
else:
    # This will run when the module is imported, e.g., by the reloader
    if ENABLE_API_ENDPOINTS:
        start_processing_thread()