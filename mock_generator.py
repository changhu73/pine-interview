import time
import uuid
import random
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class MockResponseConfig:
    """Configuration for mock response generation"""
    min_output_tokens: int = 50
    max_output_tokens: int = 500
    avg_output_tokens: int = 150
    model_name: str = "gpt-3.5-turbo"
    include_usage: bool = True

class MockOpenAIResponseGenerator:
    """Generates realistic mock OpenAI API responses"""
    
    def __init__(self, config: MockResponseConfig = None):
        self.config = config or MockResponseConfig()
        
    def generate_response(
        self,
        request_data: Dict[str, Any],
        api_key: str,
        request_id: str = None
    ) -> Dict[str, Any]:
        """
        Generate a mock OpenAI API response based on the request
        
        Args:
            request_data: The incoming request data (OpenAI format)
            api_key: The API key making the request
            request_id: Optional request ID, generates one if not provided
            
        Returns:
            Mock OpenAI API response
        """
        request_id = request_id or f"mock_req_{uuid.uuid4().hex}"
        
        # Extract request parameters
        model = request_data.get("model", self.config.model_name)
        messages = request_data.get("messages", [])
        max_tokens = request_data.get("max_tokens", 150)
        temperature = request_data.get("temperature", 0.7)
        
        # Calculate input tokens (rough estimation)
        input_tokens = self._estimate_tokens(messages)
        
        # Generate output tokens based on request
        output_tokens = min(
            max_tokens,
            self._generate_output_tokens()
        )
        
        # Generate mock response content
        response_content = self._generate_response_content(
            messages, 
            output_tokens
        )
        
        # Build response
        response = {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
        }
        
        return response
        
    def generate_streaming_response(
        self,
        request_data: Dict[str, Any],
        api_key: str,
        request_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Generate mock streaming OpenAI API response
        
        Returns:
            List of SSE events for streaming response
        """
        request_id = request_id or f"mock_req_{uuid.uuid4().hex}"
        
        # Extract parameters
        model = request_data.get("model", self.config.model_name)
        messages = request_data.get("messages", [])
        max_tokens = request_data.get("max_tokens", 150)
        
        # Calculate tokens
        input_tokens = self._estimate_tokens(messages)
        output_tokens = min(max_tokens, self._generate_output_tokens())
        
        # Generate response content
        response_content = self._generate_response_content(messages, output_tokens)
        
        # Split content into chunks for streaming
        chunks = self._split_into_chunks(response_content, output_tokens)
        
        # Build streaming events
        events = []
        
        # Initial response
        events.append({
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None
            }]
        })
        
        # Content chunks
        for chunk in chunks:
            events.append({
                "id": request_id,
                "object": "chat.completion.chunk", 
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": chunk},
                    "finish_reason": None
                }]
            })
        
        # Final response with usage
        events.append({
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
        })
        
        return events
        
    def _estimate_tokens(self, messages: List[Dict[str, str]]) -> int:
        """Rough token estimation for messages"""
        total_chars = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total_chars += len(item["text"])
        
        # Rough approximation: 1 token ≈ 4 characters
        return max(1, total_chars // 4)
        
    def _generate_output_tokens(self) -> int:
        """Generate realistic output token count"""
        # Use normal distribution around average
        mean = self.config.avg_output_tokens
        std_dev = (self.config.max_output_tokens - self.config.min_output_tokens) // 6
        
        tokens = int(random.gauss(mean, std_dev))
        return max(
            self.config.min_output_tokens,
            min(self.config.max_output_tokens, tokens)
        )
        
    def _generate_response_content(self, messages: List[Dict], target_tokens: int) -> str:
        """Generate mock response content"""
        if not messages:
            return "Hello! I'm a mock AI assistant. How can I help you today?"
            
        # Get the last user message
        last_message = messages[-1]
        user_content = last_message.get("content", "")
        
        # Generate response based on message length and target tokens
        words_per_token = 0.75  # Rough approximation
        target_words = int(target_tokens * words_per_token)
        
        # Create mock response
        response_templates = [
            "I understand you're asking about: {topic}. Let me provide a comprehensive response...",
            "Based on your question regarding {topic}, here's my analysis...",
            "Regarding {topic}, I can share the following insights...",
            "Let me help you with your question about {topic}..."
        ]
        
        template = random.choice(response_templates)
        topic = user_content[:50] + "..." if len(user_content) > 50 else user_content
        
        base_response = template.format(topic=topic)
        
        # Add filler content to reach target length
        filler_sentences = [
            "This is an important consideration in modern applications.",
            "The implications are significant for system design.",
            "Multiple factors should be taken into account.",
            "This approach offers several advantages.",
            "Let me elaborate on this point further.",
            "The technical details are quite fascinating.",
            "This represents a common challenge in the field.",
            "Understanding these concepts is crucial for success."
        ]
        
        current_words = len(base_response.split())
        remaining_words = max(0, target_words - current_words)
        
        filler_content = []
        while len(" ".join(filler_content).split()) < remaining_words:
            filler_content.append(random.choice(filler_sentences))
            
        full_response = base_response + " " + " ".join(filler_content)
        
        # Trim to approximate target
        words = full_response.split()
        if len(words) > target_words:
            words = words[:target_words]
            
        return " ".join(words)
        
    def _split_into_chunks(self, content: str, total_tokens: int) -> List[str]:
        """Split content into chunks for streaming"""
        words = content.split()
        chunks = []
        
        # Create 5-10 chunks
        num_chunks = min(random.randint(5, 10), len(words))
        words_per_chunk = max(1, len(words) // num_chunks)
        
        for i in range(0, len(words), words_per_chunk):
            chunk_words = words[i:i + words_per_chunk]
            chunks.append(" ".join(chunk_words))
            
        return [chunk for chunk in chunks if chunk.strip()]