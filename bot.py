import os
import json
import discord
from discord import app_commands
from google import genai
from google.genai import types

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GUILD_ID = 1375550312508817518
CHANNEL_ID = 1568978275978715287
# Liste de modèles essayés dans l'ordre (repli automatique en cas de surcharge)
MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.5-flash,"
    "gemini-flash-lite-latest,gemini-flash-latest,gemini-2.5-flash-lite,gemini-2.5-flash"
).split(",") if m.strip()]

SYSTEM_PROMPT = (
    "Tu es un assistant sympa sur un serveur Discord. "
    "Réponds de façon claire et concise, dans la langue de l'utilisateur. "
    "Chaque message d'utilisateur est préfixé par « pseudo (id:NUMÉRO) : ». "
    "Le NUMÉRO identifie de façon unique la personne : deux personnes avec le même pseudo "
    "mais des id différents sont deux personnes différentes. "
    "N'écris jamais ce préfixe dans tes réponses, et n'affiche pas les id sauf si on te le demande."
)

# Instructions personnalisées (sauvegardées dans un fichier).
# Sur Railway, ajoute un Volume monté sur /data et mets INSTRUCTIONS_FILE=/data/instructions.json
# pour qu'elles survivent aux redéploiements.
INSTRUCTIONS_FILE = os.environ.get("INSTRUCTIONS_FILE", "instructions.json")


def load_instructions() -> list[str]:
    try:
        with open(INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_instructions(items: list[str]) -> None:
    d = os.path.dirname(INSTRUCTIONS_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


custom_instructions = load_instructions()


def build_system_prompt() -> str:
    if not custom_instructions:
        return SYSTEM_PROMPT
    extra = "\n".join(f"- {i}" for i in custom_instructions)
    return f"{SYSTEM_PROMPT}\n\nInstructions supplémentaires à suivre impérativement :\n{extra}"


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


instructions_group = app_commands.Group(
    name="instructions",
    description="Gérer la façon dont l'IA répond",
    guild_ids=[GUILD_ID],
    default_permissions=discord.Permissions(administrator=True),
)


@instructions_group.command(name="add", description="Ajoute une instruction")
@app_commands.describe(instructions="Comment l'IA doit répondre")
async def instructions_add(interaction: discord.Interaction, instructions: str):
    custom_instructions.append(instructions.strip())
    save_instructions(custom_instructions)
    await interaction.response.send_message(
        f"✅ Instruction ajoutée ({len(custom_instructions)} au total).", ephemeral=True
    )


@instructions_group.command(name="get", description="Affiche les instructions actuelles")
async def instructions_get(interaction: discord.Interaction):
    if not custom_instructions:
        await interaction.response.send_message("Aucune instruction personnalisée.", ephemeral=True)
        return
    text = "\n".join(f"{n}. {i}" for n, i in enumerate(custom_instructions, 1))
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    await interaction.response.send_message(chunks[0], ephemeral=True)
    for c in chunks[1:]:
        await interaction.followup.send(c, ephemeral=True)


@instructions_group.command(name="remove", description="Supprime toutes les instructions")
async def instructions_remove(interaction: discord.Interaction):
    custom_instructions.clear()
    save_instructions(custom_instructions)
    await interaction.response.send_message("🗑️ Toutes les instructions ont été supprimées.", ephemeral=True)


tree.add_command(instructions_group)


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
            types.Part(text=f"{m.author.display_name} (id:{m.author.id}): {m.content}" if role == "user" else m.content)
        ]))
    history.reverse()
    history.append(types.Content(role="user", parts=[
        types.Part(text=f"{message.author.display_name} (id:{message.author.id}): {message.content}")
    ]))

    async with message.channel.typing():
        text = None
        for model in MODELS:
            try:
                resp = await gemini.aio.models.generate_content(
                    model=model,
                    contents=history,
                    config=types.GenerateContentConfig(system_instruction=build_system_prompt()),
                )
                text = resp.text or "Je n'ai pas de réponse."
                break
            except Exception as e:
                print(f"Erreur Gemini ({model}):", e)
        if text is None:
            text = "⚠️ L'IA est surchargée, réessaie dans un instant."

    for i in range(0, len(text), 1990):
        await message.reply(text[i:i + 1990], mention_author=False)


client.run(DISCORD_TOKEN)

