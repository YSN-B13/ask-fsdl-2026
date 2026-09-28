"""
Discord bot frontend for askFSDL.

Exposes an ASGI app that:
  - Verifies incoming requests from Discord (Ed25519 signature)
  - Replies to PINGs with PONG
  - Handles /ask slash commands by spawning a background worker that
    queries the askfsdl-backend qanda function and posts the answer back.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from utils import pretty_log
from enum import Enum
import aiohttp
import modal
import json
import os


image = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install(
        "pynacl",      # Ed25519 signature verification for Discord webhooks
        "requests",    # for slash command registration
        "aiohttp",     # for sending deferred responses back to Discord
        "fastapi",     # ASGI app
        "uvicorn",     # ASGI server
    )
    .add_local_python_source("utils")
)

app = modal.App(
    name="askfsdl-discord",
    image=image,
    secrets=[modal.Secret.from_name("discord-secret-fsdl")],
)


class DiscordInteractionType(Enum):
    PING = 1                    # hello from Discord
    APPLICATION_COMMAND = 2     # an actual command


class DiscordResponseType(Enum):
    PONG = 1                                    # hello back
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5    # we'll send a message later


class DiscordApplicationCommandOptionType(Enum):
    STRING = 3    # with language models, strings are all you need


@app.function(min_containers=1)
@modal.asgi_app()
def asgi():
    """The Discord webhook endpoint, wrapped in a FastAPI app.

    min_containers=1 keeps one container warm so Discord's 3-second
    interaction timeout doesn't kick in during cold starts.
    """
    web_app = FastAPI()

    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @web_app.post("/")
    async def handle_request(request: Request):
        """Verify the incoming request and, if valid, spawn a response."""
        body = await verify(request)
        data = json.loads(body.decode())

        if data.get("type") == DiscordInteractionType.PING.value:
            return {"type": DiscordResponseType.PONG.value}

        if data.get("type") == DiscordInteractionType.APPLICATION_COMMAND.value:
            application_id = data["application_id"]
            interaction_token = data["token"]
            user_id = data["member"]["user"]["id"]
            question = data["data"]["options"][0]["value"]

            pretty_log(question)

            # Kick off the real response in the background; reply immediately.
            respond.spawn(question, application_id, interaction_token, user_id)

            return {
                "type": DiscordResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE.value
            }

        raise HTTPException(status_code=400, detail="Bad request")

    return web_app


@app.function()
async def respond(
    question: str,
    application_id: str,
    interaction_token: str,
    user_id: str,
):
    """Query the backend and post the answer back to Discord."""
    try:
        qanda = modal.Function.from_name("askfsdl-backend", "qanda")
        raw_response = await qanda.remote.aio(
            question, request_id=interaction_token
        )
        pretty_log(raw_response)
        response = construct_response(raw_response, user_id, question)
    except Exception as e:
        pretty_log(f"Error: {e}")
        response = construct_error_message(user_id)

    await send_response(response, application_id, interaction_token)



async def send_response(
    response: str,
    application_id: str,
    interaction_token: str,
):
    """Posts the final message to the Discord interaction webhook."""
    url = f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}"
    payload_json = json.dumps({"content": response})

    form = aiohttp.FormData()
    form.add_field("payload_json", payload_json, content_type="application/json")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form) as resp:
            await resp.text()


async def verify(request: Request) -> bytes:
    """Verifies the Ed25519 signature on an incoming Discord request.

    Discord refuses to interact with apps that accept unsigned requests,
    so this must reject bad signatures with a 401.
    """
    public_key = os.environ["DISCORD_PUBLIC_KEY"]
    verify_key = VerifyKey(bytes.fromhex(public_key))

    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body = await request.body()

    if signature is None or timestamp is None:
        raise HTTPException(status_code=401, detail="Missing signature headers")

    message = timestamp.encode() + body
    try:
        verify_key.verify(message, bytes.fromhex(signature))
    except BadSignatureError:
        raise HTTPException(status_code=401, detail="Invalid request") from None

    return body


def construct_response(raw_response: str, user_id: str, question: str) -> str:
    """Wraps the backend's answer in a friendly Discord message."""
    rating_emojis = {
        "👍": "if the response was helpful",
        "👎": "if the response was not helpful",
    }
    emoji_reaction_text = " or ".join(
        f"react with {emoji} {reason}" for emoji, reason in rating_emojis.items()
    )
    emoji_reaction_text = emoji_reaction_text.capitalize() + "."

    return (
        f"<@{user_id}> asked: _{question}_\n\n"
        f"Here's my best guess at an answer, with sources so you can follow up:\n\n"
        f"{raw_response}\n\n"
        f"Emoji react to let us know how we're doing!\n\n"
        f"{emoji_reaction_text}\n"
    )


def construct_error_message(user_id: str) -> str:
    """Apologetic message shown when the backend fails."""
    message = f"*Sorry <@{user_id}>, an error occurred while answering your question."

    maintainer_id = os.environ.get("DISCORD_MAINTAINER_ID")
    if maintainer_id:
        message += f" I've let <@{maintainer_id}> know."
    else:
        pretty_log("No maintainer ID set")
        message += " Please try again later."

    return message + "*"


@app.function()
def create_slash_command(force: bool = False):
    """Registers the /ask slash command with Discord.

    Pass force=True to re-register even if it already exists.
    """
    import requests

    bot_token = os.environ["DISCORD_AUTH"]
    client_id = os.environ["DISCORD_CLIENT_ID"]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bot {bot_token}",
    }
    url = f"https://discord.com/api/v10/applications/{client_id}/commands"

    command_description = {
        "name": "ask",
        "description": "Ask a question about anything covered by Full Stack",
        "options": [
            {
                "name": "question",
                "description": "A question about LLMs, building AI applications, etc.",
                "type": DiscordApplicationCommandOptionType.STRING.value,
                "required": True,
                "max_length": 200,
            }
        ],
    }

    # Check what's already registered.
    response = requests.get(url, headers=headers, timeout=30)
    try:
        response.raise_for_status()
    except Exception as e:
        raise Exception("Failed to fetch existing slash commands") from e

    commands = response.json()
    if any(cmd.get("name") == "ask" for cmd in commands) and not force:
        print("slash command /ask already registered; pass force=True to re-create")
        return

    # Register (or re-register).
    response = requests.post(
        url, headers=headers, json=command_description, timeout=30
    )
    try:
        response.raise_for_status()
    except Exception as e:
        raise Exception("Failed to create slash command") from e

    print("slash command /ask registered")
