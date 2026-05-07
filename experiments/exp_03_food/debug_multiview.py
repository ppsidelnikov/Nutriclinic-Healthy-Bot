"""Отладка: пробуем скачать одно видео и видим точную причину сбоя."""

from __future__ import annotations
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

DATASET_DIR = Path(__file__).parent / "dataset"

# Берём первое блюдо из ground_truth
dishes = [json.loads(l) for l in open(DATASET_DIR / "ground_truth.jsonl") if l.strip()]
test_dish = dishes[0]["dish_id"]
print(f"Тестовое блюдо: {test_dish}\n")

for cam in ["A", "C"]:
    url = f"https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/side_angles/{test_dish}/camera_{cam}.h264"
    dest = DATASET_DIR / f"_test_{cam}.h264"
    print(f"--- camera_{cam} ---")
    print(f"URL: {url}")

    try:
        urllib.request.urlretrieve(url, dest)
        size = dest.stat().st_size
        print(f"OK: скачано {size:,} байт")
        if size < 1000:
            print(f"  СТРАННО: файл подозрительно мал, содержимое:")
            print(f"  {dest.read_bytes()[:500]!r}")
    except urllib.error.HTTPError as e:
        print(f"HTTPError {e.code}: {e.reason}")
    except Exception as e:
        print(f"Exception {type(e).__name__}: {e}")

    if dest.exists():
        dest.unlink()
    print()

# Параллельная проверка через curl с verbose
print("--- через curl (для сравнения) ---")
url = f"https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/side_angles/{test_dish}/camera_A.h264"
result = subprocess.run(
    ["curl", "-sIL", "-o", "/dev/null", "-w", "HTTP %{http_code}, size %{size_download}, redirected %{num_redirects}\n", url],
    capture_output=True, text=True, timeout=30,
)
print(result.stdout or result.stderr)
