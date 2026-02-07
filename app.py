from flask import Flask, render_template_string, send_from_directory
import requests
from datetime import datetime, timedelta, timezone
from threading import Lock
import urllib3
import os
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
TAIPEI_TZ = timezone(timedelta(hours=8))
BACKGROUND_IMAGE = "background.jpg"

# 空氣品質數據(右側 - 保留原樣)
latest_data = {
    'aqi': 'N/A', 'pm25_avg': 'N/A', 'pm10_avg': 'N/A',
    'pm10': 'N/A', 'pm25': 'N/A', 'o3': 'N/A',
    'update_time': '尚未更新', 'site_name': '頭份',
    'publish_time': 'N/A', 'has_data': False, 'last_fetch': None
}

# 天氣預報數據(左側 - 修改為預報)
forecast_data = {
    'temp': 'N/A', 'feels_like': 'N/A',
    'comfort_index': 'N/A', 'comfort_desc': '無資料',
    'comfort_emoji': '❓', 'comfort_color': 'gray',
    'humidity': 'N/A', 'wind_display': 'N/A',
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

fetch_lock = Lock()

AQI_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432?format=json&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&filters=SiteName,EQ,頭份"
AQI_HOURLY_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_213?language=en&limit=12&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8"
FORECAST_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-013?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&LocationName=頭份市"
WEATHER_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-001?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&locationName=苗栗縣"
COLD_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-004?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&CountyName=%E8%8B%97%E6%A0%97%E7%B8%A3&expires=true"
HEAT_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-005?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&CountyName=%E8%8B%97%E6%A0%97%E7%B8%A3&expires=true"
TYPHOON_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&expires=true"
RAIN_ALERT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-003?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&CountyName=%E8%8B%97%E6%A0%97%E7%B8%A3&expires=true"

def get_taipei_time():
    return datetime.now(TAIPEI_TZ)

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
                        'weather_desc': weather_desc,
                        'pop': rain_prob,
                        'forecast_time': forecast_time_display,
                        'has_data': True,
                        'last_fetch': get_taipei_time()
                    }
                    
                    print(f"✓ 預報數據更新成功")
                    print(f"  溫度: {temp}°C, 舒適度: {comfort_desc}")
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
                                'start_time': start_time,
                                'end_time': end_time,
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
                    records = data_rain['records'].get('record', [])
                    
                    if len(records) > 0:
                        for record in records:
                            hazard_name = record.get('hazardName', 'N/A')
                            title = record.get('title', 'N/A')
                            issue_time = record.get('issueTime', 'N/A')
                            expire_time = record.get('expireTime', 'N/A')
                            
                            # 豪大雨特報顏色判斷
                            alert_color = 'orange'
                            if '豪雨' in hazard_name or '豪雨' in title or '紅色' in title:
                                alert_color = 'red'
                            elif '大雨' in hazard_name or '大雨' in title or '橙色' in title:
                                alert_color = 'orange'
                            elif '黃色' in title:
                                alert_color = 'yellow'
                            
                            alerts_list.append({
                                'phenomena': hazard_name,
                                'significance': title,
                                'start_time': issue_time,
                                'end_time': expire_time,
                                'color': alert_color
                            })
                            print(f"  ⚠️ 豪大雨特報：{hazard_name} {title}")
                    else:
                        print(f"  ✓ 目前無豪大雨特報")
        except Exception as e:
            print(f"  × 豪大雨特報 API 錯誤: {e}")
            
        # 3. 低溫特報 (W-C0033-004)
        try:
            response2 = requests.get(COLD_ALERT_API_URL, timeout=10)
            print(f"低溫特報 API 狀態碼: {response2.status_code}")
            
            if response2.status_code == 200:
                data2 = response2.json()
                print(f"  🔍 API success 欄位: {data2.get('success')}")
                print(f"  🔍 API records 欄位: {data2.get('records')}")
                
                if data2.get('success') == 'true' and data2.get('records'):
                    records = data2['records'].get('record', [])
                    print(f"  🔍 record 欄位找到: {len(records)} 筆")
                    
                    # 如果 record 是空的，看看 records 裡面還有什麼
                    if len(records) == 0:
                        print(f"  🔍 完整 records 內容: {data2['records']}")
                    
                    if len(records) > 0:
                        for record in records:
                            print(f"  🔍 記錄內容: {record}")
                            
                            hazard_name = record.get('hazardName', 'N/A')
                            title = record.get('title', 'N/A')
                            issue_time = record.get('issueTime', 'N/A')
                            expire_time = record.get('expireTime', 'N/A')
                            
                            alert_color = 'blue'
                            if '橙色' in title or '嚴寒' in title:
                                alert_color = 'orange'
                            elif '黃色' in title:
                                alert_color = 'yellow'
                            
                            alerts_list.append({
                                'phenomena': hazard_name,
                                'significance': title,
                                'start_time': issue_time,
                                'end_time': expire_time,
                                'color': alert_color
                            })
                            print(f"  ⚠️ 低溫特報：{hazard_name} {title}")
                    else:
                        print(f"  ✓ 目前無低溫特報")
                else:
                    print(f"  ⚠️ API 回傳格式不符預期")
        except Exception as e:
            print(f"  × 低溫特報 API 錯誤: {e}")
            import traceback
            traceback.print_exc()
        
        # 3. 颱風警報 (W-C0034-001)
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
                                'start_time': issue_time,
                                'end_time': expire_time,
                                'color': alert_color
                            })
                            print(f"  🌀 颱風警報：{hazard_name} {title}")
                    else:
                        print(f"  ✓ 目前無颱風警報")
        except Exception as e:
            print(f"  × 颱風警報 API 錯誤: {e}")
        
        # 4. 高溫特報 (W-C0033-005)
        try:
            response4 = requests.get(HEAT_ALERT_API_URL, timeout=10)
            print(f"高溫特報 API 狀態碼: {response4.status_code}")
            
            if response4.status_code == 200:
                data4 = response4.json()
                if data4.get('success') == 'true' and data4.get('records'):
                    records = data4['records'].get('record', [])
                    
                    if len(records) > 0:
                        for record in records:
                            hazard_name = record.get('hazardName', 'N/A')
                            title = record.get('title', 'N/A')
                            issue_time = record.get('issueTime', 'N/A')
                            expire_time = record.get('expireTime', 'N/A')
                            
                            # 高溫特報顏色判斷
                            alert_color = 'orange'
                            if '紅色' in title or '極端' in title:
                                alert_color = 'red'
                            elif '橙色' in title:
                                alert_color = 'orange'
                            elif '黃色' in title:
                                alert_color = 'yellow'
                            
                            alerts_list.append({
                                'phenomena': hazard_name,
                                'significance': title,
                                'start_time': issue_time,
                                'end_time': expire_time,
                                'color': alert_color
                            })
                            print(f"  🌡️ 高溫特報：{hazard_name} {title}")
                    else:
                        print(f"  ✓ 目前無高溫特報")
        except Exception as e:
            print(f"  × 高溫特報 API 錯誤: {e}")
        
        # 5. 更新全域資料
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
        
        # 1. 先呼叫小時值 API，取得過去兩小時的測項數據
        print(f"  → 呼叫小時值 API (取過去兩小時數據)...")
        hourly_response = requests.get(AQI_HOURLY_API_URL, timeout=10, verify=False)
        print(f"  → 小時值 API 狀態碼: {hourly_response.status_code}")
        
        previous_hour_data = None
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
                
                # 排序取得最新兩個小時
                sorted_dates = sorted(grouped_data.keys(), reverse=True)
                print(f"  ✓ 找到 {len(sorted_dates)} 個不同時間點: {sorted_dates[:2]}")
                
                if len(sorted_dates) >= 2:
                    latest_hour = sorted_dates[0]
                    previous_hour = sorted_dates[1]
                    previous_hour_data = grouped_data[previous_hour]
                    print(f"  ✓ 前一小時數據: {previous_hour}")
                    print(f"  🔍 前一小時測項: {list(previous_hour_data.keys())}")
                elif len(sorted_dates) == 1:
                    print(f"  ⚠️ 只有1個時間點的數據，無法計算變化量")
                else:
                    print(f"  ⚠️ 無有效數據")
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
                'last_fetch': get_taipei_time()
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
            animation: shake 0.5s ease-in-out infinite;
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
        @keyframes shake {
            0%, 100% { transform: rotate(0deg); }
            25% { transform: rotate(-5deg); }
            75% { transform: rotate(5deg); }
        }
        
        @media (max-width: 1024px) {
            .main-container { grid-template-columns: 1fr; }
        }
    </style>
    <script>
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

                            // ★★★ 新增這行：修復舒適度背景顏色即時更新 ★★★
                            updateWeatherItemColor('[data-forecast-comfort-desc]', data.forecast_data.comfort_color);
                        }
                        
                        // 更新警特報
                        if (data.alert_data) {
                            const alertContainer = document.getElementById('alert-container');
                            if (alertContainer) {
                                if (data.alert_data.has_alert && data.alert_data.alerts.length > 0) {
                                    let alertsHTML = '';
                                    data.alert_data.alerts.forEach(alert => {
                                        alertsHTML += `
                                            <div class="weather-alert alert-${alert.color}">
                                                <div class="alert-icon">⚠️</div>
                                                <div class="alert-content">
                                                    <div class="alert-title">${alert.phenomena}${alert.significance}</div>
                                                    <div class="alert-time">生效時間：${alert.start_time} ~ ${alert.end_time}</div>
                                                </div>
                                            </div>
                                        `;
                                    });
                                    alertContainer.innerHTML = alertsHTML;
                                    alertContainer.style.display = 'block';
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

        // ★★★ 新增這段：更新天氣項目(如舒適度)的背景顏色 ★★★
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
                    <div class="weather-alert alert-{{ alert.color }}">
                        <div class="alert-icon">⚠️</div>
                        <div class="alert-content">
                            <div class="alert-title">{{ alert.phenomena }}{{ alert.significance }}</div>
                            <div class="alert-time">生效時間：{{ alert.start_time }} ~ {{ alert.end_time }}</div>
                        </div>
                    </div>
                    {% endfor %}
                {% endif %}
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
    
    bg_exists = os.path.exists(BACKGROUND_IMAGE)
    page_load_time = get_taipei_time().strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template_string(
        HTML_TEMPLATE, 
        data=latest_data,
        forecast=forecast_data,
        alerts=alert_data,
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
    
    return {
        'success': True,
        'aqi_data': latest_data,
        'forecast_data': forecast_data,
        'alert_data': alert_data,
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)











