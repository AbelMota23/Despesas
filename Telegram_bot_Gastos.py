from dotenv import load_dotenv
import os
import re
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# --- Config ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MEU_ID = 6356669235
import json

creds_json = os.getenv("GOOGLE_CREDS_JSON")
if creds_json:
    with open("credenciais.json", "w", encoding="utf-8") as f:
        f.write(creds_json)
SHEET_NAME = "GastosSemanais"  # nome exato da tua planilha

def autorizado(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == MEU_ID


def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file("credenciais.json", scopes=scopes)
    return gspread.authorize(creds)

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(update.effective_user.id)
    await update.message.reply_text("👋 Bot de Gastos!\nUsa /add para registar.\nUsa /cancel para cancelar um registo a meio.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelado. Usa /add para começar de novo.")

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("📚 Coimbra", callback_data="cat_coimbra")],
        [InlineKeyboardButton("🍔 Comida", callback_data="cat_comida")],
        [InlineKeyboardButton("🎮 Gaming", callback_data="cat_gaming")],
        [InlineKeyboardButton("🏍️ Moto", callback_data="cat_moto")],
        [InlineKeyboardButton("🛒 Compras", callback_data="cat_compras")],
        [InlineKeyboardButton("🍺 Bebida", callback_data="cat_bebida")],
        [InlineKeyboardButton("💰 Outros", callback_data="cat_outros")],
    ]
    await update.message.reply_text("Escolhe categoria:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Callback handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        await update.callback_query.answer("Sem permissão.", show_alert=True)
        return
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("cat_"):
        return  # ignora desc_...

    context.user_data['categoria'] = query.data.split('_', 1)[1]
    cat_nome = context.user_data['categoria'].title()
    await query.edit_message_text(f"✅ Categoria: {cat_nome}\nQuanto gastaste? (ex: 3.50 ou 2,50€)")

async def desc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        await update.callback_query.answer("Sem permissão.", show_alert=True)
        return
    """Só trata callbacks desc_..."""
    query = update.callback_query
    await query.answer()

    if "valor_temp" not in context.user_data or "categoria" not in context.user_data:
        await query.edit_message_text("❌ Sessão perdida. Usa /add novamente.")
        context.user_data.clear()
        return

    valor = context.user_data["valor_temp"]
    cat = context.user_data["categoria"]

    if query.data == "desc_nao":
        try:
            cliente = conectar_google_sheets()
            sheet = cliente.open(SHEET_NAME).sheet1
            sheet.append_row([date.today().strftime("%d/%m/%Y"), "", cat.title(), valor, "Despesa"])
            await query.edit_message_text(f"✅ {valor:.2f}€ em {cat.title()} registado (sem descrição)!")
        except Exception as e:
            await query.edit_message_text(f"❌ Erro ao gravar na Sheets: {type(e).__name__}")
        finally:
            context.user_data.clear()
        return

    if query.data == "desc_sim":
        context.user_data["aguarda_desc"] = True
        await query.edit_message_text("✏️ Escreve a descrição (ou /cancel):")
        return

# --- Text handler (um só) ---
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_original = (update.message.text or "").strip()

    # 1) Se está à espera da descrição
    if context.user_data.get("aguarda_desc"):
        desc = text_original[:80]  # limita tamanho
        valor = context.user_data.get("valor_temp")
        cat = context.user_data.get("categoria")

        if valor is None or cat is None:
            await update.message.reply_text("❌ Sessão perdida. Usa /add novamente.")
            context.user_data.clear()
            return

        try:
            cliente = conectar_google_sheets()
            sheet = cliente.open(SHEET_NAME).sheet1
            sheet.append_row([date.today().strftime("%d/%m/%Y"), desc, cat.title(), valor, "Despesa"])
            await update.message.reply_text(f"✅ {valor:.2f}€ em {cat.title()} registado: {desc}")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao gravar na Sheets: {type(e).__name__}")
        finally:
            context.user_data.clear()
        return

    # 2) Se já escolheu categoria, este texto deve ser o VALOR
    if context.user_data.get("categoria") and "valor_temp" not in context.user_data:
        try:
            # apanha primeiro número (3,50 / 3.50 / 10)
            match = re.search(r"(\d+(?:[.,]\d+)?)", text_original)
            if not match:
                raise ValueError("Sem número")

            valor = float(match.group(1).replace(",", "."))
            if valor <= 0:
                raise ValueError("Valor <= 0")

            context.user_data["valor_temp"] = valor

            cat = context.user_data["categoria"]
            keyboard_desc = [
                [InlineKeyboardButton("✅ Sem descrição", callback_data="desc_nao")],
                [InlineKeyboardButton("✏️ Sim, adicionar", callback_data="desc_sim")]
            ]
            await update.message.reply_text(
                f"Valor: {valor:.2f}€ em {cat.title()}\nQueres adicionar descrição?",
                reply_markup=InlineKeyboardMarkup(keyboard_desc)
            )
        except Exception:
            await update.message.reply_text("❌ Valor inválido. Ex: 3.50 ou 3,50")
        return

    # 3) Fora de fluxo
    await update.message.reply_text("Usa /add para começar um registo.")

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Falta TELEGRAM_TOKEN no ficheiro .env")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start, filters=User(MEU_ID)))
    app.add_handler(CommandHandler("add", add_expense, filters=User(MEU_ID)))
    app.add_handler(CommandHandler("cancel", cancel, filters=User(MEU_ID)))

    # MUITO IMPORTANTE: patterns para separar cat_ de desc_
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(desc_handler, pattern="^desc_"))

    # Um único handler de texto para valor/descrição
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & User(MEU_ID), text_router))

    print("🤖 Bot rodando! Usa /start")
    app.run_polling()

if __name__ == "__main__":

    main()



