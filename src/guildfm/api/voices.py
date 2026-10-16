"""The voices GuildFM can speak in: OpenAI's, and the ElevenLabs account's own."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from guildfm.auth import ActiveUser
from guildfm.prefs import VOICES

router = APIRouter()


class ElevenVoiceOut(BaseModel):
    id: str  # "elevenlabs:" and the voice's id, as stations and settings store it
    name: str


class VoicesOut(BaseModel):
    openai: list[str]
    elevenlabs: list[ElevenVoiceOut]
    elevenlabs_ready: bool  # whether there's an ElevenLabs key in .env


@router.get("/voices")
async def voices(_: ActiveUser, request: Request) -> VoicesOut:
    speech = request.app.state.speech
    return VoicesOut(
        openai=list(VOICES),
        elevenlabs=[
            ElevenVoiceOut(id=voice.voice, name=voice.name)
            for voice in await speech.eleven_voices()
        ],
        elevenlabs_ready=speech.eleven_ready,
    )
