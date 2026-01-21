import discord
from discord.ext import commands
import random
import sqlite3
import time
import asyncio
from typing import List, Tuple, Optional, Dict
import re
from dataclasses import dataclass

# ======================
# CONFIG
# ======================

PITY_LEGENDARY_ROLLS = 50

ITENS_POR_PAGINA = 18
DAILY_COOLDOWN = 86400

ROLL_COOLDOWN_SECONDS = 2          # (não usado ainda)
ROLLS_PER_HOUR_LIMIT = 120         # (não usado ainda)

# Loja

PRECO_GIRO = 250

PRECO_POCAO_LUCKY = 2500
PRECO_POCAO_BELI  = 1750

POCAO_LUCKY_MULT = 1.5
POCAO_BELI_MULT  = 2.0

POCAO_DURATION = 5 * 60  # 5 min


# ======================
# EVENTOS (CONFIG)
# ======================

EVENT_CHECK_EVERY_SECONDS = 20 * 60     # 30 min
EVENT_MIN_GAP_SECONDS = 0              # sem gap extra (você pediu 20% a cada meia hora)
EVENT_DURATION_RANGE = (5 * 60, 5 * 60)    # 1 a 5 min (nunca passa de 5)

# Probabilidades quando um evento nasce:
# both 20%, beli 35%, lucky 35%
EVENT_TYPES = [
    ("both", 20),
    ("beli", 35),
    ("lucky", 35),
]

# Multiplicadores
EVENT_MULTS = {
    "lucky": (2.0, 1.0),
    "beli":  (1.0, 2.0),
    "both":  (2.0, 2.0),
    "jjk_secret": (4.0, 2.0),  # ✅ 4x lucky e 2x beli
}

SECRET_JJK_GIF_IMPACT_URL = "https://media.discordapp.net/attachments/953094648354726019/1463280107232690280/EGZWiC.gif?ex=6971414b&is=696fefcb&hm=f0bb08b7c0aed2af607243fbc25074bd21f131d8eb303d81560a613f7b483bb9&="
SECRET_JJK_GIF_URL = "https://media.discordapp.net/attachments/953094648354726019/1463276756755546270/222779.gif?ex=69713e2d&is=696fecad&hm=01091a490bca72ead7c37bfbc7217dc6420ad6aa84171eec7e0a8160ae7dddb4&="  # coloque seu gif aqui


# onde anunciar (se None, anuncia no canal do comando que disparar)
DEFAULT_EVENT_CHANNEL_ID = 1462631540876906658  # coloque um ID se quiser fixo

# ======================
# INTENTS / BOT
# ======================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ LOCKS (coloque aqui)
USER_LOCKS: Dict[str, asyncio.Lock] = {}
LOCK_WARNED: set[str] = set()

# ======================
# MINIGAMES (TRABALHOS)
# ======================
# 🧬 Código Corrompido (corrida no chat) — a cada 30 minutos (5 min para responder)
# ⚖️ Higuruma (server-wide + botão + desafio individual) — spawn configurável
#
# IMPORTANTE:
# - Código Corrompido: 1 vencedor no canal de minigames.
# - Higuruma: cada jogador entra por botão e responde via modal (ephemeral), sem sujar o chat.

MINIGAMES_CHANNEL_ID = 1463339717763399731
HIGURUMA_CHANNEL_ID = 1463339515648282654
HIGURUMA_GIF_URL = "https://media.discordapp.net/attachments/953094648354726019/1463340267515019390/Higuruma_Hiromi_Hiromi_Higuruma_GIF_-_Higuruma_Hiromi_Hiromi_Higuruma_Hiromi_-_GIF.gif?ex=69717953&is=697027d3&hm=5736d87bec074cf54018daf86a051f8eda3a881b25f124609030835e66f50657&="

# loops
CORRUPTED_SPAWN_EVERY = 30 * 60
HIGURUMA_SPAWN_EVERY = 60 * 60  # ajuste se quiser

# tempos
CORRUPTED_TIME_LIMIT = 5 * 60  # 5 min para alguém acertar
HIGURUMA_TIME_LIMIT_SECONDS = 60  # 1 minuto fixo para cada pessoa responder
HIGURUMA_ENTRY_WINDOW_SECONDS = 5 * 60  # após 5 min do spawn, ninguém mais entra

# views
HIGURUMA_ENTRY_VIEW_TIMEOUT = float(HIGURUMA_ENTRY_WINDOW_SECONDS)  # botão de entrar fica 5 min
HIGURUMA_ANSWER_VIEW_TIMEOUT = 90.0  # tempo extra pro usuário clicar/abrir modal

# um pequeno "grace" pra não punir lag / delay de render
HIGURUMA_GRACE_SECONDS = 2


# custo/penalidade do julgamento
HIGURUMA_ENTRY_REQUIRE_GIROS = 5
HIGURUMA_ENTRY_REQUIRE_BELI = 1000
HIGURUMA_FAIL_PENALTY_GIROS = 5
HIGURUMA_FAIL_PENALTY_BELI = 1000

# item de proteção do julgamento
KAMUTOKE_ITEM_KEY = "kamutoke"
KAMUTOKE_DISPLAY_NAME = "Kamutoke"

# preço do Kamutoke na loja (ajuste livre)
KAMUTOKE_PRICE_BELI = 12000
KAMUTOKE_PRICE_ESSENCE_KEY = "essence_epic"
KAMUTOKE_PRICE_ESSENCE_QTY = 25

# imagem do embed quando o Kamutoke quebra (anula penalidade)
KAMUTOKE_BREAK_IMAGE_URL = "https://media.discordapp.net/attachments/953094648354726019/1463381838419591417/6e485b5a-bfa4-4cf8-ba67-433c2d9c6e03.png?format=webp&quality=lossless"

# auto-delete do anúncio do Higuruma (e mensagens do bot no tribunal)
HIGURUMA_ANNOUNCE_AUTO_DELETE_SECONDS = int(HIGURUMA_ENTRY_WINDOW_SECONDS)

# ==========
# Helpers
# ==========

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    flags=re.UNICODE
)

def has_emoji(s: str) -> bool:
    return bool(EMOJI_RE.search(s))

def word_count(s: str) -> int:
    parts = [p for p in s.strip().split() if p]
    return len(parts)

def normalize_spaces(s: str) -> str:
    return " ".join(s.strip().split())

def _safe_grant(uid: str, beli: int = 0, giros: int = 0) -> bool:
    """Recompensa atômica. Retorna True se commit ok."""
    try:
        if beli <= 0 and giros <= 0:
            return True
        get_user(uid)
        begin_immediate_with_retry()
        cursor.execute(
            "UPDATE users SET beli = beli + ?, giros = giros + ? WHERE user_id = ?",
            (int(beli), int(giros), str(uid))
        )
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def _safe_penalize(uid: str, beli: int = 0, giros: int = 0) -> bool:
    """Penaliza (remove) beli/giros de forma atômica. Usa valores POSITIVOS como quantidade a remover."""
    if beli <= 0 and giros <= 0:
        return True
    try:
        begin_immediate_with_retry()
        cursor.execute("SELECT beli, giros FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        if not row:
            get_user(uid)
            cursor.execute("SELECT beli, giros FROM users WHERE user_id = ?", (uid,))
            row = cursor.fetchone()
        cur_beli, cur_giros = int(row[0]), int(row[1])

        # Como a entrada exige saldo mínimo, aqui normalmente já tem.
        # Ainda assim, protege contra negativo.
        new_beli = max(0, cur_beli - int(beli))
        new_giros = max(0, cur_giros - int(giros))

        cursor.execute(
            "UPDATE users SET beli = ?, giros = ? WHERE user_id = ?",
            (new_beli, new_giros, uid)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False

# ======================
# HIGURUMA — RECOMPENSAS
# ======================

HIGURUMA_SECRET_CHANCE = 0.005  # 0.5%
HIGURUMA_SECRET_GIROS = 30
HIGURUMA_SECRET_BELI = 5000

def _higuruma_roll_reward() -> Tuple[int, int, bool]:
    """Retorna (giros, beli, is_secret)."""
    if random.random() < float(HIGURUMA_SECRET_CHANCE):
        return (int(HIGURUMA_SECRET_GIROS), int(HIGURUMA_SECRET_BELI), True)
    return (random.randint(3, 10), random.randint(500, 1500), False)

async def _higuruma_secret_cinematic(interaction: discord.Interaction, giros: int, beli: int):
    """Cinemática exclusiva para a recompensa secreta (ephemeral)."""
    e1 = discord.Embed(
        title="🩸⚖️ SENTENÇA RARA — ECO DO VOTO",
        description="O tribunal **quebrou a própria lei** por um instante…",
        color=discord.Color.dark_red()
    )
    if HIGURUMA_GIF_URL:
        e1.set_image(url=HIGURUMA_GIF_URL)
    e1.set_footer(text="⛓️ Algo impossível aconteceu.")

    await interaction.response.send_message(embed=e1, ephemeral=True)
    msg = await interaction.original_response()

    await asyncio.sleep(0.9)
    e2 = discord.Embed(
        title="🌑 O SILÊNCIO DO TRIBUNAL",
        description="Você ouviu um **eco** atravessando o servidor…\n\n**Recompensa secreta detectada.**",
        color=discord.Color.purple()
    )
    if HIGURUMA_GIF_URL:
        e2.set_image(url=HIGURUMA_GIF_URL)
    e2.set_footer(text="⚠️ 0.5% — evento ultra raro")
    await msg.edit(embed=e2)

    await asyncio.sleep(1.1)
    e3 = discord.Embed(
        title="✨ ECO DO VOTO — CONCEDIDO",
        description=f"🎟️ **+{giros} giros**\n💰 **+{fmt_currency(beli)} beli**\n\nO tribunal marcou seu nome.",
        color=discord.Color.gold()
    )
    if HIGURUMA_GIF_URL:
        e3.set_image(url=HIGURUMA_GIF_URL)
    e3.set_footer(text="🔒 Cinemática exclusiva do Eco do Voto")
    await msg.edit(embed=e3)

    # aplica a recompensa aqui (garante que o usuário não perca por erro no meio)
    _safe_grant(str(interaction.user.id), beli=beli, giros=giros)

# =========================================================
# 1) CÓDIGO CORROMPIDO — corrida (1 vencedor)
# =========================================================

@dataclass
class CorruptedState:
    active: bool
    channel_id: int
    start_ts: int
    end_ts: int
    corrupted: str
    clean: str
    winner_id: Optional[str] = None
    msg_id: Optional[int] = None

CORRUPTED_WORD_BANK = [
    "SANTUARIO MALEVOLENTE",
    "VOTO VINCULANTE",
    "SENTENCA ABSOLUTA",
    "DOMINIO PROIBIDO",
    "LEI DO DESTINO",
    "TRIBUNAL AMALDICOADO",
    "SENTENCA IMUTAVEL",
    "CONDENACAO ETERNA",
]

CORRUPTED_STATE: Dict[int, CorruptedState] = {}

def corrupt_text_hard(clean: str) -> str:
    # usa teu glitch existente (se já tiver), senão faz um fallback simples
    try:
        t = clean
        for _ in range(3):
            t = _glitch(t)  # teu efeito (já existe no bot)
        t = t.replace(" ", random.choice(["  ", "   ", " • ", "  ░  "]))
        return t
    except Exception:
        mapa = str.maketrans({"A":"Δ","E":"Ξ","I":"Ι","O":"0","S":"$","T":"Τ"})
        return clean.translate(mapa)

async def spawn_corrupted_word(guild: discord.Guild):
    if not guild:
        return
    ch = guild.get_channel(int(MINIGAMES_CHANNEL_ID)) if MINIGAMES_CHANNEL_ID else None
    if ch is None:
        return

    st = CORRUPTED_STATE.get(guild.id)
    if st and st.active and now_ts() < st.end_ts:
        return  # não sobrepõe um ativo

    clean = random.choice(CORRUPTED_WORD_BANK)
    corrupted = corrupt_text_hard(clean)

    now = now_ts()
    state = CorruptedState(
        active=True,
        channel_id=ch.id,
        start_ts=now,
        end_ts=now + int(CORRUPTED_TIME_LIMIT),
        corrupted=corrupted,
        clean=clean,
        winner_id=None
    )
    CORRUPTED_STATE[guild.id] = state

    embed = discord.Embed(
        title="🧬 CÓDIGO CORROMPIDO — CORRIDA",
        description=(
            "Uma palavra foi corrompida. **Só 1 pessoa** vence.\n"
            "Digite a versão **LIMPA** exatamente como deveria ser.\n\n"
            f"🧩 **Código:**\n`{corrupted}`\n\n"
            f"⏳ Tempo: **{int(CORRUPTED_TIME_LIMIT)}s**\n"
            "📌 Responda **neste canal**."
        ),
        color=discord.Color.dark_red()
    )
    embed.set_footer(text="⚠️ Primeiro que limpar leva a recompensa.")
    msg = await ch.send(embed=embed)
    state.msg_id = msg.id

async def end_corrupted_if_needed(guild: discord.Guild):
    st = CORRUPTED_STATE.get(guild.id)
    if not st or not st.active:
        return
    if now_ts() < st.end_ts:
        return

    st.active = False
    ch = guild.get_channel(st.channel_id)
    if not ch:
        return

    if st.winner_id:
        return

    embed = discord.Embed(
        title="🧬 CÓDIGO CORROMPIDO — FIM",
        description=(
            "⛓️ O código colapsou… ninguém limpou a tempo.\n\n"
            f"✅ Resposta era: **{st.clean}**"
        ),
        color=discord.Color.dark_grey()
    )
    await ch.send(embed=embed)

# =========================================================
# 2) HIGURUMA — server-wide + botão + desafio individual (SEM ROLL)
# =========================================================

@dataclass
class TrialTask:
    kind: str
    channel_id: int
    duration_s: int
    start_ts: int = 0
    end_ts: int = 0
    armed: bool = False
    rules: Dict[str, object] = None
    prompt: str = ""
    rules_text: str = ""

TRIAL_PARTICIPANTS: Dict[Tuple[int, str], TrialTask] = {}

# guarda o estado do evento por guild (pra fechar entrada após 5 min)
HIGURUMA_EVENT_WINDOW: Dict[int, Dict[str, int]] = {}  # guild_id -> {"spawn_ts":..., "close_ts":...}
HIGURUMA_EVENT_ID: Dict[int, int] = {}  # guild_id -> spawn_ts (id do evento)
HIGURUMA_EVENT_PARTICIPATED: Dict[Tuple[int, str], int] = {}  # (guild_id, user_id) -> event_id


def _make_trial(channel_id: int) -> TrialTask:
    """Gera desafios variados (somente resposta por texto; sem comandos)."""
    duration = int(HIGURUMA_TIME_LIMIT_SECONDS)

    # 1) resposta exata (frase curta)
    exact_bank = [
        "o voto foi aceito",
        "sentença aplicada",
        "tribunal aberto",
        "lei absoluta",
        "culpado",
        "inocente",
    ]

    # 2) perguntas de lógica/atenção simples
    logic_bank = [
        ("Qual é a **próxima letra** na sequência: A C E ?", "g"),
        ("Qual é a **próxima letra** na sequência: B D F ?", "h"),
        ("Complete: 1 2 4 8 __", "16"),
        ("Escreva ao contrário: **voto**", "otov"),
        ("Quantas letras tem a palavra **tribunal**? (apenas número)", "8"),
        ("Quantas letras tem a palavra **higuruma**? (apenas número)", "8"),
    ]

    # 3) continhas mentais (até médio, rápidas)
    def make_math():
        mode = random.choice(["add", "sub", "mix", "mul", "percent"])
        if mode == "add":
            a = random.randint(12, 89); b = random.randint(11, 79)
            return (f"Calcule: **{a} + {b}** (apenas número)", str(a + b))
        if mode == "sub":
            a = random.randint(40, 120); b = random.randint(10, min(70, a-1))
            return (f"Calcule: **{a} - {b}** (apenas número)", str(a - b))
        if mode == "mul":
            a = random.randint(6, 15); b = random.randint(3, 12)
            return (f"Calcule: **{a} × {b}** (apenas número)", str(a * b))
        if mode == "percent":
            base = random.choice([100, 200, 300, 400, 500, 600, 800, 1000])
            pct = random.choice([10, 20, 25, 50])
            return (f"Quanto é **{pct}% de {base}**? (apenas número)", str(int(base * pct / 100)))
        # mix
        a = random.randint(10, 30); b = random.randint(10, 30); c = random.randint(5, 20)
        return (f"Calcule: **({a} + {b}) - {c}** (apenas número)", str((a + b) - c))

    # 4) restrição total (texto livre, mas ainda é "pergunta")
    def make_restriction():
        banned_letter = random.choice(["a", "e", "o", "s", "r", "m", "t"])
        exact_words = random.choice([3, 4, 5])
        prompt = "Responda com **UMA frase válida**."
        rules = {
            "type": "restriction",
            "exact_words": exact_words,
            "banned_letter": banned_letter,
            "no_upper": True,
            "no_emoji": True,
            "no_digits": True,
        }
        rules_text = "\n".join([
            f"• ❌ Exatamente **{exact_words} palavras**",
            "• ❌ Tudo em minúsculo",
            f'• ❌ Não usar a letra **"{banned_letter}"**',
            "• ❌ Não usar números",
            "• ❌ Não usar emojis",
        ])
        return TrialTask("restriction", channel_id, duration, prompt=prompt, rules=rules, rules_text=rules_text)

    pick = random.random()
    if pick < 0.28:
        phrase = random.choice(exact_bank)
        return TrialTask(
            "exact",
            channel_id,
            duration,
            prompt=f'Digite exatamente: **{phrase}**',
            rules={"type": "exact", "expected": phrase},
            rules_text="• ❌ Não alterar nada\n• ❌ Sem aspas\n• ❌ Tudo em minúsculo",
        )

    if pick < 0.58:
        q, ans = random.choice(logic_bank)
        return TrialTask(
            "qa",
            channel_id,
            duration,
            prompt=q,
            rules={"type": "qa", "expected": ans},
            rules_text="• ✔️ Responda exatamente\n• ✔️ Sem emojis",
        )

    if pick < 0.82:
        q, ans = make_math()
        return TrialTask(
            "math",
            channel_id,
            duration,
            prompt=q,
            rules={"type": "math", "expected": ans},
            rules_text="• ✔️ Apenas número\n• ❌ Sem espaços",
        )

    return make_restriction()

def _trial_time_left(task: TrialTask) -> int:
    if not task.armed:
        return max(0, int(task.duration_s))
    return max(0, int(task.end_ts - now_ts()))

def _trial_expired(task: TrialTask) -> bool:
    if not task.armed:
        return False
    return now_ts() > task.end_ts + int(HIGURUMA_GRACE_SECONDS)

def _check_trial_answer(task: TrialTask, content: str) -> bool:
    s = (content or "").strip()

    if has_emoji(s):
        return False

    rule_type = (task.rules or {}).get("type")

    if rule_type == "exact":
        return normalize_spaces(s) == normalize_spaces(str(task.rules.get("expected", "")))

    if rule_type == "qa":
        # normaliza minúsculo e espaços
        expected = normalize_spaces(str(task.rules.get("expected", ""))).lower()
        got = normalize_spaces(s).lower()
        return got == expected

    if rule_type == "math":
        # apenas número (aceita +/-, mas sem espaços)
        if " " in s:
            return False
        if not re.fullmatch(r"-?\d+", s):
            return False
        return s == str(task.rules.get("expected", ""))

    if rule_type == "restriction":
        if s.startswith("!"):
            return False
        if any(c.isupper() for c in s):
            return False
        if any(ch.isdigit() for ch in s):
            return False
        if word_count(s) != int(task.rules.get("exact_words", 0)):
            return False
        banned = str(task.rules.get("banned_letter", ""))
        if banned and banned in s:
            return False
        return True

    return False

class TrialAnswerModal(discord.ui.Modal):
    def __init__(self, guild_id: int, user_id: str):
        super().__init__(title="⚖️ Julgamento — Resposta")
        self.guild_id = guild_id
        self.user_id = user_id
        self.answer = discord.ui.TextInput(
            label="Digite sua resposta",
            style=discord.TextStyle.short,
            required=True,
            max_length=120
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        key = (self.guild_id, self.user_id)
        task = TRIAL_PARTICIPANTS.get(key)
        if not task:
            await interaction.response.send_message("⚠️ Seu julgamento não está mais ativo.", ephemeral=True)
            return

        if _trial_expired(task):
            TRIAL_PARTICIPANTS.pop(key, None)
            await interaction.response.send_message("❌ Tempo esgotado. O voto foi quebrado.", ephemeral=True)
            return

        content = str(self.answer.value or "").strip()

        ok = _check_trial_answer(task, content)
        
        if not ok:
            TRIAL_PARTICIPANTS.pop(key, None)

            # Se tiver Kamutoke, ele salva a penalidade (consome 1)
            used_kamutoke = False
            if get_consumable_qty(self.user_id, KAMUTOKE_ITEM_KEY) > 0:
                used_kamutoke = consume_consumable(self.user_id, KAMUTOKE_ITEM_KEY, 1)

            if used_kamutoke:
                # cinemática exclusiva (ephemeral)
                e1 = discord.Embed(
                    title="⚡ KAMUTOKE — INTERVENÇÃO",
                    description="❌ Resposta inválida…\nMas um trovão cortou o tribunal antes da sentença.",
                    color=discord.Color.gold()
                )
                if HIGURUMA_GIF_URL:
                    e1.set_image(url=HIGURUMA_GIF_URL)
                e1.set_footer(text="O item foi consumido para anular a penalidade.")

                await interaction.response.send_message(embed=e1, ephemeral=True)
                try:
                    msg = await interaction.original_response()
                    await asyncio.sleep(0.9)
                    e2 = discord.Embed(
                        title="⚡ KAMUTOKE — QUEBRA DO JULGAMENTO",
                        description=("O **Kamutoke** se partiu em faíscas.\nA punição foi **anulada** desta vez.\n\n✅ Você **não** perdeu giros nem beli."),
                        color=discord.Color.gold()
                    )
                    e2.set_footer
                    if KAMUTOKE_BREAK_IMAGE_URL:
                        e2.set_image(url=KAMUTOKE_BREAK_IMAGE_URL)

                    e2.set_footer(text="💀 Da próxima vez, não haverá misericórdia.")
                    await msg.edit(embed=e2)
                except Exception:
                    pass
                return

            # sem Kamutoke → penalidade padrão
            _safe_penalize(self.user_id, beli=HIGURUMA_FAIL_PENALTY_BELI, giros=HIGURUMA_FAIL_PENALTY_GIROS)
            await interaction.response.send_message(
                f"❌ Resposta inválida. O voto foi quebrado.\n"
                f"💸 Penalidade: -{HIGURUMA_FAIL_PENALTY_GIROS} giros | -{fmt_currency(HIGURUMA_FAIL_PENALTY_BELI)} beli",
                ephemeral=True
            )
            return

        # sucesso
        TRIAL_PARTICIPANTS.pop(key, None)

        giros, beli, secret = _higuruma_roll_reward()
        _safe_grant(self.user_id, beli=beli, giros=giros)

        if secret:
            await _higuruma_secret_cinematic(interaction, giros, beli)
            return

        await interaction.response.send_message(
            f"✅ Voto aceito.\n🎟️ +{giros} giros | 💰 +{fmt_currency(beli)} beli",
            ephemeral=True
        )

class TrialActionView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: str):
        super().__init__(timeout=float(HIGURUMA_ANSWER_VIEW_TIMEOUT))
        self.guild_id = guild_id
        self.user_id = user_id

    async def _get_task(self, interaction: discord.Interaction) -> Optional[TrialTask]:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("❌ Esse julgamento não é seu.", ephemeral=True)
            return None
        key = (self.guild_id, self.user_id)
        task = TRIAL_PARTICIPANTS.get(key)
        if not task:
            await interaction.response.send_message("⚠️ Seu julgamento não está mais ativo.", ephemeral=True)
            return None
        if _trial_expired(task):
            TRIAL_PARTICIPANTS.pop(key, None)
            await interaction.response.send_message("❌ Tempo esgotado. O voto foi quebrado.", ephemeral=True)
            return None
        return task

    @discord.ui.button(label="✍️ Responder", style=discord.ButtonStyle.primary)
    async def answer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        task = await self._get_task(interaction)
        if not task:
            return
        await interaction.response.send_modal(TrialAnswerModal(self.guild_id, self.user_id))

class HigurumaEnterView(discord.ui.View):
    def __init__(self, guild_id: int, channel_id: int):
        super().__init__(timeout=float(HIGURUMA_ENTRY_VIEW_TIMEOUT))
        self.guild_id = guild_id
        self.channel_id = channel_id

    @discord.ui.button(label="⚖️ Entrar no Julgamento", style=discord.ButtonStyle.danger)
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user or not interaction.guild:
            return

        # janela do evento (5 min após o spawn)
        window = HIGURUMA_EVENT_WINDOW.get(interaction.guild.id)
        if not window or now_ts() > int(window.get("close_ts", 0)):
            await interaction.response.send_message("⛓️ O tribunal já fechou as portas. Chegou tarde demais.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        key = (interaction.guild.id, uid)

        # ✅ 1x por evento (mesmo se terminar rápido)
        event_id = int(window.get("spawn_ts", 0) or 0)
        if event_id and HIGURUMA_EVENT_PARTICIPATED.get(key) == event_id:
            await interaction.response.send_message("⚠️ Você já participou deste tribunal. Aguarde o próximo spawn.", ephemeral=True)
            return

        if key in TRIAL_PARTICIPANTS:
            await interaction.response.send_message("⚠️ Você já está em um julgamento ativo.", ephemeral=True)
            return


        # requisitos para participar
        cursor.execute("SELECT giros, beli FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        if not row:
            get_user(uid)
            cursor.execute("SELECT giros, beli FROM users WHERE user_id = ?", (uid,))
            row = cursor.fetchone()
        giros_now, beli_now = int(row[0]), int(row[1])

        if giros_now < HIGURUMA_ENTRY_REQUIRE_GIROS or beli_now < HIGURUMA_ENTRY_REQUIRE_BELI:
            await interaction.response.send_message(
                f"❌ Para entrar no julgamento você precisa ter **{HIGURUMA_ENTRY_REQUIRE_GIROS} giros** e **{fmt_currency(HIGURUMA_ENTRY_REQUIRE_BELI)} beli**.\n"
                f"Você tem: 🎟️ {giros_now} giros | 💰 {fmt_currency(beli_now)} beli.",
                ephemeral=True
            )
            return


        # marca participação imediatamente (evita farmar múltiplas tentativas dentro dos 5min)
        if event_id:
            HIGURUMA_EVENT_PARTICIPATED[key] = event_id

        task = _make_trial(self.channel_id)
        # arma o relógio APÓS a cinemática
        task.armed = False
        TRIAL_PARTICIPANTS[key] = task

        embed = discord.Embed(
            title="⚖️ JULGAMENTO DO VOTO — HIGURUMA",
            description="O tribunal abriu…\nA sentença será aplicada **sem piedade**.",
            color=discord.Color.dark_red()
        )
        if HIGURUMA_GIF_URL:
            embed.set_image(url=HIGURUMA_GIF_URL)
        embed.set_footer(text="⛓️ Preparando suas regras...")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        msg = await interaction.original_response()

        await asyncio.sleep(0.9)
        embed.description = "📜 As regras foram escritas.\nO tempo vai começar **agora**."
        await msg.edit(embed=embed)
        await asyncio.sleep(0.7)

        # agora inicia o relógio (depois da cinemática)
        task.start_ts = now_ts()
        task.end_ts = task.start_ts + int(task.duration_s)
        task.armed = True
        TRIAL_PARTICIPANTS[key] = task

        challenge = discord.Embed(
            title="🧠 DESAFIO — JULGAMENTO",
            description=(
                f"**PERGUNTA/DESAFIO:** {task.prompt}\n\n"
                f"**REGRAS:**\n{task.rules_text}\n\n"
                f"⏳ Tempo: **{_trial_time_left(task)}s**\n"
                "✅ Responda usando o botão abaixo (não precisa digitar no chat)."
            ),
            color=discord.Color.red()
        )
        challenge.set_footer(text="⚠️ Qualquer erro encerra o julgamento.")

        await interaction.followup.send(embed=challenge, view=TrialActionView(interaction.guild.id, uid), ephemeral=True)


async def _auto_delete_message(channel_id: int, message_id: int, delay_s: int):
    """Deleta uma mensagem do bot após delay. Silencioso se já tiver sumido."""
    try:
        await asyncio.sleep(max(0, int(delay_s)))
        ch = bot.get_channel(int(channel_id))
        if not ch:
            return
        try:
            msg = await ch.fetch_message(int(message_id))
            await msg.delete()
        except Exception:
            pass
    except Exception:
        pass

async def spawn_higuruma_event(guild: discord.Guild):
    if not guild:
        return
    ch = guild.get_channel(int(HIGURUMA_CHANNEL_ID)) if HIGURUMA_CHANNEL_ID else None
    if ch is None:
        return

    # limpa participantes antigos dessa guild
    for k in [k for k in TRIAL_PARTICIPANTS.keys() if k[0] == guild.id]:
        TRIAL_PARTICIPANTS.pop(k, None)

    spawn_ts = now_ts()
    event_id = int(spawn_ts)
    HIGURUMA_EVENT_ID[guild.id] = event_id
    # limpa marcações de participação antigas dessa guild (novo evento)
    for kk in [kk for kk in list(HIGURUMA_EVENT_PARTICIPATED.keys()) if kk[0] == guild.id]:
        HIGURUMA_EVENT_PARTICIPATED.pop(kk, None)

    HIGURUMA_EVENT_WINDOW[guild.id] = {
        "spawn_ts": event_id,
        "close_ts": int(event_id + int(HIGURUMA_ENTRY_WINDOW_SECONDS)),
    }

    embed = discord.Embed(
        title="⚖️ HIGURUMA APARECEU — TRIBUNAL ABERTO",
        description=(
            "O ar ficou pesado…\n"
            "O tribunal foi manifestado **server-wide**.\n\n"
            f"⏳ Você tem **{int(HIGURUMA_ENTRY_WINDOW_SECONDS/60)} minutos** para **entrar** no julgamento.\n"
            f"Depois disso, o tribunal fecha.\n\n"
            "Clique no botão para receber seu desafio.\n"
            "Cada pessoa recebe uma pergunta **diferente**."
        ),
        color=discord.Color.dark_red()
    )
    if HIGURUMA_GIF_URL:
        embed.set_image(url=HIGURUMA_GIF_URL)
    embed.set_footer(text="⛓️ Um único erro invalida o voto.")

    view = HigurumaEnterView(guild.id, ch.id)
    msg = await ch.send(
        content="🚨 **@everyone** 🚨",
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )

    # auto-delete do anúncio (e, por consequência, evita que o chat fique poluído)
    asyncio.create_task(_auto_delete_message(ch.id, msg.id, HIGURUMA_ANNOUNCE_AUTO_DELETE_SECONDS))


async def minigames_loop_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        # spawn do Código Corrompido a cada 30 min
        try:
            for guild in bot.guilds:
                await spawn_corrupted_word(guild)
        except Exception:
            pass

        t0 = now_ts()
        while now_ts() - t0 < CORRUPTED_SPAWN_EVERY:
            try:
                for guild in bot.guilds:
                    await end_corrupted_if_needed(guild)
            except Exception:
                pass
            await asyncio.sleep(1.0)

async def higuruma_loop_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for guild in bot.guilds:
                await spawn_higuruma_event(guild)
        except Exception:
            pass
        await asyncio.sleep(HIGURUMA_SPAWN_EVERY)

# ======================
# DATABASE
# ======================

conn = sqlite3.connect("database.db", check_same_thread=False)

conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")
conn.execute("PRAGMA busy_timeout=5000;")  # espera até 5s se estiver locked

cursor = conn.cursor()

def begin_immediate_with_retry(max_tries: int = 3, delay: float = 0.25):
    """
    Tenta BEGIN IMMEDIATE algumas vezes (pra lidar com 'database is locked').
    """
    for tentativa in range(max_tries):
        try:
            cursor.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and tentativa < max_tries - 1:
                time.sleep(delay)
                continue
            raise



def ensure_column(table: str, column: str, coltype: str, default_sql: str):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype} DEFAULT {default_sql}")
        conn.commit()

# tabela principal
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    beli INTEGER DEFAULT 0,
    giros INTEGER DEFAULT 1,
    equipado TEXT,
    last_daily INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    user_id TEXT,
    personagem TEXT,
    raridade TEXT,
    quantidade INTEGER,
    PRIMARY KEY (user_id, personagem)
)
""")

# roll history
cursor.execute("""
CREATE TABLE IF NOT EXISTS roll_history (
    user_id TEXT,
    ts INTEGER,
    personagem TEXT,
    raridade TEXT
)
""")

# antigo (pode manter, mas não usamos mais)
cursor.execute("""
CREATE TABLE IF NOT EXISTS mission_state (
    user_id TEXT PRIMARY KEY,
    day_key TEXT,
    rolls INTEGER DEFAULT 0,
    sells INTEGER DEFAULT 0,
    equips INTEGER DEFAULT 0,
    claimed_rolls INTEGER DEFAULT 0,
    claimed_sells INTEGER DEFAULT 0,
    claimed_equips INTEGER DEFAULT 0
)
""")

# NOVO: missões diárias (board)
cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_missions (
    user_id TEXT,
    day_key TEXT,
    mission_id TEXT,
    tier TEXT,
    title TEXT,
    goal INTEGER,
    reward_beli INTEGER DEFAULT 0,
    reward_giros INTEGER DEFAULT 0,
    progress INTEGER DEFAULT 0,
    claimed INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, day_key, mission_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS redeem_codes (
    code TEXT PRIMARY KEY,
    reward_giros INTEGER DEFAULT 0,
    reward_beli INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS redeem_claims (
    user_id TEXT,
    code TEXT,
    claimed_at INTEGER,
    PRIMARY KEY (user_id, code)
)
""")


# ======================
# EVENTOS / BUFFS (NOVO)
# ======================



cursor.execute("""
CREATE TABLE IF NOT EXISTS server_events (
    guild_id TEXT PRIMARY KEY,
    event_type TEXT,
    mult_lucky REAL DEFAULT 1.0,
    mult_beli REAL DEFAULT 1.0,
    start_ts INTEGER DEFAULT 0,
    end_ts INTEGER DEFAULT 0,
    channel_id TEXT DEFAULT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_buffs (
    user_id TEXT,
    guild_id TEXT,
    buff_type TEXT,
    mult REAL DEFAULT 1.0,
    start_ts INTEGER DEFAULT 0,
    end_ts INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id, buff_type)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS consumables (
    user_id TEXT,
    item TEXT,
    qty INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, item)
)
""")

conn.commit()

def clear_server_event(guild_id: int):
    gid = str(guild_id)
    cursor.execute("""
        UPDATE server_events
        SET event_type = NULL,
            mult_lucky = 1.0,
            mult_beli = 1.0,
            start_ts = 0,
            end_ts = 0,
            channel_id = NULL
        WHERE guild_id = ?
    """, (gid,))
    conn.commit()

def clear_user_buff(uid: str, guild_id: int, buff_type: str):
    cursor.execute("""
        DELETE FROM user_buffs
        WHERE user_id = ? AND guild_id = ? AND buff_type = ?
    """, (uid, str(guild_id), buff_type))
    conn.commit()

    # ======================
# CRAFT SYSTEM (NOVO)
# ======================

cursor.execute("""
CREATE TABLE IF NOT EXISTS craft_items (
    user_id TEXT,
    item TEXT,
    qty INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, item)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS craft_trackers (
    user_id TEXT PRIMARY KEY,
    active_recipe TEXT DEFAULT NULL,  -- "sukuna" | "gojo" | "yuta"
    started_ts INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS craft_missions (
    user_id TEXT,
    recipe TEXT,          -- sukuna | gojo | yuta
    mission_id TEXT,      -- ex: S01, G03, Y07
    title TEXT,
    event TEXT,           -- roll_spin | roll10_use | sell_count | high_pull | ...
    goal INTEGER,
    progress INTEGER DEFAULT 0,
    reward_item TEXT,     -- ex: finger_sukuna, eye_gojo, essence_epic...
    reward_qty INTEGER DEFAULT 0,
    claimed INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, recipe, mission_id)
)
""")

conn.commit()



# migrações
ensure_column("users", "pity_legendary", "INTEGER", "0")
ensure_column("users", "roll_hour_window", "INTEGER", "0")
ensure_column("users", "roll_hour_count", "INTEGER", "0")
ensure_column("users", "last_roll_ts", "INTEGER", "0")

# ======================
# RARIDADES
# ======================

RARIDADES = {
    "Secreto":  {"chance": 0.1, "emoji": "🟥", "color": discord.Color.red()},
    "Mítico":   {"chance": 0.5, "emoji": "🟪", "color": discord.Color.purple()},
    "Lendário": {"chance": 4,   "emoji": "🟨", "color": discord.Color.gold()},
    "Épico":    {"chance": 8,   "emoji": "🟦", "color": discord.Color.blue()},
    "Raro":     {"chance": 20,  "emoji": "🟩", "color": discord.Color.green()},
    "Incomum":  {"chance": 27.4,"emoji": "⬜", "color": discord.Color.light_grey()},
    "Comum":    {"chance": 40,  "emoji": "⬛", "color": discord.Color.dark_grey()},
}


ORDEM_RARIDADES = ["Secreto", "Mítico", "Lendário", "Épico", "Raro", "Incomum", "Comum"]

# ======================
# IDS DOS CARGOS DE RARIDADE
# ======================

ROLE_RARIDADE_IDS = {
    "Comum":    1462603576915263510,  # 🟫 COMUM
    "Incomum":  1462603578190467092,  # ⬜ INCOMUM
    "Raro":     1462603579511672902,  # 🟩 RARO
    "Épico":    1462603580963029141,  # 🟦 ÉPICO
    "Lendário": 1462603582653333537,  # 🟨 LENDÁRIO
    "Mítico":   1462603583672422591,  # 🟪 MÍTICO
    "Secreto":  1462603585383829568,  # 🟥 SECRETO
}

ITEM_DISPLAY = {
    # craft
    "finger_sukuna": "🩸 Dedo de Sukuna",
    "eye_gojo": "♾️ Olho do Gojo (Six Eyes)",
    "seal_fragment": "🧬 Fragmento do Selo",
    "core_yuta": "🧿 Núcleo do Yuta",

    # essências
    "essence_common": "✨ Essência Comum",
    "essence_uncommon": "✨ Essência Incomum",
    "essence_rare": "✨ Essência Rara",
    "essence_epic": "✨ Essência Épica",
    "essence_legendary": "✨ Essência Lendária",
    "essence_mythic": "✨ Essência Mítica",
    "essence_secret": "✨ Essência Secreta",    "kamutoke": "⚡ Kamutoke",

}


# ======================
# PERSONAGENS (edite aqui)
# ======================

PERSONAGENS: Dict[str, Dict] = {

    # ======================
    # COMUM
    # ======================
    "Kiyotaka Ijichi": {"raridade": "Comum", "role_id": 1462603586562166794, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585866458497075/kiyotaka-ijichi.gif?ex=696ebabc&is=696d693c&hm=a60e9f75f5adaf9937dcdcb56a40d1f12027fb7f56fb388f94ca32306334a4ef&="},
    "Nitta Akari": {"raridade": "Comum", "role_id": 1462603587598159966, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585865485291694/jujutsu-kaisen.gif?ex=696ebabb&is=696d693b&hm=45962d03f3d156d708c49eabf1b511de4f31fdb297e44f4017c1891351bd285f&="},
    "Junpei Yoshino": {"raridade": "Comum", "role_id": 1462603588676092138, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585866089136219/MqATVWa.gif?ex=696ebabc&is=696d693c&hm=7290f0f15df0e0bc65e26c2bf2eb4c963053e40ddb86705afa473d6600955603&="},
    "Kasumi Miwa": {"raridade": "Comum", "role_id": 1462603590056022201, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585582692860014/a23800bec8ecc96a97c0877a31eb457c.gif?ex=696eba78&is=696d68f8&hm=9c8fc953fe9848422a782c49139487b212c00a11e3ab7ed1ade8aef6d47ab907&="},
    "Momo Nishimiya": {"raridade": "Comum", "role_id": 1462603591213912146, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585583313354895/jujutsu-kaisen-momo-nishimiya.gif?ex=696eba78&is=696d68f8&hm=ddb06e01d7eff43a08b1702b8dd291fc827c1b0b2a7793da67d17105375b57c4&="},
    "Mai Zenin": {"raridade": "Comum", "role_id": 1462603592887308554, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585583678521508/mai-zenin.gif?ex=696eba78&is=696d68f8&hm=ead3512ff2de6108d8f29560038a02bde7160f8b1041acba8d3df354d3ddbc0f&="},
    "Noritoshi Kamo": {"raridade": "Comum", "role_id": 1462603594334343310, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585312088821871/DOFZ71i.gif?ex=696eba37&is=696d68b7&hm=e61f109e4372cadddd0a15201a6f932c02ae5f972fe1767d4d7927f520e707a8&="},
    "Shigemo Haruta": {"raridade": "Comum", "role_id": 1462603595609280513, "image": "https://media.discordapp.net/attachments/953094648354726019/1462585311405015091/tumblr_f80ba57e1075d9075e684d947b44f7c5_64a148d9_500.gif?ex=696eba37&is=696d68b7&hm=09b53e9f0911ec3ad15756a588d115ca9da246ee3676dd1fbf7a4597e6db5670&="},

    # ======================
    # INCOMUM
    # ======================
    "Panda": {"raridade": "Incomum", "role_id": 1462603597090127977, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584901768446073/jujutsu-kaisen-jjk.gif?ex=696eb9d6&is=696d6856&hm=a656490557a5198312ef3a230bb9c7cf060f1d2214bc4e86eb2515a497ac1590&="},
    "Toge Inumaki": {"raridade": "Incomum", "role_id": 1462603597760958578, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584902141870253/d4558de74a148b62ebaf9cd9e358e080.gif?ex=696eb9d6&is=696d6856&hm=aa58c957877c1b30d0b258e2888cf3183218d452228523a4911eeab3ac6204dc&="},
    "Aoi Todo": {"raridade": "Incomum", "role_id": 1462603599468302512, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584902472958063/2c190730f32edbce68eebfc12a885114.gif?ex=696eb9d6&is=696d6856&hm=d041f1c6a7b7cf73af3bdf34e3a87fa42e736a18a8b81e772b64a2953a258bcf&="},
    "Kento Nanami": {"raridade": "Incomum", "role_id": 1462603600227467565, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584902817153217/jujutsu-kaisen-nanami.gif?ex=696eb9d6&is=696d6856&hm=3be9f02ee4e3f8b7a960e407a7f5a26a12e2e31c21a82b2c102bc12e0f64d3fe&="},
    "Rika Orimoto": {"raridade": "Incomum", "role_id": 1462603602320294030, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584901441294407/anime-girl.gif?ex=696eb9d6&is=696d6856&hm=1ef6134bc8e8cc4d8401a5a1049b110bf93f8f46d616ba0947120c491f310226&="},

    # ======================
    # RARO
    # ======================
    "Yuji Itadori": {"raridade": "Raro", "role_id": 1462603603591041087, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584501376127141/84925f2c2d31af1d08c6ab69afdde1b5.gif?ex=696eb976&is=696d67f6&hm=b6160a5a1ab913c9c7455ab2e41d5451a9da5b9cb5d3f739c30f04af6102b6fd&="},
    "Megumi Fushiguro": {"raridade": "Raro", "role_id": 1462603605872742401, "image": "https://media.discordapp.net/attachments/953094648354726019/1462584501929508885/megumi-jujutsu-kaisen.gif?ex=696eb976&is=696d67f6&hm=d140078e1ae7b77c4a030d6144a199158e6f312f7f253a8bda8e308db9ef852c&="},
    "Nobara Kugisaki": {"raridade": "Raro", "role_id": 1462603607139422324, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462584500922880094/9e188c30a388a0073581d2cea5bb1378.gif?ex=696eb976&is=696d67f6&hm=9ab11b54c39d340cca96e8cc96f0506eced5afc2fb443e015887b0c922c57f39&"},
    "Kusakabe Atsuya": {"raridade": "Raro", "role_id": 1462603608666280153, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462584219959164989/i30mbq9wr2ke1.gif?ex=696eb933&is=696d67b3&hm=30eca87650f849f16c87fff5f74cf9577e0cc610757cc57566ab5c752b2f2583&"},
    "Shoko Ieiri": {"raridade": "Raro", "role_id": 1462603610297729076, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583685403508879/kk.gif?ex=696eb8b4&is=696d6734&hm=918199a7932c8c1e3b03363d80e982f128d1ddf173b8d693b12a7707471c4bec&="},

    # ======================
    # ÉPICO
    # ======================
    "Hanami": {"raridade": "Épico", "role_id": 1462603615956107392, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583686561009869/e717c677e76c4e0df9a22ec53418367f.gif?ex=696eb8b4&is=696d6734&hm=6fec7f3074a036ab965c9da07df4e989200a4eea793fa94b982eae8ec56d1120&="},
    "Choso": {"raridade": "Épico", "role_id": 1462603618724217015, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583687127367700/choso-cover-his-mouth-6v48wsn7nypp1ht8.gif?ex=696eb8b4&is=696d6734&hm=72435308c058cf43b989d065453d451e0a48a67b6d2323372f3b086002db197b&="},
    "Naobito Zenin": {"raridade": "Épico", "role_id": 1462603620083306802, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583685063643279/naobito-jujutsu-kaisen.gif?ex=696eb8b4&is=696d6734&hm=a0fbe661abc266435514ee790c75f38a8a7364d581fd1d300d3e7771b2712593&="},
    "Miguel": {"raridade": "Épico", "role_id": 1462603625837760522, "image": "https://media.discordapp.net/attachments/953094648354726019/1462582774774104344/miguel-jjk.png?ex=696eb7da&is=696d665a&hm=6853f7d0dbdf4e4f4b7bd606e8784bc29d20569d517cecc5e8f94eb69352625d&=&format=webp&quality=lossless"},
    "Mei Mei": {"raridade": "Épico", "role_id": 1462603626886336546, "image": "https://media.discordapp.net/attachments/953094648354726019/1462582775348461568/24020c71dec471270e63b41a5c32dff0.gif?ex=696eb7db&is=696d665b&hm=3b0c62770e5bd12d77308ba0db8e4a7b3ac7400fce283be7334faa7af4346e9c&="},

    # ======================
    # LENDÁRIO
    # ======================
    "Dagon": {"raridade": "Lendário", "role_id": 1462603617356877896, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583686833897472/dagon-jjk.gif?ex=696eb8b4&is=696d6734&hm=272929d5481e2d7982497af1c8fa1061c9e6d27f4e6cba6def8f6061b5ad2b67&="},
    "Mahito": {"raridade": "Lendário", "role_id": 1462603611946221720, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583685801840681/e5ead6b2919ed6b676e140cc714f4d08.gif?ex=696eb8b4&is=696d6734&hm=80a7ac5fc72ad798b18b57fe9b858f1ee0790422cd5a9e8a19925538457c50bb&="},
    "Jogo": {"raridade": "Lendário", "role_id": 1462603613133209666, "image": "https://media.discordapp.net/attachments/953094648354726019/1462583686183784632/jujutsu-kaisen-jogo.gif?ex=696eb8b4&is=696d6734&hm=9761db69aebeaeea75be668e853ba87e866ac476abac5421b636b502d39d16aa&="},
    "Toji Fushiguro": {"raridade": "Lendário", "role_id": 1462603622096441456, "image": "https://media.discordapp.net/attachments/953094648354726019/1462582775759634594/toji-toji-smh.gif?ex=696eb7db&is=696d665b&hm=d9cc61e8cf5359788b189a7f165c2d7dff1f73112e20617a2ee7aaf4308dbafc&="},
    "Uraume": {"raridade": "Lendário", "role_id": 1462603623619100752, "image": "https://media.discordapp.net/attachments/953094648354726019/1462582776086921357/uruame-uruame-jjk.gif?ex=696eb7db&is=696d665b&hm=33a695ecdd4591bc4eabe92f537f21d9140be76d017d42d815df26aa9cf724f6&="},
    "Naoya Zenin": {"raridade": "Lendário", "role_id": 1462603624348913860, "image": "https://media.discordapp.net/attachments/953094648354726019/1462582774442627299/naoya-naoya-zenin.gif?ex=696eb7da&is=696d665a&hm=fe970177db6c30998d5ca9b215a85c8dcf4e10aa64e5f1095462f93b8d6bdaa7&="},
    "Maki Zenin": {"raridade": "Lendário", "role_id": 1462603627930718353, "image": "https://media.discordapp.net/attachments/953094648354726019/1462582822895222966/b37e80e29b6c4efca0cf4937f855bc63.gif?ex=696eb7e6&is=696d6666&hm=aa9aaff492b1d861940c1942d7815f87c480841f98bf0a4f342c07ad2f2ccc93&="},

    # ======================
    # MÍTICO
    # ======================
    "Kenjaku": {"raridade": "Mítico", "role_id": 1462603628987814066, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462581530764378247/14-kenjaku-shows-stolen-powerful-soul.gif?ex=696eb6b2&is=696d6532&hm=e829933035bf45df888376f6214556ab70d5e46ba60ee35efccefbc61ae11404&"},
    "Yuki Tsukumo": {"raridade": "Mítico", "role_id": 1462603630308888709, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462581356658954250/yuki-yuki-tsukumo.gif?ex=696eb688&is=696d6508&hm=9fc5c5531dc650846c5b521801da7cc58836e47d990a93a710c1f08a00b3235a&"},
    "Mahoraga": {"raridade": "Mítico", "role_id": 1462603631520907275, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462581123476492510/jujutsu-kaisen-shibuya-arc-mahoraga-shibuya-arc.gif?ex=696eb651&is=696d64d1&hm=8170e321adbb0d12ba10480082737af9fb89848433b61bb2f27a6024b384069c&"},
    "Tengen": {"raridade": "Mítico", "role_id": 1462603633139908609, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462580912125378774/360.png?ex=696eb61e&is=696d649e&hm=afc0e7f4cd181a62a1daca965d85a4e99c0d1988fe08395732a678b3e96b5f0d&"},
    "Hajime Kashimo": {"raridade": "Mítico", "role_id": 1462603634897326262, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462580945021435904/download_1.gif?ex=696eb626&is=696d64a6&hm=00375a713be614c8f1f94a7462d5aa4b9e07c4e2d935cb71075e55f50439f993&"},
    "Yuta Okkotsu": {"raridade": "Mítico", "role_id": 1462603636164005930, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462580969285357669/223070.gif?ex=696eb62c&is=696d64ac&hm=35993cd3be7e6f02b58be37a63a99d4546fddc649cabbe3879ae8ae61c127ead&"},
    "Suguru Geto": {"raridade": "Mítico", "role_id": 1462603637544190045, "image": "https://cdn.discordapp.com/attachments/953094648354726019/1462581604000993391/219956.gif?ex=696eb6c3&is=696d6543&hm=6cf48b462b704fc81f9209cc0dfb85b1d858d2957c84fabacc51b8a0e5971fc6&"},

    # ======================
    # SECRETO
    # ======================
    "Ryomen Sukuna": {"raridade": "Secreto", "role_id": 1462603638617931860, "image": "https://media.discordapp.net/attachments/953094648354726019/1463276757175111690/dd03044d67c493a3514b1fe8f8c42cff.gif?ex=69713e2d&is=696fecad&hm=e7e7b6a5d9521408e3d69f7658e2b63a73d6db01a3cb584449eb9be4a7504a25&="},
    "Satoru Gojo": {"raridade": "Secreto", "role_id": 1462603640085811423, "image": "https://media.discordapp.net/attachments/953094648354726019/1462579527040634921/57b816c4a6d2bd2f15f4a6dc6ff9938c.gif?ex=696eb4d4&is=696d6354&hm=c23dce2dae6e8c81e994097dd88b9ad6ccdefa06b5c58628cfe65d4560073e1d&="},
    "Yuta Okkotsu (Gojo Body)": {"raridade": "Secreto", "role_id": 1462603641654345793, "image": "https://media.discordapp.net/attachments/953094648354726019/1462580038963691531/download.gif?ex=696eb54e&is=696d63ce&hm=9d93302fcc47c88fc2458fff6f001180339bc3f233d825601443b77fb04adc86&="},
}

CODES: Dict[str, Dict[str, int]] = {
    "UPDATE0.5!": {"giros": 15, "beli": 500},
}

# ======================
# ECONOMIA
# ======================

VALOR_VENDA = {
    "Comum": 10,
    "Incomum": 25,
    "Raro": 60,
    "Épico": 150,
    "Lendário": 400,
    "Mítico": 1200,
    "Secreto": 5000
}

ESSENCE_BY_RARITY = {
    "Comum": ("essence_common", 1),
    "Incomum": ("essence_uncommon", 2),
    "Raro": ("essence_rare", 4),
    "Épico": ("essence_epic", 8),
    "Lendário": ("essence_legendary", 15),
    "Mítico": ("essence_mythic", 30),
    "Secreto": ("essence_secret", 80),
}


# ======================
# UTIL
# ======================

# ======================
# JJK SECRET EVENT (LOCK CHAT + CINEMATIC)
# ======================

# guarda o estado original do @everyone em cada canal
JJK_LOCK_STATE: Dict[int, Dict[int, Optional[bool]]] = {}  # guild_id -> {channel_id: send_messages_value}

async def lock_guild_chat(guild: discord.Guild):
    """
    Bloqueia envio de mensagens para @everyone em TODOS os canais de texto,
    salvando o estado anterior pra restaurar depois.
    """
    if guild is None:
        return

    # já está lockado? não duplica
    if guild.id in JJK_LOCK_STATE:
        return

    JJK_LOCK_STATE[guild.id] = {}
    everyone = guild.default_role

    for ch in guild.text_channels:
        try:
            ow = ch.overwrites_for(everyone)
            # salva o valor atual (True / False / None)
            JJK_LOCK_STATE[guild.id][ch.id] = ow.send_messages
            # bloqueia
            ow.send_messages = False
            await ch.set_permissions(everyone, overwrite=ow, reason="JJK Secret Event cinematic lock")
        except discord.Forbidden:
            # sem perm de Manage Channels
            continue
        except discord.HTTPException:
            continue

async def restore_guild_chat(guild: discord.Guild):
    """
    Restaura exatamente o send_messages do @everyone como estava antes.
    """
    if guild is None:
        return

    state = JJK_LOCK_STATE.get(guild.id)
    if not state:
        return

    everyone = guild.default_role

    for ch in guild.text_channels:
        if ch.id not in state:
            continue
        try:
            prev = state[ch.id]  # True/False/None
            ow = ch.overwrites_for(everyone)
            ow.send_messages = prev  # restaura exatamente
            await ch.set_permissions(everyone, overwrite=ow, reason="JJK Secret Event cinematic restore")
        except discord.Forbidden:
            continue
        except discord.HTTPException:
            continue

    # limpa estado
    JJK_LOCK_STATE.pop(guild.id, None)


async def announce_jjk_secret_cinematic(guild: discord.Guild, channel: discord.TextChannel, duration_s: int):
    """
    CINEMÁTICA SUPREMA (JJK) — versão MAIS LONGA, DEVAGAR e MAIS INSANA:
    - trava chat no servidor inteiro
    - sequência longa de edits (com pausas seguras pra não tomar rate limit fácil)
    - destrava chat com segurança (finally)
    - anuncia evento com @everyone no final
    """
    await lock_guild_chat(guild)

    def g(text: str, intensity: float = 1.0) -> str:
        # usa seu _glitch() já existente, mas aumenta “densidade” via repetição controlada
        if intensity <= 1.0:
            return _glitch(text)
        t = text
        for _ in range(1 + int((intensity - 1.0) * 2)):
            t = _glitch(t)
        return t

    # helper pra editar com uma pausa consistente (cinema mais “devagar”)
    async def beat(sec: float):
        await asyncio.sleep(sec)

    try:
        # ==========================================================
        # FASE 0 — SELAMENTO / SILÊNCIO ABSOLUTO
        # ==========================================================
        e = discord.Embed(
            title="⛓️『 VOTO VINCULANTE 』— SELAMENTO",
            description=g(
                "…\n"
                "o ar ficou denso.\n"
                "o som foi engolido.\n\n"
                "Você sente a barreira fechando por cima do servidor.",
                1.05
            ),
            color=discord.Color.dark_red()
        )
        if SECRET_JJK_GIF_URL:
            e.set_image(url=SECRET_JJK_GIF_URL)
        e.set_footer(text="⛔ Chat travado temporariamente. Não tente falar.")
        msg = await channel.send(embed=e)
        await beat(1.25)

        # ==========================================================
        # FASE 1 — “BATIMENTOS” (aumenta o suspense sem flood)
        # ==========================================================
        pulses = [
            ("🫀『 … 』", "…tum."),
            ("🫀『 … … 』", "…tum… tum."),
            ("🫀『 … … … 』", "…tum… tum… tum."),
        ]
        for title, d in pulses:
            e.title = title
            e.description = g(
                f"{d}\n\n"
                "A barreira reage.\n"
                "Algo *do outro lado* está tentando atravessar.",
                1.15
            )
            await msg.edit(embed=e)
            await beat(1.10)

        # ==========================================================
        # FASE 2 — VARREDURA / SISTEMA CORROMPIDO
        # ==========================================================
        e.title = "📡『 VARREDURA DE ENERGIA AMALDIÇOADA 』"
        e.description = (
            f"{g('>> inicializando sensores...', 1.05)}\n"
            f"{g('>> calibrando barreira...', 1.05)}\n"
            f"{g('>> rastreando fluxo: ███████░░', 1.10)}\n\n"
            f"{g('>> ALERTA: interferência desconhecida', 1.25)}\n"
            f"{g('>> ALERTA: destino reescrito', 1.35)}\n\n"
            f"{g('não tente falar.', 1.45)}"
        )
        await msg.edit(embed=e)
        await beat(1.45)

        # ==========================================================
        # FASE 3 — PERDA DE SINAL (glitch pesado)
        # ==========================================================
        e.title = "📵『 SINAL PERDIDO 』"
        e.description = g(
            "…\n"
            "as mensagens não atravessam.\n"
            "as regras aqui dentro mudaram.\n\n"
            "o servidor foi puxado para dentro de um espaço *proibido*.",
            1.55
        )
        e.set_footer(text="⚠️ Fique pronto. Quando a contagem começar, prepare o !roll.")
        await msg.edit(embed=e)
        await beat(1.35)

        # ==========================================================
        # FASE 4 — FORMAÇÃO DO DOMÍNIO (tremor longo)
        # ==========================================================
        tremores = [
            "⚫ barreira expandindo…",
            "⚫ barreira expandindo……",
            "⚫ barreira expandindo………",
            "⚫ barreira expandindo…………",
            "⚫ barreira expandindo……………",
        ]
        for i, line in enumerate(tremores, start=1):
            e.title = f"⚫『 DOMÍNIO EM FORMAÇÃO 』({i}/{len(tremores)})"
            e.description = g(
                f"{line}\n\n"
                "O chão some.\n"
                "A gravidade vira opinião.\n"
                "A sorte vira lei.",
                1.35
            )
            await msg.edit(embed=e)
            await beat(1.05)

        # ==========================================================
        # FASE 5 — “CORTES” (impacto psicológico)
        # ==========================================================
        cuts = [
            "…um corte apareceu no vazio.",
            "…dois cortes. você nem viu de onde veio.",
            "…três cortes. a barreira está sangrando.",
        ]
        for i, c in enumerate(cuts, start=1):
            e.title = f"🗡️『 CORTES INVISÍVEIS 』— {i}"
            e.description = g(
                f"{c}\n\n"
                "Você entende.\n"
                "Isso não é um evento.\n"
                "É uma *sentença*.",
                1.50
            )
            await msg.edit(embed=e)
            await beat(1.15)

        # ==========================================================
        # FASE 6 — NOME REVELADO (o “pico” antes da contagem)
        # ==========================================================
        e.title = "🟥『 NOME DO DOMÍNIO 』"
        e.description = g(
            "S A N T U Á R I O   M A L E V O L E N T E\n\n"
            "A realidade aqui dentro aceita só um comando:\n"
            "**G I R E.**",
            1.65
        )
        await msg.edit(embed=e)
        await beat(1.55)

        # ==========================================================
        # FASE 7 — LEI DO EVENTO (mostra os bônus com estilo)
        # ==========================================================
        ml, mb = EVENT_MULTS["jjk_secret"]
        e.title = "⚠️『 LEI VINCULANTE 』— MULTIPLICADORES"
        e.description = g(
            "O destino foi forçado além do limite.\n\n"
            f"🍀 LUCKY: **x{ml}** (forçado ao impossível)\n"
            f"💰 BELI: **x{mb}** (colapso da economia)\n\n"
            "Quem girar agora…\n"
            "vai ouvir o servidor gritar.",
            1.55
        )
        e.set_footer(text="⛔ Ainda selado. Segure a ansiedade.")
        await msg.edit(embed=e)
        await beat(1.45)

        # ==========================================================
        # FASE 8 — PRÉ-COUNTDOWN (ritual)
        # ==========================================================
        ritual = [
            "…respire.",
            "…conte seus giros.",
            "…segure o comando.",
            "…não pisque.",
        ]
        for i, line in enumerate(ritual, start=1):
            e.title = f"🕯️『 RITUAL 』({i}/{len(ritual)})"
            e.description = g(
                f"{line}\n\n"
                "Quando a barreira abrir,\n"
                "o servidor vira caça.",
                1.45
            )
            await msg.edit(embed=e)
            await beat(1.10)

        # ==========================================================
        # FASE 9 — COUNTDOWN LENTO (mais pesado)
        # ==========================================================
        for n in (5, 4, 3, 2, 1):
            e.title = f"🧿『 IMPACTO IMINENTE 』— {n}"
            e.description = g("…", 1.70)
            await msg.edit(embed=e)
            await beat(0.95)

        # ==========================================================
        # FASE 10 — IMPACTO (troca gif, frase curta e brutal)
        # ==========================================================
        e.title = "🔥『 MANIFESTAÇÃO COMPLETA 』"
        e.description = g("A BARREIRA ABRIU.\n\n**AGORA… GIRE.**", 1.75)
        if SECRET_JJK_GIF_IMPACT_URL:
            e.set_image(url=SECRET_JJK_GIF_IMPACT_URL)
        await msg.edit(embed=e)
        await beat(1.10)

        # ==========================================================
        # FASE 11 — PÓS-IMPACTO (última frase antes de destravar)
        # ==========================================================
        e.title = "🟥『 ECO 』"
        e.description = g(
            "…\n"
            "se você sentiu um arrepio,\n"
            "é porque o domínio reconheceu sua presença.\n\n"
            "não desperdice esse momento.",
            1.55
        )
        e.set_footer(text="⏳ Abrindo o chat…")
        await msg.edit(embed=e)
        await beat(1.00)

    finally:
        # SEMPRE destrava
        await restore_guild_chat(guild)

    # ==========================================================
    # ANÚNCIO FINAL (evento já ativo no banco; aqui é a explosão)
    # ==========================================================
    ml, mb = EVENT_MULTS["jjk_secret"]
    end_txt = fmt_duration(duration_s)

    final = discord.Embed(
        title="🟥 EVENTO SECRETO — 『SANTUÁRIO MALEVOLENTE』",
        description=(
            "A barreira abriu por tempo limitado.\n\n"
            "🎴 **Raridades altas estão famintas.**\n"
            "⚔️ O servidor entrou em modo *caçada*.\n\n"
            "**Aproveite antes que a barreira se feche.**"
        ),
        color=discord.Color.red()
    )
    final.add_field(name="🍀 Lucky", value=f"**x{ml}**", inline=True)
    final.add_field(name="💰 Beli", value=f"**x{mb}**", inline=True)
    final.add_field(name="⏳ Duração", value=f"**{end_txt}**", inline=False)

    if SECRET_JJK_GIF_IMPACT_URL:
        final.set_image(url=SECRET_JJK_GIF_IMPACT_URL)
    elif SECRET_JJK_GIF_URL:
        final.set_image(url=SECRET_JJK_GIF_URL)

    final.set_footer(text="⚠️ Evento secreto manual. Boa sorte 😈")

    await channel.send(
        content="🚨 **@everyone** 🚨",
        embed=final,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )



async def announce_both_prelude(channel: discord.TextChannel):
    embed = discord.Embed(
        title="🌌 Algo está mudando...",
        description="O ar ficou pesado.\nUma presença estranha começou a surgir.",
        color=discord.Color.dark_red()
    )
    msg = await channel.send(embed=embed)

    # ⏳ Fase 1
    await asyncio.sleep(1.2)
    embed.title = "⚠️ Instabilidade detectada"
    embed.description = (
        "As energias do servidor entraram em **ressonância**.\n"
        "Algo **fora do comum** está se formando..."
    )
    await msg.edit(embed=embed)

    # ⏳ Fase 2
    await asyncio.sleep(1.2)
    embed.title = "👑 Convergência crítica"
    embed.description = (
        "🍀 Sorte extrema\n"
        "💰 Riqueza absoluta\n\n"
        "**Isso NÃO deveria acontecer.**"
    )
    await msg.edit(embed=embed)

    # ⏳ Fase 3 (quase lá)
    await asyncio.sleep(1.0)
    embed.title = "🔥 LIMIAR ULTRAPASSADO"
    embed.description = (
        "O servidor não conseguiu conter a energia.\n\n"
        "**Prepare-se.**"
    )
    await msg.edit(embed=embed)

    await asyncio.sleep(0.8)
    return msg  # só pra garantir controle se quiser expandir depois

async def announce_cinematic_event(channel: discord.TextChannel, event_type: str, mult_lucky: float, mult_beli: float):
    titles = {
        "lucky": "🍀✨ DISTORÇÃO DA SORTE",
        "beli":  "💰⚡ CHUVA DE BELI",
        "both":  "👑🔥 EVENTO SUPREMO"
    }

    descriptions = {
        "lucky": (
            "O fluxo do destino foi **alterado**...\n\n"
            "🍀 **SORTE AUMENTADA**\n"
            "Personagens raros sentem sua presença.\n\n"
            "**Agora é a hora de girar.**"
        ),
        "beli": (
            "O mundo começa a **transbordar riqueza**...\n\n"
            "💰 **BELI EM DOBRO**\n"
            "Cada venda vale muito mais.\n\n"
            "**Aproveite enquanto durar.**"
        ),
        "both": (
            "⚠️ **ALGO ANORMAL ESTÁ ACONTECENDO** ⚠️\n\n"
            "🍀 Sorte extrema\n"
            "💰 Beli em abundância\n\n"
            "**Um evento raríssimo tomou o servidor.**"
        )
    }

    colors = {
        "lucky": discord.Color.green(),
        "beli": discord.Color.gold(),
        "both": discord.Color.red()
    }

    embed = discord.Embed(
        title=titles.get(event_type, "🌌 EVENTO ATIVO"),
        description=descriptions.get(event_type, ""),
        color=colors.get(event_type, discord.Color.dark_purple())
    )

    embed.add_field(
        name="🔮 Multiplicadores",
        value=f"🍀 Lucky x{mult_lucky}\n💰 Beli x{mult_beli}",
        inline=False
    )

    embed.add_field(
        name="⏳ Duração",
        value="**5 minutos**",
        inline=False
    )


    embed.add_field(
        name="⚡ kamutoke",
        value=f"{fmt_currency(KAMUTOKE_PRICE_BELI)} Beli + {KAMUTOKE_PRICE_ESSENCE_QTY}x {ITEM_DISPLAY.get(KAMUTOKE_PRICE_ESSENCE_KEY, KAMUTOKE_PRICE_ESSENCE_KEY)}\n(Protege 1 falha no Julgamento do Higuruma)",
        inline=False
    )

    embed.set_footer(text="⚔️ Gire agora ou perca a chance.")

    # mensagem com @everyone
    await channel.send(
        content="🚨 **@everyone** 🚨",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )


def get_current_craft_mission(uid: str, recipe: str):
    ensure_craft_board(uid, recipe)
    cursor.execute("""
        SELECT mission_id, title, event, progress, goal, reward_item, reward_qty, claimed
        FROM craft_missions
        WHERE user_id = ? AND recipe = ?
        ORDER BY mission_id ASC
    """, (uid, recipe))
    rows = cursor.fetchall()
    for row in rows:
        if int(row[7]) == 0:  # claimed == 0
            return row
    return None


def _yuta_core_already_has(uid: str) -> bool:
    cursor.execute("SELECT qty FROM craft_items WHERE user_id = ? AND item = ? AND qty > 0", (uid, "core_yuta"))
    return cursor.fetchone() is not None

def _maybe_grant_yuta_core(uid: str):
    """
    Se TODAS as missões do Yuta estiverem CLAIMED, dá +1 core_yuta (uma vez).
    Deve ser chamado dentro de uma transação (BEGIN IMMEDIATE), com commit controlado fora.
    """
    # evita duplicar núcleo
    if _yuta_core_already_has(uid):
        return

    cursor.execute("""
        SELECT COUNT(*)
        FROM craft_missions
        WHERE user_id = ? AND recipe = 'yuta'
    """, (uid,))
    total = int(cursor.fetchone()[0] or 0)
    if total <= 0:
        return

    cursor.execute("""
        SELECT COUNT(*)
        FROM craft_missions
        WHERE user_id = ? AND recipe = 'yuta' AND claimed = 1
    """, (uid,))
    claimed = int(cursor.fetchone()[0] or 0)

    if claimed >= total:
        # dá o núcleo
        add_craft_item(uid, "core_yuta", 1, commit=False)


def add_craft_item(uid: str, item: str, qty: int, commit: bool = True):
    if qty <= 0:
        return
    cursor.execute("""
        INSERT INTO craft_items(user_id, item, qty)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, item) DO UPDATE SET qty = qty + excluded.qty
    """, (uid, item, int(qty)))
    if commit:
        conn.commit()


def get_craft_items(uid: str) -> Dict[str, int]:
    cursor.execute("SELECT item, qty FROM craft_items WHERE user_id = ? AND qty > 0", (uid,))
    return {i: int(q) for i, q in cursor.fetchall()}

def consume_craft_items(uid: str, req: Dict[str, int]) -> bool:
    """
    Remove itens de craft de forma atômica; retorna False se faltar algo.
    """
    cur = get_craft_items(uid)
    for k, v in req.items():
        if cur.get(k, 0) < int(v):
            return False

    try:
        begin_immediate_with_retry()
        for k, v in req.items():
            cursor.execute("""
                UPDATE craft_items
                SET qty = qty - ?
                WHERE user_id = ? AND item = ? AND qty >= ?
            """, (int(v), uid, k, int(v)))
        cursor.execute("DELETE FROM craft_items WHERE user_id = ? AND qty <= 0", (uid,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def get_consumables(uid: str) -> Dict[str, int]:
    cursor.execute("SELECT item, qty FROM consumables WHERE user_id = ? AND qty > 0", (uid,))
    rows = cursor.fetchall()
    return {item: int(qty) for item, qty in rows}


def get_consumable_qty(uid: str, item: str) -> int:
    cursor.execute("SELECT qty FROM consumables WHERE user_id = ? AND item = ? AND qty > 0", (uid, item))
    row = cursor.fetchone()
    return int(row[0]) if row else 0

def consume_consumable(uid: str, item: str, qty: int = 1) -> bool:
    """Consome consumível de forma atômica; retorna False se não tiver."""
    if qty <= 0:
        return True
    try:
        begin_immediate_with_retry()
        cursor.execute(
            "UPDATE consumables SET qty = qty - ? WHERE user_id = ? AND item = ? AND qty >= ?",
            (int(qty), uid, item, int(qty))
        )
        if cursor.rowcount <= 0:
            conn.rollback()
            return False
        cursor.execute("DELETE FROM consumables WHERE user_id = ? AND qty <= 0", (uid,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False



def _glitch_heavy(text: str, intensity: float = 1.6) -> str:
    """Glitch mais pesado (usado no JJK Secret) sem virar spam infinito."""
    if intensity <= 1.0:
        return _glitch(text)
    t = text
    reps = 1 + int((intensity - 1.0) * 2)
    for _ in range(reps):
        t = _glitch(t)
    return t

def _is_jjk_secret(event: Optional[dict]) -> bool:
    return bool(event) and event.get("type") == "jjk_secret"

def _glitch(text: str) -> str:
    # glitch leve, pra não virar spam / quebrar embed
    # (troca alguns caracteres por símbolos "corrompidos")
    swaps = {
        "a":"@", "e":"3", "i":"1", "o":"0", "u":"υ",
        "A":"Δ", "E":"Ξ", "I":"Ι", "O":"Ø", "U":"∪",
        "s":"$", "S":"§"
    }
    out = []
    for ch in text:
        if ch in swaps and random.random() < 0.18:
            out.append(swaps[ch])
        else:
            out.append(ch)
    return "".join(out)

async def _edit_or_send(ctx, msg: Optional[discord.Message], embed: discord.Embed) -> discord.Message:
    if msg is None:
        return await ctx.send(embed=embed)
    try:
        await msg.edit(embed=embed)
        return msg
    except discord.HTTPException:
        return await ctx.send(embed=embed)

def _secret_title(event=None) -> str:
    if event and event.get("type") == "both":
        return "👑🟥 SECRETO (EVENTO RARO ATIVO)"
    return "🟥 SECRETO DETECTADO"


def fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def get_active_user_buff(uid: str, guild_id: int, buff_type: str):
    gid = str(guild_id)
    t = now_ts()
    cursor.execute("""
        SELECT mult, start_ts, end_ts
        FROM user_buffs
        WHERE user_id = ? AND guild_id = ? AND buff_type = ?
        LIMIT 1
    """, (uid, gid, buff_type))
    row = cursor.fetchone()
    if not row:
        return None

    mult, start_ts, end_ts = row

    if int(end_ts) <= t:
        # ✅ BUG A: limpa do banco quando expira
        clear_user_buff(uid, guild_id, buff_type)
        return None

    return {"mult": float(mult), "start": int(start_ts), "end": int(end_ts)}


def now_ts() -> int:
    return int(time.time())

def get_active_server_event(guild_id: int):
    gid = str(guild_id)
    t = now_ts()
    cursor.execute("""
        SELECT event_type, mult_lucky, mult_beli, start_ts, end_ts, channel_id
        FROM server_events
        WHERE guild_id = ?
    """, (gid,))
    row = cursor.fetchone()
    if not row:
        return None

    event_type, ml, mb, start_ts, end_ts, ch = row

    if int(end_ts) <= t:
        # ✅ BUG A: limpa do banco quando expira
        if event_type is not None:
            clear_server_event(guild_id)
        return None

    return {
        "type": event_type,
        "lucky": float(ml),
        "beli": float(mb),
        "start": int(start_ts),
        "end": int(end_ts),
        "channel_id": ch
    }

def ensure_server_event_row(guild_id: int):
    gid = str(guild_id)
    cursor.execute("SELECT 1 FROM server_events WHERE guild_id = ?", (gid,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO server_events (guild_id, event_type, mult_lucky, mult_beli, start_ts, end_ts, channel_id)
            VALUES (?, NULL, 1.0, 1.0, 0, 0, NULL)
        """, (gid,))
        conn.commit()

def get_user_buff_mult(uid: str, guild_id: int) -> Dict[str, float]:
    gid = str(guild_id)
    t = now_ts()
    cursor.execute("""
        SELECT buff_type, mult, end_ts
        FROM user_buffs
        WHERE user_id = ? AND guild_id = ?
    """, (uid, gid))
    rows = cursor.fetchall()

    out = {"lucky": 1.0, "beli": 1.0}
    for btype, mult, end_ts in rows:
        if int(end_ts) > t:
            if btype in out:
                out[btype] = max(out[btype], float(mult))
    return out

def get_total_mults(uid: str, guild_id: int) -> Dict[str, float]:
    event = get_active_server_event(guild_id)
    buffs = get_user_buff_mult(uid, guild_id)

    total_lucky = buffs["lucky"] * (event["lucky"] if event else 1.0)
    total_beli  = buffs["beli"]  * (event["beli"]  if event else 1.0)

    return {"lucky": total_lucky, "beli": total_beli, "event": event}

def apply_beli_mult(amount: int, mult: float) -> int:
    # arredonda pra não perder “sensação de ganho”
    return int(round(int(amount) * float(mult)))


def seed_redeem_codes():
    rows = []
    for code, data in CODES.items():
        code_norm = code.strip().upper()
        rows.append((code_norm, int(data.get("giros", 0)), int(data.get("beli", 0)), 1))

    cursor.executemany("""
        INSERT OR IGNORE INTO redeem_codes (code, reward_giros, reward_beli, enabled)
        VALUES (?, ?, ?, ?)
    """, rows)
    conn.commit()


def sync_inventory_rarities():
    for personagem, data in PERSONAGENS.items():
        rar = data["raridade"]
        cursor.execute("""
            UPDATE inventory
            SET raridade = ?
            WHERE personagem = ?
        """, (rar, personagem))
    conn.commit()

def roll_daily_giros() -> int:
    """
    Gera de 1 a 10 giros SEMPRE.
    Distribuição estilo gacha (mais comum ganhar pouco, mas dá pra vir alto).
    Ajuste os pesos se quiser.
    """
    giros_vals = [1,2,3,4,5,6,7,8,9,10]
    weights   = [22,18,14,12,10,8,6,4,3,3]  # soma 100
    return random.choices(giros_vals, weights=weights, k=1)[0]


async def daily_cinematic_message(ctx: commands.Context) -> discord.Message:
    embed = discord.Embed(
        title="🎁 DAILY REWARD",
        description="Iniciando resgate...",
        color=discord.Color.dark_grey()
    )
    embed.set_footer(text="⏳ Aguarde...")
    msg = await ctx.send(embed=embed)

    await asyncio.sleep(0.6)
    embed.description = "🔎 Verificando registro diário..."
    await msg.edit(embed=embed)

    await asyncio.sleep(0.7)
    embed.description = "🧩 Girando a roleta de recompensas..."
    await msg.edit(embed=embed)

    await asyncio.sleep(0.7)
    embed.description = "✨ Canalizando energia..."
    await msg.edit(embed=embed)

    await asyncio.sleep(0.6)
    embed.description = "📦 Abrindo o pacote diário..."
    await msg.edit(embed=embed)

    await asyncio.sleep(0.5)
    return msg


def fmt_currency(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def day_key_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())

def get_user(uid: str):
    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (user_id, beli, giros, equipado, last_daily, pity_legendary, roll_hour_window, roll_hour_count, last_roll_ts)
            VALUES (?, 0, 1, NULL, 0, 0, 0, 0, 0)
        """, (uid,))
        conn.commit()

def raridades_disponiveis() -> List[str]:
    disponiveis = set(data["raridade"] for data in PERSONAGENS.values())
    return [r for r in ORDEM_RARIDADES if r in disponiveis]


def pick_rarity_with_pity(pity: int, lucky_mult: float = 1.0) -> str:
    permitidas = raridades_disponiveis()

    if pity >= PITY_LEGENDARY_ROLLS:
        if "Lendário" in permitidas:
            return "Lendário"
        return random.choice(permitidas)

    rar_list = permitidas[:]
    base_weights = [float(RARIDADES[r]["chance"]) for r in rar_list]

    # Lucky buff: aumenta o peso das raridades altas (Raro+)
    boosted = []
    for r, w in zip(rar_list, base_weights):
        if r in ("Raro", "Épico", "Lendário", "Mítico", "Secreto"):
            boosted.append(w * lucky_mult)
        else:
            boosted.append(w)

    return random.choices(rar_list, weights=boosted, k=1)[0]


def pick_character_in_rarity(raridade: str) -> str:
    candidatos = [nome for nome, data in PERSONAGENS.items() if data["raridade"] == raridade]
    if not candidatos:
        return random.choice(list(PERSONAGENS.keys()))
    return random.choice(candidatos)

def sortear_personagem_normal(pity: int, lucky_mult: float = 1.0) -> Tuple[str, str]:
    rar = pick_rarity_with_pity(pity, lucky_mult=lucky_mult)
    personagem = pick_character_in_rarity(rar)
    return personagem, rar


def sortear_personagem_com_pity() -> Tuple[str, str]:
    # Se cair aqui, é porque o pity bateu: lendário garantido
    rar = "Lendário"
    personagem = pick_character_in_rarity(rar)
    return personagem, rar

def update_history(uid: str, personagem: str, raridade: str):
    now = int(time.time())
    cursor.execute(
        "INSERT INTO roll_history (user_id, ts, personagem, raridade) VALUES (?, ?, ?, ?)",
        (uid, now, personagem, raridade)
    )

    # mantém no máximo 80 registros por pessoa (robusto mesmo com ts repetido)
    cursor.execute("""
        DELETE FROM roll_history
        WHERE user_id = ?
        AND rowid NOT IN (
            SELECT rowid FROM roll_history
            WHERE user_id = ?
            ORDER BY ts DESC, rowid DESC
            LIMIT 80
        )
    """, (uid, uid))

def get_last_history(uid: str, limit: int = 5) -> List[Tuple[int, str, str]]:
    cursor.execute("""
        SELECT ts, personagem, raridade
        FROM roll_history
        WHERE user_id = ?
        ORDER BY ts DESC
        LIMIT ?
    """, (uid, limit))
    return cursor.fetchall()

def chunk_list(items: List, size: int) -> List[List]:
    return [items[i:i+size] for i in range(0, len(items), size)]

def ordenar_itens(itens: List[Tuple[str, str, int]]) -> List[Tuple[str, str, int]]:
    ordem_idx = {r: i for i, r in enumerate(ORDEM_RARIDADES)}
    return sorted(itens, key=lambda x: (ordem_idx.get(x[1], 999), x[0].lower()))

def bar_progress(value: int, total: int, size: int = 10) -> str:
    if total <= 0:
        return "░" * size
    filled = int((value / total) * size)
    filled = max(0, min(size, filled))
    return "█" * filled + "░" * (size - filled)

def get_all_craft_missions(uid: str, recipe: str):
    ensure_craft_board(uid, recipe)
    cursor.execute("""
        SELECT mission_id, title, event, progress, goal, reward_item, reward_qty, claimed
        FROM craft_missions
        WHERE user_id = ? AND recipe = ?
        ORDER BY mission_id ASC
    """, (uid, recipe))
    return cursor.fetchall()

def get_current_mission_index(rows) -> int:
    for i, row in enumerate(rows):
        if int(row[7]) == 0:  # claimed == 0
            return i
    return -1

def build_craft_embed_preview(uid: str, recipe: str, preview_offset: int = 0) -> discord.Embed:
    """
    preview_offset=0 => missão atual (ativa)
    preview_offset>0 => preview da próxima (não progride ainda)
    """
    r = CRAFT_RECIPES[recipe]
    color = r["color"]
    items = get_craft_items(uid)

    # requisitos de personagem
    req_chars = r.get("requires_chars", [])
    req_lines = []
    if req_chars:
        for p in req_chars:
            ok = _has_character(uid, p)
            req_lines.append(f"{'✅' if ok else '❌'} {p}")
    else:
        req_lines.append("Nenhum requisito de personagem.")

    # custo final bonito
    cost = r["final_cost"]
    cost_lines = []
    for k, v in cost.items():
        have = items.get(k, 0)
        cost_lines.append(item_line(k, have, v))

    rows = get_all_craft_missions(uid, recipe)
    cur_idx = get_current_mission_index(rows)

    embed = discord.Embed(
        title=f"🧪 Craft Secreto — {_recipe_label(recipe)}",
        description="Você progride **uma missão por vez** (ordem do mais fácil → mais difícil).",
        color=color
    )
    embed.add_field(name="📌 Requisitos", value="\n".join(req_lines), inline=False)
    embed.add_field(name="🧰 Componentes finais", value="\n".join(cost_lines) if cost_lines else "—", inline=False)

    # craft concluído
    if cur_idx == -1 or not rows:
        embed.add_field(
            name="🎉 Status",
            value="Você já concluiu todas as missões desse craft. Se tiver os componentes, use `!craft`.",
            inline=False
        )
        embed.set_footer(text="Comandos: !craft | !craftcancel")
        return embed

    # alvo = atual + offset, com clamp
    max_offset = max(0, len(rows) - 1 - cur_idx)
    preview_offset = max(0, min(int(preview_offset), max_offset))
    target_idx = cur_idx + preview_offset
    mid, title, ev, prog, goal, reward_item, reward_qty, claimed = rows[target_idx]

    is_preview = preview_offset > 0

    if int(claimed) == 1:
        status = "✅ Coletado"
    elif is_preview:
        status = "👀 Preview (ainda bloqueada)"
    else:
        status = "🎁 Pronto pra coletar" if int(prog) >= int(goal) else "⏳ Em progresso"

    # barra: só faz sentido na missão ativa; no preview, mostra só o goal (mais limpo)
    if is_preview:
        progress_txt = f"Meta: **{goal}**"
    else:
        progress_txt = f"{bar_progress(min(int(prog), int(goal)), int(goal))} **{prog}/{goal}**"

    embed.add_field(
        name=f"📜 {'Missão atual' if not is_preview else 'Próxima missão'} ({target_idx+1}/{len(rows)})",
        value=f"**`{mid}`** — {status}\n{progress_txt}",
        inline=False
    )
    embed.add_field(name="📝 Como completar", value=title, inline=False)
    embed.add_field(name="🎁 Recompensa", value=f"+{reward_qty} {item_name(str(reward_item))}", inline=False)

    if is_preview:
        embed.set_footer(text="Preview não progride. Use ➡️ para ver mais ou voltar para a missão atual.")
    else:
        embed.set_footer(text="Use 🎁 para coletar quando ficar pronto. Depois a próxima missão libera.")

    return embed


# ======================
# MISSÕES (NOVO SISTEMA)
# ======================

def missions_catalog() -> List[Dict]:
    # event:
    #  - roll_use: conta 1 por comando !roll
    #  - roll_spin: conta giros usados (1 ou 10)
    #  - roll10_use: conta 1 quando usar !roll 10
    #  - sell_count: conta quantidade vendida
    #  - equip_use: conta equips
    #  - high_pull: conta quantos Lendário dropou (no seu código: só Lendário conta)

    return [
        # ======================
        # FÁCEIS (bônus leve: 0–1 giro)
        # ======================
        {"id":"E1", "tier":"easy", "title":"🎰 Usar 3 giros", "event":"roll_spin", "goal":3, "beli":350, "giros":1},
        {"id":"E2", "tier":"easy", "title":"🎰 Usar 6 giros", "event":"roll_spin", "goal":6, "beli":500, "giros":1},
        {"id":"E3", "tier":"easy", "title":"🪙 Vender 5 personagens", "event":"sell_count", "goal":5, "beli":450, "giros":1},
        {"id":"E4", "tier":"easy", "title":"🎭 Equipar 1 personagem", "event":"equip_use", "goal":1, "beli":250, "giros":1},
        {"id":"E5", "tier":"easy", "title":"🎰 Usar o comando !roll 4 vezes", "event":"roll_use", "goal":4, "beli":450, "giros":0},
        {"id":"E6", "tier":"easy", "title":"⚡ Fazer 1 roll 10", "event":"roll10_use", "goal":1, "beli":650, "giros":1},

        # ======================
        # MÉDIAS (1–2 giros)
        # ======================
        {"id":"M1", "tier":"medium", "title":"🎰 Usar 15 giros", "event":"roll_spin", "goal":15, "beli":950, "giros":2},
        {"id":"M2", "tier":"medium", "title":"🎰 Usar 25 giros", "event":"roll_spin", "goal":25, "beli":1300, "giros":2},
        {"id":"M3", "tier":"medium", "title":"🪙 Vender 15 personagens", "event":"sell_count", "goal":15, "beli":1100, "giros":2},
        {"id":"M4", "tier":"medium", "title":"🎭 Equipar 3 vezes", "event":"equip_use", "goal":3, "beli":900, "giros":2},
        {"id":"M5", "tier":"medium", "title":"⚡ Fazer 2 roll 10", "event":"roll10_use", "goal":2, "beli":1200, "giros":2},
        {"id":"M6", "tier":"medium", "title":"🎰 Usar o comando !roll 12 vezes", "event":"roll_use", "goal":12, "beli":1200, "giros":1},

        # ======================
        # DIFÍCEIS (2–4 giros)
        # ======================
        {"id":"H1", "tier":"hard", "title":"🌟 Conseguir 1 Lendário", "event":"high_pull", "goal":1, "beli":2200, "giros":4},
        {"id":"H2", "tier":"hard", "title":"🎰 Usar 60 giros", "event":"roll_spin", "goal":60, "beli":2400, "giros":3},
        {"id":"H3", "tier":"hard", "title":"🪙 Vender 40 personagens", "event":"sell_count", "goal":40, "beli":2100, "giros":3},
        {"id":"H4", "tier":"hard", "title":"⚡ Fazer 5 roll 10", "event":"roll10_use", "goal":5, "beli":2300, "giros":3},

        # ======================
        # BEM DIFÍCEIS (4–7 giros)
        # ======================
        {"id":"VH1", "tier":"veryhard", "title":"👑 Conseguir 2 Lendários", "event":"high_pull", "goal":2, "beli":4500, "giros":7},
        {"id":"VH2", "tier":"veryhard", "title":"🎰 Usar 140 giros", "event":"roll_spin", "goal":140, "beli":4800, "giros":6},
        {"id":"VH3", "tier":"veryhard", "title":"🪙 Vender 120 personagens", "event":"sell_count", "goal":120, "beli":4200, "giros":5},
        {"id":"VH4", "tier":"veryhard", "title":"⚡ Fazer 10 roll 10", "event":"roll10_use", "goal":10, "beli":5000, "giros":6},
    ]

# ======================
# MISSÕES CRAFTS
# ======================

CRAFT_RECIPES = {
    "sukuna": {
        "label": "🟥 Ryomen Sukuna",
        "target_personagem": "Ryomen Sukuna",
        "requires_chars": ["Yuji Itadori", "Megumi Fushiguro"],  # precisa ter no inventário
        "final_cost": {"finger_sukuna": 20},
        "emoji": "🩸",
        "color": discord.Color.red()
    },
    "gojo": {
        "label": "⚪ Satoru Gojo",
        "target_personagem": "Satoru Gojo",
        "requires_chars": [],  # opcional; você pode exigir algo aqui também
        "final_cost": {"eye_gojo": 6},
        "emoji": "♾️",
        "color": discord.Color.from_rgb(240, 240, 255)
    },
    "yuta": {
        "label": "🟥⚪ Yuta (Gojo Body)",
        "target_personagem": "Yuta Okkotsu (Gojo Body)",
        "requires_chars": ["Suguru Geto", "Yuta Okkotsu", "Rika Orimoto"],
        "final_cost": {"core_yuta": 1, "seal_fragment": 12},  # “núcleo” + fragmentos
        "emoji": "🧬",
        "color": discord.Color.red()
    },
}

def craft_missions_catalog(recipe: str) -> List[Dict]:
    # eventos disponíveis:
    # roll_spin, roll_use, roll10_use, sell_count, equip_use, high_pull

    if recipe == "sukuna":
        # 20 dedos, crescendo de leve -> pesado
        # alterna sell/spin e a cada 5 dá lendário
        spin_goals = [60, 70, 80, 90, 100, 100, 110, 120]      # nerf vs 120 fixo
        sell_goals = [80, 90, 100, 110, 120, 130, 140, 150]    # nerf vs 160 fixo
        missions = []
        si = 0
        vi = 0

        for i in range(1, 21):
            mid = f"S{i:02d}"
            if i % 5 == 0:
                missions.append({
                    "id": mid,
                    "title": f"🩸 Dedo {i}/20 — Puxar 1 Lendário",
                    "event":"high_pull",
                    "goal":1,
                    "item":"finger_sukuna",
                    "qty":1
                })
            elif i % 2 == 0:
                goal = spin_goals[min(si, len(spin_goals)-1)]
                si += 1
                missions.append({
                    "id": mid,
                    "title": f"🎰 Dedo {i}/20 — Usar {goal} giros",
                    "event":"roll_spin",
                    "goal":goal,
                    "item":"finger_sukuna",
                    "qty":1
                })
            else:
                goal = sell_goals[min(vi, len(sell_goals)-1)]
                vi += 1
                missions.append({
                    "id": mid,
                    "title": f"🪙 Dedo {i}/20 — Vender {goal} personagens",
                    "event":"sell_count",
                    "goal":goal,
                    "item":"finger_sukuna",
                    "qty":1
                })
        return missions

    if recipe == "gojo":
        # 6 olhos: ainda difícil, mas nerfado
        return [
            {"id":"G01", "title":"🎰 Six Eyes I — Usar 450 giros", "event":"roll_spin", "goal":450, "item":"eye_gojo", "qty":1},
            {"id":"G02", "title":"⚡ Six Eyes II — Fazer 25 roll 10", "event":"roll10_use", "goal":25, "item":"eye_gojo", "qty":1},
            {"id":"G03", "title":"🪙 Six Eyes III — Vender 850 personagens", "event":"sell_count", "goal":850, "item":"eye_gojo", "qty":1},
            {"id":"G04", "title":"🧤 Six Eyes IV — Equipar 40 vezes", "event":"equip_use", "goal":40, "item":"eye_gojo", "qty":1},
            {"id":"G05", "title":"👑 Six Eyes V — Puxar 4 Lendários", "event":"high_pull", "goal":4, "item":"eye_gojo", "qty":1},
            {"id":"G06", "title":"🎲 Six Eyes VI — Usar !roll 160 vezes", "event":"roll_use", "goal":160, "item":"eye_gojo", "qty":1},
        ]

    if recipe == "yuta":
        # 12 fragmentos + core (core você já vai ganhar automático no claim final, pelo patch que te mandei)
        # nerf geral: giros e roll10 menores, lendário 1 (ao invés de 2)
        missions = []
        spin_goals = [120, 130, 140, 150, 160, 170]  # nerf vs 220 fixo
        r10_goals  = [8, 9, 10, 11, 12]              # nerf vs 18 fixo
        si = 0
        ri = 0

        for i in range(1, 13):
            mid = f"Y{i:02d}"
            if i in (4, 8, 12):
                missions.append({"id": mid, "title": f"👑 Fragmento {i}/12 — Puxar 1 Lendário", "event":"high_pull", "goal":1, "item":"seal_fragment", "qty":1})
            elif i % 2 == 0:
                goal = r10_goals[min(ri, len(r10_goals)-1)]
                ri += 1
                missions.append({"id": mid, "title": f"⚡ Fragmento {i}/12 — Fazer {goal} roll 10", "event":"roll10_use", "goal":goal, "item":"seal_fragment", "qty":1})
            else:
                goal = spin_goals[min(si, len(spin_goals)-1)]
                si += 1
                missions.append({"id": mid, "title": f"🎰 Fragmento {i}/12 — Usar {goal} giros", "event":"roll_spin", "goal":goal, "item":"seal_fragment", "qty":1})
        return missions

    return []



def get_active_craft(uid: str) -> Optional[str]:
    cursor.execute("SELECT active_recipe FROM craft_trackers WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    return row[0] if row and row[0] else None

def set_active_craft(uid: str, recipe: Optional[str]):
    cursor.execute("""
        INSERT INTO craft_trackers(user_id, active_recipe, started_ts)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET active_recipe = excluded.active_recipe,
                                          started_ts = excluded.started_ts
    """, (uid, recipe, now_ts() if recipe else 0))
    conn.commit()

def ensure_craft_board(uid: str, recipe: str):
    # cria missões no banco se não existirem
    catalog = craft_missions_catalog(recipe)

    for m in catalog:
        cursor.execute("""
            INSERT OR IGNORE INTO craft_missions
            (user_id, recipe, mission_id, title, event, goal, progress, reward_item, reward_qty, claimed)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 0)
        """, (
            uid, recipe, m["id"], m["title"], m["event"], int(m["goal"]),
            m["item"], int(m["qty"])
        ))
    conn.commit()

def get_craft_missions(uid: str, recipe: str) -> List[Tuple]:
    ensure_craft_board(uid, recipe)
    cursor.execute("""
        SELECT mission_id, title, event, progress, goal, reward_item, reward_qty, claimed
        FROM craft_missions
        WHERE user_id = ? AND recipe = ?
        ORDER BY mission_id ASC
    """, (uid, recipe))
    return cursor.fetchall()


def add_craft_event(uid: str, event: str, amount: int = 1):
    recipe = get_active_craft(uid)
    if not recipe:
        return

    cur = get_current_craft_mission(uid, recipe)
    if not cur:
        return

    mid, title, ev, prog, goal, item, qty, claimed = cur

    # só progride se o evento bater com o da missão atual
    if ev != event:
        return

    new_prog = min(int(goal), int(prog) + int(amount))
    cursor.execute("""
        UPDATE craft_missions
        SET progress = ?
        WHERE user_id = ? AND recipe = ? AND mission_id = ?
    """, (new_prog, uid, recipe, mid))

    conn.commit()



def craft_claim(uid: str, recipe: str, mission_id: str) -> Tuple[bool, str]:
    ensure_craft_board(uid, recipe)

    cursor.execute("""
        SELECT title, progress, goal, reward_item, reward_qty, claimed
        FROM craft_missions
        WHERE user_id = ? AND recipe = ? AND mission_id = ?
    """, (uid, recipe, mission_id))
    row = cursor.fetchone()
    if not row:
        return False, "Missão de craft não encontrada."

    title, prog, goal, item, qty, claimed = row
    if int(claimed) == 1:
        return False, "Você já coletou essa missão."
    if int(prog) < int(goal):
        return False, f"Você ainda não completou: **{title}**"

    try:
        begin_immediate_with_retry()

        cursor.execute("""
            UPDATE craft_missions
            SET claimed = 1
            WHERE user_id = ? AND recipe = ? AND mission_id = ?
        """, (uid, recipe, mission_id))

        # ✅ recompensa principal (sem commit aqui)
        add_craft_item(uid, str(item), int(qty), commit=False)

        # ✅ se for Yuta, e agora tudo ficou claimed, dá o core automaticamente
        if recipe == "yuta":
            _maybe_grant_yuta_core(uid)

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    bonus = ""
    if recipe == "yuta":
        # só pra dar um feedbackzinho quando o core aparecer
        items_now = get_craft_items(uid)
        if items_now.get("core_yuta", 0) >= 1:
            bonus = "\n🧬 **Núcleo obtido:** +1 `core_yuta`"

    return True, f"Coletou **{title}** → +{qty} `{item}`{bonus}"

def item_name(item_key: str) -> str:
    return ITEM_DISPLAY.get(item_key, item_key)

def item_line(item_key: str, have: int, need: int) -> str:
    # sem mostrar a key feia
    return f"• {item_name(item_key)}: **{have}/{need}**"


def _recipe_label(recipe: str) -> str:
    r = CRAFT_RECIPES.get(recipe)
    return r["label"] if r else recipe

def _has_character(uid: str, personagem: str) -> bool:
    cursor.execute("SELECT 1 FROM inventory WHERE user_id = ? AND personagem = ? AND quantidade > 0", (uid, personagem))
    return cursor.fetchone() is not None

def build_craft_embed(uid: str, recipe: str) -> discord.Embed:
    r = CRAFT_RECIPES[recipe]
    color = r["color"]

    items = get_craft_items(uid)

    # requisitos de personagem
    req_chars = r.get("requires_chars", [])
    req_lines = []
    if req_chars:
        for p in req_chars:
            ok = _has_character(uid, p)
            req_lines.append(f"{'✅' if ok else '❌'} {p}")
    else:
        req_lines.append("Nenhum requisito de personagem.")

    # custo final bonito
    cost = r["final_cost"]
    cost_lines = []
    for k, v in cost.items():
        have = items.get(k, 0)
        cost_lines.append(item_line(k, have, v))

    # missão atual (1 por vez)
    cur = get_current_craft_mission(uid, recipe)

    embed = discord.Embed(
        title=f"🧪 Craft Secreto — {_recipe_label(recipe)}",
        description="Você progride **uma missão por vez** (ordem do mais fácil → mais difícil).",
        color=color
    )

    embed.add_field(name="📌 Requisitos", value="\n".join(req_lines), inline=False)
    embed.add_field(name="🧰 Componentes finais", value="\n".join(cost_lines) if cost_lines else "—", inline=False)

    if not cur:
        embed.add_field(name="🎉 Status", value="Você já concluiu todas as missões desse craft. Se tiver os componentes, use `!craft`.", inline=False)
        embed.set_footer(text="Comandos: !craft | !craftcancel")
        return embed

    mid, title, ev, prog, goal, reward_item, reward_qty, claimed = cur

    status = "🎁 Pronto pra coletar" if int(prog) >= int(goal) else "⏳ Em progresso"
    progress_txt = f"{bar_progress(min(int(prog), int(goal)), int(goal))} **{prog}/{goal}**"

    embed.add_field(name="📜 Missão atual", value=f"**`{mid}`** — {status}\n{progress_txt}", inline=False)
    embed.add_field(name="📝 Como completar", value=title, inline=False)
    embed.add_field(name="🎁 Recompensa", value=f"+{reward_qty} {item_name(str(reward_item))}", inline=False)

    embed.set_footer(text="Comandos: !craftclaim <ID> | !craft | !craftcancel")
    return embed



class CraftBoardView(discord.ui.View):
    """Painel do Craft:
    - 🎁 Coletar missão (só habilita quando a missão atual estiver pronta)
    - ➡️ Próxima missão (preview; não progride)
    """

    def __init__(self, ctx: commands.Context, recipe: str):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.recipe = recipe
        self.preview_offset = 0  # 0 = missão atual

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Só você pode usar esses botões.", ephemeral=True)
            return False
        return True

    def _calc_max_offset(self, uid: str) -> int:
        rows = get_all_craft_missions(uid, self.recipe)
        cur_idx = get_current_mission_index(rows)
        if cur_idx == -1:
            return 0
        return max(0, len(rows) - 1 - cur_idx)

    def _current_claimable(self, uid: str) -> bool:
        cur = get_current_craft_mission(uid, self.recipe)
        if not cur:
            return False
        mid, title, ev, prog, goal, reward_item, reward_qty, claimed = cur
        if int(claimed) == 1:
            return False
        return int(prog) >= int(goal)

    async def _refresh(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        max_off = self._calc_max_offset(uid)
        if self.preview_offset > max_off:
            self.preview_offset = 0

        can_collect = (self.preview_offset == 0 and self._current_claimable(uid))
        self.b_collect.disabled = not can_collect

        embed = build_craft_embed_preview(uid, self.recipe, self.preview_offset)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎁 Coletar missão", style=discord.ButtonStyle.success)
    async def b_collect(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)

        if self.preview_offset != 0:
            await interaction.response.send_message("⚠️ Volte para a missão atual para coletar.", ephemeral=True)
            return

        lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
        async with lock:
            cur = get_current_craft_mission(uid, self.recipe)
            if not cur:
                await interaction.response.send_message("⚠️ Você não tem missão atual.", ephemeral=True)
                return

            mid, title, ev, prog, goal, reward_item, reward_qty, claimed = cur
            if int(claimed) == 1:
                await interaction.response.send_message("⚠️ Essa missão já foi coletada.", ephemeral=True)
                return
            if int(prog) < int(goal):
                await interaction.response.send_message("⏳ Ainda não está pronto pra coletar.", ephemeral=True)
                return

            ok, msg = craft_claim(uid, self.recipe, str(mid))
            if not ok:
                await interaction.response.send_message(f"⚠️ {msg}", ephemeral=True)
                return

        self.preview_offset = 0
        embed = build_craft_embed_preview(uid, self.recipe, self.preview_offset)
        self.b_collect.disabled = not self._current_claimable(uid)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"🎁 {msg}", ephemeral=True)

    @discord.ui.button(label="➡️ Próxima missão", style=discord.ButtonStyle.secondary)
    async def b_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        max_off = self._calc_max_offset(uid)

        if max_off <= 0:
            self.preview_offset = 0
        else:
            self.preview_offset += 1
            if self.preview_offset > max_off:
                self.preview_offset = 0

        await self._refresh(interaction)


class CraftView(discord.ui.View):
    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=120)
        self.ctx = ctx

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Só você pode usar esses botões.", ephemeral=True)
            return False
        return True

    async def _open_panel(self, interaction: discord.Interaction, recipe: str):
        uid = str(interaction.user.id)

        current = get_active_craft(uid)
        if current and current != recipe:
            await interaction.response.send_message(
                f"⚠️ Você já tem um craft ativo: **{_recipe_label(current)}**.\n"
                f"Use `!craftcancel` pra cancelar (não reembolsa progresso).",
                ephemeral=True
            )
            return

        set_active_craft(uid, recipe)
        ensure_craft_board(uid, recipe)

        embed = build_craft_embed_preview(uid, recipe, preview_offset=0)
        await interaction.response.send_message(
            embed=embed,
            view=CraftBoardView(self.ctx, recipe),
            ephemeral=True
        )

    @discord.ui.button(label="🩸 Sukuna", style=discord.ButtonStyle.danger)
    async def b_sukuna(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_panel(interaction, "sukuna")

    @discord.ui.button(label="♾️ Gojo", style=discord.ButtonStyle.secondary)
    async def b_gojo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_panel(interaction, "gojo")

    @discord.ui.button(label="🧬 Yuta (Gojo Body)", style=discord.ButtonStyle.primary)
    async def b_yuta(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_panel(interaction, "yuta")

    @discord.ui.button(label="📜 Ver craft ativo", style=discord.ButtonStyle.success)
    async def b_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        recipe = get_active_craft(uid)
        if not recipe:
            await interaction.response.send_message(
                "Você não tem craft ativo. Clique em um dos botões.",
                ephemeral=True
            )
            return

        embed = build_craft_embed_preview(uid, recipe, preview_offset=0)
        await interaction.response.send_message(
            embed=embed,
            view=CraftBoardView(self.ctx, recipe),
            ephemeral=True
        )


def _tier_pick_counts() -> Dict[str, int]:
    # 8 missões/dia (boa quantidade sem virar grind absurdo)
    return {"easy": 3, "medium": 3, "hard": 1, "veryhard": 1}


def _tier_label(tier: str) -> str:
    return {
        "easy": "🟢 Fácil",
        "medium": "🟦 Média",
        "hard": "🟨 Difícil",
        "veryhard": "🟥 Bem difícil",
    }.get(tier, tier)

def ensure_daily_board(uid: str):
    dk = day_key_utc()

    cursor.execute("""
        SELECT 1 FROM daily_missions
        WHERE user_id = ? AND day_key = ?
        LIMIT 1
    """, (uid, dk))
    if cursor.fetchone():
        return  # já gerado hoje

    catalog = missions_catalog()
    by_tier: Dict[str, List[Dict]] = {"easy": [], "medium": [], "hard": [], "veryhard": []}
    for m in catalog:
        by_tier.setdefault(m["tier"], []).append(m)

    # seed determinístico por (dia + user), assim não muda aleatoriamente
    seed = f"{uid}:{dk}"
    rnd = random.Random(seed)

    picks = []
    counts = _tier_pick_counts()
    for tier, n in counts.items():
        pool = by_tier.get(tier, [])
        if not pool:
            continue
        if len(pool) <= n:
            chosen = pool[:]
        else:
            chosen = rnd.sample(pool, n)
        picks.extend(chosen)

    for m in picks:
        cursor.execute("""
            INSERT OR IGNORE INTO daily_missions
            (user_id, day_key, mission_id, tier, title, goal, reward_beli, reward_giros, progress, claimed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """, (
            uid, dk, m["id"], m["tier"], m["title"], int(m["goal"]),
            int(m.get("beli", 0)), int(m.get("giros", 0))
        ))
    conn.commit()

def add_mission_event(uid: str, event: str, amount: int = 1):
    ensure_daily_board(uid)
    dk = day_key_utc()

    catalog = {m["id"]: m for m in missions_catalog()}

    cursor.execute("""
        SELECT mission_id, progress, goal, claimed
        FROM daily_missions
        WHERE user_id = ? AND day_key = ?
    """, (uid, dk))
    rows = cursor.fetchall()

    for mission_id, progress, goal, claimed in rows:
        m = catalog.get(mission_id)
        if not m:
            continue
        if m["event"] != event:
            continue
        if int(claimed) == 1:
            continue

        new_prog = min(int(goal), int(progress) + int(amount))
        cursor.execute("""
            UPDATE daily_missions
            SET progress = ?
            WHERE user_id = ? AND day_key = ? AND mission_id = ?
        """, (new_prog, uid, dk, mission_id))

    conn.commit()

def get_daily_missions(uid: str) -> List[Tuple]:
    ensure_daily_board(uid)
    dk = day_key_utc()
    cursor.execute("""
        SELECT mission_id, tier, title, progress, goal, reward_beli, reward_giros, claimed
        FROM daily_missions
        WHERE user_id = ? AND day_key = ?
        ORDER BY
            CASE tier
                WHEN 'easy' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'hard' THEN 3
                WHEN 'veryhard' THEN 4
                ELSE 9
            END, mission_id
    """, (uid, dk))
    return cursor.fetchall()

def claim_daily_mission(uid: str, guild_id: int, mission_id: str) -> Tuple[bool, str]:
    ensure_daily_board(uid)
    dk = day_key_utc()

    cursor.execute("""
        SELECT title, progress, goal, reward_beli, reward_giros, claimed
        FROM daily_missions
        WHERE user_id = ? AND day_key = ? AND mission_id = ?
    """, (uid, dk, mission_id))
    row = cursor.fetchone()
    if not row:
        return False, "Missão não encontrada. Use `!missoes`."

    title, progress, goal, rb, rg, claimed = row
    if int(claimed) == 1:
        return False, "Você já coletou essa missão."
    if int(progress) < int(goal):
        return False, f"Você ainda não completou: **{title}**"

    # ✅ aplica multiplicador de Beli (evento global + poção)
    mults = get_total_mults(uid, guild_id)
    beli_mult = mults["beli"]
    rb_final = apply_beli_mult(int(rb), beli_mult)

    try:
        begin_immediate_with_retry()

        if int(rb_final) > 0:
            cursor.execute("UPDATE users SET beli = beli + ? WHERE user_id = ?", (int(rb_final), uid))
        if int(rg) > 0:
            cursor.execute("UPDATE users SET giros = giros + ? WHERE user_id = ?", (int(rg), uid))

        cursor.execute("""
            UPDATE daily_missions
            SET claimed = 1
            WHERE user_id = ? AND day_key = ? AND mission_id = ?
        """, (uid, dk, mission_id))

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    parts = []
    if int(rb_final) > 0:
        parts.append(f"+{fmt_currency(int(rb_final))} Beli")
    if int(rg) > 0:
        parts.append(f"+{int(rg)} Giros")

    bonus_txt = f" (x{beli_mult} Beli)" if beli_mult > 1.0 and int(rb) > 0 else ""
    return True, f"**{title}**{bonus_txt} → " + " / ".join(parts)


def claim_all_daily(uid: str, guild_id: int) -> Tuple[int, str]:
    ensure_daily_board(uid)
    dk = day_key_utc()

    cursor.execute("""
        SELECT mission_id
        FROM daily_missions
        WHERE user_id = ? AND day_key = ? AND claimed = 0 AND progress >= goal
    """, (uid, dk))
    ids = [r[0] for r in cursor.fetchall()]
    if not ids:
        return 0, "Nenhuma missão pronta pra coletar."

    got = 0
    rewards_b = 0
    rewards_g = 0

    # ✅ multipliers (evento/poção)
    mults = get_total_mults(uid, guild_id)
    beli_mult = mults["beli"]

    for mid in ids:
        cursor.execute("""
            SELECT reward_beli, reward_giros
            FROM daily_missions
            WHERE user_id = ? AND day_key = ? AND mission_id = ?
        """, (uid, dk, mid))
        rb, rg = cursor.fetchone()

        rb = apply_beli_mult(int(rb), beli_mult)

        rewards_b += int(rb)
        rewards_g += int(rg)

        cursor.execute("""
            UPDATE daily_missions
            SET claimed = 1
            WHERE user_id = ? AND day_key = ? AND mission_id = ?
        """, (uid, dk, mid))
        got += 1

    if rewards_b > 0:
        cursor.execute("UPDATE users SET beli = beli + ? WHERE user_id = ?", (rewards_b, uid))
    if rewards_g > 0:
        cursor.execute("UPDATE users SET giros = giros + ? WHERE user_id = ?", (rewards_g, uid))

    conn.commit()

    parts = []
    if rewards_b > 0:
        parts.append(f"+{fmt_currency(rewards_b)} Beli")
    if rewards_g > 0:
        parts.append(f"+{rewards_g} Giros")

    bonus_txt = f" (x{beli_mult} Beli)" if beli_mult > 1.0 and rewards_b > 0 else ""
    return got, f"Coletou **{got}** missão(ões){bonus_txt}: " + " / ".join(parts)


# ======================
# PERFIL (embed + view)
# ======================

def build_perfil_embed(
    ctx: commands.Context,
    beli: int,
    giros: int,
    equipado: Optional[str],
    pity: int,
    itens_pagina: List[Tuple[str, str, int]],
    page: int,
    total_pages: int,
    history: List[Tuple[int, str, str]]
) -> discord.Embed:
    color = discord.Color.blue()
    thumb = None

    # ===== estilo do evento (JJK Secret)
    event = get_active_server_event(ctx.guild.id) if ctx.guild else None
    jjk_active = bool(event) and event.get("type") == "jjk_secret"
    # modo do perfil (chars|items) usado pelo view
    if not hasattr(ctx, "_perfil_mode"):
        ctx._perfil_mode = "chars"

    if equipado and equipado in PERSONAGENS:
        rar_eq = PERSONAGENS[equipado]["raridade"]
        color = RARIDADES[rar_eq]["color"]
        thumb = PERSONAGENS[equipado].get("image")
 
    if jjk_active:
        color = discord.Color.dark_red()
        if SECRET_JJK_GIF_URL and (not thumb or "XXXX" in str(thumb)):
            thumb = SECRET_JJK_GIF_URL

    embed = discord.Embed(
        title=f"🧾 Perfil de {ctx.author.name}",
        description="Carteira + Inventário + Pity + Histórico",
        color=color
    )
    if jjk_active:
        # título/descrição corrompidos e aviso no topo
        embed.title = _glitch_heavy(f"🟥 PERFIL — DOMÍNIO ATIVO • {ctx.author.name}", 1.6)
        embed.description = _glitch_heavy("『 SANTUÁRIO MALEVOLENTE 』 — sua sorte foi forçada além do limite.", 1.45)

        try:
            left = max(0, int(event["end"]) - now_ts())
            ml = event.get("lucky", EVENT_MULTS["jjk_secret"][0])
            mb = event.get("beli", EVENT_MULTS["jjk_secret"][1])
            embed.add_field(
                name=_glitch_heavy("🟥 EVENTO SECRETO ATIVO", 1.55),
                value=_glitch_heavy(
                    f"🍀 Lucky **x{ml}** | 💰 Beli **x{mb}**\n"
                    f"⏳ resta **{fmt_duration(left)}**\n"
                    f"⚠️ Durante o evento, o **!roll** fica *bugado* e vermelho.",
                    1.45
                ),
                inline=False
            )
        except Exception:
            embed.add_field(
                name=_glitch_heavy("🟥 EVENTO SECRETO ATIVO", 1.55),
                value=_glitch_heavy("⚠️ Durante o evento, o **!roll** fica *bugado* e vermelho.", 1.4),
                inline=False
            )


    if thumb and thumb.strip() and "XXXX" not in thumb:
        embed.set_thumbnail(url=thumb)

    embed.add_field(
        name="💰 Carteira",
        value=f"**Beli:** {fmt_currency(beli)}\n**Giros:** {giros}",
        inline=True
    )

    embed.add_field(
        name="🎭 Equipado",
        value=(f"**{equipado}**" if equipado else "Nenhum"),
        inline=True
    )

    faltam = max(0, PITY_LEGENDARY_ROLLS - pity)
    embed.add_field(
        name="🎯 Pity Lendário",
        value=f"{bar_progress(pity, PITY_LEGENDARY_ROLLS)} **{pity}/{PITY_LEGENDARY_ROLLS}**\nFaltam: **{faltam}**",
        inline=False
    )

    if history:
        lines = []
        for ts, p, r in history:
            lines.append(f"{RARIDADES[r]['emoji']} **{p}** ({r})")
        embed.add_field(name="🕒 Últimos Rolls", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🕒 Últimos Rolls", value="Sem histórico ainda.", inline=False)

    if not itens_pagina:
        inv_text = "📭 Inventário vazio. Use `!roll`!"
    else:
        ordem_idx = {r: i for i, r in enumerate(ORDEM_RARIDADES)}
        por_rar: Dict[str, List[Tuple[str, int]]] = {}
        for p, r, q in itens_pagina:
            por_rar.setdefault(r, []).append((p, q))

        linhas = []
        for r in sorted(por_rar.keys(), key=lambda rr: ordem_idx.get(rr, 999)):
            linhas.append(f"**{RARIDADES[r]['emoji']} {r}**")
            for p, q in por_rar[r]:
                linhas.append(f"• {p} x{q}")
            linhas.append("")
        inv_text = "\n".join(linhas).strip()

    embed.add_field(
        name=f"🎒 {('Personagens' if getattr(ctx, '_perfil_mode', 'chars') == 'chars' else 'Itens')} — Página {page+1}/{max(1, total_pages)}",
        value=inv_text if inv_text else "—",
        inline=False
    )

    embed.set_footer(text="Comandos: !roll | !perfil | !equipar | !vender | !daily | !loja | !missoes")
    return embed

class PerfilView(discord.ui.View):
    def __init__(self, ctx: commands.Context, char_pages, item_pages, payload):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.char_pages = char_pages
        self.item_pages = item_pages
        self.mode = "chars"  # chars | items
        self.page = 0
        # payload = (uid, beli, giros, equipado, pity, history)
        self.payload = payload

    def _pages(self):
        return self.char_pages if self.mode == "chars" else self.item_pages

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Só quem abriu o perfil pode usar esses botões.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="👥 Personagens", style=discord.ButtonStyle.primary, row=0)
    async def show_chars(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "chars"
        self.page = 0
        await self._update(interaction)

    @discord.ui.button(label="🎒 Itens", style=discord.ButtonStyle.primary, row=0)
    async def show_items(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "items"
        self.page = 0
        await self._update(interaction)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        pages = self._pages()
        if self.mode != "chars" and len(pages) <= 1:
            await self._update(interaction)
            return
        if self.page > 0:
            self.page -= 1
        await self._update(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        pages = self._pages()
        if self.mode != "chars" and len(pages) <= 1:
            await self._update(interaction)
            return
        if self.page < len(pages) - 1:
            self.page += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        uid, beli, giros, equipado, pity, history = self.payload
        pages = self._pages()
        if not pages:
            pages = [[]]
        if self.page >= len(pages):
            self.page = max(0, len(pages) - 1)

        # sinaliza modo pro embed builder
        self.ctx._perfil_mode = self.mode
        embed = build_perfil_embed(
            self.ctx,
            int(beli),
            int(giros),
            equipado,
            int(pity),
            pages[self.page],
            self.page,
            len(pages),
            history
        )

        # habilita/desabilita setas dependendo do modo
        if self.mode == "items" and len(pages) <= 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True
        else:
            self.prev_button.disabled = (self.page <= 0)
            self.next_button.disabled = (self.page >= len(pages) - 1)

        # destaque do modo atual
        self.show_chars.style = discord.ButtonStyle.success if self.mode == "chars" else discord.ButtonStyle.primary
        self.show_items.style = discord.ButtonStyle.success if self.mode == "items" else discord.ButtonStyle.primary

        await interaction.response.edit_message(embed=embed, view=self)

# ======================
# EVENT
# ======================

did_sync = False

@bot.event
async def on_ready():
    global did_sync
    if not did_sync:
        try:
            sync_inventory_rarities()
        except Exception as e:
            print("❌ sync_inventory_rarities falhou:", repr(e))

        try:
            seed_redeem_codes()
        except Exception as e:
            print("❌ seed_redeem_codes falhou:", repr(e))

        did_sync = True

        # inicia loop de eventos
        bot.loop.create_task(event_loop_task())

        # inicia minigames (trabalhos)
        bot.loop.create_task(minigames_loop_task())
        bot.loop.create_task(higuruma_loop_task())

    print(f"✅ Bot online como {bot.user}")


@bot.command()
@commands.cooldown(1, 3, commands.BucketType.user)
async def resgatar(ctx, *, codigo: str = None):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        if not codigo:
            await ctx.send("❌ Use: `!resgatar <código>`")
            return

        code = codigo.strip().upper()

        cursor.execute("""
            SELECT reward_giros, reward_beli, enabled
            FROM redeem_codes
            WHERE code = ?
        """, (code,))
        row = cursor.fetchone()
        if not row:
            await ctx.send("❌ Código inválido ou não existe.")
            return

        reward_giros, reward_beli, enabled = row
        if int(enabled) != 1:
            await ctx.send("❌ Esse código está desativado.")
            return

        now = int(time.time())

        try:
            begin_immediate_with_retry()  # trava escrita (anti-corrida)
            cursor.execute("""
                INSERT INTO redeem_claims (user_id, code, claimed_at)
                VALUES (?, ?, ?)
            """, (uid, code, now))

            cursor.execute("""
                UPDATE users
                SET giros = giros + ?, beli = beli + ?
                WHERE user_id = ?
            """, (int(reward_giros), int(reward_beli), uid))

            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            await ctx.send("⚠️ Você já resgatou esse código.")
            return
        except Exception:
            conn.rollback()
            await ctx.send("❌ Erro ao resgatar. Tente novamente.")
            raise

        parts = []
        if int(reward_giros) > 0:
            parts.append(f"+{int(reward_giros)} Giros")
        if int(reward_beli) > 0:
            parts.append(f"+{fmt_currency(int(reward_beli))} Beli")

        embed = discord.Embed(
            title="🎁 Código resgatado!",
            description=f"Você resgatou: **{code}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Recompensa", value=" / ".join(parts) if parts else "—", inline=False)
        await ctx.send(embed=embed)

@bot.command()
async def roll(ctx, quantidade: int = 1):
    uid = str(ctx.author.id)
    get_user(uid)

    if quantidade not in (1, 10):
        await ctx.send("❌ Use `!roll` (1x) ou `!roll 10` (10x).")
        return

    # ✅ LOCK por usuário (anti-spam concorrente)
    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())

    # se já estiver rodando outro roll do mesmo user, avisa e espera terminar
    if lock.locked() and uid not in LOCK_WARNED:
        LOCK_WARNED.add(uid)
        await ctx.send("⏳ Seu roll anterior ainda está rodando... aguarde terminar.")

    async with lock:
        LOCK_WARNED.discard(uid)

        # =========
        # LEITURA + CHECAGEM
        # =========
        cursor.execute("SELECT giros, pity_legendary FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        if not row:
            await ctx.send("❌ Erro ao carregar seus dados.")
            return

        giros, pity = row

        # ✅ multipliers (evento + poção)
        mults = get_total_mults(uid, ctx.guild.id)
        lucky_mult = mults["lucky"]
        event = mults["event"]

        if giros < quantidade:
            await ctx.send(f"❌ Você precisa de **{quantidade} giros**. (Você tem {giros})")
            return

        # =========
        # CINEMÁTICA DO ROLL (msg única)
        # =========
        msg: Optional[discord.Message] = None
        try:
            if quantidade == 1:
                msg = await roll_cinematic_message(ctx, event=event)
            else:
                msg = await roll10_cinematic_message(ctx, event=event)
        except discord.HTTPException:
            msg = None

        # =========
        # PROCESSO DO ROLL (transação atômica)
        # =========
        try:
            begin_immediate_with_retry()

            resultados: List[Tuple[str, str]] = []
            local_pity = int(pity)
            pity_ativou = False
            high_count = 0
            high_pulls_this_command = 0

            for _ in range(quantidade):
                if local_pity >= PITY_LEGENDARY_ROLLS:
                    personagem, raridade = sortear_personagem_com_pity()
                    pity_ativou = True
                else:
                    personagem, raridade = sortear_personagem_normal(local_pity, lucky_mult=lucky_mult)

                resultados.append((personagem, raridade))

                cursor.execute("""
                    INSERT INTO inventory (user_id, personagem, raridade, quantidade)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(user_id, personagem)
                    DO UPDATE SET
                        quantidade = quantidade + 1,
                        raridade = excluded.raridade
                """, (uid, personagem, raridade))

                update_history(uid, personagem, raridade)

                # ✅ PITY: reseta ao obter lendario, mitico e secreto
                if raridade in ("Lendário", "Mítico", "Secreto"):
                    local_pity = 0
                    if raridade == "Lendário":
                        high_count += 1
                        high_pulls_this_command += 1
                else:
                    local_pity += 1

            cursor.execute("""
                UPDATE users
                SET giros = giros - ?, pity_legendary = ?
                WHERE user_id = ?
            """, (quantidade, local_pity, uid))

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # =========
        # MISSÕES
        # =========
        add_mission_event(uid, "roll_use", 1)            # 1 por comando
        add_mission_event(uid, "roll_spin", quantidade)  # giros usados
        if quantidade == 10:
            add_mission_event(uid, "roll10_use", 1)
        if high_pulls_this_command > 0:
            add_mission_event(uid, "high_pull", high_pulls_this_command)

        # ✅ CRAFT (progresso automático)
        add_craft_event(uid, "roll_use", 1)
        add_craft_event(uid, "roll_spin", quantidade)
        if quantidade == 10:
            add_craft_event(uid, "roll10_use", 1)
        if high_pulls_this_command > 0:
            add_craft_event(uid, "high_pull", high_pulls_this_command)

        # =========
        # MELHOR DROP
        # =========
        ordem_idx = {r: i for i, r in enumerate(ORDEM_RARIDADES)}
        melhor_idx = 999
        melhor = resultados[0]
        for p, r in resultados:
            idx = ordem_idx.get(r, 999)
            if idx < melhor_idx:
                melhor_idx = idx
                melhor = (p, r)

        melhor_personagem, melhor_raridade = melhor

        # =========
        # REVEAL (rápido) -> depois RESULTADO
        # =========
        aura_text = f"🔮 Aura mais forte: **{RARIDADES[melhor_raridade]['emoji']} {melhor_raridade}**"
        reveal = discord.Embed(
            title=f"🎰 GACHA x{quantidade}",
            description=aura_text,
            color=RARIDADES[melhor_raridade]["color"]
        )

        if msg:
            try:
                await msg.edit(embed=reveal)
                await asyncio.sleep(0.9)
            except discord.HTTPException:
                msg = None

        # =========
        # EMBED FINAL (RESULTADO)
        # =========
        embed = discord.Embed(
            title=f"🎰 RESULTADO x{quantidade}",
            description=(
                f"🌟 Melhor drop: **{melhor_personagem}** "
                f"({RARIDADES[melhor_raridade]['emoji']} {melhor_raridade})\n"
                f"⭐ Lendário: **{high_count}**"
            ),
            color=RARIDADES[melhor_raridade]["color"]
        )

        thumb = PERSONAGENS.get(melhor_personagem, {}).get("image")
        if thumb and thumb.strip() and "XXXX" not in thumb:
            embed.set_thumbnail(url=thumb)

        cont: Dict[str, int] = {}
        for _, r in resultados:
            cont[r] = cont.get(r, 0) + 1

        resumo = []
        for r in ORDEM_RARIDADES:
            if r in cont:
                resumo.append(f"{RARIDADES[r]['emoji']} **{r}:** {cont[r]}")
        embed.add_field(name="📊 Resumo", value="\n".join(resumo) if resumo else "—", inline=True)

        faltam = max(0, PITY_LEGENDARY_ROLLS - local_pity)
        embed.add_field(
            name="🎯 Pity (agora)",
            value=f"**{local_pity}/{PITY_LEGENDARY_ROLLS}** (faltam **{faltam}**)",
            inline=True
        )

        if quantidade == 10:
            left, right = [], []
            for i, (p, r) in enumerate(resultados):
                line = f"{RARIDADES[r]['emoji']} **{p}**"
                (left if i < 5 else right).append(line)

            embed.add_field(name="🎁 Drops (1–5)", value="\n".join(left), inline=True)
            embed.add_field(name="🎁 Drops (6–10)", value="\n".join(right), inline=True)
        else:
            p0, r0 = resultados[0]
            embed.add_field(
                name="🎁 Drop",
                value=f"{RARIDADES[r0]['emoji']} **{p0}** ({r0})",
                inline=False
            )

        if pity_ativou:
            embed.set_footer(text="✨ Pity ativou em algum roll (garantiu Lendário).")
        else:
            embed.set_footer(text="Dica: `!perfil` pra ver inventário, pity e histórico.")

        
        # =========
        # VISUAL JJK SECRET (bugado/vermelho)
        # =========
        if event and event.get("type") == "jjk_secret":
            # força estética do domínio
            embed.color = discord.Color.dark_red()
            embed.title = _glitch_heavy(f"🟥 RESULTADO — DOMÍNIO ATIVO x{quantidade}", 1.7)

            try:
                left = max(0, int(event["end"]) - now_ts())
                ml = float(event.get("lucky", EVENT_MULTS["jjk_secret"][0]))
                mb = float(event.get("beli", EVENT_MULTS["jjk_secret"][1]))
                embed.description = _glitch_heavy(
                    f"『 SANTUÁRIO MALEVOLENTE 』\n"
                    f"🍀 Lucky **x{ml}** | 💰 Beli **x{mb}**\n"
                    f"⏳ resta **{fmt_duration(left)}**\n\n"
                    f"⚠️ {ctx.author.mention}… o domínio *observa* seus giros.",
                    1.55
                )
            except Exception:
                # fallback se event não tiver end
                embed.description = _glitch_heavy("『 SANTUÁRIO MALEVOLENTE 』 — o domínio está ativo.", 1.55)

            # imagem/thumbnail
            if SECRET_JJK_GIF_IMPACT_URL:
                embed.set_image(url=SECRET_JJK_GIF_IMPACT_URL)
            elif SECRET_JJK_GIF_URL:
                embed.set_image(url=SECRET_JJK_GIF_URL)

            # footer “corrompido”
            embed.set_footer(text=_glitch_heavy("🟥 EVENTO SECRETO ATIVO • gire até a barreira fechar", 1.6))

# =========
        # CINEMÁTICAS ESPECIAIS (Mítico/Secreto) — agora EDITA a MESMA msg
        # =========
        tem_secreto = any(r == "Secreto" for _, r in resultados)
        tem_mitico = any(r == "Mítico" for _, r in resultados)

        # garante msg (uma única mensagem final)
        if msg is None:
            msg = await ctx.send(embed=embed)

        if tem_secreto:
            for p, r in resultados:
                if r == "Secreto":
                    img = PERSONAGENS.get(p, {}).get("image")
                    await secret_cinematic(ctx, p, image=img, event=event, msg=msg, result_embed=embed)
                    return

        if tem_mitico:
            for p, r in resultados:
                if r == "Mítico":
                    img = PERSONAGENS.get(p, {}).get("image")
                    await mythic_cinematic(ctx, p, image=img, event=event, msg=msg, result_embed=embed)
                    return

        # se não for mítico/secreto, mostra o resultado normal
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException:
            await ctx.send(embed=embed)


@bot.command(aliases=["inv", "carteira"])
async def perfil(ctx):
    uid = str(ctx.author.id)
    get_user(uid)

    cursor.execute("SELECT beli, giros, equipado, pity_legendary FROM users WHERE user_id = ?", (uid,))
    beli, giros, equipado, pity = cursor.fetchone()

    cursor.execute("""
        SELECT personagem, raridade, quantidade
        FROM inventory
        WHERE user_id = ?
    """, (uid,))
    itens = ordenar_itens(cursor.fetchall())

    pages = chunk_list(itens, ITENS_POR_PAGINA)
    if not pages:
        pages = [[]]

    history = get_last_history(uid, 5)


    # ===== itens (essências + consumíveis + kamutoke)
    craft = get_craft_items(uid)
    cons = get_consumables(uid)

    item_rows: List[Tuple[str, str, int]] = []

    # essências primeiro (ordem fixa)
    essence_order = [
        "essence_common","essence_uncommon","essence_rare",
        "essence_epic","essence_legendary","essence_mythic","essence_secret"
    ]
    for k in essence_order:
        q = int(craft.get(k, 0))
        if q > 0:
            item_rows.append((item_name(k), "Essências", q))

    # outras coisas de craft (se existirem)
    for k, q in craft.items():
        if k in essence_order:
            continue
        if int(q) > 0:
            item_rows.append((item_name(k), "Materiais", int(q)))

    # poções
    pl = int(cons.get("potion_lucky", 0))
    pb = int(cons.get("potion_beli", 0))
    if pl > 0:
        item_rows.append(("Poção Lucky", "Poções", pl))
    if pb > 0:
        item_rows.append(("Poção Beli", "Poções", pb))

    # kamutoke
    kk = int(cons.get(KAMUTOKE_ITEM_KEY, 0))
    if kk > 0:
        item_rows.append((KAMUTOKE_DISPLAY_NAME, "Kamutoke", kk))

    item_pages = chunk_list(item_rows, ITENS_POR_PAGINA)
    if not item_pages:
        item_pages = [[]]

    # ===== bônus ativos (evento + poções)
    event = get_active_server_event(ctx.guild.id)
    ub_lucky = get_active_user_buff(uid, ctx.guild.id, "lucky")
    ub_beli  = get_active_user_buff(uid, ctx.guild.id, "beli")

    bonus_lines = []

    if event:
        left = int(event["end"]) - now_ts()
        if event.get("type") == "jjk_secret":
            bonus_lines.append(
                _glitch_heavy(
                    f"🟥 Evento Secreto: **SANTUÁRIO MALEVOLENTE** "
                    f"(Lucky x{event['lucky']} | Beli x{event['beli']}) — resta **{fmt_duration(left)}**",
                    1.35
                )
            )
        else:
            bonus_lines.append(
                f"🌐 Evento: **{event['type']}** "
                f"(Lucky x{event['lucky']} | Beli x{event['beli']}) — resta **{fmt_duration(left)}**"
            )

    if ub_lucky:
        left = int(ub_lucky["end"]) - now_ts()
        bonus_lines.append(f"🧪 Poção Lucky (ativa): **x{ub_lucky['mult']}** — resta **{fmt_duration(left)}**")

    if ub_beli:
        left = int(ub_beli["end"]) - now_ts()
        bonus_lines.append(f"🧪 Poção Beli (ativa): **x{ub_beli['mult']}** — resta **{fmt_duration(left)}**")

    if not bonus_lines:
        bonus_lines.append("Sem bônus ativo no momento.")

    # payload agora inclui uid também (pra atualizar itens depois)
    view = PerfilView(ctx, pages, item_pages, (uid, beli, giros, equipado, pity, history))
    await ctx.send(embed=embed, view=view)

@bot.command()
async def equipar(ctx, *, personagem: str):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        if personagem not in PERSONAGENS:
            await ctx.send("❌ Personagem não registrado.")
            return

        # checa se tem no inventário
        cursor.execute("SELECT 1 FROM inventory WHERE user_id = ? AND personagem = ?", (uid, personagem))
        if not cursor.fetchone():
            await ctx.send("❌ Você não possui esse personagem.")
            return

        raridade = PERSONAGENS[personagem]["raridade"]

        role_personagem_id = int(PERSONAGENS[personagem].get("role_id", 0))
        role_raridade_id = int(ROLE_RARIDADE_IDS.get(raridade, 0))

        if role_personagem_id == 0:
            await ctx.send("⚠️ Esse personagem está com `role_id = 0` no dicionário.")
            return
        if role_raridade_id == 0:
            await ctx.send(f"⚠️ Não achei o cargo de raridade para **{raridade}** em `ROLE_RARIDADE_IDS`.")
            return

        role_personagem = ctx.guild.get_role(role_personagem_id)
        role_raridade = ctx.guild.get_role(role_raridade_id)

        if not role_personagem:
            await ctx.send("⚠️ Cargo do personagem não encontrado (ID errado ou cargo apagado).")
            return
        if not role_raridade:
            await ctx.send("⚠️ Cargo da raridade não encontrado (ID errado ou cargo apagado).")
            return

        # ===== remove TODOS cargos de personagem =====
        roles_to_remove = []
        for data in PERSONAGENS.values():
            rid = int(data.get("role_id", 0))
            if rid:
                r = ctx.guild.get_role(rid)
                if r and r in ctx.author.roles:
                    roles_to_remove.append(r)

        # ===== remove TODOS cargos de raridade =====
        for rid in ROLE_RARIDADE_IDS.values():
            r = ctx.guild.get_role(int(rid))
            if r and r in ctx.author.roles:
                roles_to_remove.append(r)

        if roles_to_remove:
            await ctx.author.remove_roles(*roles_to_remove, reason="Troca de personagem/raridade no gacha")

        # ===== adiciona personagem + raridade =====
        await ctx.author.add_roles(role_raridade, role_personagem, reason="Equipar personagem no gacha")

        # salva no banco
        cursor.execute("UPDATE users SET equipado = ? WHERE user_id = ?", (personagem, uid))
        conn.commit()

        # missão
        add_mission_event(uid, "equip_use", 1)
        add_craft_event(uid, "equip_use", 1)

        embed = discord.Embed(
            title="🎭 Equipado!",
            description=f"Você equipou **{personagem}**",
            color=RARIDADES[raridade]["color"]
        )
        embed.add_field(name="⭐ Raridade", value=f"{RARIDADES[raridade]['emoji']} {raridade}", inline=True)
        embed.add_field(name="🏷️ Cargos", value=f"{role_raridade.mention} + {role_personagem.mention}", inline=False)
        await ctx.send(embed=embed)

@bot.command()
async def desequipar(ctx):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        cursor.execute("SELECT equipado FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        equipado = row[0] if row else None

        if not equipado:
            await ctx.send("⚠️ Você não tem personagem equipado.")
            return

        roles_to_remove = []

        # remove cargos de personagem
        for data in PERSONAGENS.values():
            rid = int(data.get("role_id", 0))
            if rid:
                role = ctx.guild.get_role(rid)
                if role and role in ctx.author.roles:
                    roles_to_remove.append(role)

        # remove cargos de raridade
        for rid in ROLE_RARIDADE_IDS.values():
            role = ctx.guild.get_role(int(rid))
            if role and role in ctx.author.roles:
                roles_to_remove.append(role)

        if roles_to_remove:
            await ctx.author.remove_roles(*roles_to_remove, reason="Desequipar personagem no gacha")

        cursor.execute("UPDATE users SET equipado = NULL WHERE user_id = ?", (uid,))
        conn.commit()

        await ctx.send("✅ Personagem desequipado.")


@bot.command()
@commands.cooldown(1, 4, commands.BucketType.user)  # reduz spam e 429
async def daily(ctx):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        now = int(time.time())
        threshold = now - DAILY_COOLDOWN

        # claim atômico: só passa se last_daily <= threshold
        cursor.execute("""
            UPDATE users
            SET last_daily = ?
            WHERE user_id = ?
            AND last_daily <= ?
        """, (now, uid, threshold))
        conn.commit()

        if cursor.rowcount == 0:
            cursor.execute("SELECT last_daily FROM users WHERE user_id = ?", (uid,))
            last = cursor.fetchone()[0]
            faltam = DAILY_COOLDOWN - (now - int(last))
            faltam = max(0, faltam)
            hrs = faltam // 3600
            mins = (faltam % 3600) // 60
            await ctx.send(f"⏳ Você já coletou o daily. Volte em **{hrs}h {mins}m**.")
            return

        # ===== CINEMÁTICA (pode falhar sem quebrar tudo) =====
        msg = None
        try:
            msg = await daily_cinematic_message(ctx)
        except discord.HTTPException:
            msg = None

        # ===== RECOMPENSAS =====
        tiers = [
            ("Comum",   65.0,  (120, 240)),
            ("Incomum", 25.0,  (250, 450)),
            ("Raro",     8.0,  (500, 900)),
            ("Épico",    1.7,  (1000, 1800)),
            ("Lendário", 0.3,  (2000, 3500)),
        ]

        tier_names = [t[0] for t in tiers]
        tier_weights = [t[1] for t in tiers]
        tier_ranges = {t[0]: t[2] for t in tiers}

        tier = random.choices(tier_names, weights=tier_weights, k=1)[0]
        low, high = tier_ranges[tier]
        beli_ganho = random.randint(low, high)
        giros_ganhos = roll_daily_giros()
        mults = get_total_mults(uid, ctx.guild.id)
        beli_ganho = apply_beli_mult(beli_ganho, mults["beli"])

        cursor.execute("""
            UPDATE users
            SET beli = beli + ?, giros = giros + ?
            WHERE user_id = ?
        """, (beli_ganho, giros_ganhos, uid))
        conn.commit()

        tier_color_map = {
            "Comum": discord.Color.dark_grey(),
            "Incomum": discord.Color.light_grey(),
            "Raro": discord.Color.green(),
            "Épico": discord.Color.blue(),
            "Lendário": discord.Color.gold(),
        }
        tier_emoji_map = {
            "Comum": "⬛", "Incomum": "⬜", "Raro": "🟩", "Épico": "🟦", "Lendário": "🟨"
        }

        reveal = discord.Embed(
            title="🎁 DAILY COLETADO!",
            description=f"**{tier_emoji_map.get(tier, '🎁')} Tier: {tier}**",
            color=tier_color_map.get(tier, discord.Color.green())
        )
        reveal.add_field(name="🎟️ Giros", value=f"**+{giros_ganhos}**", inline=True)
        reveal.add_field(name="💰 Beli", value=f"**+{fmt_currency(beli_ganho)}**", inline=True)

        if giros_ganhos >= 8:
            reveal.add_field(name="🔥 SORTE INSANA!", value="Você veio **muito forte** hoje.", inline=False)
        elif giros_ganhos >= 5:
            reveal.add_field(name="✨ Boa!", value="Daily acima da média!", inline=False)
        else:
            reveal.add_field(name="📦 Ok!", value="Garantido é garantido 😈", inline=False)

        reveal.set_footer(text="Volte amanhã para resgatar de novo!")

        if msg:
            try:
                await msg.edit(embed=reveal)
            except discord.HTTPException:
                await ctx.send(embed=reveal)
        else:
            await ctx.send(embed=reveal)

@bot.command()
async def loja(ctx):
    embed = discord.Embed(
        title="🛒 Loja",
        description="Use `!comprar <item> <quantidade>`\nEx: `!comprar giro 3`",
        color=discord.Color.orange()
    )

    embed.add_field(name="🎟️ giro", value=f"{fmt_currency(PRECO_GIRO)} Beli (1 giro)", inline=False)
    embed.add_field(name="🎁 pack5", value=f"{fmt_currency(1200)} Beli (5 giros)", inline=True)
    embed.add_field(name="🎁 pack10", value=f"{fmt_currency(2300)} Beli (10 giros)", inline=True)

    embed.add_field(
        name="🧪 pocaolucky",
        value=f"{fmt_currency(PRECO_POCAO_LUCKY)} Beli (x{POCAO_LUCKY_MULT} Lucky por {POCAO_DURATION//60}min)",
        inline=False
    )
    embed.add_field(
        name="🧪 pocaobeli",
        value=f"{fmt_currency(PRECO_POCAO_BELI)} Beli (x{POCAO_BELI_MULT} Beli por {POCAO_DURATION//60}min)",
        inline=False
    )

    embed.set_footer(text="Use `!usar pocaolucky` ou `!usar pocaobeli` depois de comprar.")
    embed.add_field(
        name=f"⚡ {KAMUTOKE_ITEM_KEY}",
        value=f"{fmt_currency(KAMUTOKE_PRICE_BELI)} Beli + {KAMUTOKE_PRICE_ESSENCE_QTY}x {item_name(KAMUTOKE_PRICE_ESSENCE_KEY)} (1 {KAMUTOKE_DISPLAY_NAME})",
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command()
async def comprar(ctx, item: str = None, quantidade: int = 1):
    uid = str(ctx.author.id)
    get_user(uid)

    if item is None:
        await ctx.send("❌ Use: `!comprar <giro|pack5|pack10|pocaolucky|pocaobeli|kamutoke> <quantidade>`")
        return

    item = item.lower().strip()
    if quantidade <= 0:
        await ctx.send("❌ Quantidade inválida.")
        return

    # ✅ LOCK por usuário
    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        # ======================
        # KAMUTOKE
        # ======================
        if item == "kamutoke":
            # custo: beli + essências
            custo_beli = int(KAMUTOKE_PRICE_BELI) * int(quantidade)
            req = {str(KAMUTOKE_PRICE_ESSENCE_KEY): int(KAMUTOKE_PRICE_ESSENCE_QTY) * int(quantidade)}

            cursor.execute("SELECT beli FROM users WHERE user_id = ?", (uid,))
            beli = int(cursor.fetchone()[0] or 0)
            if beli < custo_beli:
                await ctx.send(f"❌ Beli insuficiente. Precisa de **{fmt_currency(custo_beli)}**.")
                return

            # checa essências
            cur_items = get_craft_items(uid)
            if cur_items.get(KAMUTOKE_PRICE_ESSENCE_KEY, 0) < req[KAMUTOKE_PRICE_ESSENCE_KEY]:
                await ctx.send(
                    f"❌ Faltam essências para comprar o **{KAMUTOKE_DISPLAY_NAME}**.\n"
                    f"Precisa: **{req[KAMUTOKE_PRICE_ESSENCE_KEY]}x {item_name(KAMUTOKE_PRICE_ESSENCE_KEY)}**."
                )
                return

            try:
                begin_immediate_with_retry()
                # desconta beli
                cursor.execute("UPDATE users SET beli = beli - ? WHERE user_id = ?", (custo_beli, uid))
                # consome essências
                for k, v in req.items():
                    cursor.execute(
                        "UPDATE craft_items SET qty = qty - ? WHERE user_id = ? AND item = ? AND qty >= ?",
                        (int(v), uid, k, int(v))
                    )
                    if cursor.rowcount <= 0:
                        raise RuntimeError("Craft items insufficient during transaction")
                cursor.execute("DELETE FROM craft_items WHERE user_id = ? AND qty <= 0", (uid,))
                # dá consumível
                cursor.execute("""
                    INSERT INTO consumables (user_id, item, qty)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item) DO UPDATE SET qty = qty + excluded.qty
                """, (uid, KAMUTOKE_ITEM_KEY, int(quantidade)))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            await ctx.send(
                f"⚡ Você comprou **{quantidade}x {KAMUTOKE_DISPLAY_NAME}**!\n"
                f"Use no julgamento do Higuruma: ele **anula a penalidade** 1x quando você errar."
            )
            return

        # ======================
        # POÇÕES
        # ======================
        if item in ("pocaolucky", "pocaobeli"):
            cursor.execute("SELECT beli FROM users WHERE user_id = ?", (uid,))
            beli = cursor.fetchone()[0]

            if item == "pocaolucky":
                custo_un = PRECO_POCAO_LUCKY
                key = "potion_lucky"
            else:
                custo_un = PRECO_POCAO_BELI
                key = "potion_beli"

            custo_total = custo_un * quantidade

            if beli < custo_total:
                await ctx.send(f"❌ Beli insuficiente. Precisa de **{fmt_currency(custo_total)}**.")
                return

            try:
                begin_immediate_with_retry()
                cursor.execute("UPDATE users SET beli = beli - ? WHERE user_id = ?", (custo_total, uid))
                cursor.execute("""
                    INSERT INTO consumables (user_id, item, qty)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item) DO UPDATE SET qty = qty + excluded.qty
                """, (uid, key, int(quantidade)))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            await ctx.send(f"🧪 Você comprou **{quantidade}x {item}**. Use `!usar {item}`.")
            return

        # ======================
        # KAMUTOKE (proteção do tribunal)
        # ======================
        if item == "kamutoke":
            # custo: beli + essências (craft_items)
            cursor.execute("SELECT beli FROM users WHERE user_id = ?", (uid,))
            beli = int(cursor.fetchone()[0])

            craft = get_craft_items(uid)
            have_ess = int(craft.get(KAMUTOKE_PRICE_ESSENCE_KEY, 0))

            total_beli = int(KAMUTOKE_PRICE_BELI) * int(quantidade)
            total_ess = int(KAMUTOKE_PRICE_ESSENCE_QTY) * int(quantidade)

            if beli < total_beli:
                await ctx.send(f"❌ Beli insuficiente. Precisa de **{fmt_currency(total_beli)}**.")
                return
            if have_ess < total_ess:
                ess_name = ITEM_DISPLAY.get(KAMUTOKE_PRICE_ESSENCE_KEY, KAMUTOKE_PRICE_ESSENCE_KEY)
                await ctx.send(f"❌ Essências insuficientes. Precisa de **{total_ess}x {ess_name}**.")
                return

            try:
                begin_immediate_with_retry()
                # revalida dentro da transação
                cursor.execute("SELECT beli FROM users WHERE user_id = ?", (uid,))
                beli2 = int(cursor.fetchone()[0])
                cursor.execute("SELECT qty FROM craft_items WHERE user_id = ? AND item = ? AND qty > 0", (uid, KAMUTOKE_PRICE_ESSENCE_KEY))
                row = cursor.fetchone()
                have2 = int(row[0]) if row else 0

                if beli2 < total_beli or have2 < total_ess:
                    conn.rollback()
                    await ctx.send("❌ Não foi possível concluir a compra (saldo mudou). Tente de novo.")
                    return

                cursor.execute("UPDATE users SET beli = beli - ? WHERE user_id = ?", (total_beli, uid))
                cursor.execute(
                    "UPDATE craft_items SET qty = qty - ? WHERE user_id = ? AND item = ? AND qty >= ?",
                    (total_ess, uid, KAMUTOKE_PRICE_ESSENCE_KEY, total_ess)
                )
                cursor.execute("DELETE FROM craft_items WHERE user_id = ? AND qty <= 0", (uid,))
                cursor.execute("""
                    INSERT INTO consumables (user_id, item, qty)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item) DO UPDATE SET qty = qty + excluded.qty
                """, (uid, KAMUTOKE_ITEM_KEY, int(quantidade)))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            await ctx.send(f"⚡ Você comprou **{quantidade}x {KAMUTOKE_DISPLAY_NAME}**. Ele será consumido automaticamente se você falhar no tribunal.")
            return

        # ======================
        # GIROS / PACKS
        # ======================
        packs = {
            "giro":  (1, PRECO_GIRO),
            "pack5": (5, 1200),
            "pack10": (10, 2300),
        }

        if item not in packs:
            await ctx.send("❌ Item inválido. Use: `giro`, `pack5`, `pack10`, `pocaolucky`, `pocaobeli`, `kamutoke`.")
            return

        giros_un, custo_un = packs[item]
        giros_total = giros_un * quantidade
        custo_total = custo_un * quantidade

        cursor.execute("SELECT beli FROM users WHERE user_id = ?", (uid,))
        beli = cursor.fetchone()[0]

        if beli < custo_total:
            await ctx.send(f"❌ Beli insuficiente. Precisa de **{fmt_currency(custo_total)}**.")
            return

        for tentativa in range(3):
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("""
                    UPDATE users
                    SET beli = beli - ?, giros = giros + ?
                    WHERE user_id = ?
                """, (custo_total, giros_total, uid))
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                conn.rollback()
                if "locked" in str(e).lower() and tentativa < 2:
                    await asyncio.sleep(0.3)
                    continue
                await ctx.send("❌ Banco de dados ocupado (db locked). Tente de novo em alguns segundos.")
                return

        cursor.execute("SELECT beli, giros FROM users WHERE user_id = ?", (uid,))
        beli_novo, giros_novo = cursor.fetchone()

        embed = discord.Embed(title="🛒 Compra realizada!", color=discord.Color.orange())
        embed.add_field(name="Item", value=item, inline=True)
        embed.add_field(name="Giros", value=f"+{giros_total} (total agora: **{giros_novo}**)", inline=False)
        embed.add_field(name="Custo", value=f"-{fmt_currency(custo_total)} Beli (saldo: **{fmt_currency(beli_novo)}**)", inline=False)
        await ctx.send(embed=embed)

@bot.command()
async def vender(ctx, *, args: str = None):
    if args is None:
        await ctx.send(
            "❌ Use:\n"
            "• `!vender <personagem> <quantidade|all>` (ex: `!vender Mahito 1`)\n"
            "• `!vender <raridade>` (ex: `!vender comuns`)\n"
            "Opcional:\n"
            "• `!vender <raridade> <quantidade>` (ex: `!vender comuns 10`)"
        )
        return

    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        raw = args.strip()

        rarity_alias = {
            "comum": "Comum", "comuns": "Comum",
            "incomum": "Incomum", "incomuns": "Incomum",
            "raro": "Raro", "raros": "Raro",
            "epico": "Épico", "epicos": "Épico", "épico": "Épico", "épicos": "Épico",
            "lendario": "Lendário", "lendarios": "Lendário", "lendário": "Lendário", "lendários": "Lendário",
            "mitico": "Mítico", "miticos": "Mítico", "mítico": "Mítico", "míticos": "Mítico",
            "secreto": "Secreto", "secretos": "Secreto",
        }

        parts_r = raw.rsplit(" ", 1)
        cand_rarity = parts_r[0].strip().lower()
        cand_qty = None

        if len(parts_r) == 2 and parts_r[1].strip().lower() not in ("all", "tudo", "todos"):
            try:
                cand_qty = int(parts_r[1].strip())
                cand_rarity = parts_r[0].strip().lower()
            except ValueError:
                cand_qty = None
                cand_rarity = raw.lower()

        raridade_target = rarity_alias.get(cand_rarity)

        # ==========================
        # 1) VENDER POR RARIDADE
        # ==========================
        if raridade_target:
            cursor.execute("SELECT equipado FROM users WHERE user_id = ?", (uid,))
            equipado = cursor.fetchone()[0]

            cursor.execute("""
                SELECT personagem, quantidade
                FROM inventory
                WHERE user_id = ? AND raridade = ?
                ORDER BY lower(personagem) ASC
            """, (uid, raridade_target))
            rows = cursor.fetchall()

            if not rows:
                await ctx.send(f"⚠️ Você não tem itens da raridade **{raridade_target}**.")
                return

            if equipado:
                cursor.execute("""
                    SELECT 1
                    FROM inventory
                    WHERE user_id = ? AND personagem = ? AND raridade = ?
                """, (uid, equipado, raridade_target))
                if cursor.fetchone():
                    rows = [(p, q) for (p, q) in rows if p != equipado]

            if not rows:
                await ctx.send(f"⚠️ Você só tem **{raridade_target}** equipado. Não dá pra vender.")
                return

            if cand_qty is not None:
                if cand_qty <= 0:
                    await ctx.send("❌ Quantidade inválida.")
                    return
                to_sell_limit = cand_qty
            else:
                to_sell_limit = None

            valor_unit = VALOR_VENDA.get(raridade_target, 0)
            vendido_total = 0
            ganho_total = 0
            detalhes = []

            try:
                begin_immediate_with_retry()

                for personagem, qtd_atual in rows:
                    if to_sell_limit is not None and vendido_total >= to_sell_limit:
                        break

                    qtd_vender = qtd_atual
                    if to_sell_limit is not None:
                        qtd_vender = min(qtd_atual, to_sell_limit - vendido_total)

                    if qtd_vender <= 0:
                        continue

                    cursor.execute("""
                        UPDATE inventory
                        SET quantidade = quantidade - ?
                        WHERE user_id = ? AND personagem = ?
                    """, (qtd_vender, uid, personagem))

                    cursor.execute("""
                        DELETE FROM inventory
                        WHERE user_id = ? AND personagem = ? AND quantidade <= 0
                    """, (uid, personagem))

                    vendido_total += qtd_vender
                    ganho_total += valor_unit * qtd_vender

                    if len(detalhes) < 5:
                        detalhes.append(f"• {personagem} x{qtd_vender}")

                # ✅ APLICA 2X BELI (evento/poção)
                mults = get_total_mults(uid, ctx.guild.id)
                ganho_total = apply_beli_mult(ganho_total, mults["beli"])

                cursor.execute("""
                    UPDATE users
                    SET beli = beli + ?
                    WHERE user_id = ?
                """, (ganho_total, uid))

                conn.commit()
            except Exception:
                conn.rollback()
                await ctx.send("❌ Erro ao vender por raridade. Tente novamente.")
                raise

            if vendido_total > 0:
                add_mission_event(uid, "sell_count", vendido_total)
                add_craft_event(uid, "sell_count", vendido_total)

                # ✅ ESSÊNCIAS
                ess_item, ess_each = ESSENCE_BY_RARITY.get(raridade_target, (None, 0))
                if ess_item:
                    add_craft_item(uid, ess_item, vendido_total * ess_each)

            embed = discord.Embed(title="🪙 Venda por raridade concluída!", color=discord.Color.orange())
            embed.add_field(
                name="Raridade",
                value=f"{RARIDADES[raridade_target]['emoji']} {raridade_target}",
                inline=True
            )
            embed.add_field(name="Quantidade", value=f"x{vendido_total}", inline=True)

            # mostra bônus se estiver ativo
            mults_now = get_total_mults(uid, ctx.guild.id)
            if mults_now["beli"] > 1.0:
                embed.add_field(name="💰 Bônus", value=f"x{mults_now['beli']}", inline=True)

            embed.add_field(name="Recebido", value=f"**+{fmt_currency(ganho_total)} Beli**", inline=False)

            # (opcional) mostrar essências ganhas
            ess_item, ess_each = ESSENCE_BY_RARITY.get(raridade_target, (None, 0))
            if ess_item and vendido_total > 0:
                embed.add_field(
                    name="🧪 Essência",
                    value=f"+{vendido_total * ess_each} `{ess_item}`",
                    inline=True
                )

            if detalhes:
                extra = "\n…" if len(rows) > 5 else ""
                embed.add_field(name="Detalhes", value="\n".join(detalhes) + extra, inline=False)

            if equipado:
                embed.set_footer(text=f"⚠️ O equipado ({equipado}) nunca é vendido.")
            await ctx.send(embed=embed)
            return

        # ==========================
        # 2) VENDER POR PERSONAGEM
        # ==========================
        parts = raw.rsplit(" ", 1)
        if len(parts) != 2:
            await ctx.send(
                "❌ Use: `!vender <personagem> <quantidade|all>`\n"
                "Ou: `!vender <raridade>` (ex: `!vender comuns`)"
            )
            return

        personagem = parts[0].strip()
        qtd_raw = parts[1].strip().lower()

        cursor.execute("""
            SELECT raridade, quantidade
            FROM inventory
            WHERE user_id = ? AND personagem = ?
        """, (uid, personagem))
        row = cursor.fetchone()
        if not row:
            await ctx.send("❌ Você não tem esse personagem no inventário.")
            return

        raridade, qtd_atual = row

        cursor.execute("SELECT equipado FROM users WHERE user_id = ?", (uid,))
        equipado = cursor.fetchone()[0]
        if equipado == personagem:
            await ctx.send("⚠️ Você não pode vender um personagem equipado. Use `!desequipar` primeiro.")
            return

        if qtd_raw in ("all", "tudo", "todos"):
            quantidade = int(qtd_atual)
        else:
            try:
                quantidade = int(qtd_raw)
            except ValueError:
                await ctx.send("❌ Quantidade inválida.")
                return

        if quantidade <= 0 or quantidade > int(qtd_atual):
            await ctx.send(f"❌ Quantidade inválida. Você tem **{qtd_atual}x**.")
            return

        valor_unit = VALOR_VENDA.get(raridade, 0)
        ganho = int(valor_unit) * int(quantidade)

        # ✅ APLICA 2X BELI (evento/poção)
        mults = get_total_mults(uid, ctx.guild.id)
        ganho = apply_beli_mult(ganho, mults["beli"])

        try:
            begin_immediate_with_retry()

            cursor.execute("""
                UPDATE inventory
                SET quantidade = quantidade - ?
                WHERE user_id = ? AND personagem = ?
            """, (quantidade, uid, personagem))

            cursor.execute("""
                DELETE FROM inventory
                WHERE user_id = ? AND personagem = ? AND quantidade <= 0
            """, (uid, personagem))

            cursor.execute("""
                UPDATE users
                SET beli = beli + ?
                WHERE user_id = ?
            """, (ganho, uid))

            conn.commit()
        except Exception:
            conn.rollback()
            await ctx.send("❌ Erro ao vender. Tente novamente.")
            raise

        add_mission_event(uid, "sell_count", quantidade)
        add_craft_event(uid, "sell_count", quantidade)

        # ✅ ESSÊNCIAS
        ess_item, ess_each = ESSENCE_BY_RARITY.get(raridade, (None, 0))
        if ess_item and quantidade > 0:
            add_craft_item(uid, ess_item, quantidade * ess_each)

        embed = discord.Embed(title="🪙 Venda concluída!", color=discord.Color.orange())
        embed.add_field(name="Personagem", value=f"**{personagem}**", inline=False)
        embed.add_field(name="Raridade", value=f"{RARIDADES[raridade]['emoji']} {raridade}", inline=True)
        embed.add_field(name="Quantidade", value=f"x{quantidade}", inline=True)

        if mults["beli"] > 1.0:
            embed.add_field(name="💰 Bônus", value=f"x{mults['beli']}", inline=True)

        embed.add_field(name="Recebido", value=f"**+{fmt_currency(ganho)} Beli**", inline=False)

        # (opcional) mostrar essências ganhas
        if ess_item and quantidade > 0:
            embed.add_field(
                name="🧪 Essência",
                value=f"+{quantidade * ess_each} `{ess_item}`",
                inline=True
            )

        await ctx.send(embed=embed)

        
@bot.command()
async def missoes(ctx):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        missions = get_daily_missions(uid)

        embed = discord.Embed(
            title="📜 Missões do Dia",
            description="Complete e colete recompensas!\nUse: `!claim <ID>` ou `!claimall`",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Exemplo: !claim E2")

        if not missions:
            embed.add_field(name="Sem missões", value="Não consegui gerar suas missões hoje.", inline=False)

            # ✅ adiciona a view também mesmo sem missões (pra craft continuar acessível)
            embed.add_field(
                name="🧪 Craft Secreto",
                value=(
                    "Clique num botão pra iniciar um craft (1 por vez).\n"
                    "🩸 Sukuna: 20 dedos\n"
                    "♾️ Gojo: 6 olhos\n"
                    "🧬 Yuta (Gojo Body): 12 fragmentos + núcleo\n"
                    "Use **📜 Ver craft ativo** pra ver progresso."
                ),
                inline=False
            )

            await ctx.send(embed=embed, view=CraftView(ctx))
            return

        for mid, tier, title, prog, goal, rb, rg, claimed in missions:
            status = "✅ Coletado" if int(claimed) == 1 else ("🎁 Pronto!" if int(prog) >= int(goal) else "⏳ Em progresso")

            reward_parts = []
            if int(rb) > 0:
                reward_parts.append(f"+{fmt_currency(int(rb))} Beli")
            if int(rg) > 0:
                reward_parts.append(f"+{int(rg)} Giros")
            reward_txt = " / ".join(reward_parts) if reward_parts else "—"

            embed.add_field(
                name=f"{_tier_label(tier)} • `{mid}` • {title}",
                value=f"{bar_progress(min(int(prog), int(goal)), int(goal))} **{prog}/{goal}** • {status}\n🎁 {reward_txt}",
                inline=False
            )

        # ✅ view do craft no final
        embed.add_field(
            name="🧪 Craft Secreto",
            value=(
                "Clique num botão pra iniciar um craft (1 por vez).\n"
                "🩸 Sukuna: 20 dedos\n"
                "♾️ Gojo: 6 olhos\n"
                "🧬 Yuta (Gojo Body): 12 fragmentos + núcleo\n"
                "Use **📜 Ver craft ativo** pra ver progresso."
            ),
            inline=False
        )

        await ctx.send(embed=embed, view=CraftView(ctx))



@bot.command()
async def claim(ctx, mission_id: str = None):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        if not mission_id:
            await ctx.send("❌ Use: `!claim <ID>`\nEx: `!claim E2`")
            return

        mission_id = mission_id.strip().upper()

        # pega info ANTES (pra mostrar no embed)
        ensure_daily_board(uid)
        dk = day_key_utc()
        cursor.execute("""
            SELECT tier, title, reward_beli, reward_giros, progress, goal, claimed
            FROM daily_missions
            WHERE user_id = ? AND day_key = ? AND mission_id = ?
        """, (uid, dk, mission_id))
        row = cursor.fetchone()
        if not row:
            await ctx.send("⚠️ Missão não encontrada. Use `!missoes`.")
            return

        tier, title, rb_raw, rg_raw, prog, goal, claimed = row

        # multipliers (evento + poção)
        mults = get_total_mults(uid, ctx.guild.id)
        beli_mult = float(mults["beli"])
        event = mults["event"]

        # chama a função que credita de verdade (já aplica o 2x)
        ok, msg = claim_daily_mission(uid, ctx.guild.id, mission_id)
        if not ok:
            await ctx.send(f"⚠️ {msg}")
            return

        # calcula reward final pra mostrar certinho (espelha o que a função aplicou)
        rb_final = apply_beli_mult(int(rb_raw), beli_mult) if int(rb_raw) > 0 else 0
        rg_final = int(rg_raw)

        # embed
        embed = discord.Embed(
            title="🎁 Missão coletada!",
            description=f"**{title}**\n`{mission_id}` • {_tier_label(tier)}",
            color=discord.Color.green()
        )

        reward_parts = []
        if rb_final > 0:
            reward_parts.append(f"💰 **+{fmt_currency(rb_final)}** Beli")
        if rg_final > 0:
            reward_parts.append(f"🎟️ **+{rg_final}** Giros")

        embed.add_field(
            name="Recompensa",
            value="\n".join(reward_parts) if reward_parts else "—",
            inline=False
        )

        # status / bônus
        bonus_lines = []

        if beli_mult > 1.0 and int(rb_raw) > 0:
            bonus_lines.append(f"💰 Bônus de Beli ativo: **x{beli_mult}**")

        # tempo do evento global
        if event:
            left = int(event["end"]) - now_ts()
            bonus_lines.append(f"🌐 Evento global: **{event['type']}** (resta **{fmt_duration(left)}**)")

        # tempo da poção (buff pessoal)
        ub = get_active_user_buff(uid, ctx.guild.id, "beli")
        if ub and float(ub["mult"]) > 1.0:
            left = int(ub["end"]) - now_ts()
            bonus_lines.append(f"🧪 Poção de Beli: **x{ub['mult']}** (resta **{fmt_duration(left)}**)")

        if not bonus_lines:
            bonus_lines.append("Sem bônus ativo no momento.")

        embed.add_field(name="Bônus", value="\n".join(bonus_lines), inline=False)

        # progresso final (agora deve estar claimed)
        embed.add_field(
            name="Progresso",
            value=f"{bar_progress(int(goal), int(goal))} **{goal}/{goal}** ✅",
            inline=False
        )

        embed.set_footer(text="Use `!missoes` para ver as próximas e `!claimall` para coletar tudo.")
        await ctx.send(embed=embed)


@bot.command()
async def claimall(ctx):
    uid = str(ctx.author.id)
    get_user(uid)

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        # multipliers (evento + poção)
        mults = get_total_mults(uid, ctx.guild.id)
        beli_mult = float(mults["beli"])
        event = mults["event"]

        got, msg = claim_all_daily(uid, ctx.guild.id)
        if got == 0:
            await ctx.send(f"⚠️ {msg}")
            return

        embed = discord.Embed(
            title="🎁 Claim All concluído!",
            description=f"Você coletou **{got}** missão(ões).",
            color=discord.Color.green()
        )

        embed.add_field(name="Resumo", value=msg, inline=False)

        bonus_lines = []
        if beli_mult > 1.0:
            bonus_lines.append(f"💰 Bônus de Beli ativo: **x{beli_mult}**")

        if event:
            left = int(event["end"]) - now_ts()
            bonus_lines.append(f"🌐 Evento global: **{event['type']}** (resta **{fmt_duration(left)}**)")

        ub = get_active_user_buff(uid, ctx.guild.id, "beli")
        if ub and float(ub["mult"]) > 1.0:
            left = int(ub["end"]) - now_ts()
            bonus_lines.append(f"🧪 Poção de Beli: **x{ub['mult']}** (resta **{fmt_duration(left)}**)")

        if not bonus_lines:
            bonus_lines.append("Sem bônus ativo no momento.")

        embed.add_field(name="Bônus", value="\n".join(bonus_lines), inline=False)
        embed.set_footer(text="Boa! `!missoes` pra ver o que falta completar.")
        await ctx.send(embed=embed)


@bot.command(name="set")
async def admin_set(ctx, tipo: str, member: discord.Member, quantidade: int):
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ Apenas o dono do servidor pode usar este comando.")
        return

    tipo = tipo.lower().strip()
    if tipo not in ("giros", "beli"):
        await ctx.send("❌ Tipo inválido. Use `giros` ou `beli`.")
        return

    if quantidade < 0:
        await ctx.send("❌ O valor não pode ser negativo.")
        return

    uid = str(member.id)
    get_user(uid)

    if tipo == "giros":
        cursor.execute("UPDATE users SET giros = ? WHERE user_id = ?", (quantidade, uid))
        msg = f"🎟️ {member.name} agora tem **{quantidade} giros**."
    else:
        cursor.execute("UPDATE users SET beli = ? WHERE user_id = ?", (quantidade, uid))
        msg = f"💰 {member.name} agora tem **{fmt_currency(quantidade)} Beli**."

    conn.commit()
    await ctx.send(msg)

@bot.command()
async def usar(ctx, item: str = None):
    uid = str(ctx.author.id)
    get_user(uid)

    if not item:
        await ctx.send("❌ Use: `!usar pocaolucky` ou `!usar pocaobeli`")
        return

    item = item.lower().strip()
    if item not in ("pocaolucky", "pocaobeli"):
        await ctx.send("❌ Item inválido. Use `pocaolucky` ou `pocaobeli`.")
        return

    key = "potion_lucky" if item == "pocaolucky" else "potion_beli"
    buff_type = "lucky" if item == "pocaolucky" else "beli"
    mult = POCAO_LUCKY_MULT if buff_type == "lucky" else POCAO_BELI_MULT

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        cursor.execute("SELECT qty FROM consumables WHERE user_id = ? AND item = ?", (uid, key))
        row = cursor.fetchone()
        if not row or int(row[0]) <= 0:
            await ctx.send("⚠️ Você não tem essa poção.")
            return

        t = now_ts()

        # ✅ STACK: se já tiver buff ativo, soma tempo a partir do final atual
        current = get_active_user_buff(uid, ctx.guild.id, buff_type)  # usa sua função (já limpa expirado)
        base_end = int(current["end"]) if current else t
        end = int(max(base_end, t) + POCAO_DURATION)

        try:
            begin_immediate_with_retry()

            cursor.execute("""
                UPDATE consumables
                SET qty = qty - 1
                WHERE user_id = ? AND item = ? AND qty > 0
            """, (uid, key))

            cursor.execute("""
                INSERT INTO user_buffs (user_id, guild_id, buff_type, mult, start_ts, end_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id, buff_type)
                DO UPDATE SET
                    mult = excluded.mult,
                    start_ts = CASE
                        WHEN user_buffs.end_ts > ? THEN user_buffs.start_ts
                        ELSE excluded.start_ts
                    END,
                    end_ts = excluded.end_ts
            """, (uid, str(ctx.guild.id), buff_type, float(mult), t, end, t))

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    emoji = "🍀" if buff_type == "lucky" else "💰"
    left = end - now_ts()
    await ctx.send(f"{emoji} Buff ativado! **x{mult} {buff_type.upper()}** — agora falta **{fmt_duration(left)}**.")

@bot.command()
async def craftclaim(ctx, mission_id: str = None):
    uid = str(ctx.author.id)
    get_user(uid)

    recipe = get_active_craft(uid)
    if not recipe:
        await ctx.send("⚠️ Você não tem craft ativo. Use `!missoes` e clique num craft.")
        return

    if not mission_id:
        await ctx.send("❌ Use: `!craftclaim <ID>` (ex: `!craftclaim S01`)")
        return

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        ok, msg = craft_claim(uid, recipe, mission_id.strip().upper())
        if not ok:
            await ctx.send(f"⚠️ {msg}")
            return

        embed = discord.Embed(
            title="🎁 Craft — Recompensa coletada!",
            description=msg,
            color=discord.Color.green()
        )

        items = get_craft_items(uid)
        cost = CRAFT_RECIPES[recipe]["final_cost"]

        lines = []
        for k, v in cost.items():
            lines.append(item_line(k, items.get(k, 0), v))  # ✅ bonito

        embed.add_field(
            name="🧰 Progresso de componentes",
            value="\n".join(lines) if lines else "—",
            inline=False
        )

        await ctx.send(embed=embed)

async def grant_character_to_user(ctx: commands.Context, uid: str, personagem: str, raridade: str, msg: Optional[discord.Message] = None):
    # adiciona no inventário
    cursor.execute("""
        INSERT INTO inventory (user_id, personagem, raridade, quantidade)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id, personagem)
        DO UPDATE SET quantidade = quantidade + 1, raridade = excluded.raridade
    """, (uid, personagem, raridade))
    update_history(uid, personagem, raridade)

    # dá cargos
    role_personagem_id = int(PERSONAGENS[personagem].get("role_id", 0))
    role_raridade_id = int(ROLE_RARIDADE_IDS.get(raridade, 0))

    role_personagem = ctx.guild.get_role(role_personagem_id) if role_personagem_id else None
    role_raridade = ctx.guild.get_role(role_raridade_id) if role_raridade_id else None

    if role_raridade:
        await ctx.author.add_roles(role_raridade, reason="Craft secreto (raridade)")
    if role_personagem:
        await ctx.author.add_roles(role_personagem, reason="Craft secreto (personagem)")

    conn.commit()

@bot.command()
async def craft(ctx, recipe: str = None):
    uid = str(ctx.author.id)
    get_user(uid)

    if not recipe:
        await ctx.send("❌ Use: `!craft sukuna` | `!craft gojo` | `!craft yuta`")
        return

    recipe = recipe.lower().strip()
    if recipe not in CRAFT_RECIPES:
        await ctx.send("❌ Receita inválida. Use: sukuna, gojo, yuta")
        return

    active = get_active_craft(uid)
    if active != recipe:
        await ctx.send(f"⚠️ Seu craft ativo é: **{_recipe_label(active)}** (ou nenhum). Veja em `!missoes`.")
        return

    lock = USER_LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        r = CRAFT_RECIPES[recipe]

        # checa requisitos de personagens
        for p in r.get("requires_chars", []):
            if not _has_character(uid, p):
                await ctx.send(f"❌ Você precisa ter **{p}** no inventário para craftar {r['label']}.")
                return

        # checa se coletou os itens finais
        cost = r["final_cost"]
        if not consume_craft_items(uid, cost):
            await ctx.send("❌ Você ainda não tem todos os componentes finais. Veja o progresso em `!missoes` → 📜 Ver craft ativo.")
            return

        # FINAL: gera “núcleo” automático do Yuta se você quiser (exemplo)
        # Aqui eu mantive no cost, então já consumiu core_yuta e fragmentos.

        personagem = r["target_personagem"]
        raridade = "Secreto"

        # faz um embed “resultado” pra passar pra cinemática
        embed = discord.Embed(
            title="🧪 CRAFT CONCLUÍDO!",
            description=f"Você concluiu o craft de **{personagem}**.",
            color=discord.Color.red()
        )
        embed.add_field(name="⭐ Raridade", value="🟥 Secreto", inline=True)

        # uma msg base pra editar durante a cinemática
        base_msg = await ctx.send(embed=discord.Embed(title="🧪 Forjando...", description="Não pisca.", color=r["color"]))

        # dá o personagem + cargos + inventário (antes da cinemática ou depois; eu prefiro antes pra ficar garantido)
        await grant_character_to_user(ctx, uid, personagem, raridade, msg=base_msg)

        # encerra o craft ativo
        set_active_craft(uid, None)

        # roda cinemática do secreto (a sua já é personalizada por personagem)
        img = PERSONAGENS.get(personagem, {}).get("image")
        event = get_total_mults(uid, ctx.guild.id)["event"]  # só pra title variar se tiver evento
        await secret_cinematic(ctx, personagem, image=img, event=event, msg=base_msg, result_embed=embed)


@bot.command()
async def craftcancel(ctx):
    uid = str(ctx.author.id)
    get_user(uid)

    recipe = get_active_craft(uid)
    if not recipe:
        await ctx.send("Você não tem craft ativo.")
        return

    set_active_craft(uid, None)
    await ctx.send(f"🗑️ Craft cancelado: **{_recipe_label(recipe)}**.\n⚠️ Progresso das missões fica salvo, mas você não progride enquanto não reativar.")

# (removido) comando !essencias — agora fica em !perfil -> Itens

@bot.command(aliases=["comandos"])
async def ajuda(ctx):
    embed = discord.Embed(
        title="📖 Ajuda — Sistema Gacha",
        description="Lista completa de comandos e sistemas disponíveis no bot.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎰 Gacha",
        value=(
            "`!roll` — Rola 1 personagem\n"
            "`!roll 10` — Rola 10 personagens de uma vez\n"
            "`!perfil` — Mostra seus dados, saldo e personagem equipado\n"
            "`!equipar <personagem>` — Equipa um personagem\n"
            "`!desequipar` — Remove o personagem equipado"
        ),
        inline=False
    )

    embed.add_field(
        name="🪙 Economia",
        value=(
            "`!daily` — Resgate diário (24h)\n"
            "`!loja` — Mostra a loja\n"
            "`!comprar <item> <qtd>` — Compra itens da loja\n"
            "`!vender <personagem> <qtd|all>` — Vende personagens\n"
            "`!perfil` — (botão Itens) mostra suas essências/poções/kamutoke"
        ),
        inline=False
    )

    embed.add_field(
        name="📜 Missões",
        value=(
            "`!missoes` — Mostra missões diárias + Craft Secreto\n"
            "`!claim <ID>` — Coleta uma missão diária\n"
            "`!claimall` — Coleta todas as missões prontas"
        ),
        inline=False
    )

    embed.add_field(
        name="🧪 Craft Secreto",
        value=(
            "Inicie pelo painel em `!missoes`\n"
            "• Apenas **1 craft ativo por vez**\n"
            "• Missões em ordem (fácil → difícil)\n"
            "• Progresso automático ao jogar\n\n"
            "`🎁 Coletar missão` — Pelo botão do painel\n"
            "`➡️ Próxima missão` — Preview da próxima missão\n"
            "`!craft` — Finaliza o craft quando completo\n"
            "`!craftcancel` — Cancela o craft ativo"
        ),
        inline=False
    )

    embed.add_field(
        name="⚡ Eventos & Buffs",
        value=(
            "Eventos globais automáticos:\n"
            "• 💰 2x Beli\n"
            "• 🍀 2x Lucky\n"
            "• 👑 2x Lucky + 2x Beli\n\n"
            "Poções:\n"
            "• Poção de Lucky (temporária)\n"
            "• Poção de Beli (temporária)"
        ),
        inline=False
    )

    embed.add_field(
        name="🎁 Códigos",
        value="`!resgatar <código>` — Resgata um código (1x por pessoa)",
        inline=False
    )

    embed.add_field(
        name="🛠️ Admin",
        value=(
            "`!set giros @membro <qtd>`\n"
            "`!set beli @membro <qtd>`"
        ),
        inline=False
    )

    embed.set_footer(text="Dica: jogue normalmente que as missões e crafts evoluem sozinhos 👀")
    await ctx.send(embed=embed)

def _is_guild_admin(ctx: commands.Context) -> bool:
    # dono do servidor OU admin (evita alguém com perm mínima usar)
    if ctx.guild is None:
        return False
    return (ctx.author.id == ctx.guild.owner_id) or ctx.author.guild_permissions.administrator

@bot.command(name="evento")
async def evento(ctx, tipo: str = None, dur_min: int = 5):
    """
    Spawna evento manual (admin).
    Uso:
      !evento lucky 5
      !evento beli 5
      !evento both 5
      !evento jjk 5      (evento secreto JJK: 4x lucky, 2x beli + cinemática + lock chat)
      !evento off
      !evento status
    """
    if ctx.guild is None:
        return

    if not _is_guild_admin(ctx):
        await ctx.send("❌ Só o dono/administrador pode usar esse comando.")
        return

    ensure_server_event_row(ctx.guild.id)

    if tipo is None:
        await ctx.send("Use: `!evento <jjk|lucky|beli|both|status|off> [minutos]`")
        return

    tipo = tipo.strip().lower()

    if tipo == "status":
        active = get_active_server_event(ctx.guild.id)
        if not active:
            await ctx.send("🌑 Nenhum evento ativo no momento.")
            return
        left = max(0, int(active["end"]) - now_ts())
        await ctx.send(
            f"🌟 Evento ativo: **{active['type']}** | 🍀 x{active['lucky']} | 💰 x{active['beli']} | ⏳ falta **{fmt_duration(left)}**"
        )
        return

    if tipo == "off":
        clear_server_event(ctx.guild.id)
        await ctx.send("🧹 Evento encerrado manualmente.")
        return

    if tipo not in ("lucky", "beli", "both", "jjk"):
        await ctx.send("❌ Tipo inválido. Use: `jjk`, `lucky`, `beli`, `both`, `status` ou `off`.")
        return

    # mapeia o alias do evento secreto
    if tipo == "jjk":
        tipo = "jjk_secret"

    dur_min = max(1, int(dur_min))
    duration_s = dur_min * 60

    t = now_ts()
    start = t
    end = t + duration_s

    # pega os multiplicadores do tipo
    ml, mb = EVENT_MULTS[tipo]

    # canal de anúncio: usa DEFAULT_EVENT_CHANNEL_ID se existir, senão canal atual
    channel = None
    ch_id = DEFAULT_EVENT_CHANNEL_ID
    if ch_id:
        channel = ctx.guild.get_channel(int(ch_id))
    if channel is None:
        channel = ctx.channel  # fallback pro canal onde você usou o comando

    # salva evento no banco (isso também impede spawn natural enquanto estiver ativo)
    cursor.execute("""
        UPDATE server_events
        SET event_type = ?, mult_lucky = ?, mult_beli = ?, start_ts = ?, end_ts = ?, channel_id = ?
        WHERE guild_id = ?
    """, (
        tipo, float(ml), float(mb), int(start), int(end),
        str(channel.id) if channel else None,
        str(ctx.guild.id)
    ))
    conn.commit()

    if channel:
        # 👑 BOTH: prelúdio + anúncio padrão
        if tipo == "both":
            await announce_both_prelude(channel)
            await announce_event(ctx.guild, tipo, duration_s, channel)

        # 🟥 JJK SECRET: cinemática louca + lock chat + anúncio final com @everyone
        elif tipo == "jjk_secret":
            await announce_jjk_secret_cinematic(ctx.guild, channel, duration_s)

        # normal (lucky/beli)
        else:
            await announce_event(ctx.guild, tipo, duration_s, channel)

    # REMOVIDO: não manda mensagem de confirmação no canal onde usou o comando
    return


# ======================

@bot.event
async def on_message(message: discord.Message):
    if not message.guild or message.author.bot:
        return

    guild = message.guild
    uid = str(message.author.id)
    content = message.content

    # =========================
    # 1) Código Corrompido
    # =========================
    st = CORRUPTED_STATE.get(guild.id)
    if st and st.active and message.channel.id == st.channel_id:
        if now_ts() <= st.end_ts and st.winner_id is None:
            attempt = normalize_spaces(content).upper()
            if attempt == st.clean.upper():
                st.winner_id = uid
                st.active = False

                giros = random.choice([1, 1, 2, 2, 3])
                beli = random.randint(300, 900)
                _safe_grant(uid, beli=beli, giros=giros)

                embed = discord.Embed(
                    title="🏁 VITÓRIA — CÓDIGO LIMPO",
                    description=(
                        f"👑 <@{uid}> limpou o código primeiro.\n\n"
                        f"🎟️ **+{giros} giros**\n"
                        f"💰 **+{fmt_currency(beli)} beli**\n\n"
                        f"✅ Resposta: **{st.clean}**"
                    ),
                    color=discord.Color.green()
                )
                await message.channel.send(embed=embed)

                # ainda processa comandos normalmente
                await bot.process_commands(message)
                return

    # =========================
    
    # =========================
    # 2) Higuruma — julgamento (sem spam no chat)
    # =========================
    # ✅ Interações do Higuruma acontecem via botões/modals (ephemeral).
    # Nada é validado por mensagem aqui, então o canal não vira bagunça.

    await bot.process_commands(message)


bot.run("TOKEN")