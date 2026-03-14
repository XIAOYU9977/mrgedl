import time
import math
from bot.utils import format_bytes, get_safe_percentage

async def progress_for_pyrogram(current, total, ud_type, message, start):
    now = time.time()
    diff = now - start
    if round(diff % 10.00) == 0 or current == total:
        percentage = get_safe_percentage(current, total)
        
        # Guard diff to avoid division by zero
        speed = current / diff if diff > 0 else 0
        
        elapsed_time = round(diff) * 1000
        
        # Guard speed to avoid division by zero
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        estimated_total_time = elapsed_time + time_to_completion

        elapsed_time = TimeFormatter(milliseconds=elapsed_time)
        estimated_total_time = TimeFormatter(milliseconds=estimated_total_time)

        progress = "[{0}{1}] \n**Progress**: {2}%\n".format(
            ''.join(["█" for i in range(math.floor(percentage / 10))]),
            ''.join(["░" for i in range(10 - math.floor(percentage / 10))]),
            round(percentage, 2))

        tmp = progress + "{0} of {1}\n**Speed**: {2}/s\n**ETA**: {3}\n".format(
            format_bytes(current),
            format_bytes(total),
            format_bytes(speed),
            estimated_total_time if estimated_total_time != '' else "0 s"
        )
        try:
            await message.edit(
                text="{}\n {}".format(ud_type, tmp)
            )
        except:
            pass

def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    res = ""
    if days: res += f"{days}d, "
    if hours: res += f"{hours}h, "
    if minutes: res += f"{minutes}m, "
    if seconds: res += f"{seconds}s, "
    if milliseconds: res += f"{milliseconds}ms, "
    
    return res.rstrip(", ") if res else "0ms"
