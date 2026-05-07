"""
Калибровочный эксперимент: пост-коррекция предсказаний V1 (gpt-4.1-mini).

Гипотеза: ошибки V1 систематические — модель имеет смещение по конкретным
типам блюд / нутриентам. Простая линейная коррекция вида
  y_corrected = a * y_predicted + b
обученная на train-выборке, должна снизить MAPE на test-выборке.

Сравниваются три варианта:
  • baseline       — без коррекции (V1 как есть)
  • global linear  — одна пара (a, b) на каждый нутриент
  • per-cluster    — отдельные (a, b) для simple/medium/complex кластеров

Использование:
  python calibrate.py
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split

RESULTS_DIR = Path(__file__).parent / "results"
DATASET_DIR = Path(__file__).parent / "dataset"
NUTRIENTS = ["kcal", "protein", "fat", "carbs"]


def cluster_for(n: int) -> str:
    if n == 1:    return "simple"
    if n <= 4:    return "medium"
    return "complex"


def load_data() -> pd.DataFrame:
    """Собирает (predicted, actual) по V1 для всех 301 блюд из runs.jsonl."""
    gt = {}
    for line in open(DATASET_DIR / "ground_truth.jsonl"):
        d = json.loads(line)
        gt[d["dish_id"]] = {
            "kcal":    d["kcal"],
            "protein": d["protein_g"],
            "fat":     d["fat_g"],
            "carbs":   d["carbs_g"],
            "cluster": cluster_for(len(d.get("ingredients", []))),
        }

    rows = []
    for line in open(RESULTS_DIR / "runs.jsonl"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "error" in r:
            continue
        est = r.get("estimates", {}).get("V1") or {}
        if "kcal" not in est:
            continue
        g = gt.get(r["dish_id"])
        if not g:
            continue
        rows.append({
            "dish_id": r["dish_id"],
            "cluster": g["cluster"],
            **{f"pred_{n}":   est[n]   for n in NUTRIENTS},
            **{f"actual_{n}": g[n]     for n in NUTRIENTS},
        })
    return pd.DataFrame(rows)


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    """MAE, MAPE, wMAPE (взвешенная), simulated daily error."""
    mae = float(np.mean(np.abs(pred - actual)))
    mask = actual > 0
    mape = float(np.mean(np.abs(pred[mask] - actual[mask]) / actual[mask]) * 100)
    # wMAPE: суммарная абсолютная ошибка как % от суммы эталонов.
    # Эквивалентно «сколько % от дневного потребления составит ошибка».
    wmape = float(np.sum(np.abs(pred - actual)) / np.sum(actual) * 100) if np.sum(actual) > 0 else 0.0
    # Daily simulation: 1000 случайных «дней» по 5 блюд, средняя % ошибка по дню.
    rng = np.random.default_rng(seed=42)
    daily_pcts = []
    n = len(actual)
    if n >= 5:
        for _ in range(1000):
            idx = rng.choice(n, size=5, replace=False)
            day_actual = actual[idx].sum()
            day_pred   = pred[idx].sum()
            if day_actual > 0:
                daily_pcts.append(abs(day_pred - day_actual) / day_actual * 100)
    daily_mape = float(np.mean(daily_pcts)) if daily_pcts else 0.0
    return {"MAE": mae, "MAPE": mape, "wMAPE": wmape, "daily_MAPE": daily_mape}


def fit_global(train: pd.DataFrame) -> dict:
    """Один LinearRegression на каждый нутриент."""
    out = {}
    for n in NUTRIENTS:
        X = train[[f"pred_{n}"]].values
        y = train[f"actual_{n}"].values
        reg = LinearRegression().fit(X, y)
        out[n] = {"a": float(reg.coef_[0]), "b": float(reg.intercept_)}
    return out


def fit_log_global(train: pd.DataFrame) -> dict:
    """Log-space линейная регрессия: log(y) = a*log(x) + b.
    Эквивалентна мультипликативной коррекции y = exp(b) * x^a — оптимизирует MAPE."""
    out = {}
    for n in NUTRIENTS:
        x = train[f"pred_{n}"].values
        y = train[f"actual_{n}"].values
        mask = (x > 0) & (y > 0)
        X = np.log(x[mask]).reshape(-1, 1)
        Y = np.log(y[mask])
        reg = LinearRegression().fit(X, Y)
        out[n] = {"a": float(reg.coef_[0]), "b": float(reg.intercept_)}
    return out


def fit_log_per_cluster(train: pd.DataFrame) -> dict:
    out = {}
    for cluster in ["simple", "medium", "complex"]:
        sub = train[train["cluster"] == cluster]
        if len(sub) < 5:
            out[cluster] = None
            continue
        out[cluster] = {}
        for n in NUTRIENTS:
            x = sub[f"pred_{n}"].values
            y = sub[f"actual_{n}"].values
            mask = (x > 0) & (y > 0)
            if mask.sum() < 3:
                out[cluster][n] = {"a": 1.0, "b": 0.0}
                continue
            X = np.log(x[mask]).reshape(-1, 1)
            Y = np.log(y[mask])
            reg = LinearRegression().fit(X, Y)
            out[cluster][n] = {"a": float(reg.coef_[0]), "b": float(reg.intercept_)}
    return out


def apply_log_global(df: pd.DataFrame, coeffs: dict) -> pd.DataFrame:
    out = df.copy()
    for n in NUTRIENTS:
        c = coeffs[n]
        x = df[f"pred_{n}"].values
        # для x<=0 оставляем как есть
        with np.errstate(invalid="ignore"):
            corrected = np.where(x > 0, np.exp(c["b"]) * np.power(x, c["a"]), x)
        out[f"corr_{n}"] = corrected
    return out


def apply_log_per_cluster(df: pd.DataFrame, coeffs: dict) -> pd.DataFrame:
    out = df.copy()
    for n in NUTRIENTS:
        out[f"corr_{n}"] = df[f"pred_{n}"]  # default fallback
    for cluster, c in coeffs.items():
        if c is None:
            continue
        mask = df["cluster"] == cluster
        for n in NUTRIENTS:
            x = df.loc[mask, f"pred_{n}"].values
            with np.errstate(invalid="ignore"):
                corrected = np.where(x > 0, np.exp(c[n]["b"]) * np.power(x, c[n]["a"]), x)
            out.loc[mask, f"corr_{n}"] = corrected
    return out


def fit_per_cluster(train: pd.DataFrame) -> dict:
    """LinearRegression отдельно для simple/medium/complex."""
    out = {}
    for cluster in ["simple", "medium", "complex"]:
        sub = train[train["cluster"] == cluster]
        if len(sub) < 5:
            out[cluster] = None
            continue
        out[cluster] = {}
        for n in NUTRIENTS:
            X = sub[[f"pred_{n}"]].values
            y = sub[f"actual_{n}"].values
            reg = LinearRegression().fit(X, y)
            out[cluster][n] = {"a": float(reg.coef_[0]), "b": float(reg.intercept_)}
    return out


def apply_global(df: pd.DataFrame, coeffs: dict) -> pd.DataFrame:
    out = df.copy()
    for n in NUTRIENTS:
        c = coeffs[n]
        out[f"corr_{n}"] = c["a"] * df[f"pred_{n}"] + c["b"]
    return out


def apply_per_cluster(df: pd.DataFrame, coeffs: dict) -> pd.DataFrame:
    out = df.copy()
    for n in NUTRIENTS:
        out[f"corr_{n}"] = np.nan
    for cluster, c in coeffs.items():
        if c is None:
            continue
        mask = df["cluster"] == cluster
        for n in NUTRIENTS:
            out.loc[mask, f"corr_{n}"] = c[n]["a"] * df.loc[mask, f"pred_{n}"] + c[n]["b"]
    # на случай пустого кластера — оставляем оригинальное предсказание
    for n in NUTRIENTS:
        out[f"corr_{n}"] = out[f"corr_{n}"].fillna(out[f"pred_{n}"])
    return out


def evaluate_on(df: pd.DataFrame, pred_prefix: str, label: str) -> dict:
    res = {"variant": label}
    for n in NUTRIENTS:
        pred = df[f"{pred_prefix}_{n}"].values
        actual = df[f"actual_{n}"].values
        m = metrics(actual, pred)
        for k, v in m.items():
            res[f"{k}_{n}"] = round(v, 2)
    return res


def print_table(rows: list[dict], header: str):
    print(f"\n=== {header} (по kcal) ===\n")
    print(f"{'Variant':<28} | {'MAE':>7} | {'MAPE':>7} | {'wMAPE':>7} | {'daily_MAPE':>11}")
    print("-" * 75)
    for r in rows:
        print(f"{r['variant']:<28} | {r['MAE_kcal']:>7.1f} | "
              f"{r['MAPE_kcal']:>6.1f}% | {r['wMAPE_kcal']:>6.1f}% | {r['daily_MAPE_kcal']:>10.1f}%")
    print("\nMAE — средняя абс. ошибка (ккал)")
    print("MAPE — среднее по блюдам относительной ошибки (искажается малыми порциями)")
    print("wMAPE — Σ|err| / Σactual ×100 — отражает суммарную ошибку относительно потребления")
    print("daily_MAPE — симуляция 5 случайных блюд за «день», средняя % ошибка по 1000 дней")


def main():
    df = load_data()
    print(f"Загружено {len(df)} (predicted, actual) пар по V1\n")
    print("Состав по кластерам:")
    for c, n in df["cluster"].value_counts().items():
        print(f"  {c}: {n}")

    # 70/30 train/test, стратификация по кластеру
    train, test = train_test_split(df, test_size=0.30, random_state=42, stratify=df["cluster"])
    print(f"\nTrain: {len(train)}  Test: {len(test)}\n")

    # обучаем коррекции на train
    g_coef    = fit_global(train)
    c_coef    = fit_per_cluster(train)
    lg_coef   = fit_log_global(train)
    lc_coef   = fit_log_per_cluster(train)

    # применяем на test
    test_g    = apply_global(test, g_coef)
    test_c    = apply_per_cluster(test, c_coef)
    test_lg   = apply_log_global(test, lg_coef)
    test_lc   = apply_log_per_cluster(test, lc_coef)

    rows = [
        evaluate_on(test,    "pred", "baseline (без коррекции)"),
        evaluate_on(test_g,  "corr", "linear OLS, global"),
        evaluate_on(test_c,  "corr", "linear OLS, per-cluster"),
        evaluate_on(test_lg, "corr", "log-space, global"),
        evaluate_on(test_lc, "corr", "log-space, per-cluster"),
    ]
    print_table(rows, "Метрики на TEST")

    # коэффициенты — для применения в продакшен
    print("\n=== Коэффициенты global linear (для пост-коррекции в боте) ===")
    print(f"{'Nutrient':<10} {'a':>8} {'b':>8}")
    for n in NUTRIENTS:
        print(f"{n:<10} {g_coef[n]['a']:>8.3f} {g_coef[n]['b']:>8.2f}")

    print("\n=== Коэффициенты per-cluster (a, b) ===")
    print(f"{'Cluster':<10} | "
          f"{'kcal a/b':>16} | {'protein a/b':>16} | {'fat a/b':>16} | {'carbs a/b':>16}")
    for cluster, c in c_coef.items():
        if c is None:
            print(f"{cluster:<10} | (мало данных)")
            continue
        parts = " | ".join(
            f"{c[n]['a']:>6.3f}/{c[n]['b']:>6.1f}" for n in NUTRIENTS
        )
        print(f"{cluster:<10} | {parts}")

    print("\n=== log-space global коэффициенты (формула: actual = exp(b) * predicted^a) ===")
    print(f"{'Nutrient':<10} {'a':>8} {'b':>8}   {'эквивалент при a≈1':>30}")
    for n in NUTRIENTS:
        c = lg_coef[n]
        mult = np.exp(c["b"])
        print(f"{n:<10} {c['a']:>8.3f} {c['b']:>8.3f}   множитель ≈ {mult:.3f}")

    # сохраняем
    out = {
        "linear_global":       g_coef,
        "linear_per_cluster":  c_coef,
        "log_global":          lg_coef,
        "log_per_cluster":     lc_coef,
        "train_size":          len(train),
        "test_size":           len(test),
        "test_metrics":        rows,
    }
    out_path = RESULTS_DIR / "calibration_coefficients.json"
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nКоэффициенты и метрики сохранены: {out_path}")


if __name__ == "__main__":
    main()
