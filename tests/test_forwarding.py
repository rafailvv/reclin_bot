import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.update(BOT_TOKEN='123456:TEST_TOKEN_NOT_REAL', DATABASE_HOST='127.0.0.1', DATABASE_PORT='1', DATABASE_USER='test', DATABASE_PASSWORD='test', DATABASE_NAME='test', ADMIN_IDS='1,2', AES_SECRET_KEY='test', AES_IV='1234567890123456')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from app.handlers import start


def message(text='a < b & c'):
    return SimpleNamespace(from_user=SimpleNamespace(is_bot=False,id=123,full_name='A <B>',username='example'),chat=SimpleNamespace(id=123),message_id=42,text=text)


def test_unavailable_admin_does_not_block_other_admins(monkeypatch):
    monkeypatch.setattr(start.config,'ADMIN_IDS',[1,2])
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=[TelegramForbiddenError(method=SendMessage(chat_id=1,text='x'),message='Forbidden'),None]))
    asyncio.run(start.forward_all_messages(message(),bot,AsyncMock()))
    assert bot.send_message.await_count==2
    calls=bot.send_message.await_args_list
    assert [c.kwargs['chat_id'] for c in calls]==[1,2]
    assert 'a &lt; b &amp; c' in calls[1].kwargs['text']
    assert 'A &lt;B&gt;' in calls[1].kwargs['text']
    assert calls[1].kwargs['reply_markup'].inline_keyboard[0][0].callback_data=='reply:123:42'


def test_normal_forwarding_keeps_all_recipients(monkeypatch):
    monkeypatch.setattr(start.config,'ADMIN_IDS',[1,2])
    bot=SimpleNamespace(send_message=AsyncMock())
    asyncio.run(start.forward_all_messages(message('Hello'),bot,AsyncMock()))
    assert bot.send_message.await_count==2
    assert all(c.kwargs['text'].endswith('Hello') for c in bot.send_message.await_args_list)


def test_commands_still_not_forwarded():
    bot=SimpleNamespace(send_message=AsyncMock())
    asyncio.run(start.forward_all_messages(message('/start'),bot,AsyncMock()))
    bot.send_message.assert_not_awaited()
