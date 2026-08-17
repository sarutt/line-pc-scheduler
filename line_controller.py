"""
LineController — ควบคุมหน้าต่างแอป LINE PC (Windows) เพื่อส่งข้อความเข้ากลุ่ม
วิธีทำงาน:
  1) หา (หรือเปิด) หน้าต่าง LINE
  2) คืนสภาพ + ย้าย/ปรับขนาดหน้าต่างไปตำแหน่งคงที่ แล้วโฟกัส
  3) คลิกกลุ่มที่ปักหมุดไว้บนสุด -> เข้าห้องแชท
  4) คลิกช่องพิมพ์ -> วางข้อความจาก clipboard (รองรับภาษาไทย) -> กด Enter ส่ง

หมายเหตุ: ต้อง calibrate พิกัดด้วย calibrate.py ก่อนใช้งานจริง
"""

import ctypes
import logging
import os
import time
from ctypes import wintypes

import pyautogui
import pyperclip

log = logging.getLogger("line_controller")

# กันเมาส์วิ่งชนมุมจอแล้ว fail-safe ของ pyautogui หยุดโปรแกรม
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

# ---------- พิมพ์ยูนิโค้ดผ่าน SendInput (รองรับอิโมจิ/surrogate pair ที่ send_keys ทำไม่ได้) ----------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_RETURN = 0x0D
_VK_SHIFT = 0x10
_ULONG_PTR = wintypes.WPARAM


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _ULONG_PTR))


class _MOUSEINPUT(ctypes.Structure):
    # ต้องมีเพื่อให้ union ขนาดเท่า INPUT จริง (ไม่งั้น sizeof ผิด SendInput ล้มเหลว)
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT))


class _INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT

# สำหรับจับตำแหน่งคลิกเมาส์ (เครื่องมือชี้ตำแหน่งกลุ่ม)
_VK_LBUTTON = 0x01
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = wintypes.SHORT
_user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
_user32.GetCursorPos.restype = wintypes.BOOL


def _mk(wVk=0, wScan=0, dwFlags=0):
    return _INPUT(type=_INPUT_KEYBOARD,
                  u=_INPUTUNION(ki=_KEYBDINPUT(wVk, wScan, dwFlags, 0, 0)))


def _send(*inputs):
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    sent = _user32.SendInput(n, arr, ctypes.sizeof(_INPUT))
    if sent != n:
        log.warning("SendInput ส่งได้ %d/%d (err=%s)", sent, n, ctypes.get_last_error())


def _tap_vk(vk, shift=False):
    if shift:
        _send(_mk(wVk=_VK_SHIFT))
    _send(_mk(wVk=vk))
    _send(_mk(wVk=vk, dwFlags=_KEYEVENTF_KEYUP))
    if shift:
        _send(_mk(wVk=_VK_SHIFT, dwFlags=_KEYEVENTF_KEYUP))


def type_unicode(text: str, per_char_delay: float = 0.004) -> None:
    """พิมพ์ข้อความยูนิโค้ดใด ๆ (ไทย/อิโมจิ) ลงหน้าต่างที่โฟกัสอยู่
    - '\\n' = Shift+Enter (ขึ้นบรรทัดใหม่ ไม่ส่ง)  ; Enter เดี่ยวเว้นไว้ให้ผู้เรียกกดส่งเอง
    - อักขระ >U+FFFF (อิโมจิ) ส่งเป็น surrogate pair 2 ยูนิต
    """
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            _tap_vk(_VK_RETURN, shift=True)
            continue
        utf16 = ch.encode("utf-16-le")
        units = [utf16[i] | (utf16[i + 1] << 8) for i in range(0, len(utf16), 2)]
        for cu in units:
            _send(_mk(wScan=cu, dwFlags=_KEYEVENTF_UNICODE))
            _send(_mk(wScan=cu, dwFlags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
        if per_char_delay:
            time.sleep(per_char_delay)


class LineControllerError(Exception):
    pass


class LineController:
    def __init__(self, cfg: dict):
        line_cfg = cfg["line"]
        self.window_title = line_cfg.get("window_title", "LINE")
        # class ของหน้าต่างหลัก LINE (ช่วยแยกจากหน้าต่างซ่อนที่ชื่อ "LINE" เหมือนกัน)
        self.window_class = line_cfg.get("window_class", "AllInOneWindow")
        # class ของหน้าต่างห้องแชตที่เด้งออกมาเมื่อ double-click
        self.chat_window_class = line_cfg.get("chat_window_class", "ChatWindow")
        # ชื่อห้อง/กลุ่มเป้าหมาย (ใช้ยืนยันว่าเปิดถูกห้องก่อนส่ง) เว้นว่าง=ไม่ตรวจ
        self.target_name = line_cfg.get("target_name", "")
        # ตำแหน่งช่องพิมพ์ในหน้าต่างห้องแชต: [ระยะจากซ้าย, ระยะจากล่าง] (พิกเซล)
        self.chat_input = line_cfg.get("chat_input", [90, 95])
        # ตำแหน่งปุ่มแนบไฟล์ (📎): [ระยะจากซ้าย, ระยะจากล่าง] (พิกเซล)
        self.attach_btn = line_cfg.get("attach_btn", [24, 25])
        # ปิดหน้าต่างห้องแชตหลังส่งเสร็จหรือไม่
        self.close_after = bool(line_cfg.get("close_chat_after", False))
        self.exe_path = os.path.expandvars(line_cfg.get("exe_path", ""))
        self.win_box = line_cfg["window"]
        self.coords = line_cfg["coords"]
        self.delays = line_cfg.get("delays", {})

    # ---------- helpers ----------
    def _delay(self, key: str, default: float) -> None:
        time.sleep(float(self.delays.get(key, default)))

    def _find_window(self):
        """หาหน้าต่างหลักของ LINE (เลือกอันที่มองเห็น + พื้นที่ใหญ่สุด)
        คืน HwndWrapper หรือ None
        LINE มักมีหน้าต่างชื่อ 'LINE' หลายอัน (มีหน้าต่างซ่อน) จึงต้องกรอง
        """
        from pywinauto.controls.hwndwrapper import HwndWrapper
        from pywinauto.findwindows import find_windows

        handles = []
        # 1) กรองด้วย class ก่อน (เจาะจงหน้าต่างหลัก)
        if self.window_class:
            try:
                handles = list(find_windows(class_name=self.window_class))
            except Exception:  # noqa: BLE001
                handles = []
        # 2) ถ้าไม่เจอ ค่อยใช้ title
        if not handles:
            try:
                handles = list(find_windows(title=self.window_title))
            except Exception:  # noqa: BLE001
                handles = []

        best, best_area = None, -1
        for h in handles:
            try:
                w = HwndWrapper(h)
                if not w.is_visible():
                    continue
                r = w.rectangle()
                area = (r.right - r.left) * (r.bottom - r.top)
                if area > best_area:
                    best, best_area = w, area
            except Exception:  # noqa: BLE001
                continue
        return best

    def _connect_window(self):
        """หา top-level window ของ LINE ; ถ้าไม่เจอและมี exe_path จะเปิดให้"""
        win = self._find_window()
        if win is not None:
            return win

        # ไม่เจอ -> ลองเปิด LINE
        if self.exe_path and os.path.exists(self.exe_path):
            log.info("LINE ไม่ได้เปิดอยู่ กำลังเปิดจาก %s", self.exe_path)
            os.startfile(self.exe_path)  # noqa: S606
            self._delay("after_launch", 6.0)
            win = self._find_window()
            if win is not None:
                return win
            raise LineControllerError(
                f"เปิด LINE แล้วแต่ยังหาหน้าต่าง class='{self.window_class}' / "
                f"title='{self.window_title}' ไม่เจอ"
            )

        raise LineControllerError(
            f"หาหน้าต่าง LINE ไม่เจอ (class='{self.window_class}', title='{self.window_title}') "
            f"— เปิด LINE ค้างไว้ หรือใส่ exe_path ใน config.yaml"
        )

    def _prepare_window(self):
        """คืนสภาพ ย้าย/ปรับขนาด แล้วโฟกัสหน้าต่าง LINE ; คืน rectangle"""
        win = self._connect_window()
        try:
            if win.is_minimized():
                win.restore()
        except Exception:  # noqa: BLE001
            pass

        b = self.win_box
        try:
            win.move_window(
                x=int(b["x"]), y=int(b["y"]),
                width=int(b["width"]), height=int(b["height"]),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ปรับขนาดหน้าต่างไม่สำเร็จ (%s) — ใช้ตำแหน่งเดิม", exc)

        try:
            win.set_focus()
        except Exception:  # noqa: BLE001
            # บางครั้ง set_focus ล้มเหลว ลองคลิกกลางหน้าต่างแทน
            pass

        self._delay("after_focus", 1.0)
        rect = win.rectangle()
        log.debug("LINE window rect: %s", rect)
        return rect

    def capture_click_position(self, timeout: float = 20.0):
        """เครื่องมือชี้ตำแหน่ง: จัดหน้าต่าง LINE ให้ตำแหน่งคงที่ แล้วรอผู้ใช้คลิก 1 ครั้ง
        คืนพิกัด [relx, rely] (เทียบมุมซ้ายบนหน้าต่าง) หรือ None ถ้าหมดเวลา
        """
        rect = self._prepare_window()
        start = time.time()
        # 1) รอให้ปล่อยปุ่มซ้ายก่อน (กันจับคลิกที่เพิ่งกดปุ่มบนหน้าเว็บ)
        while _user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000:
            if time.time() - start > timeout:
                return None
            time.sleep(0.01)
        # 2) รอคลิกซ้ายครั้งใหม่
        while not (_user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000):
            if time.time() - start > timeout:
                return None
            time.sleep(0.01)
        # อ่านพิกัดด้วย pyautogui.position() ให้อยู่ coordinate space เดียวกับตอนคลิกส่ง
        # (GetCursorPos เป็น physical pixels อาจไม่ตรงกับ pyautogui เมื่อมี DPI scaling)
        px, py = pyautogui.position()
        return [int(px - rect.left), int(py - rect.top)]

    def _double_click_rel(self, rect, coord_key: str) -> None:
        self._double_click_coord(rect, self.coords[coord_key])

    def _double_click_coord(self, rect, coord) -> None:
        x = rect.left + int(coord[0])
        y = rect.top + int(coord[1])
        log.debug("double-click -> (%d, %d)", x, y)
        pyautogui.doubleClick(x, y)

    def _find_chat_window(self, expected_name: str = ""):
        """หาหน้าต่างห้องแชต (pop-out, class=ChatWindow) ผ่าน UIA
        ถ้าระบุ expected_name จะเลือกเฉพาะหน้าต่างที่ชื่อ (title) ตรงกัน
        """
        from pywinauto import Desktop

        want = (expected_name or "").strip()
        fallback = None
        for w in Desktop(backend="uia").windows():
            try:
                if w.element_info.class_name != self.chat_window_class:
                    continue
                if not w.is_visible():
                    continue
                title = w.window_text()
            except Exception:  # noqa: BLE001
                continue
            if want:
                if want in title or title in want:
                    return w
            else:
                fallback = w
        return fallback

    # การพิมพ์ผ่าน send_keys ต้อง escape อักขระพิเศษเหล่านี้
    _SK_SPECIAL = set("^+%~(){}[]")

    def _sk_escape(self, s: str) -> str:
        return "".join("{" + c + "}" if c in self._SK_SPECIAL else c for c in s)

    def _type_text(self, text: str) -> None:
        """พิมพ์ข้อความลงช่องผ่าน SendInput (รองรับไทย + อิโมจิ)
        '\\n' = Shift+Enter (ขึ้นบรรทัดใหม่ ไม่ส่ง) ; ผู้เรียกกด Enter ส่งเอง
        """
        type_unicode(text)

    def _find_visible_file_dialog(self):
        """หา File Open dialog (#32770) ที่มองเห็นได้ (มีซ่อนหลายอัน จึงเลือกอันใหญ่สุด)"""
        from pywinauto.findwindows import find_windows
        from pywinauto.controls.hwndwrapper import HwndWrapper

        best, area = None, -1
        for h in find_windows(class_name="#32770"):
            try:
                w = HwndWrapper(h)
                if not w.is_visible():
                    continue
                r = w.rectangle()
                a = (r.right - r.left) * (r.bottom - r.top)
                if a > area:
                    area, best = a, h
            except Exception:  # noqa: BLE001
                continue
        return best

    def _attach_images(self, chat_rect, image_paths) -> None:
        """คลิกปุ่มแนบไฟล์ (📎) -> ใส่หลายไฟล์ในไดอะล็อกครั้งเดียว -> เปิดทั้งหมด (ยังไม่กด Enter ส่ง)
        รับได้ทั้ง str (ไฟล์เดียว) หรือ list (หลายไฟล์ — เลือกพร้อมกันในครั้งเดียว)
        """
        from pywinauto import Application
        import pywinauto.keyboard as kb

        if isinstance(image_paths, str):
            image_paths = [image_paths]
        # File dialog ต้องเป็นพาธ Windows (\) ; ครอบ "" แต่ละไฟล์ คั่นด้วยเว้นวรรค = เลือกหลายไฟล์
        quoted = " ".join(f'"{os.path.normpath(p)}"' for p in image_paths)

        px = chat_rect.left + int(self.attach_btn[0])
        py = chat_rect.bottom - int(self.attach_btn[1])
        pyautogui.click(px, py)
        self._delay("after_attach", 1.6)

        h = self._find_visible_file_dialog()
        if not h:
            raise LineControllerError("ไม่พบ File dialog หลังคลิกปุ่มแนบไฟล์ (ตรวจ attach_btn)")
        app = Application(backend="win32").connect(handle=h)
        dlg = app.window(handle=h)
        try:
            dlg.set_focus()
        except Exception:  # noqa: BLE001
            pass
        try:
            dlg.child_window(class_name="Edit", found_index=0).set_edit_text(quoted)
        except Exception:  # noqa: BLE001
            kb.send_keys(self._sk_escape(quoted), with_spaces=True)
        time.sleep(0.4)
        kb.send_keys("{ENTER}")  # เปิดไฟล์ทั้งหมด
        self._delay("after_file_open", 2.2)

    @staticmethod
    def _normalize_images(image) -> list:
        """รับ image เป็น str (พาธเดียว หรือหลายพาธคั่นด้วยขึ้นบรรทัดใหม่) หรือ list -> คืน list พาธ"""
        if not image:
            return []
        if isinstance(image, (list, tuple)):
            items = [str(p) for p in image]
        else:
            items = str(image).splitlines()
        out = []
        for p in items:
            p = os.path.expandvars(os.path.expanduser(p.strip()))
            if p:
                # แปลงเป็นพาธรูปแบบ Windows (\) — File dialog หา / ไม่เจอ
                out.append(os.path.normpath(p))
        return out

    # ---------- public ----------
    def send(self, text: str = "", image="", order: str = "image_first",
             chat_row=None, target_name: str = None, should_stop=None) -> None:
        """ส่งข้อความ/รูป เข้ากลุ่มเป้าหมาย
        - text  = ข้อความ
        - image = พาธไฟล์รูป ส่งได้ >1 รูป (ใส่เป็น list หรือ str หลายบรรทัด)
        - order = ลำดับส่ง: "image_first" (รูปก่อนข้อความ, ค่าเริ่มต้น) หรือ "text_first" (ข้อความก่อนรูป)
        - chat_row / target_name = ระบุกลุ่มเป้าหมายเจาะจง (พิกัดแถว + ชื่อยืนยัน)
              ถ้าไม่ระบุ ใช้ค่าเริ่มต้นจาก config (coords.chat_row / target_name)

        ขั้นตอน (พิสูจน์แล้วว่าเวิร์กกับ LINE PC):
          1) จัดหน้าต่างหลัก -> double-click แถวกลุ่มที่ปักหมุด (เปิดเป็นหน้าต่างแยก)
          2) หา ChatWindow + ตรวจชื่อให้ตรงเป้าหมาย (กันส่งผิดห้อง)
          3) รูป: คลิก 📎 -> File dialog -> เปิดไฟล์ ; ข้อความ: พิมพ์ (ไม่ paste) -> Enter
        """
        text = text or ""
        images = self._normalize_images(image)
        if not text and not images:
            raise ValueError("ต้องมี text หรือ image อย่างน้อยหนึ่งอย่าง")
        for p in images:
            if not os.path.exists(p):
                raise LineControllerError(f"ไม่พบไฟล์รูป: {p}")

        chat_row = chat_row if chat_row is not None else self.coords.get("chat_row", [240, 140])
        target_name = self.target_name if target_name is None else target_name

        import pywinauto.keyboard as kb

        rect = self._prepare_window()

        # 1) เปิดห้องแชท (double-click แถวกลุ่มเป้าหมาย) -> เด้งหน้าต่างแยก
        #    ลองได้ถึง 3 ครั้ง + โฟกัสหน้าต่างหลักใหม่ก่อนลองซ้ำ
        #    (เผื่อคลิกแรกแค่ปลุกหน้าต่างให้ active ทำให้ double-click ไม่ติด)
        cw = None
        for _attempt in range(3):
            self._double_click_coord(rect, chat_row)
            self._delay("after_open_chat", 1.2)
            cw = self._find_chat_window(target_name)
            if cw is not None:
                break
            rect = self._prepare_window()

        # 2) ตรวจว่าเจอหน้าต่างห้องแชต
        if cw is None:
            raise LineControllerError(
                "ไม่พบหน้าต่างห้องแชต (ChatWindow) หลัง double-click "
                "— ตรวจพิกัด chat_row / ปักหมุดกลุ่มไว้บนสุด"
            )
        title = cw.window_text()
        if target_name and target_name.strip() and \
                target_name.strip() not in title and title not in target_name.strip():
            raise LineControllerError(
                f"ห้องที่เปิด ('{title}') ไม่ตรงกับเป้าหมาย ('{target_name}') — ยกเลิกการส่งเพื่อความปลอดภัย"
            )

        # ---- ฟังก์ชันย่อย: ส่งรูป / ส่งข้อความ (แต่ละอันหา ChatWindow ใหม่เอง) ----
        def _focus_chat():
            nonlocal cw
            cw = self._find_chat_window(target_name) or cw
            try:
                cw.set_focus()
            except Exception:  # noqa: BLE001
                pass
            return cw.rectangle()

        def _stopped():
            return bool(should_stop and should_stop())

        def do_images():
            if not images:
                return
            if _stopped():
                log.info("หยุดกลางคัน (ก่อนส่งรูป) เข้า '%s'", title)
                return
            # แนบรูปทั้งหมดในครั้งเดียว -> Enter ส่งพร้อมกัน
            r = _focus_chat()
            self._attach_images(r, images)
            _focus_chat()
            kb.send_keys("{ENTER}")
            names = ", ".join(os.path.basename(p) for p in images)
            log.info("ส่งรูป %d รูปพร้อมกันเข้า '%s' (%s)", len(images), title, names)
            time.sleep(0.6)

        def do_text():
            if not text:
                return
            if _stopped():
                log.info("หยุดกลางคัน (ก่อนส่งข้อความ) เข้า '%s'", title)
                return
            r = _focus_chat()
            fl, fb = self.chat_input
            ix, iy = r.left + int(fl), r.bottom - int(fb)
            pyautogui.click(ix, iy)
            time.sleep(0.3)
            pyautogui.click(ix, iy)
            self._delay("after_click_box", 0.5)
            kb.send_keys("^a")
            time.sleep(0.1)
            kb.send_keys("{BACKSPACE}")
            time.sleep(0.1)
            self._type_text(text)
            self._delay("after_paste", 0.4)
            kb.send_keys("{ENTER}")
            log.info("ส่งข้อความสำเร็จเข้า '%s' (%d ตัวอักษร)", title, len(text))

        # 3) ส่งตามลำดับที่เลือก
        if str(order) == "text_first":
            do_text()
            do_images()
        else:
            do_images()
            do_text()

        if self.close_after:
            try:
                cw.close()
            except Exception:  # noqa: BLE001
                pass
