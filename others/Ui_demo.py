# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'demo.ui'
##
## Created by: Qt User Interface Compiler version 6.6.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(1022, 628)
        self.verticalLayout_3 = QVBoxLayout(Form)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.widget = QWidget(Form)
        self.widget.setObjectName(u"widget")
        self.widget.setMinimumSize(QSize(1000, 600))
        self.label_2 = QLabel(self.widget)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setGeometry(QRect(0, 150, 200, 50))
        self.label_2.setMinimumSize(QSize(200, 50))
        font = QFont()
        font.setPointSize(12)
        self.label_2.setFont(font)
        self.label_2.setAlignment(Qt.AlignCenter)
        self.scrollArea = QScrollArea(self.widget)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setGeometry(QRect(0, 200, 202, 352))
        self.scrollArea.setMinimumSize(QSize(0, 350))
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setEnabled(True)
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 179, 450))
        self.scrollAreaWidgetContents.setMinimumSize(QSize(0, 450))
        self.widget1 = QWidget(self.scrollAreaWidgetContents)
        self.widget1.setObjectName(u"widget1")
        self.widget1.setGeometry(QRect(0, 0, 202, 452))
        self.verticalLayout_2 = QVBoxLayout(self.widget1)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.label_3 = QLabel(self.widget1)
        self.label_3.setObjectName(u"label_3")
        self.label_3.setMinimumSize(QSize(200, 70))
        self.label_3.setFont(font)
        self.label_3.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_3)

        self.label_4 = QLabel(self.widget1)
        self.label_4.setObjectName(u"label_4")
        self.label_4.setMinimumSize(QSize(200, 70))
        self.label_4.setFont(font)
        self.label_4.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_4)

        self.label_5 = QLabel(self.widget1)
        self.label_5.setObjectName(u"label_5")
        self.label_5.setMinimumSize(QSize(200, 70))
        self.label_5.setFont(font)
        self.label_5.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_5)

        self.label_6 = QLabel(self.widget1)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setMinimumSize(QSize(200, 70))
        self.label_6.setFont(font)
        self.label_6.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_6)

        self.label_8 = QLabel(self.widget1)
        self.label_8.setObjectName(u"label_8")
        self.label_8.setMinimumSize(QSize(200, 70))
        self.label_8.setFont(font)
        self.label_8.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_8)

        self.label_7 = QLabel(self.widget1)
        self.label_7.setObjectName(u"label_7")
        self.label_7.setMinimumSize(QSize(200, 70))
        self.label_7.setFont(font)
        self.label_7.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_7)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents)
        self.widget_2 = QWidget(self.widget)
        self.widget_2.setObjectName(u"widget_2")
        self.widget_2.setGeometry(QRect(220, 0, 500, 300))
        self.label_11 = QLabel(self.widget_2)
        self.label_11.setObjectName(u"label_11")
        self.label_11.setGeometry(QRect(200, 0, 100, 40))
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(100)
        sizePolicy.setVerticalStretch(40)
        sizePolicy.setHeightForWidth(self.label_11.sizePolicy().hasHeightForWidth())
        self.label_11.setSizePolicy(sizePolicy)
        self.label_11.setFont(font)
        self.label_11.setAlignment(Qt.AlignCenter)
        self.label_17 = QLabel(self.widget_2)
        self.label_17.setObjectName(u"label_17")
        self.label_17.setGeometry(QRect(150, 170, 201, 51))
        self.label_17.setFont(font)
        self.label_17.setAlignment(Qt.AlignCenter)
        self.pushButton = QPushButton(self.widget_2)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(30, 50, 150, 40))
        self.pushButton.setFont(font)
        self.pushButton_2 = QPushButton(self.widget_2)
        self.pushButton_2.setObjectName(u"pushButton_2")
        self.pushButton_2.setGeometry(QRect(185, 50, 150, 40))
        self.pushButton_2.setFont(font)
        self.pushButton_3 = QPushButton(self.widget_2)
        self.pushButton_3.setObjectName(u"pushButton_3")
        self.pushButton_3.setGeometry(QRect(340, 50, 150, 40))
        self.pushButton_3.setFont(font)
        self.line_2 = QFrame(self.widget_2)
        self.line_2.setObjectName(u"line_2")
        self.line_2.setGeometry(QRect(0, 30, 501, 16))
        self.line_2.setFrameShadow(QFrame.Plain)
        self.line_2.setFrameShape(QFrame.HLine)
        self.widget_3 = QWidget(self.widget)
        self.widget_3.setObjectName(u"widget_3")
        self.widget_3.setGeometry(QRect(220, 320, 504, 268))
        self.widget_4 = QWidget(self.widget_3)
        self.widget_4.setObjectName(u"widget_4")
        self.widget_4.setGeometry(QRect(9, 9, 240, 250))
        self.widget_4.setMinimumSize(QSize(240, 250))
        self.label_15 = QLabel(self.widget_4)
        self.label_15.setObjectName(u"label_15")
        self.label_15.setGeometry(QRect(20, 20, 211, 81))
        self.label_15.setFont(font)
        self.label_15.setAlignment(Qt.AlignCenter)
        self.widget_5 = QWidget(self.widget_3)
        self.widget_5.setObjectName(u"widget_5")
        self.widget_5.setGeometry(QRect(255, 9, 240, 250))
        self.widget_5.setMinimumSize(QSize(240, 250))
        self.widget_5.setMaximumSize(QSize(245, 250))
        self.label_16 = QLabel(self.widget_5)
        self.label_16.setObjectName(u"label_16")
        self.label_16.setGeometry(QRect(20, 40, 191, 51))
        self.label_16.setFont(font)
        self.label_16.setAlignment(Qt.AlignCenter)
        self.line = QFrame(self.widget_3)
        self.line.setObjectName(u"line")
        self.line.setGeometry(QRect(0, -14, 501, 31))
        self.line.setFrameShadow(QFrame.Plain)
        self.line.setFrameShape(QFrame.HLine)
        self.line_3 = QFrame(self.widget_3)
        self.line_3.setObjectName(u"line_3")
        self.line_3.setGeometry(QRect(240, 0, 20, 261))
        self.line_3.setFrameShadow(QFrame.Plain)
        self.line_3.setFrameShape(QFrame.VLine)
        self.widget2 = QWidget(self.widget)
        self.widget2.setObjectName(u"widget2")
        self.widget2.setGeometry(QRect(0, 0, 202, 146))
        self.verticalLayout = QVBoxLayout(self.widget2)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self.widget2)
        self.label.setObjectName(u"label")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy1)
        self.label.setMinimumSize(QSize(200, 50))
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignCenter)

        self.verticalLayout.addWidget(self.label)

        self.label_TeamName = QLabel(self.widget2)
        self.label_TeamName.setObjectName(u"label_TeamName")
        self.label_TeamName.setEnabled(True)
        sizePolicy1.setHeightForWidth(self.label_TeamName.sizePolicy().hasHeightForWidth())
        self.label_TeamName.setSizePolicy(sizePolicy1)
        self.label_TeamName.setMinimumSize(QSize(200, 70))
        self.label_TeamName.setFont(font)
        self.label_TeamName.setAlignment(Qt.AlignCenter)

        self.verticalLayout.addWidget(self.label_TeamName)

        self.widget3 = QWidget(self.widget)
        self.widget3.setObjectName(u"widget3")
        self.widget3.setGeometry(QRect(720, 530, 278, 42))
        self.horizontalLayout_3 = QHBoxLayout(self.widget3)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.pushButton_5 = QPushButton(self.widget3)
        self.pushButton_5.setObjectName(u"pushButton_5")
        self.pushButton_5.setMinimumSize(QSize(130, 40))
        self.pushButton_5.setMaximumSize(QSize(130, 16777215))

        self.horizontalLayout_3.addWidget(self.pushButton_5)

        self.pushButton_4 = QPushButton(self.widget3)
        self.pushButton_4.setObjectName(u"pushButton_4")
        self.pushButton_4.setMinimumSize(QSize(130, 40))
        self.pushButton_4.setMaximumSize(QSize(130, 16777215))

        self.horizontalLayout_3.addWidget(self.pushButton_4)

        self.widget4 = QWidget(self.widget)
        self.widget4.setObjectName(u"widget4")
        self.widget4.setGeometry(QRect(730, 30, 268, 42))
        self.horizontalLayout_4 = QHBoxLayout(self.widget4)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.horizontalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.pushButton_6 = QPushButton(self.widget4)
        self.pushButton_6.setObjectName(u"pushButton_6")
        self.pushButton_6.setMinimumSize(QSize(130, 40))

        self.horizontalLayout_4.addWidget(self.pushButton_6)

        self.pushButton_7 = QPushButton(self.widget4)
        self.pushButton_7.setObjectName(u"pushButton_7")
        self.pushButton_7.setMinimumSize(QSize(130, 40))

        self.horizontalLayout_4.addWidget(self.pushButton_7)


        self.verticalLayout_3.addWidget(self.widget)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.label_2.setText(QCoreApplication.translate("Form", u"\u5c0f\u7ec4\u6210\u5458", None))
        self.label_3.setText(QCoreApplication.translate("Form", u"\u6210\u54581", None))
        self.label_4.setText(QCoreApplication.translate("Form", u"\u6210\u54582", None))
        self.label_5.setText(QCoreApplication.translate("Form", u"\u6210\u54583", None))
        self.label_6.setText(QCoreApplication.translate("Form", u"\u6210\u54584", None))
        self.label_8.setText(QCoreApplication.translate("Form", u"\u6210\u54585", None))
        self.label_7.setText(QCoreApplication.translate("Form", u"\u6210\u54586", None))
        self.label_11.setText(QCoreApplication.translate("Form", u"\u6d4b\u8bd5", None))
        self.label_17.setText(QCoreApplication.translate("Form", u"\u8fd9\u91cc\u8fdb\u884c\u6d4b\u8bd5\u7684\u8bbe\u7f6e", None))
        self.pushButton.setText(QCoreApplication.translate("Form", u"\u8df3\u8dc3\u6d4b\u8bd5", None))
        self.pushButton_2.setText(QCoreApplication.translate("Form", u"\u6b65\u9891\u6d4b\u8bd5", None))
        self.pushButton_3.setText(QCoreApplication.translate("Form", u"\u53cd\u5e94\u6d4b\u8bd5", None))
        self.label_15.setText(QCoreApplication.translate("Form", u"\u8fd9\u91cc\u5c55\u793a\u6d4b\u8bd5\u4eba\u5458\u4fe1\u606f", None))
        self.label_16.setText(QCoreApplication.translate("Form", u"\u8fd9\u91cc\u5c55\u793a\u6d4b\u8bd5\u65b9\u5f0f", None))
        self.label.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u5c0f\u7ec4", None))
        self.label_TeamName.setText(QCoreApplication.translate("Form", u"\u8fd9\u91cc\u5c55\u793a\u5c0f\u7ec4\u540d\u79f0", None))
        self.pushButton_5.setText(QCoreApplication.translate("Form", u"\u8bbe\u7f6e", None))
        self.pushButton_4.setText(QCoreApplication.translate("Form", u"\u9000\u51fa\u767b\u5f55", None))
        self.pushButton_6.setText(QCoreApplication.translate("Form", u"\u8d26\u6237\u767b\u5f55", None))
        self.pushButton_7.setText(QCoreApplication.translate("Form", u"\u5386\u53f2\u8bb0\u5f55", None))
    # retranslateUi

