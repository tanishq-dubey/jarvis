import time

import requests


class LLMChatClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    def submit_query(self, message):
        """
        Submit a query to the LLM Chat Server.

        Args:
            message (str): The message to send to the server.

        Returns:
            str: The query ID for the submitted query.

        Raises:
            requests.RequestException: If the request fails.

        Example:
            client = LLMChatClient('http://localhost:5001', 'your-api-key')
            query_id = client.submit_query('What is the capital of France?')
            print(f"Query ID: {query_id}")

        cURL equivalent:
            curl -X POST http://localhost:5001/api/v1/query \
                 -H "Content-Type: application/json" \
                 -H "X-API-Key: your-api-key" \
                 -d '{"message": "What is the capital of France?"}'
        """
        url = f"{self.base_url}/api/v1/query"
        data = {"message": message}
        response = requests.post(url, json=data, headers=self.headers)
        response.raise_for_status()
        return response.json()["query_id"]

    def get_query_status(self, query_id):
        """
        Get the status of a submitted query.

        Args:
            query_id (str): The ID of the query to check.

        Returns:
            dict: A dictionary containing the status and conversation history (if completed).

        Raises:
            requests.RequestException: If the request fails.

        Example:
            client = LLMChatClient('http://localhost:5001', 'your-api-key')
            status = client.get_query_status('query-id-here')
            print(f"Query status: {status['status']}")
            if status['status'] == 'completed':
                print(f"Conversation history: {status['conversation_history']}")

        cURL equivalent:
            curl -X GET http://localhost:5001/api/v1/query_status/query-id-here \
                 -H "X-API-Key: your-api-key"
        """
        url = f"{self.base_url}/api/v1/query_status/{query_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def submit_query_and_wait(self, message, max_wait_time=300, poll_interval=2):
        """
        Submit a query and wait for the result.

        Args:
            message (str): The message to send to the server.
            max_wait_time (int): Maximum time to wait for the result in seconds.
            poll_interval (int): Time between status checks in seconds.

        Returns:
            dict: The completed conversation history.

        Raises:
            requests.RequestException: If the request fails.
            TimeoutError: If the query doesn't complete within max_wait_time.

        Example:
            client = LLMChatClient('http://localhost:5001', 'your-api-key')
            result = client.submit_query_and_wait('What is the capital of France?')
            print(f"Conversation history: {result}")
        """
        query_id = self.submit_query(message)
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            status = self.get_query_status(query_id)
            if status["status"] == "completed":
                return status["conversation_history"]
            time.sleep(poll_interval)

        raise TimeoutError(f"Query did not complete within {max_wait_time} seconds")


class LLMChatAdminClient:
    def __init__(self, base_url, admin_key):
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        self.headers = {"X-Admin-Key": admin_key, "Content-Type": "application/json"}

    def generate_api_key(self, username):
        """
        Generate a new API key for a user.

        Args:
            username (str): The username to generate the API key for.

        Returns:
            dict: A dictionary containing the username and generated API key.

        Raises:
            requests.RequestException: If the request fails.

        Example:
            admin_client = LLMChatAdminClient('http://localhost:5001', 'your-admin-key')
            result = admin_client.generate_api_key('new_user')
            print(f"Generated API key for {result['username']}: {result['api_key']}")

        cURL equivalent:
            curl -X POST http://localhost:5001/admin/generate_key \
                 -H "Content-Type: application/json" \
                 -H "X-Admin-Key: your-admin-key" \
                 -d '{"username": "new_user"}'
        """
        url = f"{self.base_url}/admin/generate_key"
        data = {"username": username}
        response = requests.post(url, json=data, headers=self.headers)
        response.raise_for_status()
        return response.json()
