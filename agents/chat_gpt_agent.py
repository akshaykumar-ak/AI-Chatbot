import logging
from copy import deepcopy
from typing import Optional, List, Dict, Any

from openai import OpenAI, AsyncOpenAI

# from manager.config_manager import ConfigManager
from models.agent_config import ChatGPTAgentConfig, Message
from utils import getenv


class ChatGptAgent:
    def __init__(
        self,
        agent_config: ChatGPTAgentConfig,
        logger: Optional[logging.Logger] = None,
        messages: Optional[List[Message]] = None,
        # config_manager: ConfigManager = None
    ):
        self.async_openai_client: AsyncOpenAI
        self.openai_client: OpenAI
        self.agent_config = agent_config
        self.messages = messages or []
        self.logger = logger or logging.getLogger(__name__)
        self.openai_api_key = getenv("OPENAI_API_KEY")
        super().__init__()

        self.async_openai_client = AsyncOpenAI(
            api_key=self.openai_api_key
        )

    def format_openai_chat_messages_from_transcript(self) -> List[dict]:
        chat_messages: List[Dict[str, Optional[Any]]] = (
                ([{"role": "system", "content": self.agent_config.prompt_preamble}] if self.agent_config.prompt_preamble else [])
        )

        # merge consecutive bot messages
        new_event_logs = []
        idx = 0
        while idx < len(self.messages):
            bot_messages_buffer: List[Message] = []
            current_log = self.messages[idx]
            while isinstance(current_log, Message) and current_log.sender == "bot":
                bot_messages_buffer.append(current_log)
                idx += 1
                try:
                    current_log = self.messages[idx]
                except IndexError:
                    break
            if bot_messages_buffer:
                merged_bot_message = deepcopy(bot_messages_buffer[-1])
                merged_bot_message.text = " ".join(
                    event_log.text for event_log in bot_messages_buffer
                )
                new_event_logs.append(merged_bot_message)
            else:
                new_event_logs.append(current_log)
                idx += 1

        for event_log in new_event_logs:
            if isinstance(event_log, Message):
                chat_messages.append(
                    {
                        "role": "assistant" if event_log.sender == "bot" else "user",
                        "content": event_log.text,
                    }
                )
        return chat_messages


    def get_chat_parameters(self):
        messages = self.format_openai_chat_messages_from_transcript()
        parameters = {
            "messages": messages,
            "max_tokens": self.agent_config.max_tokens,
            "temperature": self.agent_config.temperature,
            "model": self.agent_config.model_name
        }
        return parameters

    async def generate_response(
        self,
        message: Message
    ):
        self.messages.append(message)
        if message.sender == "bot":
            return None
        chat_parameters = self.get_chat_parameters()
        if chat_parameters.get("engine") and not chat_parameters.get("model"):
            chat_parameters["model"] = chat_parameters["engine"]
            del chat_parameters["engine"]
        chat_completion = await self.async_openai_client.chat.completions.create(**chat_parameters)
        text = chat_completion.choices[0].message.content
        agent_message = Message(sender="bot", text=text)
        self.messages.append(agent_message)
        return text