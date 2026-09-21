import json
import time
import csv
import os
import sys
import urllib.request
from datetime import datetime, timedelta

# ==================== 节假日/调休数据 ====================
# 数据源 holiday-cn（https://github.com/NateScarlet/holiday-cn，按国务院公告自动更新）
# 按年拉取后缓存到本地，运行时全部为本地字典查询，不再逐日请求在线接口。
# 查找顺序：本地缓存(holidays.json) -> 内置快照 -> 缺失年份联网拉取一次 -> 按周一~周五近似兜底

HOLIDAY_CACHE_FILE = 'holidays.json'
HOLIDAY_CN_URLS = [
    'https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json',
    'https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json',
]
HOLIDAY_RETRY_INTERVAL = 24 * 3600  # 某年联网拉取失败后，24小时内不重复请求

# 内置快照：2024-2026年法定节假日与调休安排（取自holiday-cn，原始出处为国务院公告）
# True=放假(休息日)，False=调休上班(工作日)
_BUILTIN_HOLIDAYS = {
    '2024': {
        '2024-01-01': True, '2024-02-04': False, '2024-02-10': True,
        '2024-02-11': True, '2024-02-12': True, '2024-02-13': True,
        '2024-02-14': True, '2024-02-15': True, '2024-02-16': True,
        '2024-02-17': True, '2024-02-18': False, '2024-04-04': True,
        '2024-04-05': True, '2024-04-06': True, '2024-04-07': False,
        '2024-04-28': False, '2024-05-01': True, '2024-05-02': True,
        '2024-05-03': True, '2024-05-04': True, '2024-05-05': True,
        '2024-05-11': False, '2024-06-10': True, '2024-09-14': False,
        '2024-09-15': True, '2024-09-16': True, '2024-09-17': True,
        '2024-09-29': False, '2024-10-01': True, '2024-10-02': True,
        '2024-10-03': True, '2024-10-04': True, '2024-10-05': True,
        '2024-10-06': True, '2024-10-07': True, '2024-10-12': False,
    },
    '2025': {
        '2025-01-01': True, '2025-01-26': False, '2025-01-28': True,
        '2025-01-29': True, '2025-01-30': True, '2025-01-31': True,
        '2025-02-01': True, '2025-02-02': True, '2025-02-03': True,
        '2025-02-04': True, '2025-02-08': False, '2025-04-04': True,
        '2025-04-05': True, '2025-04-06': True, '2025-04-27': False,
        '2025-05-01': True, '2025-05-02': True, '2025-05-03': True,
        '2025-05-04': True, '2025-05-05': True, '2025-05-31': True,
        '2025-06-01': True, '2025-06-02': True, '2025-09-28': False,
        '2025-10-01': True, '2025-10-02': True, '2025-10-03': True,
        '2025-10-04': True, '2025-10-05': True, '2025-10-06': True,
        '2025-10-07': True, '2025-10-08': True, '2025-10-11': False,
    },
    '2026': {
        '2026-01-01': True, '2026-01-02': True, '2026-01-03': True,
        '2026-01-04': False, '2026-02-14': False, '2026-02-15': True,
        '2026-02-16': True, '2026-02-17': True, '2026-02-18': True,
        '2026-02-19': True, '2026-02-20': True, '2026-02-21': True,
        '2026-02-22': True, '2026-02-23': True, '2026-02-28': False,
        '2026-04-04': True, '2026-04-05': True, '2026-04-06': True,
        '2026-05-01': True, '2026-05-02': True, '2026-05-03': True,
        '2026-05-04': True, '2026-05-05': True, '2026-05-09': False,
        '2026-06-19': True, '2026-06-20': True, '2026-06-21': True,
        '2026-09-20': False, '2026-09-25': True, '2026-09-26': True,
        '2026-09-27': True, '2026-10-01': True, '2026-10-02': True,
        '2026-10-03': True, '2026-10-04': True, '2026-10-05': True,
        '2026-10-06': True, '2026-10-07': True, '2026-10-10': False,
    },
}

# 运行内存缓存：{日期: 是否放假}，以及各年份最近一次联网拉取失败的时间戳
_holiday_cache = {}
_holiday_failed = {}
_holiday_loaded = False


def _holiday_cache_path():
    return os.path.join(app_dir(), HOLIDAY_CACHE_FILE)


def _load_holiday_cache():
    """进程内首次使用时，把内置快照和本地缓存文件加载进内存"""
    global _holiday_loaded, _holiday_failed
    if _holiday_loaded:
        return
    _holiday_loaded = True
    for year_days in _BUILTIN_HOLIDAYS.values():
        _holiday_cache.update(year_days)
    try:
        with open(_holiday_cache_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        for year_days in data.get('years', {}).values():
            _holiday_cache.update(year_days)
        _holiday_failed = data.get('failed', {})
    except Exception:
        pass


def _save_holiday_cache(new_years, new_failed):
    """把联网拉取到的年度数据/失败记录合并写入本地缓存文件"""
    try:
        path = _holiday_cache_path()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
        data.setdefault('years', {}).update(new_years)
        failed = dict(data.get('failed', {}))
        failed.update(new_failed)
        for ys in new_years:
            failed.pop(ys, None)
        if failed:
            data['failed'] = failed
        else:
            data.pop('failed', None)
        data['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _fetch_year_days(year):
    """联网获取某一年的节假日数据，返回 {日期: 是否放假}，失败返回None"""
    for url in HOLIDAY_CN_URLS:
        try:
            req = urllib.request.Request(url.format(year=year), headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            days = data.get('days')
            if isinstance(days, list) and days:
                return {d['date']: bool(d['isOffDay']) for d in days if d.get('date')}
        except Exception:
            continue
    return None


def ensure_holiday_data(start_date, end_date, progress=None):
    """确保查询范围覆盖年份的节假日数据就绪（缓存优先，仅缺失的年份联网拉取一次）"""
    _load_holiday_cache()
    try:
        y0 = datetime.strptime(start_date, '%Y-%m-%d').year
        y1 = datetime.strptime(end_date, '%Y-%m-%d').year
    except ValueError:
        return
    now = time.time()
    new_years, new_failed = {}, {}
    for year in range(y0, y1 + 1):
        ys = str(year)
        if any(d.startswith(ys) for d in _holiday_cache):
            continue
        if ys in _BUILTIN_HOLIDAYS:
            _holiday_cache.update(_BUILTIN_HOLIDAYS[ys])
            continue
        last_fail = _holiday_failed.get(ys)
        if isinstance(last_fail, (int, float)) and now - last_fail < HOLIDAY_RETRY_INTERVAL:
            continue
        if progress:
            progress(f'联网获取{ys}年节假日/调休安排...')
        days = _fetch_year_days(year)
        if days:
            _holiday_cache.update(days)
            new_years[ys] = days
        else:
            new_failed[ys] = now
    if new_years or new_failed:
        _save_holiday_cache(new_years, new_failed)


def day_type(date_str):
    """
    判断日期类型
    :param date_str: 日期字符串，格式为 'YYYY-MM-DD'
    :return: 'workday' 工作日（含周末调休上班日）；'rest' 休息日（周末和法定节假日）
    数据只覆盖内置快照/缓存年份；其余年份可用 run_scrape 前先调 ensure_holiday_data 联网补齐，
    否则按周一~周五近似判断。
    """
    _load_holiday_cache()
    if date_str in _holiday_cache:
        return 'rest' if _holiday_cache[date_str] else 'workday'
    try:
        return 'workday' if datetime.strptime(date_str, '%Y-%m-%d').weekday() < 5 else 'rest'
    except ValueError:
        return 'rest'


def is_workday(date_str):
    """判断是否工作日（含调休上班日；法定节假日即使是周一~周五也不算）"""
    return day_type(date_str) == 'workday'


def quarter_bounds(date_str):
    """
    返回日期所在季度的第一天和最后一天（'YYYY-MM-DD'）
    季度划分：1-3月 / 4-6月 / 7-9月 / 10-12月
    """
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    start_month = (dt.month - 1) // 3 * 3 + 1
    first = dt.replace(month=start_month, day=1)
    if start_month == 10:
        last = dt.replace(month=12, day=31)
    else:
        last = dt.replace(month=start_month + 3, day=1) - timedelta(days=1)
    return first.strftime('%Y-%m-%d'), last.strftime('%Y-%m-%d')


def remaining_quarter_workdays(end_date):
    """
    计算 end_date（不含）到其所在季度末的剩余工作日天数
    调休上班的周末算工作日，法定节假日（即使在周中）不算
    """
    try:
        _, quarter_last = quarter_bounds(end_date)
        d = datetime.strptime(end_date, '%Y-%m-%d')
        last = datetime.strptime(quarter_last, '%Y-%m-%d')
    except ValueError:
        return 0
    count = 0
    while d < last:
        d += timedelta(days=1)
        if is_workday(d.strftime('%Y-%m-%d')):
            count += 1
    return count


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

    工作日（含调休上班日）：加班 = 下班打卡时间 - 正常下班时间
    休息日（周末+法定节假日）：全天计加班 = 下班打卡时间 - 上班打卡时间
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

def build_results(records, start_date, end_date, work_end_time, unchecked_days):
    """
    计算查询范围内每条记录的加班时长和汇总数据
    - 工作日（含调休上班日）：加班 = 下班打卡 - 正常下班时间；
      只打了上班卡的视为17:20准时下班（0加班，仍计入分母）
    - 休息日（周末+法定节假日）：有打卡即全天计加班 = 下班打卡 - 上班打卡（不计入分母）
    :return: (明细列表, 汇总dict)
    """
    all_results = []
    for date_str in sorted(records.keys()):
        if start_date <= date_str <= end_date:
            rec = records[date_str]
            if len(rec) >= 4 and rec[2]:
                overtime_min = calc_overtime(rec[2], rec[3], date_str, work_end_time)
                all_results.append([date_str, rec[1], rec[2], rec[3], fmt_hours(overtime_min), overtime_min])

    total_overtime_min = sum(r[5] for r in all_results)
    weekend_overtime_min = sum(r[5] for r in all_results if not is_workday(r[0]))
    workday_count = sum(1 for r in all_results if is_workday(r[0]))
    denominator = (unchecked_days + workday_count) * 4 * 60
    percent = total_overtime_min / denominator * 100 if denominator > 0 else 0

    summary = {
        'total_overtime_hours': total_overtime_min / 60,
        'total_overtime_str': fmt_hours(total_overtime_min),
        'full_overtime_hours': denominator / 60,
        'full_overtime_str': fmt_hours(denominator),
        'percent': percent,
        'workday_count': workday_count,
        'unchecked_days': unchecked_days,
        'weekend_overtime_hours': weekend_overtime_min / 60,
        'quarter_end_date': quarter_bounds(end_date)[1],
        'remaining_quarter_workdays': remaining_quarter_workdays(end_date),
    }
    return all_results, summary

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

    # 节假日/调休数据按年缓存，仅在缺失时联网补一次
    emit('正在检查节假日/调休数据...')
    ensure_holiday_data(start_date, end_date, emit)

    csv_file = os.path.join(app_dir(), '打卡记录.csv')
    existing_records = read_existing_csv(csv_file)
    csv_first, csv_last = get_csv_date_range(csv_file)
    unchecked_days = int(config.get('unchecked_days', '0') or 0)

    # 情况1：CSV完全覆盖查询范围，直接用已有数据重新计算
    if existing_records and csv_first and csv_last:
        if start_date >= csv_first and end_date <= csv_last:
            emit('已有完整数据，无需登录查询...')
            all_results, summary = build_results(
                existing_records, start_date, end_date, work_end_time, unchecked_days)

            return {
                'record_count': len(all_results),
                'csv_file': csv_file,
                **summary,
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

    # 浏览器相关依赖仅在需要登录爬取时才导入
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup

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

            all_results, summary = build_results(
                merged, start_date, end_date, work_end_time, unchecked_days)

            # 保存所有合并后的记录到CSV（只打上班卡的行也保留，便于下次增量）
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['日期', '星期', '上班时间', '下班时间', '加班时间'])
                for date_str in sorted(merged.keys()):
                    rec = merged[date_str]
                    if len(rec) >= 4 and rec[2]:
                        ot_min = calc_overtime(rec[2], rec[3], date_str, work_end_time)
                        writer.writerow([date_str, rec[1], rec[2], rec[3], fmt_hours(ot_min)])

            return {
                'record_count': len(all_results),
                'new_count': len(new_records),
                'csv_file': csv_file,
                **summary,
            }

        finally:
            browser.close()
