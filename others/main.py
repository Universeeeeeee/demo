# main.py
import sys
from PySide6.QtWidgets import QApplication, QWidget
from Ui_demo import Ui_Form  # 确保文件名是 Ui_demo.py（不要用 demo.py）

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 创建主窗口并绑定 UI
    window = QWidget()
    ui = Ui_Form()
    ui.setupUi(window)
    window.show()

    sys.exit(app.exec())
