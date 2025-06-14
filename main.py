import logging
import os
from datetime import datetime, UTC

import backoff
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.models import OpenAPI
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from agents.chat_gpt_agent import ChatGptAgent
from models.agent_config import Message, ClientAgentConfig, FetchClientAgentConfig, \
    ConversationHistory
from utils import getenv

load_dotenv()

mongo_client = None
mongo_db = None
config_collection = None
conversation_collection = None

API_BASE_PATH = os.getenv("API_BASE_PATH", '')
# fast api app creation

def check_system_envs():
    assert getenv("OPENAI_API_KEY"), "Missing required environment variable: OPENAI_API_KEY"
    assert getenv("MONGODB_URI"), "Missing required environment variable: MONGODB_URI"
    assert getenv("MONGODB_DATABASE"), "Missing required environment variable: MONGODB_DATABASE"
    assert getenv("CONFIG_COLLECTION"), "Missing required environment variable: CONFIG_COLLECTION"
    assert getenv("CONVERSATION_COLLECTION"), "Missing required environment variable: CONVERSATION_COLLECTION"


check_system_envs()

app = FastAPI(
    title="ChatBot",
    summary="ChatBot!",
    version='v0.0.1',
    redoc_url=f"{API_BASE_PATH}/redoc",
    docs_url=f"{API_BASE_PATH}/docs",
    openapi_url=f"{API_BASE_PATH}/openapi.json",
    swagger_ui_parameters={
        "displayRequestDuration": True,
        "displayOperationId": True,
        "syntaxHighlight.theme": "agate",
    },
)

# config the origins and handle CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def is_mongo_alive(mongo_client):
    try:
        await mongo_client.admin.command("ping")
        return True
    except ServerSelectionTimeoutError:
        return False


@backoff.on_exception(backoff.expo, ConnectionFailure, max_tries=3, jitter=None)
async def update_mongo_db():
    global mongo_client
    global mongo_db
    global config_collection
    global conversation_collection

    if mongo_client is None or not await is_mongo_alive(mongo_client):
        try:
            mongo_client = AsyncIOMotorClient(getenv("MONGODB_URI"))
            mongo_db = mongo_client[getenv("MONGODB_DATABASE")]
            config_collection = mongo_db[getenv("CONFIG_COLLECTION")]
            conversation_collection = mongo_db[getenv("CONVERSATION_COLLECTION")]
        except ConnectionFailure as e:
            raise


chat_router = APIRouter()

@chat_router.get(f"/openapi.json", response_model=OpenAPI, include_in_schema=False)
async def openapi(request: Request):
    return JSONResponse(app.openapi())


# API for accessing OpenAPI Docs
@chat_router.get("/docs", include_in_schema=False)
def swagger(request: Request):
    client_host = request.client.host
    logging.info(f"[{client_host}] - OpenAPI Specs was hit")
    return get_swagger_ui_html(
        openapi_url=f"{API_BASE_PATH}/openapi.json",
        title="ChatBot",
    )


@chat_router.post("/add_config")
async def insert_client_config(
    config: ClientAgentConfig
):
    global config_collection
    try:
        # update db to make sure it is active
        await update_mongo_db()

        result = await config_collection.update_one(
            {"client_id": config.client_id, "config_id": config.config_id},
            {"$set": {"agent_config": config.agent_config.model_dump(), "bot_name": config.bot_name ,"created_at": datetime.now(UTC)}},
            upsert=True,
        )

        if result.modified_count == 0:
            return {
                "status": "success",
                "status_code": 200,
                "message": "Configuration inserted successfully",
            }
        else:
            return {
                "status": "success",
                "status_code": 200,
                "message": "Configuration updated successfully",
            }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@chat_router.post("/get_config")
async def insert_client_config(
    config: FetchClientAgentConfig
):
    global config_collection
    try:
        # update db to make sure it is active
        await update_mongo_db()
        result = await config_collection.find_one({"client_id": config.client_id, "config_id": config.config_id})
        if not result:
            return JSONResponse({"error": "No such bot config found."}, status_code=400)
        agent_config = ClientAgentConfig.model_validate(result)
        return agent_config
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def start_chat(websocket: WebSocket, client_id: str, config_id: str, chat_id: str):
    global config_collection
    global conversation_collection
    try:
        await websocket.accept()
        await update_mongo_db()
        chat_agent = None
        result = await config_collection.find_one({"client_id": client_id, "config_id": config_id})
        if not result:
            await websocket.close(reason="No such bot config found")
            return
        client_agent_config = ClientAgentConfig.model_validate(result)
        agent_config = client_agent_config.agent_config
        chat_history = await conversation_collection.find_one({"client_id": client_id, "config_id": config_id, "chat_id": chat_id})
        chat_history = ConversationHistory.model_validate(chat_history)
        chat_agent = ChatGptAgent(agent_config=agent_config, messages=chat_history.messages)
        if not chat_history.messages:
            if agent_config.user_initial_message:
                user_initial_message = Message(text=agent_config.user_initial_message)
                bot_response = await chat_agent.generate_response(user_initial_message)
                await websocket.send_text(bot_response)

            if agent_config.bot_initial_message:
                bot_initial_message = Message(sender="bot", text=agent_config.bot_initial_message)
                await chat_agent.generate_response(bot_initial_message)
                await websocket.send_text(agent_config.bot_initial_message)

        while True:
            message = await websocket.receive_text()
            if message:
                user_message = Message(text=message)
                bot_response = await chat_agent.generate_response(user_message)
                await websocket.send_text(bot_response)
    except WebSocketDisconnect:
        conversation_history = ConversationHistory(
            client_id=client_id,
            config_id=config_id,
            chat_id=chat_id,
            bot_name=client_agent_config.bot_name,
            messages=chat_agent.messages
        )
        result = await conversation_collection.update_one(
            {"chat_id": conversation_history.chat_id},
            {"$set": conversation_history.model_dump()},
            upsert=True,
        )


chat_router.websocket("/chat/{client_id}/{config_id}/{chat_id}")(start_chat)
app.include_router(chat_router, prefix=API_BASE_PATH)