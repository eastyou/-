import os, sys, cv2, hashlib, threading, smtplib
from datetime import datetime
from PyQt5.QtCore import Qt, QTimer, QTime
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QSpinBox, QMessageBox, QTimeEdit)
from pynput import mouse, keyboard

# ------------------- 配置 -------------------
KEY_FILENAME = "unlock.key"
STATUS_FILENAME = os.path.join(os.getcwd(), "lock_status.txt")
SMTP_INFO = {
    'server': 'smtp.gmail.com',
    'port': 587,
    'sender': 'youremail@gmail.com',
    'password': 'your_app_password'
}
ADMIN_EMAIL = "admin@domain.com"

# ------------------- 密码哈希 -------------------
def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode('utf-8')).hexdigest()

# ------------------- 拍照 + 水印 + 邮件 -------------------
def add_watermark(img, text):
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, text, (10, img.shape[0]-10), font, 0.8, (255,255,255), 2, cv2.LINE_AA)
    return img

def send_email(receiver_email, subject, body, attachment_path):
    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg['From'] = SMTP_INFO['sender']
        msg['To'] = receiver_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with open(attachment_path, 'rb') as f:
            part = MIMEBase('application','octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition',f'attachment; filename="{os.path.basename(attachment_path)}"')
            msg.attach(part)

        server = smtplib.SMTP(SMTP_INFO['server'],SMTP_INFO['port'])
        server.starttls()
        server.login(SMTP_INFO['sender'],SMTP_INFO['password'])
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print("邮件发送失败:", e)

def take_photo_and_send(receiver_email=None):
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.exists(desktop): desktop=os.getcwd()
    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M')
    filename=os.path.join(desktop,f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    cap=cv2.VideoCapture(0)
    if not cap.isOpened(): return
    ret,frame=cap.read()
    cap.release()
    if ret:
        frame=add_watermark(frame,f"{timestamp} 非法使用一体机")
        cv2.imwrite(filename,frame)
        if receiver_email:
            threading.Thread(target=send_email,args=(receiver_email,"非法使用警告",
                                                     f"捕获到非法使用，时间：{timestamp}",filename)).start()

# ------------------- 红色闪烁 -------------------
class WarningFlash(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.showFullScreen()
        self.flash_state=False
        label=QLabel("警告：检测到非法触碰！")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color:white;font-size:60px;font-weight:bold;")
        layout=QVBoxLayout(); layout.addWidget(label); self.setLayout(layout)
        self.timer=QTimer(); self.timer.timeout.connect(self.flash); self.timer.start(300)
    def flash(self):
        self.flash_state=not self.flash_state
        self.setStyleSheet("background-color: red;" if self.flash_state else "background-color: #8B0000;")

# ------------------- 锁屏 -------------------
class LockScreen(QWidget):
    def __init__(self, hashed_pwd, receiver_email=None):
        super().__init__()
        self.unlock_password=hashed_pwd
        self.receiver_email=receiver_email
        self.warning_screen=None

        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.showFullScreen()
        self.setStyleSheet("background-color:#202124;")

        label=QLabel("电脑已锁定")
        label.setStyleSheet("color:white;font-size:40px;")
        label.setAlignment(Qt.AlignCenter)

        self.pwd_input=QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.setPlaceholderText("输入密码解锁")

        btn=QPushButton("解锁")
        btn.clicked.connect(self.try_unlock)

        layout=QVBoxLayout()
        layout.addStretch()
        layout.addWidget(label)
        layout.addWidget(self.pwd_input)
        layout.addWidget(btn)
        layout.addStretch()
        self.setLayout(layout)

        self.mouse_listener = mouse.Listener(on_click=self.on_input_detected,on_move=self.on_input_detected)
        self.kb_listener = keyboard.Listener(on_press=self.on_input_detected)
        self.mouse_listener.start()
        self.kb_listener.start()

        self.pwd_input.keyPressEvent=self.key_press_event_wrapper(self.pwd_input.keyPressEvent)

    def key_press_event_wrapper(self,orig_event):
        def wrapper(event):
            if event.key()==Qt.Key_F12: self.check_usb_key()
            orig_event(event)
        return wrapper

    def check_usb_key(self):
        drives=[f"{d}:/" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:/")]
        for d in drives:
            key_path=os.path.join(d,KEY_FILENAME)
            if os.path.exists(key_path):
                QMessageBox.information(self,"恢复","检测到管理员密钥，已解锁")
                self.mouse_listener.stop(); self.kb_listener.stop(); self.close(); return
        QMessageBox.warning(self,"提示","未检测到密钥文件")

    def on_input_detected(self,*args):
        if self.pwd_input.hasFocus(): return
        if not hasattr(self,'taken'):
            self.taken=True
            threading.Thread(target=take_photo_and_send,args=(self.receiver_email,)).start()
            self.warning_screen=WarningFlash(); self.warning_screen.show()
            QTimer.singleShot(5000,self.warning_screen.close) # 警告显示5秒

    def try_unlock(self):
        if hash_password(self.pwd_input.text())==self.unlock_password:
            if self.warning_screen: self.warning_screen.close()
            self.mouse_listener.stop(); self.kb_listener.stop(); self.close()
        else:
            QMessageBox.warning(self,"错误","密码不正确！")
            self.pwd_input.clear()

# ------------------- 唯一密钥 -------------------
def generate_key_file():
    if not os.path.exists(KEY_FILENAME):
        key=hashlib.sha256(os.urandom(32)).hexdigest()
        with open(KEY_FILENAME,'w') as f: f.write(key)
        print(f"生成唯一密钥文件 {KEY_FILENAME}，请保存到管理员U盘")

# ------------------- 锁屏状态 -------------------
def write_lock_status(status):
    with open(STATUS_FILENAME,'w') as f: f.write(status)
def read_lock_status():
    if os.path.exists(STATUS_FILENAME):
        with open(STATUS_FILENAME,'r') as f: return f.read().strip()
    return "UNLOCKED"

def check_abnormal_boot(receiver_email=None):
    if read_lock_status()=="LOCKED":
        print("检测到上次异常关机，触发报警")
        take_photo_and_send(receiver_email)

# ------------------- 主界面 -------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("电脑禁用锁定器")
        self.setFixedSize(450,350)
        self.setStyleSheet("background-color:#282c34;color:white;font-size:16px;")

        layout=QVBoxLayout()
        layout.addWidget(QLabel("锁屏时长（分钟）"))
        self.lock_duration=QSpinBox(); self.lock_duration.setRange(1,300); self.lock_duration.setValue(1)
        layout.addWidget(self.lock_duration)

        layout.addWidget(QLabel("解锁密码（字母+数字，至少6位）"))
        self.pwd_input=QLineEdit(); self.pwd_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pwd_input)

        layout.addWidget(QLabel("每日自动锁屏开始时间"))
        self.start_time=QTimeEdit(); self.start_time.setTime(QTime.currentTime())
        layout.addWidget(self.start_time)

        layout.addWidget(QLabel("每日自动锁屏结束时间"))
        self.end_time=QTimeEdit(); self.end_time.setTime(QTime.currentTime())
        layout.addWidget(self.end_time)

        self.btn_start=QPushButton("启动后台守护")
        self.btn_start.clicked.connect(self.start_guard)
        layout.addWidget(self.btn_start)
        self.setLayout(layout)

    def start_guard(self):
        pwd=self.pwd_input.text()
        if len(pwd)<6 or not any(c.isalpha() for c in pwd) or not any(c.isdigit() for c in pwd):
            QMessageBox.warning(self,"错误","密码至少6位，且包含字母和数字！"); return
        self.hashed_pwd=hash_password(pwd)
        self.timer=QTimer()
        self.timer.timeout.connect(self.check_lock_time)
        self.timer.start(60000) # 每分钟检查一次
        QMessageBox.information(self,"提示","后台守护已启动，程序将自动锁屏")

    def check_lock_time(self):
        now=QTime.currentTime()
        start=self.start_time.time(); end=self.end_time.time()
        if start<=now<=end:
            self.lock_screen=LockScreen(self.hashed_pwd,receiver_email=ADMIN_EMAIL)
            self.lock_screen.show()

# ------------------- 程序入口 -------------------
if __name__=="__main__":
    generate_key_file()
    check_abnormal_boot(receiver_email=ADMIN_EMAIL)
    write_lock_status("LOCKED")

    app=QApplication(sys.argv)
    win=MainWindow(); win.show()
    app.exec_()

    write_lock_status("UNLOCKED")