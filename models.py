import ollama
import structlog

logger = structlog.get_logger()

class ModelManager:
    def __init__(self):
        self.model_capabilities = {
            "ajindal/llama3.1-storm:8b": ["general_knowledge", "reasoning", "tool_calling", "conversation", "multilingual", "instruction_following"],
            "llama3.1:8b": ["general_knowledge", "reasoning", "tool_calling", "conversation", "multilingual", "instruction_following"],
            "qwen2.5:7b": ["general_knowledge", "reasoning", "tool_calling", "conversation", "multilingual", "instruction_following"],
            "llama3.2:3b": ["summarization", "instruction_following", "tool_calling", "multilingual"],
            "llava:7b": ["visual_reasoning", "visual_conversation", "visual_tool_calling", "vision", "ocr", "multimodal"],
        }
        logger.info("ModelManager initialized", model_capabilities=self.model_capabilities)

    def get_model_capabilities(self, model_name):
        capabilities = self.model_capabilities.get(model_name, [])
        logger.debug("Retrieved model capabilities", model=model_name, capabilities=capabilities)
        return capabilities

    def select_best_model(self, required_capability):
        suitable_models = [model for model, capabilities in self.model_capabilities.items() if required_capability in capabilities]
        selected_model = suitable_models[0] if suitable_models else list(self.model_capabilities.keys())[0]
        logger.info("Selected best model", required_capability=required_capability, selected_model=selected_model)
        return selected_model

    def generate_text(self, model_name, prompt, max_length=100, system="You are a helpful assistant.", tools=[]):
        # Check if model exists
        try:
            ollama.pull(model_name)
            logger.debug("Model pulled successfully", model=model_name)
        except ollama.RequestError as e:
            if "not found" in str(e):
                logger.error("Model not found", model=model_name)
                return "Model not found"
            else:
                logger.exception("Error pulling model", model=model_name, error=str(e))
                raise e
            

        response = ollama.generate(model=model_name, prompt=prompt, system=system, tools=tools, max_tokens=max_length)
        logger.debug("Text generated", model=model_name, response=response['response'])
        return response['response']

model_manager = ModelManager()