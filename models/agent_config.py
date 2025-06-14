from datetime import datetime, UTC
from typing import Optional, List

from pydantic import BaseModel, Field


class Message(BaseModel):
    sender: str = "user"
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FunctionFragment(BaseModel):
    name: str
    arguments: str


class ChatGPTAgentConfig(BaseModel):
    prompt_preamble: str
    max_tokens: int = 400
    temperature: float = 0.3
    user_initial_message: Optional[str] = None
    bot_initial_message: Optional[str] = None
    model_name: str = "gpt-4o-mini"


class ClientAgentConfig(BaseModel):
    client_id: str
    config_id: str
    agent_config: ChatGPTAgentConfig
    bot_name: str = "Untitled Bot"


class FetchClientAgentConfig(BaseModel):
    client_id: str
    config_id: str


class ConversationHistory(BaseModel):
    client_id: str
    config_id: str
    bot_name: str
    chat_id: str
    messages: List[Message] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))