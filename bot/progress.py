import time

def calculate_progress(current, total):
    if total == 0:
        return 0
    return (current / total) * 100

def progress_bar(percentage):
    completed = int(percentage / 10)
    return "█" * completed + "░" * (10 - completed)

async def get_progress_text(current, total, start_time, title="Processing"):
    pct = calculate_progress(current, total)
    bar = progress_bar(pct)
    
    elapsed_time = time.time() - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    
    from bot.utils import format_size, format_duration
    
    speed_text = f"{format_size(speed)}/s" if speed > 0 else "0B/s"
    
    if speed > 0:
        eta = (total - current) / speed
        eta_text = format_duration(eta)
    else:
        eta_text = "--:--:--"

    return (
        f"**{title}**\n"
        f"进度: `{bar}` {pct:.1f}%\n"
        f"已完成: {format_size(current)} / {format_size(total)}\n"
        f"速度: {speed_text}\n"
        f"ETA: {eta_text}"
    )
