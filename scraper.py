from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import csv
import os
import sys
from datetime import datetime, timedelta

try:
    # 离线法定节假日数据（含每年调休补班安排）
    from chinese_calendar import is_workday as _cn_is_workday
except ImportError:
    _cn_is_workday = None

# 缓存节假日数据
_holiday_cache = {}

def is_workday(date_str):
    """
    判断指定日期是否为工作日（周末调休补班算工作日，周中的法定节假日不算）
    :param date_str: 日期字符串，格式为 'YYYY-MM-DD'
    :return: True表示工作日，False表示节假日或周末
    """
    if date_str in _holiday_cache:
        return _holiday_cache[date_str]

    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        _holiday_cache[date_str] = False
        return False

    if _cn_is_workday is not None:
        try:
            result = bool(_cn_is_workday(dt))
        except NotImplementedError:
            # 库数据未覆盖该年份（如下一年放假安排未发布），退回周一~周五近似
            result = dt.weekday() < 5
    else:
        # 未安装chinese_calendar时的近似处理
        result = dt.weekday() < 5

    _holiday_cache[date_str] = result
    return result

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def app_dir():
    """exe（或脚本）所在目录，用于存放需要持久化的输出文件"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def find_system_browser():
    """查找系统浏览器路径"""
    # 优先找Edge，其次Chrome
    edge_paths = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    chrome_paths = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ]
    for p in edge_paths + chrome_paths:
        if os.path.exists(p):
            return p
    return None

def calc_overtime(check_in_str, check_out_str, date_str, work_end='17:20'):
    """
    计算加班时长
    :param check_in_str: 上班打卡时间
    :param check_out_str: 下班打卡时间
    :param date_str: 日期字符串，格式为 'YYYY-MM-DD'
    :param work_end: 正常下班时间
    :return: 加班时长（分钟）
    """
    try:
        co = datetime.strptime(check_out_str.strip(), '%H:%M:%S')
        
        # 判断是否为调休工作日
        if is_workday(date_str):
            # 调休工作日：加班 = 下班时间 - 17:20
            we = datetime.strptime(work_end, '%H:%M')
            diff = (co - we).total_seconds() / 60
        else:
            # 普通周末：加班 = 下班时间 - 上班时间
            ci = datetime.strptime(check_in_str.strip(), '%H:%M:%S')
            diff = (co - ci).total_seconds() / 60
        
        return max(diff, 0)
    except:
        return 0

def fmt_hours(minutes):
    if minutes <= 0:
        return ''
    h = int(minutes // 60)
    m = int(minutes % 60)
    if h > 0 and m > 0:
        return f'{h}小时{m}分钟'
    elif h > 0:
        return f'{h}小时'
    else:
        return f'{m}分钟'

def get_date_chunks(start_str, end_str, chunk_days=29):
    start = datetime.strptime(start_str, '%Y-%m-%d')
    end = datetime.strptime(end_str, '%Y-%m-%d')
    chunks = []
    while start <= end:
        chunk_end = min(start + timedelta(days=chunk_days), end)
        chunks.append((start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')))
        start = chunk_end + timedelta(days=1)
    return chunks

def read_existing_csv(csv_file):
    """读取已有的打卡记录CSV，返回 {日期: [日期, 星期, 上班时间, 下班时间]} 字典"""
    existing = {}
    if os.path.exists(csv_file):
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) >= 4:
                    date_str = row[0].strip()
                    existing[date_str] = row[:4]  # [日期, 星期, 上班时间, 下班时间]
    return existing

def get_csv_date_range(csv_file):
    """获取CSV中第一条和最后一条记录的日期"""
    first_date = None
    last_date = None
    if os.path.exists(csv_file):
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) >= 1 and row[0].strip():
                    date_str = row[0].strip()
                    if first_date is None:
                        first_date = date_str
                    last_date = date_str
    return first_date, last_date

def run_scrape(config, progress=None):

    def emit(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    username = config['username']
    password = config['password']
    start_date = config['start_date']
    end_date = config['end_date']
    work_end_time = config.get('work_end_time', '17:20')
    login_url = config.get('login_url', '')

    if not login_url:
        login_url = (
            'https://192.168.36.67/eassso/login?service=http%3A%2F%2F192.168.36.67%3A80%2Fshr%2Fdynamic.do'
            '%3Fuipk%3Dcom.kingdee.eas.hr.ats.app.WorkCalendarItem.listSelf'
            '%26inFrame%3Dtrue%26fromHeader%3Dtrue'
            '%26serviceId%3DqBEWMTx%252FSFqo38ksWGkgPfI9KRA%253D'
        )

    csv_file = os.path.join(app_dir(), '打卡记录.csv')
    existing_records = read_existing_csv(csv_file)
    csv_first, csv_last = get_csv_date_range(csv_file)

    # 情况1：CSV完全覆盖查询范围，直接用已有数据重新计算
    if existing_records and csv_first and csv_last:
        if start_date >= csv_first and end_date <= csv_last:
            emit('已有完整数据，无需登录查询...')
            # 只计算查询范围内的加班时长
            all_results = []
            for date_str in sorted(existing_records.keys()):
                if start_date <= date_str <= end_date:
                    rec = existing_records[date_str]
                    if len(rec) >= 4 and rec[2] and rec[3]:
                        overtime_min = calc_overtime(rec[2], rec[3], date_str, work_end_time)
                        overtime_str = fmt_hours(overtime_min)
                        all_results.append([date_str, rec[1], rec[2], rec[3], overtime_str, overtime_min])

            all_results.sort(key=lambda x: x[0])
            total_overtime_min = sum(
                calc_overtime(r[2], r[3], r[0], work_end_time)
                for r in all_results if r[2] and r[3]
            )
            weekend_overtime_min = sum(
                calc_overtime(r[2], r[3], r[0], work_end_time)
                for r in all_results if r[2] and r[3] and not is_workday(r[0])
            )
            workday_count = sum(1 for r in all_results if is_workday(r[0]))
            unchecked_days = int(config.get('unchecked_days', '0') or 0)
            denominator = (unchecked_days + workday_count) * 4 * 60
            percent = total_overtime_min / denominator * 100 if denominator > 0 else 0

            return {
                'record_count': len(all_results),
                'total_overtime_hours': total_overtime_min / 60,
                'total_overtime_str': fmt_hours(total_overtime_min),
                'full_overtime_hours': denominator / 60,
                'full_overtime_str': fmt_hours(denominator),
                'percent': percent,
                'workday_count': workday_count,
                'unchecked_days': unchecked_days,
                'weekend_overtime_hours': weekend_overtime_min / 60,
                'csv_file': csv_file,
            }

    # 情况2：需要爬取缺失日期
    # 计算需要爬取的日期范围：查询范围 - CSV已有范围
    scrape_ranges = []
    if csv_first and csv_last:
        # CSV有数据，计算缺失的范围
        csv_last_dt = datetime.strptime(csv_last, '%Y-%m-%d')
        csv_last_next = (csv_last_dt + timedelta(days=1)).strftime('%Y-%m-%d')
        if start_date < csv_first:
            scrape_ranges.append((start_date, csv_first))
        if end_date > csv_last:
            scrape_ranges.append((csv_last_next, end_date))
    else:
        # CSV没有数据，爬取全部
        scrape_ranges.append((start_date, end_date))

    if existing_records:
        emit(f'已有 {len(existing_records)} 条记录，仅爬取缺失日期...')
    else:
        emit('无历史记录，全量爬取...')

    with sync_playwright() as p:
        emit('正在启动浏览器...')
        # 优先使用系统Edge，其次Chrome
        browser = None
        for channel in ['msedge', 'chrome']:
            try:
                browser = p.chromium.launch(headless=True, channel=channel, args=['--ignore-certificate-errors'])
                emit(f'使用{channel}')
                time.sleep(1)
                break
            except Exception:
                continue
        if not browser:
            raise RuntimeError('未找到系统浏览器，请安装Edge或Chrome')
        page = browser.new_page()

        try:
            emit('正在访问登录页面...')
            page.goto(login_url, timeout=30000)
            page.wait_for_selector('#username', timeout=10000)
            page.fill('#username', username)
            page.fill('#password', password)
            page.click('#loginSubmit')
            emit('正在登录...')
            try:
                page.wait_for_function("document.title.includes('s-HR')", timeout=15000)
            except Exception:
                raise RuntimeError('登录失败：请检查工号/密码是否正确，或网络/服务器是否正常')

            time.sleep(5)
            emit('登录成功，正在加载考勤页面...')

            target_frame = page.main_frame
            for frame in page.frames:
                if 'dynamic.do' in frame.url or 'WorkCalendar' in frame.url:
                    target_frame = frame
                    break

            try:
                target_frame.wait_for_selector('#query', timeout=15000)
            except:
                pass
            time.sleep(2)

            # 爬取缺失的范围
            new_records = []
            for range_idx, (range_start, range_end) in enumerate(scrape_ranges):
                chunks = get_date_chunks(range_start, range_end)
                for idx, (chunk_start, chunk_end) in enumerate(chunks, 1):
                    emit(f'正在查询第 {range_idx+1} 段第 {idx}/{len(chunks)} 小段：{chunk_start} ~ {chunk_end} ...')
                    begin_input = target_frame.locator('#beginDate')
                    begin_input.click()
                    begin_input.fill('')
                    time.sleep(0.3)
                    begin_input.fill(chunk_start)

                    end_input = target_frame.locator('#endDate')
                    end_input.click()
                    end_input.fill('')
                    time.sleep(0.3)
                    end_input.fill(chunk_end)

                    time.sleep(0.5)
                    target_frame.locator('#query').click()

                    time.sleep(4)
                    try:
                        target_frame.wait_for_selector('[aria-describedby="grid_punchCardTime"]', timeout=10000)
                    except:
                        pass
                    time.sleep(1)

                    html = target_frame.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    rows = soup.find_all('tr', class_='jqgrow')

                    for row in rows:
                        date_str = ''
                        date_td = row.find('td', attrs={'aria-describedby': 'grid_date'})
                        if date_td:
                            a_tag = date_td.find('a')
                            if a_tag:
                                date_str = a_tag.get('title', '') or a_tag.get_text().strip()
                            else:
                                date_str = date_td.get('title', '') or date_td.get_text().strip()

                        week = ''
                        week_td = row.find('td', attrs={'aria-describedby': 'grid_week'})
                        if week_td:
                            week = week_td.get('title', '') or week_td.get_text().strip()

                        punch_time = ''
                        time_td = row.find('td', attrs={'aria-describedby': 'grid_punchCardTime'})
                        if time_td:
                            punch_time = time_td.get('title', '') or time_td.get_text().strip()

                        if punch_time and punch_time != '--':
                            if ',' in punch_time and ':' in punch_time:
                                times = [t.strip() for t in punch_time.split(',')]
                                check_in = times[0]
                                check_out = times[-1]
                                new_records.append([date_str, week, check_in, check_out])
                            elif ':' in punch_time:
                                new_records.append([date_str, week, punch_time, '', ''])

                    time.sleep(1)
                    emit(f'第 {idx}/{len(chunks)} 小段解析完成')
                    time.sleep(1)

            # 合并新旧数据：新的覆盖旧的
            merged = dict(existing_records)
            for rec in new_records:
                date_str = rec[0]
                merged[date_str] = rec[:4]

            # 计算查询范围内的记录
            all_results = []
            for date_str in sorted(merged.keys()):
                if start_date <= date_str <= end_date:
                    rec = merged[date_str]
                    if len(rec) >= 4 and rec[2] and rec[3]:
                        overtime_min = calc_overtime(rec[2], rec[3], date_str, work_end_time)
                        overtime_str = fmt_hours(overtime_min)
                        all_results.append([date_str, rec[1], rec[2], rec[3], overtime_str, overtime_min])

            all_results.sort(key=lambda x: x[0])
            total_overtime_min = sum(
                calc_overtime(r[2], r[3], r[0], work_end_time)
                for r in all_results if r[2] and r[3]
            )
            weekend_overtime_min = sum(
                calc_overtime(r[2], r[3], r[0], work_end_time)
                for r in all_results if r[2] and r[3] and not is_workday(r[0])
            )
            workday_count = sum(1 for r in all_results if is_workday(r[0]))
            unchecked_days = int(config.get('unchecked_days', '0') or 0)
            denominator = (unchecked_days + workday_count) * 4 * 60
            percent = total_overtime_min / denominator * 100 if denominator > 0 else 0

            # 保存所有合并后的记录到CSV
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['日期', '星期', '上班时间', '下班时间', '加班时间'])
                for date_str in sorted(merged.keys()):
                    rec = merged[date_str]
                    if len(rec) >= 4 and rec[2] and rec[3]:
                        ot_min = calc_overtime(rec[2], rec[3], date_str, work_end_time)
                        ot_str = fmt_hours(ot_min)
                        writer.writerow([date_str, rec[1], rec[2], rec[3], ot_str])

            return {
                'record_count': len(all_results),
                'new_count': len(new_records),
                'total_overtime_hours': total_overtime_min / 60,
                'total_overtime_str': fmt_hours(total_overtime_min),
                'full_overtime_hours': denominator / 60,
                'full_overtime_str': fmt_hours(denominator),
                'percent': percent,
                'workday_count': workday_count,
                'unchecked_days': unchecked_days,
                'weekend_overtime_hours': weekend_overtime_min / 60,
                'csv_file': csv_file,
            }

        finally:
            browser.close()
