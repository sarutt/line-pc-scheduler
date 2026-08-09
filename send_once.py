"""
send_once.py — ทดสอบส่งข้อความ 1 ครั้งทันที (ใช้ตรวจว่าพิกัด/หน่วงเวลาถูกต้อง)

วิธีใช้:
  python send_once.py "ข้อความที่จะส่ง"
  python send_once.py            # ถ้าไม่ใส่ จะส่งข้อความทดสอบเริ่มต้น
"""

import sys

from config_util import load_config, setup_logging
from line_controller import LineController


def main() -> None:
    setup_logging()
    cfg = load_config()

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = "ทดสอบส่งข้อความจาก LINE PC Scheduler ✅"

    ctrl = LineController(cfg)
    ctrl.send(text)


if __name__ == "__main__":
    main()
