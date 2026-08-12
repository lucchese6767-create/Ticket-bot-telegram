# ============================================================
# TICKET BOT TELEGRAM
# Estilo Ticket King
#
# Python 3.10+
# python-telegram-bot >= 22.0
#
# Variáveis de ambiente:
#
# BOT_TOKEN=TOKEN_DO_BOT
# SUPPORT_CHAT_ID=-1001234567890
# LOG_CHAT_ID=-1001234567890
# OWNER_IDS=123456789,987654321
#
# O SUPPORT_CHAT_ID precisa ser um SUPERGRUPO com:
# - Tópicos/Fórum ativados
# - O bot como administrador
# - Permissão para gerenciar tópicos
# ============================================================

import os
import io
import html
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

SUPPORT_CHAT_ID = int(
    os.getenv("SUPPORT_CHAT_ID", "0")
)

LOG_CHAT_ID = int(
    os.getenv("LOG_CHAT_ID", "0")
)

OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

DATABASE = os.getenv(
    "DATABASE",
    "tickets.db"
)


# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    )
)

logger = logging.getLogger("ticket_bot")


# ============================================================
# CATEGORIAS
# ============================================================

CATEGORIES = {
    "compras": "🛒 Compras",
    "suporte": "🛠️ Suporte",
    "financeiro": "💰 Financeiro",
    "outros": "📦 Outros",
}


# ============================================================
# PRIORIDADES
# ============================================================

PRIORITIES = {
    "baixa": "🟢 Baixa",
    "normal": "🟡 Normal",
    "alta": "🟠 Alta",
    "urgente": "🔴 Urgente",
}


# ============================================================
# CARGOS
# ============================================================

ROLES = {
    "trainee": {
        "name": "🎓 Treinando",
        "level": 1,
    },
    "support": {
        "name": "👨‍💻 Suporte",
        "level": 2,
    },
    "supervisor": {
        "name": "🛡️ Supervisor",
        "level": 3,
    },
    "admin": {
        "name": "👑 Administrador",
        "level": 4,
    },
}


# ============================================================
# BANCO
# ============================================================

def get_db():
    conn = sqlite3.connect(
        DATABASE,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,

            category TEXT NOT NULL,

            status TEXT NOT NULL
                DEFAULT 'open',

            priority TEXT NOT NULL
                DEFAULT 'normal',

            topic_id INTEGER,

            assigned_to INTEGER,

            created_at TEXT NOT NULL,

            closed_at TEXT,

            closed_by INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,

            username TEXT,
            full_name TEXT,

            role TEXT NOT NULL
                DEFAULT 'support',

            added_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_staff (
            ticket_id INTEGER NOT NULL,

            user_id INTEGER NOT NULL,

            added_at TEXT NOT NULL,

            PRIMARY KEY(ticket_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            ticket_id INTEGER NOT NULL,

            sender_id INTEGER NOT NULL,

            sender_type TEXT NOT NULL,

            message_type TEXT,

            content TEXT,

            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            ticket_id INTEGER,

            actor_id INTEGER,

            action TEXT NOT NULL,

            details TEXT,

            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# UTILITÁRIOS
# ============================================================

def now():
    return datetime.now().strftime(
        "%d/%m/%Y %H:%M:%S"
    )


def esc(value):
    if value is None:
        return ""

    return html.escape(str(value))


def user_label(user):

    if user.username:
        return f"@{user.username}"

    return user.full_name or str(user.id)


def row_to_tuple(row):

    if row is None:
        return None

    return tuple(row)


# ============================================================
# PERMISSÕES
# ============================================================

def is_owner(user_id):

    return user_id in OWNER_IDS


def get_staff(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_staff_role(user_id):

    if is_owner(user_id):
        return "admin"

    staff = get_staff(user_id)

    if not staff:
        return None

    return staff["role"]


def has_permission(
    user_id,
    minimum_role="support"
):

    role = get_staff_role(user_id)

    if not role:
        return False

    if role not in ROLES:
        return False

    if minimum_role not in ROLES:
        return False

    return (
        ROLES[role]["level"]
        >= ROLES[minimum_role]["level"]
    )


# ============================================================
# EQUIPE
# ============================================================

def add_staff_db(
    user_id,
    username,
    full_name,
    role="support"
):

    if role not in ROLES:
        role = "support"

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO staff
        (
            user_id,
            username,
            full_name,
            role,
            added_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        full_name,
        role,
        now()
    ))

    conn.commit()
    conn.close()


def remove_staff_db(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM staff
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


def update_staff_role(
    user_id,
    role
):

    if role not in ROLES:
        return False

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE staff
        SET role = ?
        WHERE user_id = ?
    """, (
        role,
        user_id
    ))

    changed = cur.rowcount > 0

    conn.commit()
    conn.close()

    return changed


def list_staff():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        ORDER BY role DESC, added_at ASC
    """)

    rows = cur.fetchall()

    conn.close()

    return rows


# ============================================================
# TICKETS
# ============================================================

def create_ticket(
    user_id,
    username,
    full_name,
    category
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tickets
        (
            user_id,
            username,
            full_name,
            category,
            status,
            priority,
            created_at
        )
        VALUES (?, ?, ?, ?, 'open', 'normal', ?)
    """, (
        user_id,
        username,
        full_name,
        category,
        now()
    ))

    ticket_id = cur.lastrowid

    conn.commit()
    conn.close()

    return ticket_id


def get_ticket(ticket_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE id = ?
        LIMIT 1
    """, (ticket_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_open_ticket(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE user_id = ?
        AND status = 'open'
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_ticket_by_topic(topic_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE topic_id = ?
        AND status = 'open'
        LIMIT 1
    """, (topic_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_all_open_tickets():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM tickets
        WHERE status = 'open'
        ORDER BY
            CASE priority
                WHEN 'urgente' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'normal' THEN 3
                WHEN 'baixa' THEN 4
                ELSE 5
            END,
            id ASC
    """)

    rows = cur.fetchall()

    conn.close()

    return rows


def set_topic(
    ticket_id,
    topic_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET topic_id = ?
        WHERE id = ?
    """, (
        topic_id,
        ticket_id
    ))

    conn.commit()
    conn.close()


def assign_ticket(
    ticket_id,
    user_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET assigned_to = ?
        WHERE id = ?
    """, (
        user_id,
        ticket_id
    ))

    conn.commit()
    conn.close()


def set_priority(
    ticket_id,
    priority
):

    if priority not in PRIORITIES:
        return False

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET priority = ?
        WHERE id = ?
    """, (
        priority,
        ticket_id
    ))

    conn.commit()
    conn.close()

    return True


def close_ticket(
    ticket_id,
    closed_by
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET
            status = 'closed',
            closed_at = ?,
            closed_by = ?
        WHERE id = ?
        AND status = 'open'
    """, (
        now(),
        closed_by,
        ticket_id
    ))

    changed = cur.rowcount > 0

    conn.commit()
    conn.close()

    return changed


# ============================================================
# AGENTES DO TICKET
# ============================================================

def add_ticket_staff(
    ticket_id,
    user_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO ticket_staff
        (
            ticket_id,
            user_id,
            added_at
        )
        VALUES (?, ?, ?)
    """, (
        ticket_id,
        user_id,
        now()
    ))

    conn.commit()
    conn.close()


def remove_ticket_staff(
    ticket_id,
    user_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM ticket_staff
        WHERE ticket_id = ?
        AND user_id = ?
    """, (
        ticket_id,
        user_id
    ))

    changed = cur.rowcount > 0

    conn.commit()
    conn.close()

    return changed


def has_ticket_access(
    ticket_id,
    user_id
):

    if has_permission(
        user_id,
        "support"
    ):
        return True

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM ticket_staff
        WHERE ticket_id = ?
        AND user_id = ?
        LIMIT 1
    """, (
        ticket_id,
        user_id
    ))

    result = cur.fetchone()

    conn.close()

    return result is not None


def get_ticket_staff(ticket_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            ts.user_id,
            s.username,
            s.full_name,
            s.role
        FROM ticket_staff ts
        LEFT JOIN staff s
            ON s.user_id = ts.user_id
        WHERE ts.ticket_id = ?
        ORDER BY ts.added_at ASC
    """, (ticket_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


# ============================================================
# MENSAGENS
# ============================================================

def save_message(
    ticket_id,
    sender_id,
    sender_type,
    message_type,
    content
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages
        (
            ticket_id,
            sender_id,
            sender_type,
            message_type,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        ticket_id,
        sender_id,
        sender_type,
        message_type,
        content,
        now()
    ))

    conn.commit()
    conn.close()


def get_messages(ticket_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM messages
        WHERE ticket_id = ?
        ORDER BY id ASC
    """, (ticket_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


# ============================================================
# LOGS
# ============================================================

def save_log(
    ticket_id,
    actor_id,
    action,
    details=""
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO logs
        (
            ticket_id,
            actor_id,
            action,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        ticket_id,
        actor_id,
        action,
        details,
        now()
    ))

    conn.commit()
    conn.close()


async def send_log(
    context,
    text
):

    if LOG_CHAT_ID == 0:
        return

    try:

        await context.bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=text,
            parse_mode="HTML"
        )

    except Exception:

        logger.exception(
            "Erro enviando log."
        )


# ============================================================
# TRANSCRIÇÃO
# ============================================================

def generate_transcript(ticket):

    messages = get_messages(
        ticket["id"]
    )

    lines = []

    lines.append(
        "=========================================="
    )

    lines.append(
        f"TICKET #{ticket['id']:04d}"
    )

    lines.append(
        "=========================================="
    )

    lines.append(
        f"Usuário: {ticket['username'] or ticket['full_name']}"
    )

    lines.append(
        f"ID: {ticket['user_id']}"
    )

    lines.append(
        f"Categoria: {ticket['category']}"
    )

    lines.append(
        f"Prioridade: {ticket['priority']}"
    )

    lines.append(
        f"Status: {ticket['status']}"
    )

    lines.append(
        f"Criado: {ticket['created_at']}"
    )

    lines.append(
        f"Fechado: {ticket['closed_at'] or '-'}"
    )

    lines.append(
        f"Responsável: {ticket['assigned_to'] or '-'}"
    )

    lines.append("")

    lines.append(
        "================ MENSAGENS ================"
    )

    lines.append("")

    for message in messages:

        sender_type = message["sender_type"]
        sender_id = message["sender_id"]
        message_type = message["message_type"]
        content = message["content"] or ""

        lines.append(
            f"[{message['created_at']}] "
            f"{sender_type.upper()} "
            f"ID:{sender_id} "
            f"TYPE:{message_type}"
        )

        lines.append(content)

        lines.append("")

    lines.append(
        "=========================================="
    )

    return "\n".join(lines)


async def send_transcript(
    context,
    ticket
):

    if LOG_CHAT_ID == 0:
        return

    transcript = generate_transcript(
        ticket
    )

    file = io.BytesIO(
        transcript.encode("utf-8")
    )

    file.name = (
        f"ticket-{ticket['id']:04d}.txt"
    )

    try:

        await context.bot.send_document(
            chat_id=LOG_CHAT_ID,
            document=file,
            caption=(
                f"📜 <b>Transcrição</b>\n\n"
                f"🎫 Ticket: "
                f"<code>#{ticket['id']:04d}</code>\n"
                f"👤 Usuário: "
                f"<code>{ticket['user_id']}</code>\n"
                f"📂 Categoria: "
                f"{esc(ticket['category'])}\n"
                f"🚨 Prioridade: "
                f"{esc(ticket['priority'])}"
            ),
            parse_mode="HTML"
        )

    except Exception:

        logger.exception(
            "Erro enviando transcrição."
        )


# ============================================================
# PAINÉIS
# ============================================================

def main_panel():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎫 Abrir Ticket",
                callback_data="open_ticket"
            )
        ],
        [
            InlineKeyboardButton(
                "📌 Meu Ticket",
                callback_data="my_ticket"
            )
        ]
    ])


def category_panel():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 Compras",
                callback_data="cat_compras"
            )
        ],
        [
            InlineKeyboardButton(
                "🛠️ Suporte",
                callback_data="cat_suporte"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Financeiro",
                callback_data="cat_financeiro"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 Outros",
                callback_data="cat_outros"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Voltar",
                callback_data="back_main"
            )
        ]
    ])


def ticket_user_panel(
    ticket_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔒 Fechar Ticket",
                callback_data=f"user_close_{ticket_id}"
            )
        ]
    ])


def staff_ticket_panel(
    ticket_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎯 Assumir",
                callback_data=f"claim_{ticket_id}"
            ),
            InlineKeyboardButton(
                "🔒 Fechar",
                callback_data=f"close_{ticket_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🚨 Prioridade",
                callback_data=f"priority_{ticket_id}"
            )
        ]
    ])


def priority_panel(
    ticket_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 Baixa",
                callback_data=f"setprio_{ticket_id}_baixa"
            )
        ],
        [
            InlineKeyboardButton(
                "🟡 Normal",
                callback_data=f"setprio_{ticket_id}_normal"
            )
        ],
        [
            InlineKeyboardButton(
                "🟠 Alta",
                callback_data=f"setprio_{ticket_id}_alta"
            )
        ],
        [
            InlineKeyboardButton(
                "🔴 Urgente",
                callback_data=f"setprio_{ticket_id}_urgente"
            )
        ]
    ])


# ============================================================
# TEXTO DO TICKET
# ============================================================

def ticket_text(ticket):

    assigned = (
        f"<code>{ticket['assigned_to']}</code>"
        if ticket["assigned_to"]
        else "Ninguém"
    )

    priority = PRIORITIES.get(
        ticket["priority"],
        ticket["priority"]
    )

    return (
        f"🎫 <b>TICKET #{ticket['id']:04d}</b>\n\n"
        f"👤 Usuário: "
        f"{esc(ticket['username'] or ticket['full_name'])}\n"
        f"🆔 ID: "
        f"<code>{ticket['user_id']}</code>\n"
        f"📂 Categoria: "
        f"{esc(ticket['category'])}\n"
        f"🚨 Prioridade: "
        f"{esc(priority)}\n"
        f"🎯 Responsável: "
        f"{assigned}\n"
        f"📅 Criado: "
        f"{esc(ticket['created_at'])}\n\n"
        f"🟢 Status: "
        f"<b>{esc(ticket['status'])}</b>"
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    if update.effective_chat.type != ChatType.PRIVATE:
        return

    user = update.effective_user

    await update.message.reply_text(
        f"👋 Olá, <b>{esc(user.first_name)}</b>!\n\n"
        "🎫 <b>CENTRAL DE ATENDIMENTO</b>\n\n"
        "Abra um ticket para falar com nossa equipe.",
        parse_mode="HTML",
        reply_markup=main_panel()
    )


# ============================================================
# /TICKET
# ============================================================

async def ticket_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.message.reply_text(
        "🎫 <b>CENTRAL DE TICKETS</b>\n\n"
        "Escolha a categoria:",
        parse_mode="HTML",
        reply_markup=category_panel()
    )


# ============================================================
# /PAINEL
# ============================================================

async def painel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not has_permission(
        user.id,
        "support"
    ):

        await update.message.reply_text(
            "❌ Você não possui permissão."
        )

        return

    if update.effective_chat.id != SUPPORT_CHAT_ID:

        await update.message.reply_text(
            "❌ Use este comando no grupo de suporte."
        )

        return

    tickets = get_all_open_tickets()

    if not tickets:

        await update.message.reply_text(
            "📭 <b>Nenhum ticket aberto.</b>",
            parse_mode="HTML"
        )

        return

    text = (
        "🎫 <b>PAINEL DE TICKETS</b>\n\n"
    )

    for ticket in tickets[:30]:

        priority = PRIORITIES.get(
            ticket["priority"],
            ticket["priority"]
        )

        text += (
            f"🎫 <b>#{ticket['id']:04d}</b>\n"
            f"👤 {esc(ticket['username'] or ticket['full_name'])}\n"
            f"📂 {esc(ticket['category'])}\n"
            f"🚨 {esc(priority)}\n"
            f"🎯 {ticket['assigned_to'] or 'Ninguém'}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# ABRIR TICKET
# ============================================================

async def open_ticket_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "🎫 <b>CENTRAL DE TICKETS</b>\n\n"
        "Escolha a categoria:",
        parse_mode="HTML",
        reply_markup=category_panel()
    )


# ============================================================
# CRIAR TICKET
# ============================================================

async def category_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    existing = get_open_ticket(
        user.id
    )

    if existing:

        await query.edit_message_text(
            f"⚠️ Você já possui um ticket aberto.\n\n"
            f"🎫 <b>#{existing['id']:04d}</b>",
            parse_mode="HTML",
            reply_markup=ticket_user_panel(
                existing["id"]
            )
        )

        return

    category_map = {
        "cat_compras": "compras",
        "cat_suporte": "suporte",
        "cat_financeiro": "financeiro",
        "cat_outros": "outros",
    }

    category_key = category_map.get(
        query.data
    )

    if not category_key:
        return

    category = CATEGORIES[
        category_key
    ]

    if SUPPORT_CHAT_ID == 0:

        await query.edit_message_text(
            "❌ <b>SUPPORT_CHAT_ID não configurado.</b>",
            parse_mode="HTML"
        )

        return

    # --------------------------------------------------------
    # CRIA NO BANCO
    # --------------------------------------------------------

    ticket_id = create_ticket(
        user.id,
        user.username,
        user.full_name,
        category
    )

    ticket = get_ticket(ticket_id)

    # --------------------------------------------------------
    # CRIA TÓPICO
    # --------------------------------------------------------

    try:

        topic = await context.bot.create_forum_topic(
            chat_id=SUPPORT_CHAT_ID,
            name=(
                f"🎫 #{ticket_id:04d} - "
                f"{user_label(user)[:50]}"
            )
        )

        topic_id = topic.message_thread_id

        set_topic(
            ticket_id,
            topic_id
        )

    except Exception as e:

        logger.exception(
            "Erro criando tópico."
        )

        close_ticket(
            ticket_id,
            user.id
        )

        await query.edit_message_text(
            "❌ Não consegui criar o ticket.\n\n"
            "Verifique se o bot é administrador do "
            "grupo e possui permissão para gerenciar tópicos."
        )

        return

    # --------------------------------------------------------
    # REGISTRA LOG
    # --------------------------------------------------------

    save_log(
        ticket_id,
        user.id,
        "ticket_created",
        category
    )

    # --------------------------------------------------------
    # ENVIA PARA EQUIPE
    # --------------------------------------------------------

    try:

        await context.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            message_thread_id=topic_id,
            text=(
                "🎫 <b>NOVO TICKET</b>\n\n"
                f"{ticket_text(ticket)}\n\n"
                "👨‍💻 Um membro da equipe pode assumir "
                "este atendimento.\n\n"
                "Comandos disponíveis:\n"
                "<code>/assumir</code>\n"
                "<code>/adicionar ID</code>\n"
                "<code>/remover ID</code>\n"
                "<code>/fechar</code>\n"
                "<code>/prioridade</code>"
            ),
            parse_mode="HTML",
            reply_markup=staff_ticket_panel(
                ticket_id
            )
        )

    except Exception:

        logger.exception(
            "Erro enviando mensagem para suporte."
        )

    # --------------------------------------------------------
    # AVISA USUÁRIO
    # --------------------------------------------------------

    await query.edit_message_text(
        "✅ <b>Ticket criado!</b>\n\n"
        f"🎫 Número: <b>#{ticket_id:04d}</b>\n"
        f"📂 Categoria: {esc(category)}\n"
        "🟢 Status: Aberto\n\n"
        "Envie sua mensagem aqui. "
        "Nossa equipe receberá automaticamente.",
        parse_mode="HTML",
        reply_markup=ticket_user_panel(
            ticket_id
        )
    )

    await send_log(
        context,
        (
            "🎫 <b>NOVO TICKET</b>\n\n"
            f"Ticket: <code>#{ticket_id:04d}</code>\n"
            f"Usuário: <code>{user.id}</code>\n"
            f"Categoria: {esc(category)}"
        )
    )


# ============================================================
# MEU TICKET
# ============================================================

async def my_ticket_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    ticket = get_open_ticket(
        user.id
    )

    if not ticket:

        await query.edit_message_text(
            "📭 Você não possui nenhum ticket aberto.",
            reply_markup=main_panel()
        )

        return

    await query.edit_message_text(
        ticket_text(ticket),
        parse_mode="HTML",
        reply_markup=ticket_user_panel(
            ticket["id"]
        )
    )


# ============================================================
# FECHAR PELO USUÁRIO
# ============================================================

async def user_close_ticket(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    try:

        ticket_id = int(
            query.data.split("_")[-1]
        )

    except (ValueError, IndexError):

        return

    ticket = get_ticket(
        ticket_id
    )

    if not ticket:

        await query.edit_message_text(
            "❌ Ticket não encontrado."
        )

        return

    if ticket["user_id"] != user.id:

        await query.answer(
            "❌ Este ticket não pertence a você.",
            show_alert=True
        )

        return

    if ticket["status"] != "open":

        await query.edit_message_text(
            "ℹ️ Este ticket já está fechado."
        )

        return

    close_ticket(
        ticket_id,
        user.id
    )

    save_log(
        ticket_id,
        user.id,
        "ticket_closed",
        "Fechado pelo usuário"
    )

    ticket = get_ticket(
        ticket_id
    )

    # --------------------------------------------------------
    # AVISA EQUIPE
    # --------------------------------------------------------

    if ticket["topic_id"]:

        try:

            await context.bot.send_message(
                chat_id=SUPPORT_CHAT_ID,
                message_thread_id=ticket["topic_id"],
                text=(
                    "🔒 <b>TICKET FECHADO</b>\n\n"
                    f"O usuário fechou o ticket "
                    f"<b>#{ticket_id:04d}</b>."
                ),
                parse_mode="HTML"
            )

        except Exception:

            logger.exception(
                "Erro avisando fechamento."
            )

    await send_transcript(
        context,
        ticket
    )

    await send_log(
        context,
        (
            "🔒 <b>TICKET FECHADO</b>\n\n"
            f"Ticket: <code>#{ticket_id:04d}</code>\n"
            f"Fechado por: <code>{user.id}</code>"
        )
    )

    await query.edit_message_text(
        f"🔒 <b>Ticket #{ticket_id:04d} fechado.</b>\n\n"
        "Obrigado pelo contato.",
        parse_mode="HTML",
        reply_markup=main_panel()
    )


# ============================================================
# /ASSUMIR
# ============================================================

async def assumir_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if update.effective_chat.id != SUPPORT_CHAT_ID:
        return

    if not has_permission(
        user.id,
        "support"
    ):

        await update.message.reply_text(
            "❌ Você não faz parte da equipe."
        )

        return

    topic_id = update.effective_message.message_thread_id

    if not topic_id:

        await update.message.reply_text(
            "❌ Este comando precisa ser usado dentro de um ticket."
        )

        return

    ticket = get_ticket_by_topic(
        topic_id
    )

    if not ticket:

        await update.message.reply_text(
            "❌ Este tópico não está vinculado a um ticket."
        )

        return

    assign_ticket(
        ticket["id"],
        user.id
    )

    add_ticket_staff(
        ticket["id"],
        user.id
    )

    save_log(
        ticket["id"],
        user.id,
        "ticket_claimed",
        f"Assumido por {user.id}"
    )

    await update.message.reply_text(
        f"🎯 <b>Ticket assumido!</b>\n\n"
        f"👨‍💻 Responsável: "
        f"<code>{user.id}</code>",
        parse_mode="HTML"
    )

    try:

        await context.bot.send_message(
            chat_id=ticket["user_id"],
            text=(
                "🎯 <b>Seu ticket foi assumido!</b>\n\n"
                f"Um atendente da equipe está "
                f"atendendo você agora.\n\n"
                f"🎫 Ticket: "
                f"<code>#{ticket['id']:04d}</code>"
            ),
            parse_mode="HTML"
        )

    except Exception:
        pass


# ============================================================
# /ADICIONAR
# ============================================================

async def adicionar_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if update.effective_chat.id != SUPPORT_CHAT_ID:
        return

    if not has_permission(
        user.id,
        "supervisor"
    ):

        await update.message.reply_text(
            "❌ Apenas supervisores ou administradores podem adicionar agentes."
        )

        return

    topic_id = update.effective_message.message_thread_id

    ticket = get_ticket_by_topic(
        topic_id
    )

    if not ticket:

        await update.message.reply_text(
            "❌ Use este comando dentro de um ticket."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Uso:\n"
            "<code>/adicionar 123456789</code>",
            parse_mode="HTML"
        )

        return

    try:

        target_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID inválido."
        )

        return

    add_ticket_staff(
        ticket["id"],
        target_id
    )

    save_log(
        ticket["id"],
        user.id,
        "agent_added",
        f"Agente {target_id}"
    )

    await update.message.reply_text(
        f"➕ Agente <code>{target_id}</code> "
        "adicionado ao ticket.",
        parse_mode="HTML"
    )


# ============================================================
# /REMOVER
# ============================================================

async def remover_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if update.effective_chat.id != SUPPORT_CHAT_ID:
        return

    if not has_permission(
        user.id,
        "supervisor"
    ):

        await update.message.reply_text(
            "❌ Apenas supervisores ou administradores podem remover agentes."
        )

        return

    topic_id = update.effective_message.message_thread_id

    ticket = get_ticket_by_topic(
        topic_id
    )

    if not ticket:

        await update.message.reply_text(
            "❌ Use este comando dentro de um ticket."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Uso:\n"
            "<code>/remover 123456789</code>",
            parse_mode="HTML"
        )

        return

    try:

        target_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID inválido."
        )

        return

    removed = remove_ticket_staff(
        ticket["id"],
        target_id
    )

    if not removed:

        await update.message.reply_text(
            "⚠️ Esse agente não está atribuído ao ticket."
        )

        return

    save_log(
        ticket["id"],
        user.id,
        "agent_removed",
        f"Agente {target_id}"
    )

    await update.message.reply_text(
        f"➖ Agente <code>{target_id}</code> "
        "removido do ticket.",
        parse_mode="HTML"
    )


# ============================================================
# /PRIORIDADE
# ============================================================

async def prioridade_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if update.effective_chat.id != SUPPORT_CHAT_ID:
        return

    if not has_permission(
        user.id,
        "support"
    ):

        return

    topic_id = update.effective_message.message_thread_id

    ticket = get_ticket_by_topic(
        topic_id
    )

    if not ticket:

        return

    if not context.args:

        await update.message.reply_text(
            "🚨 <b>Prioridades:</b>\n\n"
            "<code>/prioridade baixa</code>\n"
            "<code>/prioridade normal</code>\n"
            "<code>/prioridade alta</code>\n"
            "<code>/prioridade urgente</code>",
            parse_mode="HTML"
        )

        return

    priority = context.args[0].lower()

    if priority not in PRIORITIES:

        await update.message.reply_text(
            "❌ Prioridade inválida."
        )

        return

    set_priority(
        ticket["id"],
        priority
    )

    save_log(
        ticket["id"],
        user.id,
        "priority_changed",
        priority
    )

    await update.message.reply_text(
        f"🚨 Prioridade alterada para "
        f"<b>{esc(PRIORITIES[priority])}</b>.",
        parse_mode="HTML"
    )

    try:

        await context.bot.send_message(
            chat_id=ticket["user_id"],
            text=(
                f"🚨 A prioridade do seu ticket "
                f"<b>#{ticket['id']:04d}</b> foi atualizada."
            ),
            parse_mode="HTML"
        )

    except Exception:
        pass


)
    )

    application.add_handler(
        CallbackQueryHandler(
            staff_callback,
            pattern=r"^(claim|close|priority)_\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            staff_callback,
            pattern=r"^setprio_\d+_(baixa|normal|alta|urgente)$"
        )
    )

    # --------------------------------------------------------
    # MENSAGENS
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & ~filters.COMMAND,
            private_message_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Chat(
                SUPPORT_CHAT_ID
            )
            & ~filters.COMMAND,
            support_message_handler
        )
    )

    # --------------------------------------------------------
    # ERROS
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "TICKET BOT INICIADO"
    )

    logger.info(
        "SUPPORT_CHAT_ID: %s",
        SUPPORT_CHAT_ID
    )

    logger.info(
        "LOG_CHAT_ID: %s",
        LOG_CHAT_ID
    )

    logger.info(
        "OWNERS: %s",
        OWNER_IDS
    )

    logger.info(
        "======================================"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()
