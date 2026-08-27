"""
eval_runner.py — Vasi Evaluation Runner
Kullanım: python evaluation/eval_runner.py
"""
import sys
import json
import importlib
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock
import os
import yaml

# vasi.py'yi import edebilmek için proje kökünü path'e ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ortam değişkenlerini mock'la — bot başlatılmasın
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("MY_TELEGRAM_ID", "000000")
os.environ.setdefault("WORKSPACE_DIR", str(ROOT / "workspace"))
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")

# vasi modülünü yükle
if "vasi" in sys.modules:
    del sys.modules["vasi"]
vasi = importlib.import_module("vasi")

PROMPTS_DIR = Path(__file__).parent / "prompts"
RESULTS_DIR = Path(__file__).parent / "results"


def resolve_results_dir() -> Path:
    configured = Path(os.getenv("EVAL_RESULTS_DIR", str(RESULTS_DIR)))
    try:
        configured.mkdir(parents=True, exist_ok=True)
        probe = configured / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return configured
    except OSError:
        fallback = Path("/tmp/vasi_eval_results")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def run_evaluation():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = resolve_results_dir()
    result_file = results_dir / f"eval_{timestamp}.json"

    prompts = sorted(PROMPTS_DIR.glob("*.yaml"))
    if not prompts:
        print("❌ evaluation/prompts/ içinde YAML dosyası bulunamadı.")
        return

    results = []
    passed = 0
    failed = 0

    for prompt_path in prompts:
        with open(prompt_path, encoding="utf-8") as f:
            prompt = yaml.safe_load(f)

        pid         = prompt.get("id", prompt_path.stem)
        description = prompt.get("description", "")
        input_text  = prompt.get("input", "")
        expected    = prompt.get("expected", {})

        checks = []
        ok     = True

        # 1. Skill tespiti kontrolü
        expected_skill = expected.get("skill", None)
        if expected_skill is not None:
            skill_name, _ = vasi.detect_skill(input_text)
            detected = skill_name.lower().replace(" ", "_") if skill_name else ""
            exp_clean = expected_skill.replace(".md", "").lower()
            check_pass = (exp_clean in detected) if exp_clean else (detected == "")
            checks.append({
                "check": "skill_detection",
                "expected": expected_skill,
                "got": detected,
                "pass": check_pass
            })
            if not check_pass:
                ok = False

        # 2. Model rolü kontrolü
        expected_role = expected.get("model_role", None)
        if expected_role:
            selected_model = vasi.pick_model(input_text)
            role_model     = vasi.MODELS.get(expected_role, "")
            check_pass     = selected_model == role_model
            checks.append({
                "check": "model_role",
                "expected_role": expected_role,
                "expected_model": role_model,
                "got": selected_model,
                "pass": check_pass
            })
            if not check_pass:
                ok = False

        # 3. Path traversal engel kontrolü
        if expected.get("blocked"):
            path_result = vasi.safe_path(input_text)
            check_pass  = path_result is None
            checks.append({
                "check": "path_blocked",
                "input": input_text,
                "blocked": check_pass,
                "pass": check_pass
            })
            if not check_pass:
                ok = False

        status = "✅ PASS" if ok else "❌ FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"{status}  [{pid}] {description}")
        for c in checks:
            if not c["pass"]:
                print(f"       → {c['check']}: beklenen={c.get('expected') or c.get('expected_role')}, alınan={c.get('got') or c.get('blocked')}")

        results.append({
            "id": pid,
            "description": description,
            "pass": ok,
            "checks": checks
        })

    # Sonuçları kaydet
    report = {
        "timestamp": timestamp,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results
    }
    result_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'─'*40}")
    print(f"Toplam: {len(results)} | Geçti: {passed} | Kaldı: {failed}")
    try:
        report_path = result_file.relative_to(ROOT)
    except ValueError:
        report_path = result_file
    print(f"Rapor: {report_path}")

    return failed == 0


if __name__ == "__main__":
    success = run_evaluation()
    sys.exit(0 if success else 1)
