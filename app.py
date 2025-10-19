from flask import Flask, render_template_string, send_from_directory
import requests
from datetime import datetime, timedelta, timezone
from threading import Lock
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
TAIPEI_TZ = timezone(timedelta(hours=8))
BACKGROUND_IMAGE = "background.jpg"

latest_data = {
    'aqi': 'N/A', 'pm25_avg': 'N/A', 'pm10_avg': 'N/A',
    'pm10': 'N/A', 'pm25': 'N/A', 'o3': 'N/A',
    'update_time': '尚未更新', 'site_name': '頭份',
    'publish_time': 'N/A', 'has_data': False, 'last_fetch': None
}

previous_data = {
    'aqi': None, 'pm25_avg': None, 'pm10_avg': None,
    'pm10': None, 'pm25': None, 'o3': None
}

weather_data = {
    'temp': 'N/A', 'temp_max': 'N/A', 'temp_min': 'N/A',
    'feels_like': 'N/A', 'humidity': 'N/A', 'pop': 'N/A',
    'weather_desc': 'N/A', 'wind_speed': 'N/A', 'wind_dir': 'N/A',
    'uvi': 'N/A', 'has_data': False, 'last_fetch': None
}

fetch_lock = Lock()

AQI_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432?format=json&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&filters=SiteName,EQ,頭份"
WEATHER_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&StationId=C0E730"
UVI_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0005-001?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&StationName=新竹"

def get_taipei_time():
    return datetime.now(TAIPEI_TZ)

def fetch_air_quality_data():
    global latest_data, previous_data
    try:
        response = requests.get(AQI_API_URL, timeout=10, verify=False)
        data = response.json()
        
        if data.get('records'):
            records = data['records']
            valid_records = [r for r in records if r.get('publishtime')]
            record = valid_records[0] if valid_records else records[0]
            
            aqi = record.get('aqi', 'N/A')
            pm25 = record.get('pm2.5', 'N/A')
            pm25_avg = record.get('pm2.5_avg', 'N/A')
            pm10 = record.get('pm10', 'N/A')
            pm10_avg = record.get('pm10_avg', 'N/A')
            o3 = record.get('o3', 'N/A')
            
            def calculate_change(current, previous):
                if current == 'N/A' or current == '' or previous is None:
                    return None
                try:
                    curr_val, prev_val = float(current), float(previous)
                    change = curr_val - prev_val
                    if change > 0: return f"↑ +{change:.1f}"
                    elif change < 0: return f"↓ {change:.1f}"
                    else: return "─ 0"
                except: return None
            
            def get_level_info(value, thresholds, labels):
                if value == 'N/A' or value == '': return 'gray', '無資料'
                try:
                    val = float(value)
                    if val <= thresholds[0]: return 'green', labels[0]
                    elif val <= thresholds[1]: return 'yellow', labels[1]
                    elif val <= thresholds[2]: return 'orange', labels[2]
                    else: return 'red', labels[3]
                except: return 'gray', '無資料'
            
            aqi_change = calculate_change(aqi, previous_data['aqi'])
            pm25_avg_change = calculate_change(pm25_avg, previous_data['pm25_avg'])
            pm10_avg_change = calculate_change(pm10_avg, previous_data['pm10_avg'])
            pm10_change = calculate_change(pm10, previous_data['pm10'])
            pm25_change = calculate_change(pm25, previous_data['pm25'])
            o3_change = calculate_change(o3, previous_data['o3'])
            
            try:
                previous_data['aqi'] = float(aqi) if aqi != 'N/A' else previous_data['aqi']
                previous_data['pm25_avg'] = float(pm25_avg) if pm25_avg != 'N/A' else previous_data['pm25_avg']
                previous_data['pm10_avg'] = float(pm10_avg) if pm10_avg != 'N/A' else previous_data['pm10_avg']
                previous_data['pm10'] = float(pm10) if pm10 != 'N/A' else previous_data['pm10']
                previous_data['pm25'] = float(pm25) if pm25 != 'N/A' else previous_data['pm25']
                previous_data['o3'] = float(o3) if o3 != 'N/A' else previous_data['o3']
            except: pass
            
            aqi_color, aqi_label = get_level_info(aqi, [50, 100, 150], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm25_avg_color, pm25_avg_label = get_level_info(pm25_avg, [15.4, 35.4, 54.4], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm10_avg_color, pm10_avg_label = get_level_info(pm10_avg, [54, 125, 254], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm10_color, pm10_label = get_level_info(pm10, [54, 125, 254], ['良好', '普通', '對敏感族群不健康', '不健康'])
            pm25_color, pm25_label = get_level_info(pm25, [15.4, 35.4, 54.4], ['良好', '普通', '對敏感族群不健康', '不健康'])
            o3_color, o3_label = get_level_info(o3, [54, 70, 85], ['良好', '普通', '對敏感族群不健康', '不健康'])
            
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
                'has_data': True, 'last_fetch': get_taipei_time()
            }
        else:
            latest_data['has_data'] = False
    except Exception as e:
        print(f"AQI錯誤: {e}")
        latest_data['has_data'] = False

def fetch_weather_data():
    global weather_data
    try:
        print(f"正在呼叫頭份觀測站 API...")
        
        # 抓取頭份觀測站即時資料
        response = requests.get(WEATHER_API_URL, timeout=10)
        print(f"觀測站 API 狀態碼: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        
        # 檢查回應
        print(f"API success 值: {data.get('success')}")
        print(f"有 records: {bool(data.get('records'))}")
        
        # 抓取新竹 UVI
        try:
            uvi_response = requests.get(UVI_API_URL, timeout=10)
            uvi_data = uvi_response.json()
        except:
            uvi_data = {}
        
        # 修正：success 是字串，且要檢查 records
        if data.get('success') == 'true' and 'records' in data:
            records = data.get('records', {})
            stations = records.get('Station', [])
            
            print(f"找到 {len(stations)} 個觀測站")
            
            if len(stations) > 0:
                station = stations[0]
                print(f"測站名稱: {station.get('StationName')}")
                
                obs_time = station.get('ObsTime', {}).get('DateTime', 'N/A')
                weather_element = station.get('WeatherElement', {})
                
                # 取得各項氣象觀測資料
                temp = weather_element.get('AirTemperature', 'N/A')
                humidity = weather_element.get('RelativeHumidity', 'N/A')
                wind_speed = weather_element.get('WindSpeed', 'N/A')
                wind_dir = weather_element.get('WindDirection', 'N/A')
                weather_desc = weather_element.get('Weather', '觀測中')
                
                # 取得當日最高/最低溫
                daily_extreme = weather_element.get('DailyExtreme', {})
                daily_high_info = daily_extreme.get('DailyHigh', {}).get('TemperatureInfo', {})
                daily_low_info = daily_extreme.get('DailyLow', {}).get('TemperatureInfo', {})
                daily_high = daily_high_info.get('AirTemperature', 'N/A')
                daily_low = daily_low_info.get('AirTemperature', 'N/A')
                
                # 取得降雨量
                now_info = weather_element.get('Now', {})
                precipitation = now_info.get('Precipitation', 'N/A')
                
                # 風向轉換（度數轉方位）
                def degree_to_direction(degree):
                    if degree == 'N/A' or degree == '-99' or degree == -99:
                        return 'N/A'
                    try:
                        deg = float(degree)
                        directions = ['北', '北北東', '東北', '東北東', '東', '東南東', '東南', '南南東',
                                    '南', '南南西', '西南', '西南西', '西', '西北西', '西北', '北北西']
                        index = round(deg / 22.5) % 16
                        return directions[index]
                    except:
                        return 'N/A'
                
                wind_dir_text = degree_to_direction(wind_dir)
                
                # 取得 UVI（新竹測站 - O-A0003-001）
                uvi = 'N/A'
                uvi_level = '無資料'
                uvi_color = 'gray'
                
                if uvi_data.get('success') == 'true' and uvi_data.get('records'):
                    uvi_stations = uvi_data['records'].get('Station', [])
                    for uvi_station in uvi_stations:
                        station_name = uvi_station.get('StationName', '')
                        station_id = uvi_station.get('StationId', '')
                        if '新竹' in station_name or station_id == '467571':
                            weather_element = uvi_station.get('WeatherElement', {})
                            uvi_value = weather_element.get('UVIndex', 'N/A')
                            
                            if uvi_value and uvi_value != '-99' and uvi_value != 'N/A':
                                try:
                                    uvi_num = float(uvi_value)
                                    uvi = str(uvi_num)
                                    
                                    # UVI 分級
                                    if uvi_num <= 2:
                                        uvi_level = '低量級'
                                        uvi_color = 'green'
                                    elif uvi_num <= 5:
                                        uvi_level = '中量級'
                                        uvi_color = 'yellow'
                                    elif uvi_num <= 7:
                                        uvi_level = '高量級'
                                        uvi_color = 'orange'
                                    elif uvi_num <= 10:
                                        uvi_level = '過量級'
                                        uvi_color = 'red'
                                    else:
                                        uvi_level = '危險級'
                                        uvi_color = 'purple'
                                except:
                                    pass
                            break
                
                weather_data = {
                    'temp': temp,
                    'temp_max': daily_high,
                    'temp_min': daily_low,
                    'feels_like': temp,
                    'humidity': humidity,
                    'pop': precipitation,
                    'weather_desc': weather_desc,
                    'wind_speed': wind_speed,
                    'wind_dir': wind_dir_text,
                    'uvi': uvi,
                    'uvi_level': uvi_level,
                    'uvi_color': uvi_color,
                    'has_data': True,
                    'last_fetch': get_taipei_time()
                }
                print(f"✓ 頭份觀測站數據更新成功")
                print(f"  溫度: {temp}°C, 濕度: {humidity}%, 天氣: {weather_desc}")
                return
            else:
                print("× 沒有找到觀測站資料")
        else:
            print(f"× API 回應檢查失敗")
            print(f"  success={data.get('success')}, records存在={bool(data.get('records'))}")
        
        weather_data['has_data'] = False
        
    except requests.exceptions.RequestException as e:
        print(f"× 觀測站 API 請求錯誤: {e}")
        weather_data['has_data'] = False
    except Exception as e:
        print(f"× 觀測站數據解析錯誤: {e}")
        import traceback
        traceback.print_exc()
        weather_data['has_data'] = False
                    'has_data': True,
                    'last_fetch': get_taipei_time()
                }
                print(f"✓ 頭份觀測站數據更新成功")
                print(f"  溫度: {temp}°C, 濕度: {humidity}%, 天氣: {weather_desc}")
                return
            else:
                print("× 沒有找到觀測站資料")
        else:
            print(f"× API 回應檢查失敗")
            print(f"  success={data.get('success')}, records存在={bool(data.get('records'))}")
        
        weather_data['has_data'] = False
        
    except requests.exceptions.RequestException as e:
        print(f"× 觀測站 API 請求錯誤: {e}")
        weather_data['has_data'] = False
    except Exception as e:
        print(f"× 觀測站數據解析錯誤: {e}")
        import traceback
        traceback.print_exc()
        weather_data['has_data'] = False
def should_fetch_data():
    if latest_data['last_fetch'] is None or weather_data['last_fetch'] is None:
        return True
    return get_taipei_time() - latest_data['last_fetch'] > timedelta(minutes=5)

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
        .weather-item.humidity { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .weather-item.rain { background: linear-gradient(135deg, #00c6ff 0%, #0072ff 100%); }
        .weather-item.wind { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        .weather-item.uvi { background: linear-gradient(135deg, #ffd89b 0%, #ff6b6b 100%); }
        .weather-label { font-size: 0.9em; opacity: 0.9; }
        .weather-value { font-size: 1.5em; font-weight: bold; }
        .temp-display {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            margin-bottom: 15px;
        }
        .temp-main { font-size: 3em; font-weight: bold; }
        .temp-range { font-size: 1em; margin-top: 10px; opacity: 0.9; }
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
            transition: transform 0.3s ease;
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
        .data-change.up { color: #c0392b; background: rgba(192, 57, 43, 0.2); }
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
        
        @media (max-width: 1024px) {
            .main-container { grid-template-columns: 1fr; }
        }
    </style>
    <script>
        setTimeout(function() { location.reload(); }, 240000);
    </script>
</head>
<body>
    <div class="main-container">
        <div class="weather-container">
            <h2>🌤️ 天氣概況</h2>
            <div class="site-info">頭份市</div>
            
            {% if weather.has_data %}
            <div class="weather-desc-box">{{ weather.weather_desc }}</div>
            
            <div class="temp-display">
                <div class="temp-main">{{ weather.temp }}°C</div>
                <div class="temp-range">↑ {{ weather.temp_max }}°C / ↓ {{ weather.temp_min }}°C</div>
            </div>
            
            <div class="weather-grid">
                <div class="weather-item">
                    <span class="weather-label">體感溫度</span>
                    <span class="weather-value">{{ weather.feels_like }}°C</span>
                </div>
                <div class="weather-item humidity">
                    <span class="weather-label">相對濕度</span>
                    <span class="weather-value">{{ weather.humidity }}%</span>
                </div>
                <div class="weather-item rain">
                    <span class="weather-label">降雨量</span>
                    <span class="weather-value">{{ weather.pop }} mm</span>
                </div>
                <div class="weather-item wind">
                    <span class="weather-label">風速 ({{ weather.wind_dir }})</span>
                    <span class="weather-value">{{ weather.wind_speed }} m/s</span>
                </div>
                <div class="weather-item uvi">
                    <span class="weather-label">紫外線 (新竹)</span>
                    <span class="weather-value">{{ weather.uvi }}</span>
                </div>
            </div>
            {% else %}
            <div class="error-message"><h3>⚠️ 天氣資料載入中</h3></div>
            {% endif %}
        </div>
        
        <div class="container">
            <h1>🌤️ 空氣品質監測</h1>
            <div class="site-info">監測站點：{{ data.site_name }}</div>
            
            {% if data.has_data %}
            <div class="data-grid">
                <div class="data-card {{ data.aqi_color }}">
                    <div class="data-label">空氣品質指標 (AQI)</div>
                    <div class="data-value">
                        <span>{{ data.aqi }}</span>
                        {% if data.aqi_change %}
                        <span class="data-change {{ 'up' if '↑' in data.aqi_change else ('down' if '↓' in data.aqi_change else 'same') }}">{{ data.aqi_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">指數</div>
                    <div class="data-status">{{ data.aqi_label }}</div>
                </div>
                
                <div class="data-card {{ data.pm25_avg_color }}">
                    <div class="data-label">PM2.5 平均</div>
                    <div class="data-value">
                        <span>{{ data.pm25_avg }}</span>
                        {% if data.pm25_avg_change %}
                        <span class="data-change {{ 'up' if '↑' in data.pm25_avg_change else ('down' if '↓' in data.pm25_avg_change else 'same') }}">{{ data.pm25_avg_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm25_avg_label }}</div>
                </div>
                
                <div class="data-card {{ data.pm10_avg_color }}">
                    <div class="data-label">PM10 平均</div>
                    <div class="data-value">
                        <span>{{ data.pm10_avg }}</span>
                        {% if data.pm10_avg_change %}
                        <span class="data-change {{ 'up' if '↑' in data.pm10_avg_change else ('down' if '↓' in data.pm10_avg_change else 'same') }}">{{ data.pm10_avg_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm10_avg_label }}</div>
                </div>
                
                <div class="data-card {{ data.pm25_color }}">
                    <div class="data-label">PM2.5</div>
                    <div class="data-value">
                        <span>{{ data.pm25 }}</span>
                        {% if data.pm25_change %}
                        <span class="data-change {{ 'up' if '↑' in data.pm25_change else ('down' if '↓' in data.pm25_change else 'same') }}">{{ data.pm25_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm25_label }}</div>
                </div>
                
                <div class="data-card {{ data.pm10_color }}">
                    <div class="data-label">PM10</div>
                    <div class="data-value">
                        <span>{{ data.pm10 }}</span>
                        {% if data.pm10_change %}
                        <span class="data-change {{ 'up' if '↑' in data.pm10_change else ('down' if '↓' in data.pm10_change else 'same') }}">{{ data.pm10_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">μg/m³</div>
                    <div class="data-status">{{ data.pm10_label }}</div>
                </div>
                
                <div class="data-card {{ data.o3_color }}">
                    <div class="data-label">臭氧 (O₃)</div>
                    <div class="data-value">
                        <span>{{ data.o3 }}</span>
                        {% if data.o3_change %}
                        <span class="data-change {{ 'up' if '↑' in data.o3_change else ('down' if '↓' in data.o3_change else 'same') }}">{{ data.o3_change }}</span>
                        {% endif %}
                    </div>
                    <div class="data-unit">ppb</div>
                    <div class="data-status">{{ data.o3_label }}</div>
                </div>
            </div>
            
            <div class="update-info">
                <div>🖥️ 頁面載入時間：<span class="update-time">{{ page_load_time }}</span></div>
                <div style="margin-top: 5px;">📡 資料抓取時間：{{ data.update_time }}</div>
                {% if data.publish_time != 'N/A' %}
                <div style="margin-top: 5px;">📊 環境部發布時間：{{ data.publish_time }}</div>
                {% endif %}
                <div class="refresh-note">⏱️ 資料每5分鐘檢查更新 | 頁面每4分鐘自動刷新</div>
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
                fetch_weather_data()
    
    bg_exists = os.path.exists(BACKGROUND_IMAGE)
    page_load_time = get_taipei_time().strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template_string(
        HTML_TEMPLATE, 
        data=latest_data,
        weather=weather_data,
        page_load_time=page_load_time,
        bg_image=BACKGROUND_IMAGE if bg_exists else None
    )

@app.route('/background')
def background():
    if os.path.exists(BACKGROUND_IMAGE):
        directory = os.path.dirname(os.path.abspath(BACKGROUND_IMAGE)) or '.'
        filename = os.path.basename(BACKGROUND_IMAGE)
        return send_from_directory(directory, filename)
    return "", 404

fetch_air_quality_data()
fetch_weather_data()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)






