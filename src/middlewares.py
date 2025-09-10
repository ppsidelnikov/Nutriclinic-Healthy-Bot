from aiogram import BaseMiddleware
from typing import Callable, Awaitable, Any
from aiogram.types import TelegramObject, Message, CallbackQuery
from pathlib import Path
from tempfile import NamedTemporaryFile
import os
from db.db import AsyncSessionLocal
from db.db_write import insert_message_log_from_message, insert_message_log_from_callback
from db.minio_io import ensure_bucket, upload_file

class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        try:
            if isinstance(event, Message):
                message_content_key = None
                # If message contains a photo or an image document, upload it to MinIO and log the key
                try:
                    if event.photo:
                        tg_file = event.photo[-1]
                        file_id = tg_file.file_id
                        filename_hint = f"{tg_file.file_unique_id}.jpg"
                    elif event.document and event.document.mime_type and event.document.mime_type.startswith("image/"):
                        tg_file = event.document
                        file_id = tg_file.file_id
                        filename_hint = tg_file.file_name or f"{tg_file.file_unique_id}.bin"
                    else:
                        tg_file = None

                    if tg_file is not None:
                        ensure_bucket()
                        buf_path = None
                        try:
                            # download to temp file
                            with NamedTemporaryFile(delete=False) as tmp:
                                buf_path = tmp.name
                                await event.bot.download(tg_file, destination=tmp)
                            ext = Path(filename_hint).suffix or ".bin"
                            key = f"chat/{event.chat.id}/msg/{event.message_id}/{file_id}{ext}"
                            uploaded_key = upload_file(buf_path, key)
                            message_content_key = uploaded_key
                        finally:
                            if buf_path and os.path.exists(buf_path):
                                try:
                                    os.remove(buf_path)
                                except OSError:
                                    pass
                except Exception as e:
                    print("LoggingMiddleware media upload error:", repr(e))

                async with AsyncSessionLocal() as session:
                    await insert_message_log_from_message(
                        session,
                        event,
                        message_content=message_content_key,
                    )
            elif isinstance(event, CallbackQuery):
                async with AsyncSessionLocal() as session:
                    await insert_message_log_from_callback(session, event)
        except Exception as e:
            print("LoggingMiddleware error:", repr(e))

        return await handler(event, data)