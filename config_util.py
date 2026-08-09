"""โหลด config.yaml + ตั้งค่า logging (ใช้ร่วมกันทุกสคริปต์)"""

import logging
import os
import sys

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "line_sender.log")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(
            "ไม่พบ config.yaml — กรุณาคัดลอก config.example.yaml เป็น config.yaml ก่อน",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_targets(cfg: dict) -> list:
    """คืนรายชื่อกลุ่มเป้าหมายทั้งหมดที่นิยามไว้: [{name, chat_row}]
    ถ้าไม่ได้นิยาม line.targets จะ fallback เป็นกลุ่มเดียวจาก target_name + coords.chat_row
    """
    line = cfg.get("line", {}) or {}
    defined = line.get("targets") or []
    out = []
    for t in defined:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        row = t.get("chat_row") or line.get("coords", {}).get("chat_row", [240, 140])
        out.append({"name": name, "chat_row": row})
    if not out:
        out = [{
            "name": (line.get("target_name") or "").strip(),
            "chat_row": line.get("coords", {}).get("chat_row", [240, 140]),
        }]
    return out


def resolve_targets(cfg: dict, want) -> list:
    """เลือกกลุ่มเป้าหมายสำหรับข้อความหนึ่ง
    want = ชื่อกลุ่มที่ต้องการ (list หรือ str คั่นด้วย ,) ; ว่าง/None = ส่งทุกกลุ่มที่นิยามไว้
    """
    allt = get_targets(cfg)
    if not want:
        return allt
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",")]
    want = [w.strip() for w in want if str(w).strip()]
    if not want:
        return allt
    sel = [t for t in allt if t["name"] in want]
    return sel or allt


def setup_logging(level=logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )
