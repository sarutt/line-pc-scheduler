"""
calibrate.py — ช่วยหาพิกัดคลิก (chat_row / message_box) สำหรับ config.yaml

วิธีใช้:
  1) เปิด LINE PC ให้ล็อกอินและปักหมุดกลุ่มเป้าหมายไว้บนสุด
  2) รัน:  python calibrate.py
  3) สคริปต์จะย้าย/ปรับขนาดหน้าต่าง LINE ตาม config.yaml ให้ก่อน
  4) เอาเมาส์ไปวางบน "กลุ่มที่ปักหมุด" แล้วดูค่าพิกัด (relative) ที่พิมพ์ออกมา
  5) เอาเมาส์ไปวางบน "ช่องพิมพ์ข้อความ" แล้วดูค่าพิกัด
  6) นำค่าไปใส่ใน config.yaml -> line.coords.chat_row / message_box
  กด Ctrl+C เพื่อออก
"""

import time

import pyautogui

from config_util import load_config, setup_logging
from line_controller import LineController


def main() -> None:
    setup_logging()
    cfg = load_config()
    ctrl = LineController(cfg)

    print("กำลังจัดหน้าต่าง LINE ให้อยู่ตำแหน่งคงที่ ...")
    rect = ctrl._prepare_window()  # noqa: SLF001 (ใช้ภายในสำหรับ calibrate)
    print(f"หน้าต่าง LINE: left={rect.left} top={rect.top} "
          f"right={rect.right} bottom={rect.bottom}\n")
    print("เอาเมาส์ไปวางบนจุดที่ต้องการ แล้วอ่านค่า 'relative' ด้านล่าง")
    print("(relative = พิกัดเทียบกับมุมซ้ายบนของหน้าต่าง LINE — เอาค่านี้ไปใส่ config)")
    print("กด Ctrl+C เพื่อออก\n")

    try:
        while True:
            x, y = pyautogui.position()
            rel_x = x - rect.left
            rel_y = y - rect.top
            print(f"  screen=({x:>4},{y:>4})   relative=[{rel_x:>4}, {rel_y:>4}]",
                  end="\r", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nจบการ calibrate")


if __name__ == "__main__":
    main()
