from bot.utils import get_episode_number

test_cases = [
    ("Attack on Titan E01.mkv", 1),
    ("Episode 5 Naruto.mp4", 5),
    ("03.one.piece.mkv", 3),
    ("Season 1 Episode 10.mkv", 10),
    ("No number here.mkv", 999),
]

for filename, expected in test_cases:
    result = get_episode_number(filename)
    print(f"File: {filename} -> Extracted: {result} (Expected: {expected})")
    assert result == expected

print("All regex tests passed!")
