import logging
import os
from datetime import datetime, UTC, timedelta
from typing import Dict

import backoff
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Depends
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.models import OpenAPI
from fastapi.security import HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from pymongo.synchronous.collection import Collection
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from agents.chat_gpt_agent import ChatGptAgent
from models.agent_config import Message, ClientAgentConfig, FetchClientAgentConfig, \
    ConversationHistory, User
from utils import getenv

load_dotenv()

mongo_client: Collection = None
mongo_db: Collection = None
config_collection: Collection = None
conversation_collection: Collection = None

API_BASE_PATH = os.getenv("API_BASE_PATH", '')
# fast api app creation

required_env_keys = [
    "OPENAI_API_KEY",
    "MONGODB_URI",
    "MONGODB_DATABASE",
    "CONFIG_COLLECTION",
    "CONVERSATION_COLLECTION",
    "JWT_FAKE_USER",
    "JWT_FAKE_PASSWORD",
    "JWT_SECRET_KEY"
]
def check_system_envs():
    for key in required_env_keys:
        assert getenv(key), f"Missing required environment variable: {key}"

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

oauth2_scheme = HTTPBearer()

def create_jwt_token(data: dict, expires_delta: timedelta = None):
    # things to encode
    to_encode = data.copy()
    # set token expiry
    expire = datetime.now(UTC) + timedelta(days=3600)
    # update token expiry
    to_encode.update({"exp": expire})
    # encode JWT
    encoded_jwt = jwt.encode(
        to_encode, getenv("JWT_SECRET_KEY"), algorithm=getenv("JWT_ALGORITHM", "HS256")
    )
    # return encoded JWT
    return encoded_jwt


# Function to decode and verify the JWT token
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        # get token credentials
        token_credentials = token.credentials
        # decode JWT payload
        payload = jwt.decode(
            token_credentials,
            getenv("JWT_SECRET_KEY"),
            algorithms=[getenv("JWT_ALGORITHM", "HS256")],
        )
        # get username from payload
        username: str = payload.get("sub")
        # if no username invalidate
        if username is None:
            raise HTTPException(status_code=400, detail="Token Invalid")
        return username
    except jwt.exceptions.ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="Token Expired"
        )
    except Exception as e:
        logging.exception(str(e))
        raise HTTPException(status_code=401, detail="Unauthorized")


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


# An API Endpoint to loging in
@chat_router.post("/auth/login", tags=["Authentication"])
async def login(user: User) -> Dict:
    # Fake user password auth
    if (
            user.username == os.environ["JWT_FAKE_USER"]
            and user.password == os.environ["JWT_FAKE_PASSWORD"]
    ):
        # Generate a JWT token for the user.
        token = create_jwt_token({"sub": user.username})
        # return for API Call
        return JSONResponse({"access_token": token, "token_type": "bearer"})
    else:
        # raise exception if user or pass not valid
        raise HTTPException(status_code=401, detail="Invalid credentials")


# An API endpoint to validate User
@chat_router.post("/auth/validate", tags=["Authentication"])
async def validate_token(
        current_user: str = Depends(get_current_user),
) -> Dict:
    return JSONResponse({"detail": "Token Valid", "username": current_user})


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
    config: ClientAgentConfig,
    current_user: str = Depends(get_current_user)
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
async def get_client_config(
    config: FetchClientAgentConfig,
    current_user: str = Depends(get_current_user)
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


@chat_router.get("/client/list")
async def get_client_config(current_user: str = Depends(get_current_user)):
    global config_collection
    try:
        # update db to make sure it is active
        await update_mongo_db()
        unique_clients = await config_collection.distinct("client_id")
        print(unique_clients)
        if not unique_clients:
            return JSONResponse({"error": f"No clients found."}, status_code=400)
        return JSONResponse(unique_clients)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@chat_router.get("/list/{client_id}")
async def get_client_config(
    client_id: str,
    current_user: str = Depends(get_current_user)
):
    global config_collection
    try:
        # update db to make sure it is active
        await update_mongo_db()
        cursor = config_collection.find(
            {"client_id": client_id},
            {"client_id": 1, "config_id": 1, "bot_name": 1, "_id": 0}
        )
        results = await cursor.to_list(length=None)
        if not results:
            return JSONResponse({"error": f"No agents found for client {client_id}"}, status_code=400)
        return JSONResponse(results)
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
        if chat_history:
            chat_history = ConversationHistory.model_validate(chat_history)
            chat_agent = ChatGptAgent(agent_config=agent_config, messages=chat_history.messages)
        else:
            chat_agent = ChatGptAgent(agent_config=agent_config)
        if not chat_history:
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