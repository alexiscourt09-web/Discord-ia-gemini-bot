import os
import discord
from discord import app_commands
from google import genai
from google.genai import types

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GUILD_ID = 1375550312508817518
CHANNEL_ID = 1568978275978715287
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = (
    "Tu es un assistant sympa sur un serveur Discord. "
    "Réponds de façon claire et concise, dans la langue de l'utilisateur."
)

intents = discord.Intents.default()
intents.message_content = True  # à activer aussi dans le portail développeur

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
gemini = genai.Client(api_key=GEMINI_API_KEY)

active = True  # /start et /stop changent cette valeur


@tree.command(name="start", description="Réactive les réponses du bot",
              guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def start(interaction: discord.Interaction):
    global active
    active = True
    await interaction.response.send_message("✅ Bot activé.")


@tree.command(name="stop", description="Arrête les réponses du bot",
              guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def stop(interaction: discord.Interaction):
    global active
    active = False
    await interaction.response.send_message("⏸️ Bot désactivé.")


@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    # Quitte tout serveur non autorisé
    for g in client.guilds:
        if g.id != GUILD_ID:
            await g.leave()
    print(f"Connecté en tant que {client.user}")


@client.event
async def on_guild_join(guild: discord.Guild):
    if guild.id != GUILD_ID:
        await guild.leave()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.channel.id != CHANNEL_ID or not active:
        return
    if not message.content.strip():
        return

    # Contexte : les 100 derniers messages du salon
    history = []
    async for m in message.channel.history(limit=100, before=message):
        role = "model" if m.author == client.user else "user"
        history.append(types.Content(role=role, parts=[
            types.Part(text=f"{m.author.display_name}: {m.content}" if role == "user" else m.content)
        ]))
    history.reverse()
    history.append(types.Content(role="user", parts=[
        types.Part(text=f"{message.author.display_name}: {message.content}")
    ]))

    async with message.channel.typing():
        try:
            resp = await gemini.aio.models.generate_content(
                model=MODEL,
                contents=history,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            text = resp.text or "Je n'ai pas de réponse."
        except Exception as e:
            print("Erreur Gemini:", e)
            text = "⚠️ Erreur avec l'IA, réessaie plus tard."

    for i in range(0, len(text), 1990):
        await message.reply(text[i:i + 1990], mention_author=False)


client.run(DISCORD_TOKEN)
