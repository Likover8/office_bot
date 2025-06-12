from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
import asyncio

API_TOKEN = '8087657192:AAGS85PcbVynIAJN9h12Ic4Pd8YspnWzaxM'

bot = Bot(token=API_TOKEN)
dp  = Dispatcher()

# Схема мест: 3 ряда по 4
SEAT_ROWS = [
    ["A1","B1","C1","D1"],
    ["A2","B2","C2","D2"],
    ["A3","B3","C3","D3"],
]

reserved_seats = {}   # chat_id → {seat: owner_id}
marketing_seats = {}  # chat_id → set(seat)
occupied       = {}   # chat_id → {seat: user_id}
user_seat      = {}   # chat_id → {user_id: seat}
chart_message  = {}   # chat_id → message_id

EMOJI = {
    "free":      "🌕",
    "occupied":  "🌑",
    "reserved":  "🌓",
    "marketing": "🤍",
    "plant":     "🌿",
}

def init_chat(cid: int):
    reserved_seats.setdefault(cid, {})
    marketing_seats.setdefault(cid, {"A2","A3"})
    occupied.setdefault(cid, {})
    user_seat.setdefault(cid, {})

async def build_chart_html(cid: int) -> str:
    init_chat(cid)
    status = {}
    for row in SEAT_ROWS:
        for s in row:
            if s in marketing_seats[cid]:
                status[s] = EMOJI["marketing"]
            elif s in occupied[cid]:
                status[s] = EMOJI["occupied"]
            elif s in reserved_seats[cid]:
                status[s] = EMOJI["reserved"]
            else:
                status[s] = EMOJI["free"]

    lines = ["┌───────── Окно ──────────┐"]
    for row in SEAT_ROWS:
        left  = "".join(f"[<i>{s}</i>{status[s]}]" for s in row[:2])
        right = "".join(f"[<i>{s}</i>{status[s]}]" for s in row[2:])
        lines.append(f"{left}    {right}")
    lines.append(EMOJI["plant"]*6 + "    " + EMOJI["plant"]*6)
    lines.append("└───────── Проход ────────┘")

    out = ["<pre>"] + lines + ["</pre>\n", "В офисе сейчас:"]
    for uid, seat in user_seat[cid].items():
        member = await bot.get_chat_member(cid, uid)
        out.append(f"{member.user.full_name} [{seat}]")
    out.append(f"\nВсего людей в офисе: {len(user_seat[cid])}\n")
    out += [
        "🌕 — свободно",
        "🌑 — занято",
        "🌓 — закреплено (требует подтверждения)",
        "🤍 — маркетинг (недоступно)",
    ]
    return "\n".join(out)

def seat_keyboard(cid: int) -> InlineKeyboardMarkup:
    init_chat(cid)
    kb = []
    for row in SEAT_ROWS:
        btns = []
        for s in row:
            if s in marketing_seats[cid] or s in occupied[cid]:
                continue
            btns.append(InlineKeyboardButton(text=s, callback_data=f"book|{s}"))
        if btns:
            kb.append(btns)
    # «Я ушёл» показываем, пока в офисе хотя бы один
    if user_seat[cid]:
        kb.append([InlineKeyboardButton(text="Я ушёл", callback_data="leave")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command(commands=["attendance"]))
async def cmd_attendance(message: types.Message):
    cid = message.chat.id
    init_chat(cid)
    occupied[cid].clear()
    user_seat[cid].clear()
    # reserved_seats сохраняем
    chart = await build_chart_html(cid)
    msg = await bot.send_message(
        chat_id=cid,
        text=chart,
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    chart_message[cid] = msg.message_id

@dp.message(Command(commands=["reserve"]))
async def cmd_reserve(message: types.Message):
    cid = message.chat.id
    init_chat(cid)
    if not message.reply_to_message:
        return await message.reply(
            "Чтобы закрепить место, ответьте `/reserve <место>` на сообщение пользователя.",
            parse_mode="Markdown"
        )
    parts = message.text.split()
    if len(parts)!=2:
        return await message.reply("Неверный формат. `/reserve <место>`", parse_mode="Markdown")
    seat = parts[1].upper()
    if seat not in sum(SEAT_ROWS, []):
        return await message.reply(f"Места `{seat}` не существует.", parse_mode="Markdown")
    if seat in marketing_seats[cid] or seat in occupied[cid]:
        return await message.reply("Место недоступно.", parse_mode="Markdown")

    owner = message.reply_to_message.from_user
    reserved_seats[cid][seat] = owner.id

    await bot.edit_message_text(
        chat_id=cid,
        message_id=chart_message[cid],
        text=await build_chart_html(cid),
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    await message.reply(f"Место <i>{seat}</i> закреплено за {owner.full_name}.", parse_mode="HTML")

@dp.message(Command(commands=["unreserve"]))
async def cmd_unreserve(message: types.Message):
    cid = message.chat.id
    init_chat(cid)
    parts = message.text.split()
    if len(parts)!=2:
        return await message.reply("Неверный формат. `/unreserve <место>`", parse_mode="Markdown")
    seat = parts[1].upper()
    if seat not in reserved_seats[cid]:
        return await message.reply(f"Место `{seat}` не закреплено.", parse_mode="Markdown")
    reserved_seats[cid].pop(seat)

    await bot.edit_message_text(
        chat_id=cid,
        message_id=chart_message[cid],
        text=await build_chart_html(cid),
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    await message.reply(f"Закрепление для <i>{seat}</i> удалено.", parse_mode="HTML")

@dp.callback_query(lambda c: c.data and c.data.startswith("book|"))
async def book_seat(cb: types.CallbackQuery):
    cid, uid = cb.message.chat.id, cb.from_user.id
    init_chat(cid)
    _, seat = cb.data.split("|")
    if seat in marketing_seats[cid]:
        return await cb.answer("Маркетинговое место недоступно.", show_alert=True)

    owner = reserved_seats[cid].get(seat)
    if owner and owner!=uid:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Разрешить", callback_data=f"allow|{seat}|{uid}"),
            InlineKeyboardButton(text="Отказать",  callback_data=f"deny|{seat}|{uid}")
        ]])
        owner_member = await bot.get_chat_member(cid, owner)
        notif = await bot.send_message(
            chat_id=cid,
            text=(
                f"<a href='tg://user?id={owner}'>{owner_member.user.full_name}</a>, "
                f"{cb.from_user.full_name} хочет занять {seat}. Разрешить?"
            ),
            parse_mode="HTML",
            reply_markup=kb
        )
        asyncio.create_task(_auto_delete(cid, notif.message_id, 15))
        return await cb.answer()

    if seat in occupied[cid]:
        return await cb.answer("Уже занято.", show_alert=True)

    prev = user_seat[cid].pop(uid, None)
    if prev:
        occupied[cid].pop(prev, None)
    occupied[cid][seat] = uid
    user_seat[cid][uid] = seat

    await bot.edit_message_text(
        chat_id=cid,
        message_id=chart_message[cid],
        text=await build_chart_html(cid),
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    await cb.answer("Место забронировано.")

@dp.callback_query(lambda c: c.data and c.data.startswith("allow|"))
async def allow_cb(cb: types.CallbackQuery):
    cid = cb.message.chat.id
    _, seat, req = cb.data.split("|")
    owner     = cb.from_user.id
    requester = int(req)
    init_chat(cid)
    if reserved_seats[cid].get(seat)!=owner:
        return await cb.answer("Только владелец может разрешить.", show_alert=True)

    await bot.delete_message(cid, cb.message.message_id)
    if seat in occupied[cid]:
        return await cb.answer("Уже занято.", show_alert=True)

    prev = user_seat[cid].pop(requester, None)
    if prev:
        occupied[cid].pop(prev, None)
    occupied[cid][seat]       = requester
    user_seat[cid][requester] = seat

    await bot.edit_message_text(
        chat_id=cid,
        message_id=chart_message[cid],
        text=await build_chart_html(cid),
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )

    member = await bot.get_chat_member(cid, requester)
    mention = f"<a href='tg://user?id={requester}'>{member.user.full_name}</a>"
    notif = await bot.send_message(
        chat_id=cid,
        text=f"{mention}, вам разрешили занять место {seat}.",
        parse_mode="HTML"
    )
    asyncio.create_task(_auto_delete(cid, notif.message_id, 15))
    await cb.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("deny|"))
async def deny_cb(cb: types.CallbackQuery):
    cid = cb.message.chat.id
    _, seat, req = cb.data.split("|")
    owner     = cb.from_user.id
    requester = int(req)
    init_chat(cid)
    if reserved_seats[cid].get(seat)!=owner:
        return await cb.answer("Только владелец может отказать.", show_alert=True)

    await bot.delete_message(cid, cb.message.message_id)
    member = await bot.get_chat_member(cid, requester)
    mention = f"<a href='tg://user?id={requester}'>{member.user.full_name}</a>"
    notif = await bot.send_message(
        chat_id=cid,
        text=f"{mention}, к сожалению, место сейчас недоступно.",
        parse_mode="HTML"
    )
    asyncio.create_task(_auto_delete(cid, notif.message_id, 15))
    await cb.answer()

@dp.callback_query(lambda c: c.data=="leave")
async def leave_cb(cb: types.CallbackQuery):
    cid, uid = cb.message.chat.id, cb.from_user.id
    init_chat(cid)
    if uid not in user_seat[cid]:
        return await cb.answer("Похоже, вы ещё не в офисе.", show_alert=True)

    prev = user_seat[cid].pop(uid)
    occupied[cid].pop(prev, None)

    await bot.edit_message_text(
        chat_id=cid,
        message_id=chart_message[cid],
        text=await build_chart_html(cid),
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    await cb.answer("Вы вышли из офиса.")

async def _auto_delete(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand("attendance","Показать рассадку"),
        BotCommand("reserve",   "Закрепить место"),
        BotCommand("unreserve", "Снять закрепление"),
    ])

if __name__=="__main__":
    dp.run_polling(bot, skip_updates=True, on_startup=on_startup)
