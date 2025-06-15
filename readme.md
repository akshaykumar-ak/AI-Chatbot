
# 🧠 AI ChatBot Server

A production-ready chatbot server powered by OpenAI's API and built using FastAPI. It features persistent conversation storage using MongoDB and is organized with a clean, modular structure.

---

## 🚀 Features

- 🤖 Chat agent logic powered by OpenAI (GPT)
- 🗃️ MongoDB for storing configuration and conversation history
- ⚡ FastAPI backend for scalability and performance
- 🔧 Uvicorn for local development, Gunicorn for production
- 📦 Environment management via `.env` and `python-dotenv`

---

## 📁 Project Structure

```bash
AI-Chatbot/
├── agents/
│   └── chat_gpt_agent.py       # Chat agent logic
├── models/
│   └── agent_config.py         # Config model and schema
├── .env                        # Environment variables file (not committed)
├── dev-run.sh                  # Uvicorn dev run script
├── gunicorn.conf.py            # Gunicorn production config
├── main.py                     # FastAPI entry point
├── prod-run.sh                 # Gunicorn prod run script
├── readme.md                   # Project documentation
├── requirements.txt            # Python dependencies
└── utils.py                    # Utility functions
```

---

## 🔧 Environment Variables

Create a `.env` file in the root directory with the following required variables:

```env
OPENAI_API_KEY=your-openai-api-key
MONGODB_URI=your-mongodb-uri
MONGODB_DATABASE=your-db-name
CONFIG_COLLECTION=your-config-collection
CONVERSATION_COLLECTION=your-conversations-collection
```

These are loaded at runtime using `load_dotenv()` and validated with assertions:

```python
assert getenv("OPENAI_API_KEY"), "Missing required environment variable: OPENAI_API_KEY"
...
```

---

## 📦 Installation

Clone the repo:

```bash
git clone https://github.com/akshaykumar-ak/AI-Chatbot.git
cd AI-Chatbot
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file as described above.

---

## 🧪 Development

Run the chatbot locally with auto-reload and debugging:

```bash
chmod +x dev-run.sh
./dev-run.sh
```

> This uses `uvicorn` with `--reload` for fast local development.

---

## 🏭 Production

Run the chatbot in production mode using Gunicorn:

```bash
chmod +x prod-run.sh
./prod-run.sh
```

> Ensure `gunicorn.conf.py` is tuned for your server environment.

---

## 📃 API Overview
- `GET /client/list`: Get clients list
- `GET /list/{client_id}`: Get agents lists for a client
- `POST /add_config`: Add or Update client agent config details using client_id and config_id
- `GET /get_config`: Get client agent config details using client_id and config_id
- `WS/WSS /chat/{client_id}/{config_id}/{chat_id}`: Chat with Agent using Websocket.

---

## 🛡️ Best Practices

- Keep your `.env` file private (`.gitignore` it)
- Use HTTPS in production (via a reverse proxy like Nginx)
- Use process managers like `supervisor` or `systemd` for stability
- Monitor logs and configure proper logging in production

---

## 📃 License

MIT License. See `LICENSE` file for full terms.
