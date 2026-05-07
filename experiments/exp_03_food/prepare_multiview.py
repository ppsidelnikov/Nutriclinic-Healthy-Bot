"""Скачивает боковые видео-ракурсы Nutrition5k и извлекает по одному кадру.

Структура Nutrition5k:
  imagery/realsense_overhead/<dish_id>/rgb.png  ← уже есть
  imagery/side_angles/<dish_id>/camera_{A,B,C,D}.h264  ← скачиваем здесь

Пробуем камеры A→B→C→D по очереди, берём первые 2 которые скачались,
извлекаем средний кадр через ffmpeg и сохраняем в dataset/images_multiview/.

Использование:
  python prepare_multiview.py            # все блюда
  python prepare_multiview.py --limit 5  # только первые 5 блюд (для проверки)
"""

from __future__ import annotations
import json
import argparse
import subprocess
import urllib.request
from pathlib import Path
from tqdm import tqdm

DATASET_DIR = Path(__file__).parent / "dataset"
MV_DIR = DATASET_DIR / "images_multiview"
TMP_DIR = DATASET_DIR / "_tmp_videos"

VIDEO_URL = "https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/side_angles/{dish_id}/camera_{cam}.h264"
# В Nutrition5k не у каждого блюда есть все 4 камеры — пробуем все,
# берём первые 2 которые скачались
CAMERAS_TRY = ["A", "B", "C", "D"]
N_CAMERAS_NEEDED = 2


def extract_middle_frame(video_path: Path, out_path: Path, verbose: bool = False) -> bool:
    """Извлекает кадр примерно из середины видео.

    Для raw h264 без контейнера: считаем общее число кадров через ffprobe
    (count_frames), берём средний через select-фильтр, fallback — первый кадр.
    """
    target_n = None
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames",
             "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=60,
        )
        frames = int(probe.stdout.strip()) if probe.stdout.strip() else 0
        if frames > 0:
            target_n = frames // 2
    except Exception:
        pass

    if target_n is not None:
        cmd = ["ffmpeg", "-y", "-i", str(video_path),
               "-vf", f"select=eq(n\\,{target_n})", "-frames:v", "1",
               "-q:v", "2", str(out_path)]
    else:
        cmd = ["ffmpeg", "-y", "-i", str(video_path),
               "-frames:v", "1", "-q:v", "2", str(out_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if out_path.exists() and out_path.stat().st_size > 0:
            return True
        if verbose:
            print(f"  ffmpeg stderr: {result.stderr.decode(errors='replace')[:300]}")
        return False
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"  ffmpeg timeout")
        return False


def download_video(dish_id: str, cam: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    url = VIDEO_URL.format(dish_id=dish_id, cam=cam)
    try:
        urllib.request.urlretrieve(url, dest)
        if dest.stat().st_size > 1000:
            return True
        dest.unlink(missing_ok=True)
        return False
    except Exception:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Ограничить число блюд (для проверки)")
    parser.add_argument("--verbose", action="store_true", help="Печатать ffmpeg stderr при сбое")
    args = parser.parse_args()

    MV_DIR.mkdir(exist_ok=True)
    TMP_DIR.mkdir(exist_ok=True)

    gt_path = DATASET_DIR / "ground_truth.jsonl"
    dishes = [json.loads(l) for l in open(gt_path) if l.strip()]
    if args.limit:
        dishes = dishes[: args.limit]
    print(f"Обрабатываю {len(dishes)} блюд, ищу до {N_CAMERAS_NEEDED} ракурсов из {CAMERAS_TRY}\n")

    n_dishes_full = n_dishes_partial = n_dishes_empty = 0
    n_frames_ok = 0
    pbar = tqdm(dishes, desc="dishes", unit="d", ncols=90, colour="cyan")
    for d in pbar:
        dish_id = d["dish_id"]
        # Подсчёт уже извлечённых кадров для этого блюда
        existing = [c for c in CAMERAS_TRY
                    if (MV_DIR / f"{dish_id}_cam{c}.png").exists()
                    and (MV_DIR / f"{dish_id}_cam{c}.png").stat().st_size > 0]
        n_have = len(existing)

        # Пробуем оставшиеся камеры пока не наберём нужное число
        for cam in CAMERAS_TRY:
            if n_have >= N_CAMERAS_NEEDED:
                break
            out_frame = MV_DIR / f"{dish_id}_cam{cam}.png"
            if out_frame.exists() and out_frame.stat().st_size > 0:
                continue

            tmp_video = TMP_DIR / f"{dish_id}_cam{cam}.h264"
            if not download_video(dish_id, cam, tmp_video):
                continue
            if extract_middle_frame(tmp_video, out_frame, verbose=args.verbose):
                n_have += 1
                n_frames_ok += 1
            tmp_video.unlink(missing_ok=True)

        if n_have >= N_CAMERAS_NEEDED:
            n_dishes_full += 1
        elif n_have > 0:
            n_dishes_partial += 1
        else:
            n_dishes_empty += 1

        pbar.set_postfix_str(f"full={n_dishes_full} partial={n_dishes_partial} empty={n_dishes_empty}")

    # очистка tmp
    if TMP_DIR.exists():
        for f in TMP_DIR.iterdir():
            f.unlink()
        TMP_DIR.rmdir()

    print(f"\nСтатистика по блюдам:")
    print(f"  с {N_CAMERAS_NEEDED}+ ракурсами:  {n_dishes_full}")
    print(f"  с 1 ракурсом:                {n_dishes_partial}")
    print(f"  без ракурсов:                {n_dishes_empty}")
    print(f"Всего извлечено кадров за этот прогон: {n_frames_ok}")
    print(f"Кадры сохранены: {MV_DIR}")


if __name__ == "__main__":
    main()
