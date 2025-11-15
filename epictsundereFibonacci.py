import asyncio

import discord
from discord.ext import commands
import yt_dlp
import imageio_ffmpeg
import os

# ====================== CONFIGURAÇÕES ======================



TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN is None:
    print("ERRO: variável de ambiente DISCORD_TOKEN não está definida.")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True  # importante para ler comandos por texto

bot = commands.Bot(command_prefix="!", intents=intents)

# Fila por servidor
queues = {}  # {guild_id: [str(query1), str(query2), ...]}


def get_queue(guild_id: int):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]


# ====================== YT-DLP / FFMPEG ======================

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

FFMPEG_EXECUTABLE = imageio_ffmpeg.get_ffmpeg_exe()

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("webpage_url")

    @classmethod
    async def from_query(cls, query: str, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(query, download=not stream)
        )

        # Se for resultado de busca, pega o primeiro
        if "entries" in data:
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)

        source = discord.FFmpegPCMAudio(
            filename,
            executable=FFMPEG_EXECUTABLE,
            **FFMPEG_OPTIONS,
        )
        return cls(source, data=data)


# ====================== FUNÇÃO PLAY NEXT ======================

async def play_next(ctx: commands.Context):
    """Toca a próxima música da fila, se houver."""
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_connected():
        return

    queue = get_queue(ctx.guild.id)
    if not queue:
        await ctx.send("📭 Fila acabou.")
        return

    query = queue.pop(0)

    try:
        player = await YTDLSource.from_query(query, loop=bot.loop, stream=True)
    except Exception as e:
        await ctx.send("❌ Erro ao carregar a música.")
        print(f"Erro YTDL: {e}")
        # tenta tocar a próxima
        await play_next(ctx)
        return

    def after_playing(error):
        if error:
            print(f"Erro no player: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Erro na fila: {e}")

    voice_client.play(player, after=after_playing)
    await ctx.send(f"▶️ Tocando agora: **{player.title}**\n🔗 {player.url}")


# ====================== EVENTOS ======================

@bot.event
async def on_ready():
    print(f"Bot logado como {bot.user} (ID: {bot.user.id})")
    print("------")


# ====================== COMANDOS ======================

@bot.command(name="join", help="Entra no canal de voz.")
async def join(ctx: commands.Context):
    if ctx.author.voice is None:
        await ctx.send("❌ Você precisa estar em um canal de voz.")
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await channel.connect()
        await ctx.send(f"✅ Entrei em: **{channel}**")
    else:
        await ctx.voice_client.move_to(channel)
        await ctx.send(f"🔄 Movido para: **{channel}**")


@bot.command(name="play", help="Toca uma música do YouTube. Uso: !play <nome ou link>")
async def play(ctx: commands.Context, *, query: str):
    if ctx.author.voice is None and ctx.voice_client is None:
        await ctx.send("❌ Entre em um canal de voz ou use `!join` antes.")
        return

    # Se não estiver conectado ainda, conecta
    if ctx.voice_client is None:
        await join(ctx)

    queue = get_queue(ctx.guild.id)
    queue.append(query)

    await ctx.send(f"➕ Adicionado à fila: **{query}**")

    voice_client = ctx.voice_client
    if not voice_client.is_playing():
        await play_next(ctx)


@bot.command(name="skip", help="Pula a música atual.")
async def skip(ctx: commands.Context):
    if ctx.voice_client is None or not ctx.voice_client.is_playing():
        await ctx.send("❌ Não estou tocando nada.")
        return

    ctx.voice_client.stop()
    await ctx.send("⏭ Música pulada.")


@bot.command(name="stop", help="Para de tocar e limpa a fila.")
async def stop(ctx: commands.Context):
    queue = get_queue(ctx.guild.id)
    queue.clear()

    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()

    await ctx.send("⛔ Parei a música e limpei a fila.")


@bot.command(name="leave", help="Sai do canal de voz.")
async def leave(ctx: commands.Context):
    if ctx.voice_client is None:
        await ctx.send("❌ Não estou em nenhum canal de voz.")
        return

    queue = get_queue(ctx.guild.id)
    queue.clear()

    await ctx.voice_client.disconnect()
    await ctx.send("👋 Saí do canal de voz.")


@bot.command(name="queue", help="Mostra a fila de músicas.")
async def show_queue(ctx: commands.Context):
    queue = get_queue(ctx.guild.id)
    if not queue:
        await ctx.send("📭 A fila está vazia.")
        return

    msg = "📜 **Fila de músicas:**\n"
    for i, item in enumerate(queue, start=1):
        msg += f"{i}. {item}\n"

    await ctx.send(msg)


# ====================== INICIAR O BOT ======================

bot.run(TOKEN)
