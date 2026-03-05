import os
import httpx
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def transcribe_audio(local_path: str) -> str:
    """Transcreve o áudio usando Whisper API."""
    with open(local_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="pt",
        )
    return response.text


async def generate_insights(transcription: str, duration: int, user_name: str) -> str:
    """Gera insights da ligação usando GPT-4o."""
    prompt = f"""Você é um analista de qualidade de vendas da CENAT, empresa de pós-graduação.

Analise a transcrição abaixo de uma ligação comercial e gere um relatório de insights para o gestor.

Atendente: {user_name or 'N/A'}
Duração: {duration}s

Transcrição:
{transcription}

Gere um relatório estruturado com:

1. **Resumo** — O que foi discutido em 2-3 frases.
2. **Tom da conversa** — Positivo / Neutro / Negativo. Justifique.
3. **Interesse do lead** — Alto / Médio / Baixo. Justifique.
4. **Objeções identificadas** — Liste as principais objeções do lead.
5. **Pontos fortes do atendente** — O que foi bem feito.
6. **Pontos de melhoria** — O que pode melhorar.
7. **Próximos passos sugeridos** — Ação recomendada para o atendente.

Seja direto e objetivo. Use bullet points onde necessário."""

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )
    return response.choices[0].message.content