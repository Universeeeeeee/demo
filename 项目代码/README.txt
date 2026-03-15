# 安装说明

1. 确保安装了 Python 3.8 或更高版本。
2. 在当前目录下打开命令行，运行以下命令安装依赖：
   pip install -r requirements.txt

# 运行说明

## 1. 硬件控制 (即插即用)
运行：
python led_con.py

注意：默认情况下程序会自动寻找当前目录下的 CyUsbInterface.dll。如果提示“加载 DLL 失败”，请确保该 DLL 文件就在当前目录下。
(或者用记事本打开对应脚本，将 dll_path 修改为正确的绝对路径)

## 2. 数据分析
运行：
python 2data_show.py
