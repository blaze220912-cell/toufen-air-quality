from flask import Flask, render_template_string, send_from_directory
import requests
from datetime import datetime, timedelta, timezone
from threading import Lock
import urllib3
import os
import json
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
TAIPEI_TZ = timezone(timedelta(hours=8))
BACKGROUND_IMAGE = "background.jpg"

# 空氣品質數據(右側 - 保留原樣)
latest_data = {
    'aqi': 'N/A', 'pm25_avg': 'N/A', 'pm10_avg': 'N/A',
    'pm10': 'N/A', 'pm25': 'N/A', 'o3': 'N/A',
    'update_time': '尚未更新', 'site_name': '頭份',
    'publish_time': 'N/A', 'has_data': False, 'last_fetch': None,
    'trend': []   # ★ 新增:過去12小時趨勢資料
}

# 天氣預報數據(左側 - 修改為預報)
forecast_data = {
    'temp': 'N/A', 'feels_like': 'N/A',
    'comfort_index': 'N/A', 'comfort_desc': '無資料',
    'comfort_emoji': '❓', 'comfort_color': 'gray',
    'humidity': 'N/A', 'wind_display': 'N/A',
    'wind_speed_ms': None,   # ★ 新增:數值風速(m/s),供跑步指數計算
    'weather_desc': 'N/A', 'pop': 'N/A',
    'forecast_time': 'N/A',
    'has_data': False, 'last_fetch': None
}

# 天氣警特報數據
alert_data = {
    'has_alert': False,
    'alerts': [],
    'last_fetch': None
}

# ★ 新增:跑步適宜度指數
running_data = {
    'has_data': False,
    'score': 0,
    'level': '資料載入中',
    'emoji': '⏳',
    'color': 'gray',
    'reasons_text': ''
}

fetch_lock = Lock()

AQI_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432?format=json&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&filters=SiteName,EQ,頭份"
# ★ 修改:limit 拉高到 200 並加上站點過濾,確保能取回完整 12 小時 × 多測項的數據
AQI_HOURLY_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_213?language=en&limit=200&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&filters=sitename,EQ,Toufen"
FORECAST_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-013?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&LocationName=頭份市"
WEATHER_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-001?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&locationName=苗栗縣"
COLD_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-004?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&CountyName=%E8%8B%97%E6%A0%97%E7%B8%A3&expires=true"
HEAT_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-005?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&CountyName=%E8%8B%97%E6%A0%97%E7%B8%A3&expires=true"
TYPHOON_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&expires=true"
RAIN_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-003?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&CountyName=%E8%8B%97%E6%A0%97%E7%B8%A3&expires=true"

def get_taipei_time():
    return datetime.now(TAIPEI_TZ)

def parse_number(value):
    """從字串中安全解析數值('≥11'、'3.5'、'N/A' 都能處理)"""
    if value is None:
        return None
    m = re.search(r'-?\d+(\.\d+)?', str(value))
    return float(m.group()) if m else None

# 取得舒適度表情與顏色
def get_comfort_emoji_color(desc):
    desc_lower = desc.lower() if desc else ''

    if '舒適' in desc or 'comfortable' in desc_lower:
        return '😊', 'green'
    elif '悶熱' in desc or '悶' in desc:
        return '😓', 'orange'
    elif '易中暑' in desc or '炎熱' in desc:
        return '🥵', 'red'
    elif '寒冷' in desc or '冷' in desc:
        return '🥶', 'blue'
    else:
        return '😐', 'yellow'

# ★ 依警報類型取得專屬圖示,並判定是否為「嚴重級」(呼吸燈等級)
def get_alert_visual(phenomena, significance, color):
    """回傳 (icon, severe)。severe=True 會套用呼吸燈醒目動畫。"""
    text = f"{phenomena or ''}{significance or ''}"

    if '颱風' in text:
        icon = '🌀'
    elif '超大豪雨' in text or '大豪雨' in text:
        icon = '🌧️'
    elif '豪雨' in text:
        icon = '🌧️'
    elif '大雨' in text:
        icon = '🌦️'
    elif '低溫' in text or '寒流' in text:
        icon = '🥶'
    elif '高溫' in text:
        icon = '🥵'
    elif '濃霧' in text:
        icon = '🌫️'
    elif '強風' in text or '陸上強風' in text:
        icon = '💨'
    else:
        icon = '⚠️'

    # 嚴重級判定:颱風、超大豪雨、大豪雨,或任何紅色警戒
    severe = (
        '颱風' in text
        or '超大豪雨' in text
        or '大豪雨' in text
        or color == 'red'
    )
    return icon, severe

# ★★★ 新增:跑步適宜度指數 ★★★
def calculate_running_index():
    """
    綜合空品(AQI/PM2.5即時值)與天氣預報(體感、濕度、降雨機率、風速)
    計算 0-100 的跑步適宜度分數。

    風速扣分規則(依使用者標準:9 m/s 以下不扣分,超過 9 m/s 開始列入):
        <=9 m/s   : 0
        9~11 m/s  : -10(逆風已明顯吃力)
        11~13 m/s : -22(6級風,配速嚴重受影響)
        13~15 m/s : -35(接近7級,路樹落枝風險)
        >15 m/s   : -50(基本不宜路跑)
    """
    global running_data

    penalties = []  # (原因文字, 扣分)

    aqi = parse_number(latest_data.get('aqi'))
    pm25 = parse_number(latest_data.get('pm25'))
    feels = parse_number(forecast_data.get('feels_like'))
    if feels is None:
        feels = parse_number(forecast_data.get('temp'))
    humidity = parse_number(forecast_data.get('humidity'))
    pop = parse_number(forecast_data.get('pop'))
    wind = forecast_data.get('wind_speed_ms')

    # 核心資料都拿不到就不評分
    if aqi is None and feels is None:
        running_data = {
            'has_data': False, 'score': 0, 'level': '資料不足',
            'emoji': '❓', 'color': 'gray', 'reasons_text': ''
        }
        return

    # 1. AQI
    if aqi is not None:
        if aqi > 150:
            penalties.append((f'AQI {aqi:.0f} 不健康', 60))
        elif aqi > 100:
            penalties.append((f'AQI {aqi:.0f} 對敏感族群不健康', 30))
        elif aqi > 50:
            penalties.append((f'AQI {aqi:.0f} 普通', 10))

    # 2. PM2.5 即時值(高強度運動換氣量大,額外看細懸浮微粒)
    if pm25 is not None:
        if pm25 > 54.4:
            penalties.append((f'PM2.5 {pm25:.0f} 偏高', 35))
        elif pm25 > 35.4:
            penalties.append((f'PM2.5 {pm25:.0f} 略高', 18))
        elif pm25 > 15.4:
            penalties.append((f'PM2.5 {pm25:.0f}', 8))

    # 3. 體感溫度
    if feels is not None:
        if feels > 36:
            penalties.append((f'體感 {feels:.0f}°C 易中暑', 50))
        elif feels > 33:
            penalties.append((f'體感 {feels:.0f}°C 炎熱', 32))
        elif feels > 30:
            penalties.append((f'體感 {feels:.0f}°C 偏熱', 18))
        elif feels > 26:
            penalties.append((f'體感 {feels:.0f}°C 微熱', 8))
        elif feels < 5:
            penalties.append((f'體感 {feels:.0f}°C 嚴寒', 25))
        elif feels < 10:
            penalties.append((f'體感 {feels:.0f}°C 寒冷', 12))
        elif feels < 15:
            penalties.append((f'體感 {feels:.0f}°C 偏涼', 3))

    # 4. 相對濕度(高溫高濕排汗散熱差,加重扣分)
    if humidity is not None:
        if humidity > 85:
            extra = 5 if (feels is not None and feels > 26) else 0
            penalties.append((f'濕度 {humidity:.0f}% 悶濕', 8 + extra))
        elif humidity > 70:
            penalties.append((f'濕度 {humidity:.0f}%', 4))

    # 5. 降雨機率
    if pop is not None:
        if pop >= 70:
            penalties.append((f'降雨機率 {pop:.0f}%', 25))
        elif pop >= 50:
            penalties.append((f'降雨機率 {pop:.0f}%', 15))
        elif pop >= 30:
            penalties.append((f'降雨機率 {pop:.0f}%', 6))

    # 6. 風速(依你的標準:>9 m/s 才開始扣分)
    if wind is not None:
        if wind > 15:
            penalties.append((f'風速 {wind:.0f} m/s 強風', 50))
        elif wind > 13:
            penalties.append((f'風速 {wind:.0f} m/s 過強', 35))
        elif wind > 11:
            penalties.append((f'風速 {wind:.0f} m/s 偏強', 22))
        elif wind > 9:
            penalties.append((f'風速 {wind:.0f} m/s 逆風吃力', 10))

    score = max(0, 100 - sum(p[1] for p in penalties))

    if score >= 85:
        level, emoji, color = '絕佳,放心開跑!', '🏃', 'green'
    elif score >= 70:
        level, emoji, color = '適合跑步', '👍', 'green'
    elif score >= 55:
        level, emoji, color = '尚可,注意補水與強度', '💧', 'yellow'
    elif score >= 40:
        level, emoji, color = '勉強,建議縮短距離', '⚠️', 'orange'
    else:
        level, emoji, color = '建議休息或改室內訓練', '🛑', 'red'

    # 取扣分最多的前 4 項作為說明
    penalties.sort(key=lambda p: p[1], reverse=True)
    if penalties:
        reasons_text = '主要扣分:' + '、'.join(
            f'{txt}(-{pt})' for txt, pt in penalties[:4]
        )
    else:
        reasons_text = '各項條件均佳,是跑步的好時機'

    running_data = {
        'has_data': True,
        'score': int(score),
        'level': level,
        'emoji': emoji,
        'color': color,
        'reasons_text': reasons_text
    }
    print(f"✓ 跑步指數計算完成:{score:.0f} 分({level})")

# 抓取天氣預報(左側)
def fetch_weather_forecast():
    global forecast_data
    try:
        print(f"正在呼叫頭份預報 API...")
        response = requests.get(FORECAST_API_URL, timeout=10)
        print(f"預報 API 狀態碼: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if data.get('success') == 'true' and data.get('records'):
            locations = data['records']['Locations'][0]['Location']

            if len(locations) > 0:
                location = locations[0]
                weather_elements = location['WeatherElement']

                # 取得第一筆時間資料(最接近當前)
                temp_element = next((e for e in weather_elements if e['ElementName'] == '溫度'), None)
                feels_element = next((e for e in weather_elements if e['ElementName'] == '體感溫度'), None)
                comfort_element = next((e for e in weather_elements if e['ElementName'] == '舒適度指數'), None)
                humidity_element = next((e for e in weather_elements if e['ElementName'] == '相對濕度'), None)
                wind_speed_element = next((e for e in weather_elements if e['ElementName'] == '風速'), None)
                wind_dir_element = next((e for e in weather_elements if e['ElementName'] == '風向'), None)
                weather_element = next((e for e in weather_elements if e['ElementName'] == '天氣現象'), None)
                pop_element = next((e for e in weather_elements if e['ElementName'] == '3小時降雨機率'), None)

                # 取第一筆資料
                forecast_time = 'N/A'
                temp = 'N/A'
                feels_like = 'N/A'
                comfort_index = 'N/A'
                comfort_desc = '無資料'
                humidity = 'N/A'
                wind_speed = 'N/A'
                wind_scale = 'N/A'
                wind_dir = 'N/A'
                weather_desc = 'N/A'
                rain_prob = 'N/A'

                if temp_element and len(temp_element['Time']) > 0:
                    # 取得當前時間並計算下一個整點
                    current_time = get_taipei_time()
                    next_hour = (current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                    print(f"  當前時間: {current_time.strftime('%H:%M')}, 尋找下一整點: {next_hour.strftime('%H:00')}")

                    # 找到符合下一整點的預報
                    target_time = None
                    target_index = 0
                    for i, time_data in enumerate(temp_element['Time']):
                        data_time_str = time_data.get('DataTime', '')
                        try:
                            data_time = datetime.fromisoformat(data_time_str.replace('+08:00', ''))
                            if data_time.hour == next_hour.hour and data_time.date() == next_hour.date():
                                target_time = time_data
                                target_index = i
                                break
                        except:
                            continue

                    # 如果找不到，用第一筆
                    if target_time is None:
                        print(f"  ⚠️ 找不到 {next_hour.strftime('%H:00')} 的預報，使用第一筆")
                        target_time = temp_element['Time'][0]
                        target_index = 0

                    forecast_time = target_time.get('DataTime', 'N/A')
                    temp = target_time['ElementValue'][0].get('Temperature', 'N/A')
                    print(f"  ✓ 預報時間: {forecast_time}")

                    # 其他氣象要素使用相同索引
                    if feels_element and len(feels_element['Time']) > target_index:
                        feels_like = feels_element['Time'][target_index]['ElementValue'][0].get('ApparentTemperature', 'N/A')

                    if comfort_element and len(comfort_element['Time']) > target_index:
                        comfort_value = comfort_element['Time'][target_index]['ElementValue'][0]
                        comfort_index = comfort_value.get('ComfortIndex', 'N/A')
                        comfort_desc = comfort_value.get('ComfortIndexDescription', '無資料')

                    if humidity_element and len(humidity_element['Time']) > target_index:
                        humidity = humidity_element['Time'][target_index]['ElementValue'][0].get('RelativeHumidity', 'N/A')

                    if wind_speed_element and len(wind_speed_element['Time']) > target_index:
                        wind_value = wind_speed_element['Time'][target_index]['ElementValue'][0]
                        wind_speed = wind_value.get('WindSpeed', 'N/A')
                        wind_scale = wind_value.get('BeaufortScale', 'N/A')

                    if wind_dir_element and len(wind_dir_element['Time']) > target_index:
                        wind_dir = wind_dir_element['Time'][target_index]['ElementValue'][0].get('WindDirection', 'N/A')

                    if weather_element and len(weather_element['Time']) > target_index:
                        weather_desc = weather_element['Time'][target_index]['ElementValue'][0].get('Weather', 'N/A')

                    if pop_element and len(pop_element['Time']) > target_index:
                        rain_prob = pop_element['Time'][target_index]['ElementValue'][0].get('ProbabilityOfPrecipitation', 'N/A')

                    # 組合風速風向顯示
                    if wind_dir != 'N/A' and wind_speed != 'N/A' and wind_scale != 'N/A':
                        wind_display = f"{wind_dir} 平均風速{wind_scale}級(每秒{wind_speed}公尺)"
                    else:
                        wind_display = 'N/A'

                    # 取得舒適度表情
                    comfort_emoji, comfort_color = get_comfort_emoji_color(comfort_desc)


                    try:
                        dt = datetime.fromisoformat(forecast_time.replace('+08:00', ''))
                        forecast_time_display = dt.strftime('%m/%d %H:%M')
                    except:
                        forecast_time_display = forecast_time

                    forecast_data = {
                        'temp': temp,
                        'feels_like': feels_like,
                        'comfort_index': comfort_index,
                        'comfort_desc': comfort_desc,
                        'comfort_emoji': comfort_emoji,
                        'comfort_color': comfort_color,
                        'humidity': humidity,
                        'wind_display': wind_display,
                        'wind_speed_ms': parse_number(wind_speed),   # ★ 數值風速,供跑步指數使用('≥11' 也能解析)
                        'weather_desc': weather_desc,
                        'pop': rain_prob,
                        'forecast_time': forecast_time_display,
                        'has_data': True,
                        'last_fetch': get_taipei_time()
                    }

                    print(f"✓ 預報數據更新成功")
                    print(f"  溫度: {temp}°C, 舒適度: {comfort_desc}, 風速: {forecast_data['wind_speed_ms']} m/s")
                    return

        forecast_data['has_data'] = False

    except Exception as e:
        print(f"× 抓取預報數據失敗: {e}")
        import traceback
        traceback.print_exc()
        forecast_data['has_data'] = False

# 抓取天氣警特報
def fetch_weather_alerts():
    global alert_data
    try:
        print(f"正在呼叫天氣警特報 API...")

        alerts_list = []

        # 時間格式化函數
        def format_time(time_str):
            """將 ISO 時間格式轉換為易讀格式"""
            if time_str == 'N/A' or not time_str:
                return 'N/A'
            try:
                # 解析 ISO 8601 格式
                dt = datetime.fromisoformat(time_str.replace('+08:00', ''))
                # 轉換為 "月/日 時:分" 格式
                return dt.strftime('%m/%d %H:%M')
            except:
                return time_str

        # 1. 一般警特報 (W-C0033-001) - 強風、大雨等
        try:
            response1 = requests.get(WEATHER_ALERT_API_URL, timeout=10)
            print(f"一般警特報 API 狀態碼: {response1.status_code}")

            if response1.status_code == 200:
                data1 = response1.json()
                if data1.get('success') == 'true' and data1.get('records'):
                    locations = data1['records'].get('location', [])

                    if len(locations) > 0:
                        location = locations[0]
                        hazard_conditions = location.get('hazardConditions', {})
                        hazards = hazard_conditions.get('hazards', [])

                        for hazard in hazards:
                            info = hazard.get('info', {})
                            valid_time = hazard.get('validTime', {})

                            phenomena = info.get('phenomena', 'N/A')
                            significance = info.get('significance', 'N/A')
                            start_time = valid_time.get('startTime', 'N/A')
                            end_time = valid_time.get('endTime', 'N/A')

                            alert_color = 'orange'
                            if '豪雨' in phenomena:
                                alert_color = 'red'
                            elif '強風' in phenomena or '大雨' in phenomena:
                                alert_color = 'orange'
                            elif '濃霧' in phenomena:
                                alert_color = 'yellow'

                            alerts_list.append({
                                'phenomena': phenomena,
                                'significance': significance,
                                'start_time': format_time(start_time),
                                'end_time': format_time(end_time),
                                'color': alert_color
                            })
                            print(f"  ⚠️ 一般警特報：{phenomena}{significance}")
        except Exception as e:
            print(f"  × 一般警特報 API 錯誤: {e}")

        # 2. 豪大雨特報 (W-C0033-003)
        try:
            response_rain = requests.get(RAIN_ALERT_API_URL, timeout=10)
            print(f"豪大雨特報 API 狀態碼: {response_rain.status_code}")

            if response_rain.status_code == 200:
                data_rain = response_rain.json()

                if data_rain.get('success') == 'true' and data_rain.get('records'):
                    info_list = data_rain['records'].get('info', [])

                    if len(info_list) > 0:
                        processed_alerts = set()
                        current_time = get_taipei_time()  # 取得當前時間

                        for info in info_list:
                            headline = info.get('headline', 'N/A')
                            effective = info.get('effective', 'N/A')
                            expires = info.get('expires', 'N/A')

                            # 過濾已解除的警報（標題包含「解除」）
                            if '解除' in headline:
                                print(f"  ℹ️ 略過已解除的警報：{headline}")
                                continue

                            # 檢查是否已過期
                            try:
                                expire_dt = datetime.fromisoformat(expires.replace('+08:00', ''))
                                expire_dt = expire_dt.replace(tzinfo=TAIPEI_TZ)
                                if current_time > expire_dt:
                                    print(f"  ℹ️ 略過已過期的警報：{headline}")
                                    continue
                            except:
                                pass

                            alert_color = 'orange'
                            severity_level = '豪大雨特報'

                            for param in info.get('parameter', []):
                                if param.get('valueName') == 'alert_color':
                                    color_value = param.get('value', '').lower()
                                    if '紅' in color_value or 'red' in color_value:
                                        alert_color = 'red'
                                    elif '橙' in color_value or 'orange' in color_value:
                                        alert_color = 'orange'
                                    elif '黃' in color_value or 'yellow' in color_value:
                                        alert_color = 'yellow'
                                if param.get('valueName') == 'severity_level':
                                    severity_level = param.get('value', '豪大雨特報')

                            has_toufen = False
                            for area in info.get('area', []):
                                if '頭份' in area.get('areaDesc', '') or '苗栗' in area.get('areaDesc', ''):
                                    has_toufen = True
                                    break

                            alert_key = f"{headline}_{severity_level}_{alert_color}"
                            if has_toufen and alert_key not in processed_alerts:
                                processed_alerts.add(alert_key)

                                alerts_list.append({
                                    'phenomena': headline,
                                    'significance': severity_level,
                                    'start_time': format_time(effective),
                                    'end_time': format_time(expires),
                                    'color': alert_color
                                })
                                print(f"  ⚠️ 豪大雨特報：{headline} - {severity_level}")
                    else:
                        print(f"  ✓ 目前無豪大雨特報")
        except Exception as e:
            print(f"  × 豪大雨特報 API 錯誤: {e}")
            import traceback
            traceback.print_exc()

        # 3. 低溫特報 (W-C0033-004)
        try:
            response2 = requests.get(COLD_ALERT_API_URL, timeout=10)
            print(f"低溫特報 API 狀態碼: {response2.status_code}")

            if response2.status_code == 200:
                data2 = response2.json()

                if data2.get('success') == 'true' and data2.get('records'):
                    # 注意：資料在 info 陣列，不是 record 陣列！
                    info_list = data2['records'].get('info', [])
                    print(f"  🔍 找到 {len(info_list)} 筆 info")

                    if len(info_list) > 0:
                        processed_alerts = set()
                        current_time = get_taipei_time()  # 取得當前時間

                        for info in info_list:
                            headline = info.get('headline', 'N/A')
                            description = info.get('description', 'N/A')
                            effective = info.get('effective', 'N/A')
                            expires = info.get('expires', 'N/A')

                            # 過濾已解除的警報
                            if '解除' in headline:
                                print(f"  ℹ️ 略過已解除的警報：{headline}")
                                continue

                            # 檢查是否已過期
                            try:
                                expire_dt = datetime.fromisoformat(expires.replace('+08:00', ''))
                                expire_dt = expire_dt.replace(tzinfo=TAIPEI_TZ)
                                if current_time > expire_dt:
                                    print(f"  ℹ️ 略過已過期的警報：{headline}")
                                    continue
                            except:
                                pass

                            # 取得顏色等級
                            alert_color = 'blue'
                            for param in info.get('parameter', []):
                                if param.get('valueName') == 'alert_color':
                                    color_value = param.get('value', '').lower()
                                    if '橙' in color_value or 'orange' in color_value:
                                        alert_color = 'orange'
                                    elif '黃' in color_value or 'yellow' in color_value:
                                        alert_color = 'yellow'
                                    elif '紅' in color_value or 'red' in color_value:
                                        alert_color = 'red'
                                    break

                            # 取得嚴重程度
                            severity_level = '低溫特報'
                            for param in info.get('parameter', []):
                                if param.get('valueName') == 'severity_level':
                                    severity_level = param.get('value', '低溫特報')
                                    break

                            # 檢查是否包含頭份市
                            has_toufen = False
                            for area in info.get('area', []):
                                if '頭份' in area.get('areaDesc', ''):
                                    has_toufen = True
                                    break

                            # 避免重複加入相同警報
                            alert_key = f"{headline}_{severity_level}_{alert_color}"
                            if has_toufen and alert_key not in processed_alerts:
                                processed_alerts.add(alert_key)

                                alerts_list.append({
                                    'phenomena': headline,
                                    'significance': severity_level,
                                    'start_time': format_time(effective),
                                    'end_time': format_time(expires),
                                    'color': alert_color
                                })
                                print(f"  ⚠️ 低溫特報：{headline} - {severity_level} ({alert_color})")

                        if len(processed_alerts) == 0:
                            print(f"  ✓ 苗栗縣頭份市目前無低溫特報")
                    else:
                        print(f"  ✓ 目前無低溫特報")
        except Exception as e:
            print(f"  × 低溫特報 API 錯誤: {e}")
            import traceback
            traceback.print_exc()

        # 4. 颱風警報 (W-C0034-001)
        try:
            response3 = requests.get(TYPHOON_ALERT_API_URL, timeout=10)
            print(f"颱風警報 API 狀態碼: {response3.status_code}")

            if response3.status_code == 200:
                data3 = response3.json()
                if data3.get('success') == 'true' and data3.get('records'):
                    records = data3['records'].get('record', [])

                    if len(records) > 0:
                        for record in records:
                            hazard_name = record.get('hazardName', 'N/A')
                            title = record.get('title', 'N/A')
                            issue_time = record.get('issueTime', 'N/A')
                            expire_time = record.get('expireTime', 'N/A')

                            # 颱風警報用紅色（最高等級）
                            alert_color = 'red'

                            alerts_list.append({
                                'phenomena': hazard_name,
                                'significance': title,
                                'start_time': format_time(issue_time),
                                'end_time': format_time(expire_time),
                                'color': alert_color
                            })
                            print(f"  🌀 颱風警報：{hazard_name} {title}")
                    else:
                        print(f"  ✓ 目前無颱風警報")
        except Exception as e:
            print(f"  × 颱風警報 API 錯誤: {e}")

        # 5. 高溫特報 (W-C0033-005)
        try:
            response4 = requests.get(HEAT_ALERT_API_URL, timeout=10)
            print(f"高溫特報 API 狀態碼: {response4.status_code}")

            if response4.status_code == 200:
                data4 = response4.json()

                if data4.get('success') == 'true' and data4.get('records'):
                    # 注意：資料在 info 陣列，不是 record 陣列！
                    info_list = data4['records'].get('info', [])
                    print(f"  🔍 找到 {len(info_list)} 筆 info")

                    if len(info_list) > 0:
                        processed_alerts = set()
                        current_time = get_taipei_time()  # 取得當前時間

                        for info in info_list:
                            headline = info.get('headline', 'N/A')
                            description = info.get('description', 'N/A')
                            effective = info.get('effective', 'N/A')
                            expires = info.get('expires', 'N/A')

                            # 過濾已解除的警報
                            if '解除' in headline:
                                print(f"  ℹ️ 略過已解除的警報：{headline}")
                                continue

                            # 檢查是否已過期
                            try:
                                expire_dt = datetime.fromisoformat(expires.replace('+08:00', ''))
                                expire_dt = expire_dt.replace(tzinfo=TAIPEI_TZ)
                                if current_time > expire_dt:
                                    print(f"  ℹ️ 略過已過期的警報：{headline}")
                                    continue
                            except:
                                pass

                            # 取得顏色等級
                            alert_color = 'orange'
                            for param in info.get('parameter', []):
                                if param.get('valueName') == 'alert_color':
                                    color_value = param.get('value', '').lower()
                                    if '紅' in color_value or 'red' in color_value:
                                        alert_color = 'red'
                                    elif '橙' in color_value or 'orange' in color_value:
                                        alert_color = 'orange'
                                    elif '黃' in color_value or 'yellow' in color_value:
                                        alert_color = 'yellow'
                                    break

                            # 取得嚴重程度
                            severity_level = '高溫特報'
                            for param in info.get('parameter', []):
                                if param.get('valueName') == 'severity_level':
                                    severity_level = param.get('value', '高溫特報')
                                    break

                            # 檢查是否包含頭份市或苗栗縣
                            has_toufen = False
                            for area in info.get('area', []):
                                area_desc = area.get('areaDesc', '')
                                if '頭份' in area_desc or '苗栗' in area_desc:
                                    has_toufen = True
                                    break

                            # 避免重複加入相同警報
                            alert_key = f"{headline}_{severity_level}_{alert_color}"
                            if has_toufen and alert_key not in processed_alerts:
                                processed_alerts.add(alert_key)

                                alerts_list.append({
                                    'phenomena': headline,
                                    'significance': severity_level,
                                    'start_time': format_time(effective),
                                    'end_time': format_time(expires),
                                    'color': alert_color
                                })
                                print(f"  🌡️ 高溫特報：{headline} - {severity_level} ({alert_color})")

                        if len(processed_alerts) == 0:
                            print(f"  ✓ 苗栗縣頭份市目前無高溫特報")
                    else:
                        print(f"  ✓ 目前無高溫特報")
        except Exception as e:
            print(f"  × 高溫特報 API 錯誤: {e}")
            import traceback
            traceback.print_exc()

        # 6. 統一為每則警報標上專屬圖示與嚴重等級(呼吸燈)
        for a in alerts_list:
            icon, severe = get_alert_visual(a.get('phenomena', ''), a.get('significance', ''), a.get('color', 'orange'))
            a['icon'] = icon
            a['severe'] = severe

        # 嚴重警報排在最前面
        alerts_list.sort(key=lambda a: (not a.get('severe', False)))

        # 7. 更新全域資料
        if len(alerts_list) > 0:
            alert_data = {
                'has_alert': True,
                'alerts': alerts_list,
                'last_fetch': get_taipei_time()
            }
            print(f"✓ 警特報數據更新成功：共 {len(alerts_list)} 則警報")
        else:
            alert_data = {
                'has_alert': False,
                'alerts': [],
                'last_fetch': get_taipei_time()
            }
            print(f"✓ 目前無任何天氣警特報")

    except Exception as e:
        print(f"× 抓取警特報數據失敗: {e}")
        import traceback
        traceback.print_exc()
        alert_data['has_alert'] = False

# 抓取空氣品質(右側)
def fetch_air_quality_data():
    global latest_data
    try:
        print(f"正在呼叫 AQI API...")

        # 1. 先呼叫小時值 API，取得過去 12 小時的測項數據
        print(f"  → 呼叫小時值 API (取過去12小時數據)...")
        hourly_response = requests.get(AQI_HOURLY_API_URL, timeout=10, verify=False)
        print(f"  → 小時值 API 狀態碼: {hourly_response.status_code}")

        previous_hour_data = None
        trend_series = []   # ★ 新增:趨勢資料序列
        if hourly_response.status_code == 200:
            hourly_data = hourly_response.json()
            # 小時值 API 直接返回 list，不是 dict
            if isinstance(hourly_data, list) and len(hourly_data) > 0:
                hourly_records = hourly_data
                print(f"  ✓ 取得 {len(hourly_records)} 筆小時值數據")
            elif isinstance(hourly_data, dict) and hourly_data.get('records'):
                hourly_records = hourly_data['records']
                print(f"  ✓ 取得 {len(hourly_records)} 筆小時值數據")
            else:
                hourly_records = []
                print(f"  ⚠️ 小時值 API 無數據")

            if len(hourly_records) > 0:
                # 將垂直格式轉換為水平格式
                grouped_data = {}
                for record in hourly_records:
                    if record.get('sitename') == 'Toufen':
                        monitor_date = record.get('monitordate', '')
                        item_name = record.get('itemname', '')
                        concentration = record.get('concentration', 'N/A')

                        if monitor_date not in grouped_data:
                            grouped_data[monitor_date] = {}

                        grouped_data[monitor_date][item_name] = concentration

                # 排序取得最新兩個小時(供變化量計算)
                sorted_dates = sorted(grouped_data.keys(), reverse=True)
                print(f"  ✓ 找到 {len(sorted_dates)} 個不同時間點: {sorted_dates[:2]}")

                if len(sorted_dates) >= 2:
                    previous_hour = sorted_dates[1]
                    previous_hour_data = grouped_data[previous_hour]
                    print(f"  ✓ 前一小時數據: {previous_hour}")
                elif len(sorted_dates) == 1:
                    print(f"  ⚠️ 只有1個時間點的數據，無法計算變化量")
                else:
                    print(f"  ⚠️ 無有效數據")

                # ★ 建立過去12小時趨勢序列(時間由舊到新)
                asc_dates = sorted(grouped_data.keys())[-12:]
                for d in asc_dates:
                    items = grouped_data[d]
                    # monitordate 格式如 "2026-07-12 14:00",取小時部分作為標籤
                    label = d[-5:] if len(d) >= 5 else d
                    trend_series.append({
                        'time': label,
                        'pm25': parse_number(items.get('PM2.5')),
                        'pm10': parse_number(items.get('PM10')),
                        'o3': parse_number(items.get('Ozone'))
                    })
                print(f"  ✓ 趨勢序列建立完成:{len(trend_series)} 個時間點")
            else:
                print(f"  ⚠️ 小時值 API 無數據")
        else:
            print(f"  ⚠️ 小時值 API 呼叫失敗")

        # 2. 呼叫即時觀測 API，取得當前數據
        print(f"  → 呼叫即時觀測 API...")
        response = requests.get(AQI_API_URL, timeout=10, verify=False)
        print(f"  → 即時 API 狀態碼: {response.status_code}")

        response.raise_for_status()
        data = response.json()

        # 即時觀測 API 也可能直接返回 list
        if isinstance(data, list) and len(data) > 0:
            records = data
        elif isinstance(data, dict) and data.get('records'):
            records = data['records']
        else:
            records = []

        if len(records) > 0:
            valid_records = [r for r in records if r.get('publishtime')]
            if valid_records:
                valid_records.sort(key=lambda x: x.get('publishtime', ''), reverse=True)
                record = valid_records[0]
            else:
                record = records[0]

            # 當前數據
            aqi = record.get('aqi', 'N/A')
            pm25 = record.get('pm2.5', 'N/A')
            pm25_avg = record.get('pm2.5_avg', 'N/A')
            pm10 = record.get('pm10', 'N/A')
            pm10_avg = record.get('pm10_avg', 'N/A')
            o3 = record.get('o3', 'N/A')

            publish_time_str = record.get('publishtime', '')

            # 3. 計算變化量（當前 - 前一小時）
            def calculate_change(current, previous_data, key):
                """計算變化量：當前值 - 前一小時值"""
                if current == 'N/A' or current == '' or previous_data is None:
                    return None

                # 小時值 API 的測項名稱對應
                item_name_mapping = {
                    'pm2.5_avg': 'PM2.5',
                    'pm10_avg': 'PM10',
                    'pm2.5': 'PM2.5',
                    'pm10': 'PM10',
                    'o3': 'Ozone'
                }

                item_name = item_name_mapping.get(key)
                if not item_name:
                    return None

                previous_value = previous_data.get(item_name, 'N/A')
                if previous_value == 'N/A' or previous_value == '':
                    return None

                try:
                    curr_val = float(current)
                    prev_val = float(previous_value)
                    change = curr_val - prev_val
                    if change > 0:
                        result = f"↑ +{change:.1f}"
                    elif change < 0:
                        result = f"↓ {change:.1f}"
                    else:
                        result = "─ 0"
                    print(f"  計算 {key} ({item_name}): {prev_val} → {curr_val} = {result}")
                    return result
                except Exception as e:
                    print(f"  計算 {key} 錯誤: {e}")
                    return None

            # 計算所有變化量
            if previous_hour_data:
                print(f"  → 計算變化量（當前 vs 前一小時）")
                aqi_change = None
                pm25_avg_change = calculate_change(pm25_avg, previous_hour_data, 'pm2.5_avg')
                pm10_avg_change = calculate_change(pm10_avg, previous_hour_data, 'pm10_avg')
                pm10_change = calculate_change(pm10, previous_hour_data, 'pm10')
                pm25_change = calculate_change(pm25, previous_hour_data, 'pm2.5')
                o3_change = calculate_change(o3, previous_hour_data, 'o3')
            else:
                print(f"  ⚠️ 無前一小時數據，變化量為空")
                aqi_change = None
                pm25_avg_change = None
                pm10_avg_change = None
                pm10_change = None
                pm25_change = None
                o3_change = None

            # 4. 判斷空氣品質等級
            def get_level_info(value, thresholds, labels):
                if value == 'N/A' or value == '':
                    return 'gray', '無資料'
                try:
                    val = float(value)
                    if val <= thresholds[0]:
                        return 'green', labels[0]
                    elif val <= thresholds[1]:
                        return 'yellow', labels[1]
                    elif val <= thresholds[2]:
                        return 'orange', labels[2]
                    else:
                        return 'red', labels[3]
                except:
                    return 'gray', '無資料'

            aqi_color, aqi_label = get_level_info(aqi, [50, 100, 150], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm25_avg_color, pm25_avg_label = get_level_info(pm25_avg, [15.4, 35.4, 54.4], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm10_avg_color, pm10_avg_label = get_level_info(pm10_avg, [54, 125, 254], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm10_color, pm10_label = get_level_info(pm10, [54, 125, 254], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm25_color, pm25_label = get_level_info(pm25, [15.4, 35.4, 54.4], ['良好', '普通', '對敏感族群不健康', '不健康'])
            o3_color, o3_label = get_level_info(o3, [54, 70, 85], ['良好', '普通', '對敏感族群不健康', '不健康'])

            # 5. 更新全域數據
            latest_data = {
                'aqi': aqi, 'aqi_color': aqi_color, 'aqi_label': aqi_label, 'aqi_change': aqi_change,
                'pm25_avg': pm25_avg, 'pm25_avg_color': pm25_avg_color, 'pm25_avg_label': pm25_avg_label, 'pm25_avg_change': pm25_avg_change,
                'pm10_avg': pm10_avg, 'pm10_avg_color': pm10_avg_color, 'pm10_avg_label': pm10_avg_label, 'pm10_avg_change': pm10_avg_change,
                'pm10': pm10, 'pm10_color': pm10_color, 'pm10_label': pm10_label, 'pm10_change': pm10_change,
                'pm25': pm25, 'pm25_color': pm25_color, 'pm25_label': pm25_label, 'pm25_change': pm25_change,
                'o3': o3, 'o3_color': o3_color, 'o3_label': o3_label, 'o3_change': o3_change,
                'update_time': get_taipei_time().strftime('%Y-%m-%d %H:%M:%S'),
                'site_name': record.get('sitename', '頭份'),
                'publish_time': record.get('publishtime', 'N/A'),
                'has_data': True,
                'last_fetch': get_taipei_time(),
                'trend': trend_series   # ★ 趨勢資料
            }

            print(f"✅ AQI 數據更新成功")
            print(f"   當前時間: {publish_time_str}")
            if previous_hour_data:
                print(f"   前一小時有 {len(previous_hour_data)} 個測項")
            print(f"   當前 AQI: {aqi} (無變化量)")
            print(f"   PM2.5 avg: {pm25_avg}, 變化: {pm25_avg_change}")

        else:
            latest_data['has_data'] = False

    except Exception as e:
        print(f"× 抓取 AQI 數據失敗: {e}")
        import traceback
        traceback.print_exc()
        latest_data['has_data'] = False

def should_fetch_data():
    """檢查是否需要更新數據 - 三個數據源都要考慮"""
    current_time = get_taipei_time()

    # 如果任一數據未初始化,需要更新
    if latest_data['last_fetch'] is None or forecast_data['last_fetch'] is None or alert_data['last_fetch'] is None:
        return True

    # 檢查空品數據是否超過3分鐘
    aqi_expired = current_time - latest_data['last_fetch'] > timedelta(minutes=3)

    # 檢查預報數據是否超過3分鐘
    forecast_expired = current_time - forecast_data['last_fetch'] > timedelta(minutes=3)

    # 檢查警特報數據是否超過3分鐘
    alert_expired = current_time - alert_data['last_fetch'] > timedelta(minutes=3)

    # 任一個過期就需要更新
    return aqi_expired or forecast_expired or alert_expired

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>頭份環境監測</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Microsoft JhengHei', sans-serif;
            {% if bg_image %}
            background: url('/background') center center / cover no-repeat fixed;
            {% else %}
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            {% endif %}
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .main-container {
            max-width: 1400px;
            width: 100%;
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 20px;
        }
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        h1 { text-align: center; color: #333; margin-bottom: 10px; font-size: 2.5em; }
        h2 { text-align: center; color: #333; margin-bottom: 20px; font-size: 1.8em; }
        .site-info { text-align: center; color: #666; margin-bottom: 30px; font-size: 1.1em; }

        .weather-container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        .weather-grid { display: grid; gap: 15px; }
        .weather-item {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            padding: 15px;
            border-radius: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .weather-item.temp { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        .weather-item.feels { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); }
        .weather-item.comfort.green { background: linear-gradient(135deg, #00d084 0%, #00a86b 100%); }
        .weather-item.comfort.yellow { background: linear-gradient(135deg, #ffd700 0%, #ffb900 100%); }
        .weather-item.comfort.orange { background: linear-gradient(135deg, #ff8c00 0%, #ff6b00 100%); }
        .weather-item.comfort.red { background: linear-gradient(135deg, #ff4757 0%, #e84118 100%); }
        .weather-item.comfort.blue { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
        .weather-item.comfort.gray { background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%); }
        .weather-item.humidity { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .weather-item.wind { background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%); color: #333; }
        .weather-item.pop { background: linear-gradient(135deg, #00c6ff 0%, #0072ff 100%); }
        .weather-label { font-size: 0.9em; opacity: 0.9; }
        .weather-value { font-size: 1.5em; font-weight: bold; }
        .weather-value-large { font-size: 2em; font-weight: bold; }
        .comfort-emoji { font-size: 2.5em; }
        .weather-desc-box {
            background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            color: #333;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            font-size: 1.2em;
            font-weight: bold;
            margin-bottom: 15px;
        }
        .forecast-time {
            text-align: center;
            color: #666;
            font-size: 0.9em;
            margin-top: 15px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }

        /* ★★★ 跑步適宜度指數卡片 ★★★ */
        .run-card {
            color: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
            transition: background 0.5s ease;
        }
        .run-card.green  { background: linear-gradient(135deg, #00d084 0%, #00a86b 100%); }
        .run-card.yellow { background: linear-gradient(135deg, #ffd700 0%, #ffb900 100%); color: #333; }
        .run-card.orange { background: linear-gradient(135deg, #ff8c00 0%, #ff6b00 100%); }
        .run-card.red    { background: linear-gradient(135deg, #ff4757 0%, #e84118 100%); }
        .run-card.gray   { background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%); }
        .run-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .run-title { font-size: 0.95em; opacity: 0.9; letter-spacing: 1px; }
        .run-emoji { font-size: 2.6em; }
        .run-score {
            font-size: 3em;
            font-weight: 900;
            line-height: 1;
        }
        .run-score small { font-size: 0.35em; font-weight: normal; opacity: 0.85; margin-left: 2px; }
        .run-level {
            font-size: 1.15em;
            font-weight: bold;
            margin-top: 8px;
        }
        .run-reasons {
            font-size: 0.82em;
            margin-top: 8px;
            opacity: 0.92;
            line-height: 1.5;
        }

        .data-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .data-card {
            color: white;
            padding: 25px;
            border-radius: 15px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
            transition: transform 0.3s ease, background 0.5s ease;
        }
        .data-card.green { background: linear-gradient(135deg, #00d084 0%, #00a86b 100%); }
        .data-card.yellow { background: linear-gradient(135deg, #ffd700 0%, #ffb900 100%); }
        .data-card.orange { background: linear-gradient(135deg, #ff8c00 0%, #ff6b00 100%); }
        .data-card.red { background: linear-gradient(135deg, #ff4757 0%, #e84118 100%); }
        .data-card.gray { background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%); }
        .data-card:hover { transform: translateY(-5px); }
        .data-label { font-size: 0.9em; opacity: 0.9; margin-bottom: 10px; }
        .data-value {
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }
        .data-change {
            font-size: 0.35em;
            font-weight: normal;
            padding: 3px 8px;
            border-radius: 5px;
            white-space: nowrap;
        }
        .data-change.up { color: #c0392b; background: rgba(192, 57, 43, 0.2); font-weight: 900; border: 1px solid rgba(192, 57, 43, 0.3); }
        .data-change.down { color: #27ae60; background: rgba(39, 174, 96, 0.2); }
        .data-change.same { color: #95a5a6; background: rgba(149, 165, 166, 0.2); }
        .data-unit { font-size: 0.8em; opacity: 0.8; }
        .data-status {
            font-size: 0.85em;
            margin-top: 8px;
            padding: 5px 10px;
            background: rgba(255, 255, 255, 0.2);
            border-radius: 15px;
            font-weight: 500;
        }
        .update-info {
            text-align: center;
            color: #666;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 10px;
            margin-top: 20px;
        }
        .update-time { font-weight: bold; color: #667eea; }
        .refresh-note { margin-top: 10px; font-size: 0.9em; color: #888; }
        .error-message {
            background: #fff3cd;
            color: #856404;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            margin: 20px 0;
            border: 2px solid #ffc107;
        }

        /* ★★★ 12小時趨勢圖 ★★★ */
        .trend-container {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .trend-title {
            font-size: 1.1em;
            font-weight: bold;
            color: #333;
            margin-bottom: 4px;
        }
        .trend-legend {
            font-size: 0.82em;
            color: #666;
            margin-bottom: 10px;
        }
        .trend-legend .dot {
            display: inline-block;
            width: 10px; height: 10px;
            border-radius: 50%;
            margin: 0 4px 0 12px;
            vertical-align: middle;
        }
        .trend-legend .dot.pm25 { background: #e74c3c; margin-left: 0; }
        .trend-legend .dot.pm10 { background: #f39c12; }
        #trend-chart svg { width: 100%; height: auto; display: block; }
        .trend-empty {
            text-align: center;
            color: #999;
            padding: 25px 0;
            font-size: 0.95em;
        }

        .alert-container {
            margin-bottom: 20px;
            transition: opacity 0.5s ease-in-out;
        }
        .weather-alert {
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
            animation: alertPulse 2s ease-in-out infinite;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }
        .weather-alert.alert-red {
            background: linear-gradient(135deg, #ff4757 0%, #e84118 100%);
            color: white;
            border: 2px solid #c23616;
        }
        .weather-alert.alert-orange {
            background: linear-gradient(135deg, #ffa502 0%, #ff6348 100%);
            color: white;
            border: 2px solid #e17055;
        }
        .weather-alert.alert-yellow {
            background: linear-gradient(135deg, #ffd700 0%, #ffb900 100%);
            color: #333;
            border: 2px solid #f39c12;
        }
        .alert-icon {
            font-size: 2em;
        }
        .alert-content {
            flex: 1;
        }
        .alert-title {
            font-size: 1.2em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        .alert-time {
            font-size: 0.9em;
            opacity: 0.9;
        }
        @keyframes alertPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.85; }
        }

        /* ★★★ 嚴重級警報:呼吸燈設計 ★★★ */
        .weather-alert.severe {
            animation: none;
            border-width: 3px;
            position: relative;
        }
        .weather-alert.alert-red.severe {
            animation: breatheRed 2.5s ease-in-out infinite;
        }
        .weather-alert.alert-orange.severe {
            animation: breatheOrange 2.5s ease-in-out infinite;
        }
        @keyframes breatheRed {
            0%, 100% {
                box-shadow: 0 0 5px 1px rgba(232, 65, 24, 0.3), 0 4px 12px rgba(0, 0, 0, 0.15);
                filter: brightness(1);
            }
            50% {
                box-shadow: 0 0 20px 7px rgba(232, 65, 24, 0.55), 0 4px 12px rgba(0, 0, 0, 0.15);
                filter: brightness(1.07);
            }
        }
        @keyframes breatheOrange {
            0%, 100% {
                box-shadow: 0 0 5px 1px rgba(255, 99, 72, 0.28), 0 4px 12px rgba(0, 0, 0, 0.15);
                filter: brightness(1);
            }
            50% {
                box-shadow: 0 0 17px 6px rgba(255, 99, 72, 0.5), 0 4px 12px rgba(0, 0, 0, 0.15);
                filter: brightness(1.06);
            }
        }
        .weather-alert.severe .alert-icon {
            font-size: 2.6em;
            animation: iconBreathe 2.5s ease-in-out infinite;
        }
        @keyframes iconBreathe {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.12); }
        }
        .weather-alert.severe .alert-title {
            font-size: 1.35em;
            letter-spacing: 0.5px;
        }
        .alert-badge {
            display: inline-block;
            background: rgba(255, 255, 255, 0.28);
            border: 1px solid rgba(255, 255, 255, 0.6);
            font-size: 0.62em;
            font-weight: 900;
            padding: 2px 10px;
            border-radius: 12px;
            margin-left: 10px;
            letter-spacing: 3px;
            vertical-align: middle;
            animation: badgeBlink 2.5s ease-in-out infinite;
        }
        @keyframes badgeBlink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.55; }
        }
        /* 尊重使用者的減少動態偏好(暈眩體質友善) */
        @media (prefers-reduced-motion: reduce) {
            .weather-alert, .weather-alert.severe,
            .weather-alert.severe .alert-icon, .alert-badge {
                animation: none !important;
            }
            .weather-alert.severe {
                box-shadow: 0 0 14px 5px rgba(232, 65, 24, 0.4);
            }
        }

        @media (max-width: 1024px) {
            .main-container { grid-template-columns: 1fr; }
        }
    </style>
    <script>
        const INITIAL_TREND = {{ trend_json|safe }};

        function updateData() {
            fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        if (data.aqi_data.has_data) {
                            updateElement('[data-aqi]', data.aqi_data.aqi);
                            updateElement('[data-pm25-avg]', data.aqi_data.pm25_avg);
                            updateElement('[data-pm10-avg]', data.aqi_data.pm10_avg);
                            updateElement('[data-pm25]', data.aqi_data.pm25);
                            updateElement('[data-pm10]', data.aqi_data.pm10);
                            updateElement('[data-o3]', data.aqi_data.o3);

                            updateChange('[data-aqi-change]', data.aqi_data.aqi_change);
                            updateChange('[data-pm25-avg-change]', data.aqi_data.pm25_avg_change);
                            updateChange('[data-pm10-avg-change]', data.aqi_data.pm10_avg_change);
                            updateChange('[data-pm25-change]', data.aqi_data.pm25_change);
                            updateChange('[data-pm10-change]', data.aqi_data.pm10_change);
                            updateChange('[data-o3-change]', data.aqi_data.o3_change);

                            // 更新背景顏色
                            updateCardColor('[data-aqi]', data.aqi_data.aqi_color);
                            updateCardColor('[data-pm25-avg]', data.aqi_data.pm25_avg_color);
                            updateCardColor('[data-pm10-avg]', data.aqi_data.pm10_avg_color);
                            updateCardColor('[data-pm25]', data.aqi_data.pm25_color);
                            updateCardColor('[data-pm10]', data.aqi_data.pm10_color);
                            updateCardColor('[data-o3]', data.aqi_data.o3_color);

                            // 更新狀態標籤
                            updateStatus('[data-aqi]', data.aqi_data.aqi_label);
                            updateStatus('[data-pm25-avg]', data.aqi_data.pm25_avg_label);
                            updateStatus('[data-pm10-avg]', data.aqi_data.pm10_avg_label);
                            updateStatus('[data-pm25]', data.aqi_data.pm25_label);
                            updateStatus('[data-pm10]', data.aqi_data.pm10_label);
                            updateStatus('[data-o3]', data.aqi_data.o3_label);

                            updateElement('[data-publish-time]', data.aqi_data.publish_time);

                            // ★ 重繪趨勢圖
                            drawTrend(data.aqi_data.trend);
                        }

                        if (data.forecast_data.has_data) {
                            updateElement('[data-forecast-temp]', data.forecast_data.temp);
                            updateElement('[data-forecast-feels]', data.forecast_data.feels_like);
                            updateElement('[data-forecast-comfort]', data.forecast_data.comfort_index);
                            updateElement('[data-forecast-comfort-desc]', data.forecast_data.comfort_desc);
                            updateElement('[data-forecast-comfort-emoji]', data.forecast_data.comfort_emoji);
                            updateElement('[data-forecast-humidity]', data.forecast_data.humidity);
                            updateElement('[data-forecast-wind]', data.forecast_data.wind_display);
                            updateElement('[data-forecast-weather]', data.forecast_data.weather_desc);
                            updateElement('[data-forecast-pop]', data.forecast_data.pop);
                            updateElement('[data-forecast-time]', data.forecast_data.forecast_time);

                            // 修復舒適度背景顏色即時更新
                            updateWeatherItemColor('[data-forecast-comfort-desc]', data.forecast_data.comfort_color);
                        }

                        // ★ 更新跑步適宜度指數
                        if (data.running_data && data.running_data.has_data) {
                            updateElement('[data-run-score]', data.running_data.score);
                            updateElement('[data-run-level]', data.running_data.level);
                            updateElement('[data-run-emoji]', data.running_data.emoji);
                            updateElement('[data-run-reasons]', data.running_data.reasons_text);
                            const runCard = document.getElementById('run-card');
                            if (runCard) {
                                runCard.classList.remove('green', 'yellow', 'orange', 'red', 'gray');
                                runCard.classList.add(data.running_data.color);
                            }
                        }

                        // 更新警特報(含嚴重級呼吸燈與專屬圖示)
                        if (data.alert_data) {
                            const alertContainer = document.getElementById('alert-container');
                            if (alertContainer) {
                                if (data.alert_data.has_alert && data.alert_data.alerts.length > 0) {
                                    let alertsHTML = '';
                                    data.alert_data.alerts.forEach(alert => {
                                        const severeClass = alert.severe ? ' severe' : '';
                                        const icon = alert.icon || '⚠️';
                                        const badge = alert.severe ? '<span class="alert-badge">緊急</span>' : '';
                                        alertsHTML += `
                                            <div class="weather-alert alert-${alert.color}${severeClass}">
                                                <div class="alert-icon">${icon}</div>
                                                <div class="alert-content">
                                                    <div class="alert-title">${alert.phenomena}${alert.significance}${badge}</div>
                                                    <div class="alert-time">生效時間：${alert.start_time} ~ ${alert.end_time}</div>
                                                </div>
                                            </div>
                                        `;
                                    });
                                    alertContainer.innerHTML = alertsHTML;
                                    alertContainer.style.display = 'block';
                                    syncAlertAnimations();
                                } else {
                                    alertContainer.innerHTML = '';
                                    alertContainer.style.display = 'none';
                                }
                            }
                        }

                        updateElement('[data-page-time]', data.page_load_time);

                        console.log('✓ 數據更新成功', new Date().toLocaleTimeString());
                    }
                })
                .catch(error => {
                    console.error('× 更新失敗:', error);
                });
        }

        // ★★★ 12小時 PM2.5 / PM10 趨勢圖(純 SVG,零相依套件) ★★★
        function drawTrend(trend) {
            const box = document.getElementById('trend-chart');
            if (!box) return;

            const pts = (trend || []).filter(t => t && (t.pm25 !== null || t.pm10 !== null));
            if (pts.length < 2) {
                box.innerHTML = '<div class="trend-empty">趨勢資料累積中,請稍後…</div>';
                return;
            }

            // 圖表尺寸與邊界
            const W = 640, H = 190;
            const padL = 34, padR = 12, padT = 12, padB = 26;
            const plotW = W - padL - padR;
            const plotH = H - padT - padB;

            // Y 軸範圍:0 ~ 最大值*1.15(至少 20,避免低值時線貼頂)
            let maxVal = 0;
            pts.forEach(t => {
                if (t.pm25 !== null) maxVal = Math.max(maxVal, t.pm25);
                if (t.pm10 !== null) maxVal = Math.max(maxVal, t.pm10);
            });
            const yMax = Math.max(20, Math.ceil(maxVal * 1.15));

            const xPos = i => padL + (pts.length === 1 ? plotW / 2 : (i / (pts.length - 1)) * plotW);
            const yPos = v => padT + plotH - (v / yMax) * plotH;

            // 建立折線 path(遇到 null 資料點自動斷線)
            function buildPath(key) {
                let d = '', pen = false;
                pts.forEach((t, i) => {
                    const v = t[key];
                    if (v === null || v === undefined) { pen = false; return; }
                    d += (pen ? ' L ' : ' M ') + xPos(i).toFixed(1) + ' ' + yPos(v).toFixed(1);
                    pen = true;
                });
                return d;
            }

            // 資料點圓點
            function buildDots(key, color) {
                let s = '';
                pts.forEach((t, i) => {
                    const v = t[key];
                    if (v === null || v === undefined) return;
                    s += `<circle cx="${xPos(i).toFixed(1)}" cy="${yPos(v).toFixed(1)}" r="3" fill="${color}"><title>${t.time} ${key.toUpperCase()}: ${v}</title></circle>`;
                });
                return s;
            }

            // Y 軸格線(3 條)
            let grid = '';
            for (let g = 1; g <= 3; g++) {
                const val = Math.round(yMax * g / 3);
                const y = yPos(val).toFixed(1);
                grid += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#e0e0e0" stroke-width="1" stroke-dasharray="4 4"/>`;
                grid += `<text x="${padL - 6}" y="${(+y + 4)}" text-anchor="end" font-size="10" fill="#999">${val}</text>`;
            }

            // X 軸時間標籤(最多顯示 6 個,避免擁擠)
            let xLabels = '';
            const step = Math.max(1, Math.ceil(pts.length / 6));
            pts.forEach((t, i) => {
                if (i % step === 0 || i === pts.length - 1) {
                    xLabels += `<text x="${xPos(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="10" fill="#888">${t.time}</text>`;
                }
            });

            box.innerHTML = `
                <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="過去12小時 PM2.5 與 PM10 趨勢圖">
                    ${grid}
                    <path d="${buildPath('pm10')}" fill="none" stroke="#f39c12" stroke-width="2" stroke-linejoin="round"/>
                    <path d="${buildPath('pm25')}" fill="none" stroke="#e74c3c" stroke-width="2.5" stroke-linejoin="round"/>
                    ${buildDots('pm10', '#f39c12')}
                    ${buildDots('pm25', '#e74c3c')}
                </svg>
            `;
        }

        // 讓所有警報的呼吸燈/圖示/徽章從同一個時間原點開始,達成完全同步閃爍
        function syncAlertAnimations() {
            const targets = document.querySelectorAll(
                '.weather-alert.severe, .weather-alert.severe .alert-icon, .alert-badge'
            );
            targets.forEach(el => { el.style.animation = 'none'; });
            void document.body.offsetWidth; // 強制 reflow
            targets.forEach(el => { el.style.animation = ''; });
        }

        function updateElement(selector, value) {
            const el = document.querySelector(selector);
            if (el && value !== undefined && value !== null) {
                el.textContent = value;
            }
        }

        function updateChange(selector, value) {
            const el = document.querySelector(selector);
            if (el) {
                if (value !== null && value !== undefined && value !== '') {
                    el.textContent = value;
                    el.style.display = '';
                    el.className = 'data-change';
                    if (value.includes('↑')) el.className += ' up';
                    else if (value.includes('↓')) el.className += ' down';
                    else el.className += ' same';
                } else {
                    el.style.display = 'none';
                }
            }
        }

        function updateCardColor(selector, colorClass) {
            const el = document.querySelector(selector);
            if (el) {
                const card = el.closest('.data-card');
                if (card) {
                    card.classList.remove('green', 'yellow', 'orange', 'red', 'gray');
                    if (colorClass) {
                        card.classList.add(colorClass);
                    }
                }
            }
        }

        // 更新天氣項目(如舒適度)的背景顏色
        function updateWeatherItemColor(selector, colorClass) {
            const el = document.querySelector(selector);
            if (el) {
                const item = el.closest('.weather-item');
                if (item) {
                    item.classList.remove('green', 'yellow', 'orange', 'red', 'blue', 'gray');
                    if (colorClass) {
                        item.classList.add(colorClass);
                    }
                }
            }
        }

        function updateStatus(selector, statusText) {
            const el = document.querySelector(selector);
            if (el) {
                const card = el.closest('.data-card');
                if (card) {
                    const statusEl = card.querySelector('.data-status');
                    if (statusEl && statusText) {
                        statusEl.textContent = statusText;
                    }
                }
            }
        }

        // 頁面載入時:同步警報動畫 + 繪製初始趨勢圖
        window.addEventListener('load', function() {
            syncAlertAnimations();
            drawTrend(INITIAL_TREND);
        });

        setInterval(updateData, 180000);  // 每3分鐘更新一次
        setTimeout(updateData, 10000);    // 10秒後首次自動更新
    </script>
</head>
<body>
    <div class="main-container">
        <div class="weather-container">
            <h2>🌤️ 天氣預報</h2>

            <!-- 天氣警特報區域 -->
            <div class="alert-container" id="alert-container">
                {% if alerts.has_alert %}
                    {% for alert in alerts.alerts %}
                    <div class="weather-alert alert-{{ alert.color }}{% if alert.severe %} severe{% endif %}">
                        <div class="alert-icon">{{ alert.get('icon', '⚠️') }}</div>
                        <div class="alert-content">
                            <div class="alert-title">{{ alert.phenomena }}{{ alert.significance }}{% if alert.severe %}<span class="alert-badge">緊急</span>{% endif %}</div>
                            <div class="alert-time">生效時間：{{ alert.start_time }} ~ {{ alert.end_time }}</div>
                        </div>
                    </div>
                    {% endfor %}
                {% endif %}
            </div>

            <!-- ★★★ 跑步適宜度指數 ★★★ -->
            <div class="run-card {{ run.color }}" id="run-card">
                <div class="run-title">🏃 跑步適宜度指數</div>
                <div class="run-top">
                    <span class="run-score"><span data-run-score>{{ run.score }}</span><small>/100</small></span>
                    <span class="run-emoji" data-run-emoji>{{ run.emoji }}</span>
                </div>
                <div class="run-level" data-run-level>{{ run.level }}</div>
                <div class="run-reasons" data-run-reasons>{{ run.reasons_text }}</div>
            </div>

            <div class="site-info">頭份市</div>

            {% if forecast.has_data %}
            <div class="weather-desc-box"><span data-forecast-weather>{{ forecast.weather_desc }}</span></div>

            <div class="weather-grid">
                <div class="weather-item temp">
                    <span class="weather-label">🌡️ 溫度</span>
                    <span class="weather-value-large"><span data-forecast-temp>{{ forecast.temp }}</span>°C</span>
                </div>

                <div class="weather-item feels">
                    <span class="weather-label">🌡️ 體感溫度</span>
                    <span class="weather-value"><span data-forecast-feels>{{ forecast.feels_like }}</span>°C</span>
                </div>

                <div class="weather-item comfort {{ forecast.comfort_color }}">
                    <div>
                        <div class="weather-label">😊 舒適度</div>
                        <div style="font-size: 0.8em; margin-top: 5px;"><span data-forecast-comfort-desc>{{ forecast.comfort_desc }}</span> (指數 <span data-forecast-comfort>{{ forecast.comfort_index }}</span>)</div>
                    </div>
                    <span class="comfort-emoji" data-forecast-comfort-emoji>{{ forecast.comfort_emoji }}</span>
                </div>

                <div class="weather-item humidity">
                    <span class="weather-label">💧 相對濕度</span>
                    <span class="weather-value"><span data-forecast-humidity>{{ forecast.humidity }}</span>%</span>
                </div>

                <div class="weather-item pop">
                    <span class="weather-label">☔ 降雨機率</span>
                    <span class="weather-value"><span data-forecast-pop>{{ forecast.pop }}</span>%</span>
                </div>

                <div class="weather-item wind">
                    <div style="width: 100%;">
                        <div class="weather-label" style="margin-bottom: 8px;">🌬️ 風速與風向</div>
                        <div style="font-size: 1em; font-weight: bold;" data-forecast-wind>{{ forecast.wind_display }}</div>
                    </div>
                </div>
            </div>

            <div class="forecast-time">
                📅 預報時間：<span data-forecast-time>{{ forecast.forecast_time }}</span>
            </div>
            {% else %}
            <div class="error-message"><h3>⚠️ 預報資料載入中</h3></div>
            {% endif %}
        </div>

        <div class="container">
            <h1><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="50" height="50">
  <defs>
    <linearGradient id="cloudGradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#E8F4F8;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#B8D4E0;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="particleGradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#FFD93D;stop-opacity:0.8" />
      <stop offset="100%" style="stop-color:#FFA83D;stop-opacity:0.8" />
    </linearGradient>
    <filter id="shadow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="2"/>
      <feOffset dx="0" dy="2" result="offsetblur"/>
      <feComponentTransfer>
        <feFuncA type="linear" slope="0.3"/>
      </feComponentTransfer>
      <feMerge>
        <feMergeNode/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
  <g filter="url(#shadow)">
    <ellipse cx="35" cy="45" rx="18" ry="15" fill="url(#cloudGradient)"/>
    <ellipse cx="50" cy="40" rx="20" ry="18" fill="url(#cloudGradient)"/>
    <ellipse cx="65" cy="45" rx="18" ry="15" fill="url(#cloudGradient)"/>
    <rect x="25" y="45" width="50" height="15" fill="url(#cloudGradient)"/>
    <ellipse cx="30" cy="60" rx="10" ry="8" fill="url(#cloudGradient)"/>
    <ellipse cx="50" cy="62" rx="15" ry="10" fill="url(#cloudGradient)"/>
    <ellipse cx="70" cy="60" rx="10" ry="8" fill="url(#cloudGradient)"/>
  </g>
  <g opacity="0.9">
    <circle cx="25" cy="70" r="3.5" fill="url(#particleGradient)">
      <animate attributeName="cy" values="70;75;70" dur="3s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.6;1;0.6" dur="3s" repeatCount="indefinite"/>
    </circle>
    <circle cx="45" cy="75" r="4" fill="url(#particleGradient)">
      <animate attributeName="cy" values="75;80;75" dur="2.5s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.7;1;0.7" dur="2.5s" repeatCount="indefinite"/>
    </circle>
    <circle cx="65" cy="72" r="3" fill="url(#particleGradient)">
      <animate attributeName="cy" values="72;77;72" dur="2.8s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.5;0.9;0.5" dur="2.8s" repeatCount="indefinite"/>
    </circle>
    <circle cx="35" cy="78" r="2.5" fill="#FFB84D" opacity="0.7">
      <animate attributeName="cy" values="78;82;78" dur="3.2s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.4;0.8;0.4" dur="3.2s" repeatCount="indefinite"/>
    </circle>
    <circle cx="55" cy="80" r="2" fill="#FFB84D" opacity="0.6">
      <animate attributeName="cy" values="80;84;80" dur="2.7s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.3;0.7;0.3" dur="2.7s" repeatCount="indefinite"/>
    </circle>
    <circle cx="75" cy="76" r="2.5" fill="#FFCC5C" opacity="0.6">
      <animate attributeName="cy" values="76;80;76" dur="3.5s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.4;0.8;0.4" dur="3.5s" repeatCount="indefinite"/>
    </circle>
    <circle cx="20" cy="65" r="1.5" fill="#FFD93D" opacity="0.5">
      <animate attributeName="cy" values="65;68;65" dur="2.2s" repeatCount="indefinite"/>
    </circle>
    <circle cx="70" cy="68" r="1.5" fill="#FFD93D" opacity="0.5">
      <animate attributeName="cy" values="68;71;68" dur="2.9s" repeatCount="indefinite"/>
    </circle>
    <circle cx="50" cy="85" r="1.8" fill="#FFA83D" opacity="0.5">
      <animate attributeName="cy" values="85;88;85" dur="3.3s" repeatCount="indefinite"/>
    </circle>
  </g>
  <ellipse cx="45" cy="38" rx="12" ry="6" fill="white" opacity="0.4"/>
  <ellipse cx="60" cy="42" rx="8" ry="4" fill="white" opacity="0.3"/>
</svg> 空氣品質監測</h1>
            <div class="site-info">監測站點：{{ data.site_name }}</div>

            {% if data.has_data %}
            <div class="data-grid">
                <div class="data-card {{ data.aqi_color }}">
                    <div class="data-label">空氣品質指標 (AQI)</div>
                    <div class="data-value">
                        <span data-aqi>{{ data.aqi }}</span>
                        {% if data.aqi_change %}
                        <span data-aqi-change class="data-change {{ 'up' if '↑' in data.aqi_change else ('down' if '↓' in data.aqi_change else 'same') }}">{{ data.aqi_change }}</span>
                        {% else %}
                        <span data-aqi-change class="data-change" style="display:none;"></span>
                        {% endif %}
                    </div>
                    <div class="data-unit">指數</div>
                    <div class="data-status">{{ data.aqi_label }}</div>
                </div>

                <div class="data-card {{ data.pm25_avg_color }}">
                    <div class="data-label">PM2.5 平均</div>
                    <div class="data-value">
                        <span data-pm25-avg>{{ data.pm25_avg }}</span>
                        {% if data.pm25_avg_change %}
                        <span data-pm25-avg-change class="data-change {{ 'up' if '↑' in data.pm25_avg_change else ('down' if '↓' in data.pm25_avg_change else 'same') }}">{{ data.pm25_avg_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm25_avg_label }}</div>
                </div>

                <div class="data-card {{ data.pm10_avg_color }}">
                    <div class="data-label">PM10 平均</div>
                    <div class="data-value">
                        <span data-pm10-avg>{{ data.pm10_avg }}</span>
                        {% if data.pm10_avg_change %}
                        <span data-pm10-avg-change class="data-change {{ 'up' if '↑' in data.pm10_avg_change else ('down' if '↓' in data.pm10_avg_change else 'same') }}">{{ data.pm10_avg_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm10_avg_label }}</div>
                </div>

                <div class="data-card {{ data.pm25_color }}">
                    <div class="data-label">PM2.5</div>
                    <div class="data-value">
                        <span data-pm25>{{ data.pm25 }}</span>
                        {% if data.pm25_change %}
                        <span data-pm25-change class="data-change {{ 'up' if '↑' in data.pm25_change else ('down' if '↓' in data.pm25_change else 'same') }}">{{ data.pm25_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm25_label }}</div>
                </div>

                <div class="data-card {{ data.pm10_color }}">
                    <div class="data-label">PM10</div>
                    <div class="data-value">
                        <span data-pm10>{{ data.pm10 }}</span>
                        {% if data.pm10_change %}
                        <span data-pm10-change class="data-change {{ 'up' if '↑' in data.pm10_change else ('down' if '↓' in data.pm10_change else 'same') }}">{{ data.pm10_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm10_label }}</div>
                </div>

                <div class="data-card {{ data.o3_color }}">
                    <div class="data-label">臭氧 (O₃)</div>
                    <div class="data-value">
                        <span data-o3>{{ data.o3 }}</span>
                        {% if data.o3_change %}
                        <span data-o3-change class="data-change {{ 'up' if '↑' in data.o3_change else ('down' if '↓' in data.o3_change else 'same') }}">{{ data.o3_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">ppb</div>
                    <div class="data-status">{{ data.o3_label }}</div>
                </div>
            </div>

            <!-- ★★★ 過去12小時趨勢圖 ★★★ -->
            <div class="trend-container">
                <div class="trend-title">📈 過去 12 小時懸浮微粒趨勢</div>
                <div class="trend-legend">
                    <span class="dot pm25"></span>PM2.5
                    <span class="dot pm10"></span>PM10
                    <span style="margin-left:12px; color:#aaa;">(μg/m³,滑鼠移到資料點可看數值)</span>
                </div>
                <div id="trend-chart"><div class="trend-empty">趨勢圖載入中…</div></div>
            </div>

            <div class="update-info">
                <div>🖥️ 頁面載入時間：<span class="update-time" data-page-time>{{ page_load_time }}</span></div>
                <div style="margin-top: 5px;">📡 資料抓取時間：{{ data.update_time }}</div>
                {% if data.publish_time != 'N/A' %}
                <div style="margin-top: 5px;">📊 環境部發布時間：<span data-publish-time>{{ data.publish_time }}</span></div>
                {% endif %}
                <div class="refresh-note">⏱️ 資料每3分鐘自動更新</div>
            </div>
            {% else %}
            <div class="error-message">
                <h2>⚠️ 尚未取得資料</h2>
                <p style="margin-top: 10px;">請稍後重新整理頁面。</p>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if should_fetch_data():
        with fetch_lock:
            if should_fetch_data():
                fetch_air_quality_data()
                fetch_weather_forecast()
                fetch_weather_alerts()

    # ★ 每次請求都重新計算跑步指數(純記憶體運算,零成本)
    calculate_running_index()

    bg_exists = os.path.exists(BACKGROUND_IMAGE)
    page_load_time = get_taipei_time().strftime('%Y-%m-%d %H:%M:%S')

    return render_template_string(
        HTML_TEMPLATE,
        data=latest_data,
        forecast=forecast_data,
        alerts=alert_data,
        run=running_data,
        trend_json=json.dumps(latest_data.get('trend', [])),
        page_load_time=page_load_time,
        bg_image=BACKGROUND_IMAGE if bg_exists else None
    )

@app.route('/api/data')
def api_data():
    if should_fetch_data():
        with fetch_lock:
            if should_fetch_data():
                fetch_air_quality_data()
                fetch_weather_forecast()
                fetch_weather_alerts()

    # ★ 每次請求都重新計算跑步指數
    calculate_running_index()

    # last_fetch 是 datetime 物件無法直接 JSON 序列化,先淺拷貝並移除
    aqi_out = {k: v for k, v in latest_data.items() if k != 'last_fetch'}
    forecast_out = {k: v for k, v in forecast_data.items() if k != 'last_fetch'}
    alert_out = {k: v for k, v in alert_data.items() if k != 'last_fetch'}

    return {
        'success': True,
        'aqi_data': aqi_out,
        'forecast_data': forecast_out,
        'alert_data': alert_out,
        'running_data': running_data,
        'page_load_time': get_taipei_time().strftime('%Y-%m-%d %H:%M:%S')
    }

@app.route('/background')
def background():
    if os.path.exists(BACKGROUND_IMAGE):
        directory = os.path.dirname(os.path.abspath(BACKGROUND_IMAGE)) or '.'
        filename = os.path.basename(BACKGROUND_IMAGE)
        return send_from_directory(directory, filename)
    return "", 404


fetch_air_quality_data()
fetch_weather_forecast()
fetch_weather_alerts()
calculate_running_index()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
