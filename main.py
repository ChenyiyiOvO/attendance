import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import sys
import threading

CONFIG_FILE = 'config.json'

def resource_path(relative_path):
    """获取资源文件路径，兼容PyInstaller打包"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def app_dir():
    """exe（或脚本）所在目录，用于存放需要持久化的文件"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def load_config():
    # 优先读 exe 所在目录（用户保存的配置）
    path = os.path.join(app_dir(), CONFIG_FILE)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 回退：读打包内置的默认配置
    bundled = resource_path(CONFIG_FILE)
    if os.path.exists(bundled):
        with open(bundled, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'username': '', 'password': '',
        'start_date': '', 'end_date': '',
        'work_end_time': '17:20',
        'unchecked_days': '0',
        'login_url': ''
    }

def save_config(cfg):
    path = os.path.join(app_dir(), CONFIG_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

class OvertimeCalcWindow:
    """加班百分比计算器窗口"""
    def __init__(self, parent, p=0, q=116, y=0, quarter_end=''):
        self.window = tk.Toplevel(parent)
        self.window.title('加班时长百分比计算器')
        self.window.geometry('500x500')
        self.window.resizable(True, True)

        self.build_ui(p, q, y, quarter_end)

    def build_ui(self, p, q, y, quarter_end):
        input_frame = ttk.LabelFrame(self.window, text='参数设置', padding=10)
        input_frame.pack(padx=15, pady=10, fill='x')

        params = [
            ('p', 'p (已加班时长/小时):', str(p)),
            ('q', 'q (满加班时长/小时):', str(q)),
            ('y', 'y (本季度剩余工作日/天):', str(y)),
            ('weekend', 'weekend (未来休息日加班总时长/小时):', '0'),
            ('base_time', '加班起算时间:', '17:20'),
            ('h步长', 'h步长 (每次递增/小时):', '0.5'),
            ('循环次数', '循环次数:', '11'),
        ]

        self.entries = {}
        for i, (key, label, default) in enumerate(params):
            ttk.Label(input_frame, text=label).grid(row=i, column=0, sticky='e', padx=5, pady=3)
            entry = ttk.Entry(input_frame, width=20)
            entry.insert(0, default)
            entry.grid(row=i, column=1, padx=5, pady=3)
            self.entries[key] = entry

        if quarter_end:
            ttk.Label(self.window, text=f'y 已自动填入本季度剩余工作日（季度截至 {quarter_end}，可手动修改）',
                      foreground='gray').pack(pady=2)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text='计算', command=self.calculate).pack(side='left', padx=10)

        result_frame = ttk.LabelFrame(self.window, text='计算结果', padding=10)
        result_frame.pack(padx=15, pady=5, fill='both', expand=True)

        self.result_text = tk.Text(result_frame, height=12, font=('Consolas', 10))
        scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        self.result_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

    def calculate(self):
        try:
            p = float(self.entries['p'].get())
            q = float(self.entries['q'].get())
            y = float(self.entries['y'].get())
            weekend = float(self.entries['weekend'].get())
            base_time = self.entries['base_time'].get().strip()
            step = float(self.entries['h步长'].get())
            count = int(self.entries['循环次数'].get())

            from datetime import datetime, timedelta
            base_dt = datetime.strptime(base_time, '%H:%M')
        except ValueError:
            messagebox.showerror('错误', '请输入有效的数字或时间(HH:MM)')
            return

        self.result_text.delete('1.0', tk.END)

        header = f'{"每天加班":>10} {"加班到":>10} {"百分比":>10}'
        self.result_text.insert(tk.END, header + '\n')
        self.result_text.insert(tk.END, '-' * 40 + '\n')

        h = 0
        print(f'计算参数: p={p}, q={q}, y={y}, weekend={weekend}, base_time={base_time}, step={step}, count={count}\n')
        for i in range(count):
            if (q + y * h) != 0:
                x = (p + y * h + weekend) / (q + y * 4) * 100
                # print(f'计算第{i+1}次: h={h}, p={p}, q={q}, y={y}, weekend={weekend}, 百分比={x:.2f}%')
            else:
                x = 0

            leave_dt = base_dt + timedelta(hours=h)
            leave_str = leave_dt.strftime('%H:%M')

            line = f'{h:>10.1f} {leave_str:>10} {x:>10.2f}%'
            self.result_text.insert(tk.END, line + '\n')
            h += step

        self.result_text.insert(tk.END, '-' * 40 + '\n')
        self.result_text.insert(tk.END, f'\n已加班: {p}小时, 满额: {q}小时\n')
        self.result_text.insert(tk.END, f'连续天数: {int(y)}, 周末加班: {weekend}小时\n')
        self.result_text.insert(tk.END, f'步长: 每次+{step}小时, 共{count}次\n')

class AttendanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title('考勤打卡记录爬取工具')
        self.root.geometry('480x380')
        self.root.resizable(False, False)

        self.config = load_config()
        self.build_ui()

    def build_ui(self):
        frame = ttk.LabelFrame(self.root, text='配置信息', padding=10)
        frame.pack(padx=15, pady=10, fill='x')

        labels = ['工号:', '密码:', '起始日期:', '终止日期:', '加班起算时间:', '未打卡工作日天数(居家等):']
        keys = ['username', 'password', 'start_date', 'end_date', 'work_end_time', 'unchecked_days']
        self.entries = {}

        for i, (label, key) in enumerate(zip(labels, keys)):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky='e', padx=5, pady=4)
            entry = ttk.Entry(frame, width=30, show='*' if key == 'password' else '')
            entry.insert(0, str(self.config.get(key, '')))
            entry.grid(row=i, column=1, padx=5, pady=4)
            self.entries[key] = entry

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=10)

        self.run_btn = ttk.Button(btn_frame, text='开始爬取', command=self.run)
        self.run_btn.pack(side='left', padx=10)

        ttk.Button(btn_frame, text='保存配置', command=self.save).pack(side='left', padx=10)

        self.status_var = tk.StringVar(value='就绪')
        ttk.Label(self.root, textvariable=self.status_var, foreground='gray').pack(pady=5)

    def save(self):
        for key, entry in self.entries.items():
            self.config[key] = entry.get().strip()
        try:
            save_config(self.config)
            messagebox.showinfo('提示', '配置已保存到程序目录')
        except Exception as e:
            messagebox.showerror('错误', f'保存配置失败：{e}')

    def run(self):
        for key, entry in self.entries.items():
            self.config[key] = entry.get().strip()

        if not self.config['username'] or not self.config['password']:
            messagebox.showerror('错误', '请输入工号和密码')
            return
        if not self.config['start_date'] or not self.config['end_date']:
            messagebox.showerror('错误', '请输入起止日期')
            return

        ud = self.config.get('unchecked_days', '').strip()
        if ud and (not ud.isdigit()):
            messagebox.showerror('错误', '未打卡工作日天数需为非负整数')
            return

        self.run_btn.config(state='disabled')
        self.status_var.set('正在运行，请勿关闭浏览器...')
        threading.Thread(target=self.do_scrape, daemon=True).start()

    def do_scrape(self):
        def progress(msg):
            self.root.after(0, lambda: self.status_var.set(msg))

        try:
            from scraper import run_scrape
            result = run_scrape(self.config, progress)
            self.root.after(0, lambda: self.on_done(result))
        except Exception as e:
            # except块结束时会自动删除e，必须先取出消息再交给延迟执行的lambda
            msg = str(e)
            self.root.after(0, lambda: self.on_error(msg))

    def on_done(self, result):
        self.run_btn.config(state='normal')
        self.status_var.set('完成')

        # 解析结果，提取参数（y为自动计算的本季度剩余工作日）
        p = result.get('total_overtime_hours', 0)
        q = result.get('full_overtime_hours', 116)
        y = result.get('remaining_quarter_workdays', 0)
        quarter_end = result.get('quarter_end_date', '')

        # 显示结果摘要
        summary = (
            f"共 {result.get('record_count', 0)} 条记录\n"
            f"总加班: {result.get('total_overtime_str', '')}\n"
            f"满额加班: {result.get('full_overtime_str', '')}\n"
            f"加班时长百分比: {result.get('percent', 0):.2f}%\n"
            f"本季度剩余工作日: {y} 天（截至 {quarter_end}）\n"
            f"已保存到: {result.get('csv_file', '')}"
        )
        messagebox.showinfo('完成', summary)

        # 打开计算器，自动填充参数
        OvertimeCalcWindow(self.root, p=p, q=q, y=y, quarter_end=quarter_end)

    def on_error(self, msg):
        self.run_btn.config(state='normal')
        self.status_var.set('出错')
        messagebox.showerror('错误', msg)

if __name__ == '__main__':
    root = tk.Tk()
    app = AttendanceApp(root)
    root.mainloop()
