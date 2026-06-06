# -*- coding: utf-8 -*-
import sys
import ctypes
import winreg
import subprocess
import win32gui
import win32process
import win32api
import win32con
import psutil
from ctypes import wintypes
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QHBoxLayout,
                             QMessageBox, QSystemTrayIcon, QMenu, QAction,
                             QVBoxLayout, QLabel, QFrame, QButtonGroup, QRadioButton, QCheckBox,
                             QSpinBox, QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QTimer, QSettings, QSharedMemory, QPropertyAnimation, QEasingCurve, QRect, QEvent
from PyQt5.QtGui import QIcon, QPainter, QColor, QBrush, QFontMetrics, QPixmap, QFont, QFontDatabase

# ---------------------------- 单实例控制 ---------------------------------
def check_single_instance():
    shared_memory = QSharedMemory("EmergencyTaskManager_SingleInstance")
    if shared_memory.attach():
        return True
    if shared_memory.create(1):
        return False
    return True

# ---------------------------- 全局配置 ---------------------------------
current_config = {}
last_active_hwnd = None

def load_global_config():
    s = QSettings("EmergencyTaskManager", "Settings")
    global current_config
    current_config = {
        "auto_start": s.value("auto_start", False, type=bool),
        "mode": s.value("mode", 1, type=int),
        "no_confirm_kill": s.value("no_confirm_kill", False, type=bool),
        "fullscreen_no_kill": s.value("fullscreen_no_kill", False, type=bool),
        "font_family": s.value("font_family", "Microsoft YaHei", type=str),
        "font_size": s.value("font_size", 10, type=int)
    }

def save_global_config():
    s = QSettings("EmergencyTaskManager", "Settings")
    for k, v in current_config.items():
        s.setValue(k, v)
    s.sync()
    set_auto_start(current_config["auto_start"])
    apply_global_font()

def apply_global_font():
    font = QFont(current_config["font_family"], current_config["font_size"])
    QApplication.setFont(font)
    for widget in QApplication.allWidgets():
        widget.setFont(font)

# ---------------------------- 辅助函数 ---------------------------------
user32 = ctypes.windll.user32
user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.IsHungAppWindow.restype = wintypes.BOOL

def is_window_not_responding(hwnd):
    try:
        return user32.IsHungAppWindow(hwnd) != 0
    except:
        return False

def is_fullscreen(hwnd):
    try:
        rect = win32gui.GetWindowRect(hwnd)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        monitor = win32api.MonitorFromWindow(hwnd)
        monitor_info = win32api.GetMonitorInfo(monitor)
        work_area = monitor_info["Work"]
        covers_work = (rect[0] <= work_area[0] and rect[1] <= work_area[1] and
                       rect[2] >= work_area[2] and rect[3] >= work_area[3])
        if not covers_work:
            return False
        if not (style & win32con.WS_CAPTION):
            return True
        if (style & win32con.WS_MAXIMIZE) and not (style & win32con.WS_BORDER):
            return True
        return False
    except:
        return False

def set_auto_start(enable):
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "EmergencyTaskManager"
    path = sys.argv[0]
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, path)
        else:
            try: winreg.DeleteValue(k, name)
            except: pass
        winreg.CloseKey(k)
    except Exception as e:
        print("开机自启动设置失败", e)

def open_system_settings():
    subprocess.Popen("start ms-settings:", shell=True)

def send_menu_key():
    win32api.keybd_event(win32con.VK_APPS, 0, 0, 0)
    win32api.keybd_event(win32con.VK_APPS, 0, win32con.KEYEVENTF_KEYUP, 0)

def open_program_menu():
    global last_active_hwnd
    if last_active_hwnd and win32gui.IsWindow(last_active_hwnd):
        try:
            win32gui.ShowWindow(last_active_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(last_active_hwnd)
            QTimer.singleShot(1000, send_menu_key)
        except:
            pass

# ---------------------------- 滚动按钮 ---------------------------------
class ScrollingButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.full_text = text
        self.offset = 0
        self.scroll_timer = QTimer()
        self.scroll_timer.timeout.connect(self.update_offset)
        self.scroll_timer.start(100)
        self.setMinimumWidth(80)

    def setText(self, text):
        self.full_text = text
        self.update_text()

    def update_text(self):
        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(self.full_text)
        if text_width <= self.width():
            super().setText(self.full_text)
            self.scroll_timer.stop()
        else:
            self.scroll_timer.start()
            self.offset = 0
            self.update_offset()

    def update_offset(self):
        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(self.full_text)
        if text_width > self.width():
            self.offset = (self.offset + 2) % (text_width + self.width())
            scroll_text = self.full_text + "   " + self.full_text
            visible_len = int((self.width() / text_width) * len(scroll_text)) + 1
            visible_text = scroll_text[self.offset:self.offset + visible_len]
            super().setText(visible_text)
        else:
            super().setText(self.full_text)

    def resizeEvent(self, event):
        self.update_text()
        super().resizeEvent(event)

# ---------------------------- 悬浮按钮 ---------------------------------
_our_button_hwnds = set()

class FloatingButton(QWidget):
    def __init__(self, target_hwnd, target_pid, parent=None):
        super().__init__(parent)
        self.target_hwnd = target_hwnd
        self.target_pid = target_pid

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a6ea5;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #2c4e7a; }
        """)
        self.settings_btn.clicked.connect(self.open_settings)

        self.kill_btn = ScrollingButton("❌ 结束进程")
        self.kill_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: bold;
                font-family: 'Microsoft YaHei';
            }
            QPushButton:hover { background-color: #cc0000; }
        """)
        self.kill_btn.clicked.connect(self.terminate_process)

        layout.addWidget(self.settings_btn)
        layout.addWidget(self.kill_btn)
        self.adjustSize()

        self.load_config()
        self.update_kill_visibility()

        _our_button_hwnds.add(int(self.winId()))

        self.pos_timer = QTimer()
        self.pos_timer.timeout.connect(self.update_position)
        self.pos_timer.start(150)

    def load_config(self):
        self.mode = current_config["mode"]
        self.fullscreen_no_kill = current_config["fullscreen_no_kill"]

    def update_kill_visibility(self):
        try:
            active = (win32gui.GetForegroundWindow() == self.target_hwnd)
            hung = is_window_not_responding(self.target_hwnd)
            full = is_fullscreen(self.target_hwnd)

            if active:
                self.settings_btn.setVisible(True)
                if self.mode == 1:
                    show_kill = True
                elif self.mode == 2:
                    show_kill = hung
                elif self.mode == 3:
                    show_kill = True
                elif self.mode == 4:
                    show_kill = hung
                else:
                    show_kill = True
                if self.fullscreen_no_kill and not hung and full:
                    show_kill = False
                self.kill_btn.setVisible(show_kill)
                self.setVisible(True)
                self.adjustSize()
                return

            if self.mode == 1:
                show = hung
            elif self.mode == 2:
                show = hung
            elif self.mode == 3:
                show = False
            elif self.mode == 4:
                show = hung
            else:
                show = True
            if self.fullscreen_no_kill and not hung and full:
                show = False
            self.kill_btn.setVisible(show)
            self.settings_btn.setVisible(show)
            self.setVisible(show)
            if show:
                self.adjustSize()
        except Exception as e:
            print("更新可见性异常:", e)
            self.kill_btn.setVisible(True)
            self.settings_btn.setVisible(True)
            self.setVisible(True)

    def update_position(self):
        if win32gui.IsWindow(self.target_hwnd):
            rect = win32gui.GetWindowRect(self.target_hwnd)
            x = rect[2] - self.width() - 8
            y = rect[1] - 27
            screen = QApplication.primaryScreen().availableGeometry()
            if x + self.width() > screen.right():
                x = screen.right() - self.width()
            if y < screen.top():
                y = rect[1] + 15
            self.move(x, y)
        else:
            self.close()

    def terminate_process(self):
        if not current_config["no_confirm_kill"]:
            reply = QMessageBox.question(self, "确认结束进程",
                                         f"确定要结束进程吗？\nPID: {self.target_pid}",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        try:
            proc = psutil.Process(self.target_pid)
            proc.terminate()
            self.close()
        except psutil.AccessDenied:
            QMessageBox.critical(self, "权限不足", "无法结束进程，权限不足。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"结束失败: {e}")

    def open_settings(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'show_sidebar'):
            parent = parent.parent()
        if parent:
            parent.show_sidebar()

    def closeEvent(self, event):
        _our_button_hwnds.discard(int(self.winId()))
        self.pos_timer.stop()
        event.accept()

# ---------------------------- 侧边栏（主菜单 + 子菜单 + 动画 + 字体列表）---------------------------------
class SettingsSidebar(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.sidebar_width = 400  # 加宽以容纳字体列表
        screen = QApplication.primaryScreen().availableGeometry()
        self.screen_w = screen.width()
        self.screen_h = screen.height()
        self.setFixedSize(self.sidebar_width, self.screen_h)

        self.bg = QWidget(self)
        self.bg.setObjectName("bg")
        self.bg.setStyleSheet("""
            QWidget#bg {
                background-color: rgba(30,32,38,220);
                border-left: 2px solid rgba(255,255,255,30);
            }
            QPushButton {
                background-color: rgba(50,55,65,230);
                border: none;
                border-radius: 12px;
                padding: 12px;
                color: white;
                font-size: 14px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: rgba(70,75,85,230);
            }
            QLabel {
                color: white;
                font-size: 18px;
                font-weight: bold;
            }
            QRadioButton, QCheckBox {
                color: white;
                font-size: 13px;
                spacing: 8px;
            }
            QListWidget {
                background-color: #3a3c42;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 4px;
            }
            QListWidget::item:selected {
                background-color: #4caf50;
            }
            QSpinBox {
                background-color: #3a3c42;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        self.stack = QWidget(self.bg)
        self.stack.setGeometry(0, 0, self.sidebar_width, self.screen_h)
        self.main_menu = QWidget(self.stack)
        self.sub_menu = QWidget(self.stack)
        self.init_main_menu()
        self.init_sub_menu()
        self.stack_layout = QVBoxLayout(self.stack)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.stack_layout.addWidget(self.main_menu)
        self.stack_layout.addWidget(self.sub_menu)
        self.sub_menu.hide()
        self.main_menu.show()

        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(320)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        # 子菜单切换动画（透明度动画）
        self.fade_anim = QPropertyAnimation()
        self.fade_anim.setDuration(200)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)

        self.installEventFilter(self)
        self.setMouseTracking(True)

    def init_main_menu(self):
        layout = QVBoxLayout(self.main_menu)
        layout.setContentsMargins(25, 30, 25, 30)
        layout.setSpacing(30)

        title = QLabel("设置")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(title)

        self.btn_system = self.create_big_button("💻", "系统设置")
        self.btn_program = self.create_big_button("📌", "程序菜单")
        self.btn_tray = self.create_big_button("🎛️", "软件设置")

        self.btn_system.clicked.connect(self.on_system_settings)
        self.btn_program.clicked.connect(self.on_program_menu)
        self.btn_tray.clicked.connect(self.switch_to_sub_menu)

        layout.addWidget(self.btn_system)
        layout.addWidget(self.btn_program)
        layout.addWidget(self.btn_tray)
        layout.addStretch()

    def create_big_button(self, icon, text):
        btn = QPushButton()
        btn.setFixedHeight(90)
        btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(50,55,65,230);
                border: none;
                border-radius: 16px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: rgba(70,75,85,230);
            }
        """)
        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(0, 8, 0, 8)
        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        text_label = QLabel(text)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        btn_layout.addWidget(icon_label)
        btn_layout.addWidget(text_label)
        return btn

    def init_sub_menu(self):
        layout = QVBoxLayout(self.sub_menu)
        layout.setContentsMargins(25, 30, 25, 30)
        layout.setSpacing(12)

        back_btn = QPushButton("← 返回主菜单")
        back_btn.setStyleSheet("background-color: #3a6ea5; text-align: left; padding: 8px;")
        back_btn.clicked.connect(self.switch_to_main_menu)
        layout.addWidget(back_btn)

        self.cb_auto = QCheckBox("🔁 开机自启动")
        layout.addWidget(self.cb_auto)

        mode_label = QLabel("显示模式 (四选一)")
        mode_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        layout.addWidget(mode_label)

        self.mode_group = QButtonGroup(self)
        self.radio1 = QRadioButton("非活跃进程仅在未响应显示结束进程")
        self.radio2 = QRadioButton("所有进程仅未响应显示结束进程")
        self.radio3 = QRadioButton("仅活跃进程一直显示结束进程")
        self.radio4 = QRadioButton("仅活跃进程未响应显示结束进程")
        for rb in [self.radio1, self.radio2, self.radio3, self.radio4]:
            self.mode_group.addButton(rb)
            layout.addWidget(rb)

        mode_desc = QLabel(
            "🔹 模式1: 活跃窗口一直显示，非活跃窗口只在卡死时显示\n"
            "🔹 模式2: 所有窗口不卡死就不显示\n"
            "🔹 模式3: 只有活跃窗口显示，其他窗口不管\n"
            "🔹 模式4: 只有活跃窗口卡死时才显示"
        )
        mode_desc.setWordWrap(True)
        mode_desc.setStyleSheet("font-size: 11px; color: #aaa; background-color: rgba(0,0,0,0.3); border-radius: 6px; padding: 6px;")
        layout.addWidget(mode_desc)

        self.cb_no_confirm = QCheckBox("🔪 结束进程不询问（慎选）")
        layout.addWidget(self.cb_no_confirm)

        self.cb_fullscreen = QCheckBox("🖥️ 全屏应用非卡死情况下不弹出结束按钮")
        layout.addWidget(self.cb_fullscreen)

        # 字体设置：使用 QListWidget 列出所有系统字体
        font_label = QLabel("字体设置")
        font_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(font_label)

        self.font_list = QListWidget()
        self.font_list.setMaximumHeight(150)
        self.font_list.setSelectionMode(QListWidget.SingleSelection)
        # 获取系统所有字体
        db = QFontDatabase()
        all_fonts = db.families()
        for font_name in all_fonts:
            item = QListWidgetItem(font_name)
            self.font_list.addItem(item)
        self.font_list.itemClicked.connect(self.on_font_selected)

        layout.addWidget(self.font_list)

        # 字号选择
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("字号:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 20)
        self.font_spin.setValue(10)
        self.font_spin.valueChanged.connect(self.on_font_size_changed)
        size_layout.addWidget(self.font_spin)
        size_layout.addStretch()
        layout.addLayout(size_layout)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 保存配置")
        cancel_btn = QPushButton("❌ 取消")
        save_btn.setStyleSheet("background-color: #4caf50;")
        cancel_btn.setStyleSheet("background-color: #f44336;")
        save_btn.clicked.connect(self.save_and_exit)
        cancel_btn.clicked.connect(self.switch_to_main_menu)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.load_config_to_ui()

    def on_font_selected(self, item):
        # 选中字体后临时更新预览（不保存，等待保存按钮）
        self.selected_font = item.text()
        # 可以实时预览，但为了性能，仅在保存时真正应用

    def on_font_size_changed(self, value):
        self.selected_font_size = value

    def load_config_to_ui(self):
        self.cb_auto.setChecked(current_config["auto_start"])
        mode = current_config["mode"]
        if mode == 1:
            self.radio1.setChecked(True)
        elif mode == 2:
            self.radio2.setChecked(True)
        elif mode == 3:
            self.radio3.setChecked(True)
        else:
            self.radio4.setChecked(True)
        self.cb_no_confirm.setChecked(current_config["no_confirm_kill"])
        self.cb_fullscreen.setChecked(current_config["fullscreen_no_kill"])
        # 在字体列表中高亮当前配置的字体
        current_font = current_config["font_family"]
        items = self.font_list.findItems(current_font, Qt.MatchExactly)
        if items:
            self.font_list.setCurrentItem(items[0])
        else:
            # 如果找不到，默认选第一个
            self.font_list.setCurrentRow(0)
        self.font_spin.setValue(current_config["font_size"])
        self.selected_font = current_font
        self.selected_font_size = current_config["font_size"]

    def save_and_exit(self):
        current_config["auto_start"] = self.cb_auto.isChecked()
        if self.radio1.isChecked():
            current_config["mode"] = 1
        elif self.radio2.isChecked():
            current_config["mode"] = 2
        elif self.radio3.isChecked():
            current_config["mode"] = 3
        else:
            current_config["mode"] = 4
        current_config["no_confirm_kill"] = self.cb_no_confirm.isChecked()
        current_config["fullscreen_no_kill"] = self.cb_fullscreen.isChecked()
        # 获取选中的字体和字号
        selected_item = self.font_list.currentItem()
        if selected_item:
            current_config["font_family"] = selected_item.text()
        current_config["font_size"] = self.font_spin.value()
        save_global_config()
        if self.main_app:
            self.main_app.refresh_buttons_config()
        QMessageBox.information(self, "保存成功", "配置已保存成功！")
        self.switch_to_main_menu()
        apply_global_font()

    def switch_to_main_menu(self):
        # 淡出子菜单，淡入主菜单
        self.fade_anim.stop()
        self.fade_anim.setTargetObject(self.sub_menu)
        self.fade_anim.setPropertyName(b"windowOpacity")
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self._on_sub_hidden)
        self.fade_anim.start()

    def _on_sub_hidden(self):
        self.sub_menu.hide()
        self.main_menu.show()
        self.fade_anim.setTargetObject(self.main_menu)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

    def switch_to_sub_menu(self):
        self.fade_anim.stop()
        self.fade_anim.setTargetObject(self.main_menu)
        self.fade_anim.setPropertyName(b"windowOpacity")
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self._on_main_hidden)
        self.fade_anim.start()

    def _on_main_hidden(self):
        self.main_menu.hide()
        self.sub_menu.show()
        self.fade_anim.setTargetObject(self.sub_menu)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

    def on_system_settings(self):
        open_system_settings()
        self.hide_anim()

    def on_program_menu(self):
        open_program_menu()
        self.hide_anim()

    def eventFilter(self, obj, event):
        if obj == self:
            if event.type() == QEvent.Leave:
                self.hide_anim()
            elif event.type() == QEvent.MouseButtonPress:
                if not self.rect().contains(event.pos()):
                    self.hide_anim()
        return super().eventFilter(obj, event)

    def show_anim(self):
        self.anim.stop()
        start = QRect(self.screen_w, 0, self.sidebar_width, self.screen_h)
        end = QRect(self.screen_w - self.sidebar_width, 0, self.sidebar_width, self.screen_h)
        self.setGeometry(start)
        self.show()
        self.anim.setStartValue(start)
        self.anim.setEndValue(end)
        self.anim.start()

    def hide_anim(self):
        self.anim.stop()
        current = self.geometry()
        end = QRect(self.screen_w, 0, self.sidebar_width, self.screen_h)
        self.anim.setStartValue(current)
        self.anim.setEndValue(end)
        self.anim.finished.connect(self.on_hide_finished)
        self.anim.start()

    def on_hide_finished(self):
        self.hide()
        try:
            self.anim.finished.disconnect()
        except:
            pass

# ---------------------------- 主程序 ---------------------------------
class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setVisible(False)
        self.buttons = {}
        self.sidebar = None

        load_global_config()
        apply_global_font()

        self.last_active_timer = QTimer()
        self.last_active_timer.timeout.connect(self.update_last_active)
        self.last_active_timer.start(500)

        self.scan_and_update()
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.scan_and_update)
        self.scan_timer.start(800)

        self.visibility_timer = QTimer()
        self.visibility_timer.timeout.connect(self.refresh_buttons_visibility)
        self.visibility_timer.start(300)

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.create_tray_icon())
        self.tray.setToolTip("应急结束任务管理")
        menu = QMenu()
        show_action = QAction("⚙️ 设置", self)
        show_action.triggered.connect(self.show_sidebar)
        menu.addAction(show_action)
        quit_action = QAction("🚪 退出", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def create_tray_icon(self):
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(30,144,255)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(8,8,48,48,12,12)
        p.setPen(Qt.white)
        p.drawText(20,40,"E")
        p.end()
        return QIcon(pix)

    def update_last_active(self):
        global last_active_hwnd
        hwnd = win32gui.GetForegroundWindow()
        if hwnd and hwnd not in _our_button_hwnds:
            last_active_hwnd = hwnd

    def show_sidebar(self):
        if not self.sidebar:
            self.sidebar = SettingsSidebar(self)
        if self.sidebar.isVisible():
            self.sidebar.hide_anim()
        else:
            self.sidebar.show_anim()

    def refresh_buttons_config(self):
        for btn in self.buttons.values():
            btn.load_config()
            btn.update_kill_visibility()

    def scan_and_update(self):
        current_hwnds = set()
        def enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                if hwnd in _our_button_hwnds:
                    return True
                current_hwnds.add(hwnd)
            return True
        win32gui.EnumWindows(enum_cb, None)

        for hwnd in list(self.buttons.keys()):
            if hwnd not in current_hwnds:
                btn = self.buttons.pop(hwnd)
                btn.close()
                btn.deleteLater()

        for hwnd in current_hwnds:
            if hwnd in self.buttons:
                continue
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                if proc.name().lower() == "explorer.exe":
                    continue
            except:
                continue
            btn = FloatingButton(hwnd, pid, parent=self)
            btn.show()
            self.buttons[hwnd] = btn

    def refresh_buttons_visibility(self):
        for btn in self.buttons.values():
            btn.update_kill_visibility()

    def quit_app(self):
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()

if __name__ == "__main__":
    if check_single_instance():
        print("程序已在运行中，禁止启动第二个实例")
        sys.exit(0)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    main = MainApp()
    sys.exit(app.exec_())
