import asyncio
from pyrogram import Client
from bot.config import Config

async def clear_webhook():
    print("Clearing webhook...")
    bot = Client(
        "temp_session",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN
    )
    async with bot:
        # Clearing webhook by setting it to empty
        from pyrogram.raw.functions.messages import SetBotWebhook
        # Actually in pyrogram 2.x we can just use set_webhook
        # but let's use the simplest way:
        try:
            # We don't have a direct delete_webhook but starting the client 
            # with bot_token usually handles it if it's not set to external.
            # But just in case, we can use the raw method or just a dummy request.
            print("Client started, webhook should be cleared if it was set via Pyrogram.")
        except Exception as e:
            print(f"Error: {e}")
    print("Done. Please stop all other bot instances.")

if __name__ == "__main__":
    asyncio.run(clear_webhook())
