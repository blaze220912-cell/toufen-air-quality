from flask import Flask, render_template_string, send_from_directory, jsonify
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

forecast_data = {
    'temp': 'N/A', 'feels_like': 'N/A',
    'comfort_index': 'N/A', 'comfort_desc': '無資料',
    'comfort_emoji': '❓', 'comfort_color': 'gray',
    'humidity': 'N/A', 'wind_display': 'N/A',
    'weather_desc': 'N/A', 'pop': 'N/A',
    'forecast_time': 'N/A',
    'has_data': False, 'last_fetch': None
}

fetch_lock = Lock()

AQI_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_213?format=json&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&limit=2&sort=monitordate desc"
FORECAST_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-013?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&LocationName=頭份市"

def get_taipei_time():
    return datetime.now(TAIPEI_TZ)

def get_comfort_emoji_color(desc):
    desc_lower = desc.lower() if desc else ''
    if '舒適' in desc: return '😊', 'green'
    elif '悶熱' in desc: return '😓', 'orange'
    elif '易中暑' in desc or '炎熱' in desc: return '🥵', 'red'
    elif '寒冷' in desc or '冷' in desc: return '🥶', 'blue'
    else: return '😐', 'yellow'

def fetch_weather_forecast():
    global forecast_data
    try:
        print("正在呼叫頭份預報 API...")
        response = requests.get(FORECAST_API_URL, timeout=10)
        print(f"預報 API 狀態碼: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        
        if data.get('success') == 'true' and data.get('records'):
            locations = data['records']['Locations'][0]['Location']
            if len(locations) > 0:
                location = locations[0]
                weather_elements = location['WeatherElement']
                
                temp_element = next((e for e in weather_elements if e['ElementName'] == '溫度'), None)
                feels_element = next((e for e in weather_elements if e['ElementName'] == '體感溫度'), None)
                comfort_element = next((e for e in weather_elements if e['ElementName'] == '舒適度指數'), None)
                humidity_element = next((e for e in weather_elements if e['ElementName'] == '相對濕度'), None)
                wind_speed_element = next((e for e in weather_elements if e['ElementName'] == '風速'), None)
                wind_dir_element = next((e for e in weather_elements if e['ElementName'] == '風向'), None)
                weather_element = next((e for e in weather_elements if e['ElementName'] == '天氣現象'), None)
                pop_element = next((e for e in weather_elements if e['ElementName'] == '3小時降雨機率'), None)
                
                current_time = get_taipei_time()
                temp_times = temp_element['Time'] if temp_element else []
                
                closest_index = 0
                min_diff = float('inf')
                
                for i, time_data in enumerate(temp_times):
                    try:
                        forecast_dt = datetime.strptime(time_data.get('DataTime', ''), '%Y-%m-%dT%H:%M:%S%z')
                        forecast_dt_naive = forecast_dt.replace(tzinfo=None)
                        current_time_naive = current_time.replace(tzinfo=None)
                        diff = (forecast_dt_naive - current_time_naive).total_seconds()
                        if diff >= 0 and diff < min_diff:
                            min_diff = diff
                            closest_index = i
                    except:
                        continue
                
                forecast_time = temp = feels_like = comfort_index = comfort_desc = humidity = wind_speed = wind_scale = wind_dir = weather_desc = pop = 'N/A'
                
                if temp_element and len(temp_element['Time']) > closest_index:
                    first_time = temp_element['Time'][closest_index]
                    forecast_time_raw = first_time.get('DataTime', 'N/A')
                    temp = first_time['ElementValue'][0].get('Temperature', 'N/A')
                    try:
                        dt = datetime.strptime(forecast_time_raw, '%Y-%m-%dT%H:%M:%S%z')
                        forecast_time = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        forecast_time = forecast_time_raw
                
                if feels_element and len(feels_element['Time']) > closest_index:
                    feels_like = feels_element['Time'][closest_index]['ElementValue'][0].get('ApparentTemperature', 'N/A')
                if comfort_element and len(comfort_element['Time']) > closest_index:
                    comfort_value = comfort_element['Time'][closest_index]['ElementValue'][0]
                    comfort_index = comfort_value.get('ComfortIndex', 'N/A')
                    comfort_desc = comfort_value.get('ComfortIndexDescription', '無資料')
                if humidity_element and len(humidity_element['Time']) > closest_index:
                    humidity = humidity_element['Time'][closest_index]['ElementValue'][0].get('RelativeHumidity', 'N/A')
                if wind_speed_element and len(wind_speed_element['Time']) > closest_index:
                    wind_value = wind_speed_element['Time'][closest_index]['ElementValue'][0]
                    wind_speed = wind_value.get('WindSpeed', 'N/A')
                    wind_scale = wind_value.get('BeaufortScale', 'N/A')
                if wind_dir_element and len(wind_dir_element['Time']) > closest_index:
                    wind_dir = wind_dir_element['Time'][closest_index]['ElementValue'][0].get('WindDirection', 'N/A')
                if weather_element and len(weather_element['Time']) > closest_index:
                    weather_desc = weather_element['Time'][closest_index]['ElementValue'][0].get('Weather', 'N/A')
                if pop_element and len(pop_element['Time']) > closest_index:
                    pop = pop_element['Time'][closest_index]['ElementValue'][0].get('ProbabilityOfPrecipitation', 'N/A')
                
                wind_display = f"{wind_dir} 平均風速{wind_scale}級(每秒{wind_speed}公尺)" if wind_dir != 'N/A' and wind_speed != 'N/A' and wind_scale != 'N/A' else 'N/A'
                comfort_emoji, comfort_color = get_comfort_emoji_color(comfort_desc)
                
                forecast_data = {
                    'temp': temp, 'feels_like': feels_like, 'comfort_index': comfort_index, 'comfort_desc': comfort_desc,
                    'comfort_emoji': comfort_emoji, 'comfort_color': comfort_color, 'humidity': humidity,
                    'wind_display': wind_display, 'weather_desc': weather_desc, 'pop': pop,
                    'forecast_time': forecast_time, 'has_data': True, 'last_fetch': get_taipei_time()
                }
                print(f"✓ 預報更新成功")
                return
        forecast_data['has_data'] = False
    except Exception as e:
        print(f"× 預報失敗: {e}")
        forecast_data['has_data'] = False

def fetch_air_quality_data():
    global latest_data
    try:
        print("正在呼叫 AQI 小時值 API...")
        response = requests.get(AQI_API_URL, timeout=10, verify=False)
        print(f"AQI API 狀態碼: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        
        if data.get('records') and len(data['records']) >= 2:
            records = data['records']
            records.sort(key=lambda x: x.get('monitordate', ''), reverse=True)
            current_record = records[0]
            previous_record = records[1] if len(records) > 1 else None
            
            print(f"當前: {current_record.get('monitordate')}")
            if previous_record:
                print(f"前一小時: {previous_record.get('monitordate')}")
            
            aqi = current_record.get('aqi', 'N/A')
            pm25 = current_record.get('pm2.5', 'N/A')
            pm25_avg = current_record.get('pm2.5_avg', 'N/A')
            pm10 = current_record.get('pm10', 'N/A')
            pm10_avg = current_record.get('pm10_avg', 'N/A')
            o3 = current_record.get('o3', 'N/A')
            
            def calculate_change(current, previous):
                if current == 'N/A' or current == '' or previous == 'N/A' or previous == '' or previous is None:
                    return None
                try:
                    curr_val = float(current)
                    prev_val = float(previous)
                    change = curr_val - prev_val
                    if change > 0: return f"↑ +{change:.1f}"
                    elif change < 0: return f"↓ {change:.1f}"
                    else: return "─ 0"
                except:
                    return None
            
            if previous_record:
                aqi_change = calculate_change(aqi, previous_record.get('aqi'))
                pm25_avg_change = calculate_change(pm25_avg, previous_record.get('pm2.5_avg'))
                pm10_avg_change = calculate_change(pm10_avg, previous_record.get('pm10_avg'))
                pm10_change = calculate_change(pm10, previous_record.get('pm10'))
                pm25_change = calculate_change(pm25, previous_record.get('pm2.5'))
                o3_change = calculate_change(o3, previous_record.get('o3'))
                print(f"變化: AQI {aqi_change}")
            else:
                aqi_change = pm25_avg_change = pm10_avg_change = pm10_change = pm25_change = o3_change = None
            
            def get_level_info(value, thresholds, labels):
                if value == 'N/A' or value == '': return 'gray', '無資料'
                try:
                    val = float(value)
                    if val <= thresholds[0]: return 'green', labels[0]
                    elif val <= thresholds[1]: return 'yellow', labels[1]
                    elif val <= thresholds[2]: return 'orange', labels[2]
                    else: return 'red', labels[3]
                except:
                    return 'gray', '無資料'
            
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
                'site_name': '頭份', 'publish_time': current_record.get('monitordate', 'N/A'),
                'has_data': True, 'last_fetch': get_taipei_time()
            }
            print(f"✓ AQI更新成功")
        else:
            latest_data['has_data'] = False
    except Exception as e:
        print(f"× AQI失敗: {e}")
        latest_data['has_data'] = False

def should_fetch_data():
    current_time = get_taipei_time()
    if latest_data['last_fetch'] is None or forecast_data['last_fetch'] is None:
        return True
    aqi_expired = current_time - latest_data['last_fetch'] > timedelta(minutes=5)
    forecast_expired = current_time - forecast_data['last_fetch'] > timedelta(minutes=5)
    return aqi_expired or forecast_expired
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
            min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px;
        }
        .main-container { max-width: 1400px; width: 100%; display: grid; grid-template-columns: 350px 1fr; gap: 20px; }
        .container { background: rgba(255, 255, 255, 0.95); border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); }
        h1 { text-align: center; color: #333; margin-bottom: 10px; font-size: 2.5em; }
        h2 { text-align: center; color: #333; margin-bottom: 20px; font-size: 1.8em; }
        .site-info { text-align: center; color: #666; margin-bottom: 30px; font-size: 1.1em; }
        .weather-container { background: rgba(255, 255, 255, 0.95); border-radius: 20px; padding: 30px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); }
        .weather-grid { display: grid; gap: 15px; }
        .weather-item { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; padding: 15px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; }
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
        .weather-desc-box { background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%); color: #333; padding: 15px; border-radius: 10px; text-align: center; font-size: 1.2em; font-weight: bold; margin-bottom: 15px; }
        .forecast-time { text-align: center; color: #666; font-size: 0.9em; margin-top: 15px; padding: 10px; background: #f8f9fa; border-radius: 5px; }
        .data-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .data-card { color: white; padding: 25px; border-radius: 15px; text-align: center; box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2); transition: transform 0.3s ease; }
        .data-card.green { background: linear-gradient(135deg, #00d084 0%, #00a86b 100%); }
        .data-card.yellow { background: linear-gradient(135deg, #ffd700 0%, #ffb900 100%); }
        .data-card.orange { background: linear-gradient(135deg, #ff8c00 0%, #ff6b00 100%); }
        .data-card.red { background: linear-gradient(135deg, #ff4757 0%, #e84118 100%); }
        .data-card.gray { background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%); }
        .data-card:hover { transform: translateY(-5px); }
        .data-label { font-size: 0.9em; opacity: 0.9; margin-bottom: 10px; }
        .data-value { font-size: 2.5em; font-weight: bold; margin-bottom: 5px; display: flex; align-items: center; justify-content: center; gap: 10px; }
        .data-change { font-size: 0.35em; font-weight: normal; padding: 3px 8px; border-radius: 5px; white-space: nowrap; }
        .data-change.up { color: #c0392b; background: rgba(192, 57, 43, 0.2); }
        .data-change.down { color: #27ae60; background: rgba(39, 174, 96, 0.2); }
        .data-change.same { color: #95a5a6; background: rgba(149, 165, 166, 0.2); }
        .data-unit { font-size: 0.8em; opacity: 0.8; }
        .data-status { font-size: 0.85em; margin-top: 8px; padding: 5px 10px; background: rgba(255, 255, 255, 0.2); border-radius: 15px; font-weight: 500; }
        .update-info { text-align: center; color: #666; padding: 20px; background: #f8f9fa; border-radius: 10px; margin-top: 20px; }
        .update-time { font-weight: bold; color: #667eea; }
        .refresh-note { margin-top: 10px; font-size: 0.9em; color: #888; }
        .error-message { background: #fff3cd; color: #856404; padding: 20px; border-radius: 10px; text-align: center; margin: 20px 0; border: 2px solid #ffc107; }
        @media (max-width: 1024px) { .main-container { grid-template-columns: 1fr; } }
    </style>
    <script>
        function updateData() {
            fetch('/api/data').then(response => response.json()).then(data => {
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
                    }
                    updateElement('[data-page-time]', data.page_load_time);
                }
            }).catch(error => console.error('更新失敗:', error));
        }
        function updateElement(selector, value) {
            const el = document.querySelector(selector);
            if (el && value !== undefined && value !== null) el.textContent = value;
        }
        function updateChange(selector, value) {
            const el = document.querySelector(selector);
            if (el) {
                if (value !== null && value !== undefined && value !== '') {
                    el.textContent = value; el.style.display = ''; el.className = 'data-change';
                    if (value.includes('↑')) el.className += ' up';
                    else if (value.includes('↓')) el.className += ' down';
                    else el.className += ' same';
                } else el.style.display = 'none';
            }
        }
        setInterval(updateData, 300000);
        setTimeout(updateData, 10000);
    </script>
</head>
<body>
    <div class="main-container">
        <div class="weather-container">
            <h2>🌤️ 天氣預報</h2>
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
                        <div style="font-size:0.8em;margin-top:5px;"><span data-forecast-comfort-desc>{{ forecast.comfort_desc }}</span> (指數 <span data-forecast-comfort>{{ forecast.comfort_index }}</span>)</div>
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
                    <div style="width:100%;">
                        <div class="weather-label" style="margin-bottom:8px;">🌬️ 風速與風向</div>
                        <div style="font-size:1em;font-weight:bold;" data-forecast-wind>{{ forecast.wind_display }}</div>
                    </div>
                </div>
            </div>
            <div class="forecast-time">📅 預報時間：<span data-forecast-time>{{ forecast.forecast_time }}</span></div>
            {% else %}
            <div class="error-message"><h3>⚠️ 預報資料載入中</h3></div>
            {% endif %}
        </div>
    <div class="container">
            <h1>🌫️ 空氣品質監測</h1>
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
                        {% else %}
                        <span data-pm25-avg-change class="data-change" style="display:none;"></span>
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
                        {% else %}
                        <span data-pm10-avg-change class="data-change" style="display:none;"></span>
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
                        {% else %}
                        <span data-pm25-change class="data-change" style="display:none;"></span>
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
                        {% else %}
                        <span data-pm10-change class="data-change" style="display:none;"></span>
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
                        {% else %}
                        <span data-o3-change class="data-change" style="display:none;"></span>
                        {% endif %}
                    </div>
                    <div class="data-unit">ppb</div>
                    <div class="data-status">{{ data.o3_label }}</div>
                </div>
            </div>
            <div class="update-info">
                <div>🖥️ 頁面載入時間：<span class="update-time" data-page-time>{{ page_load_time }}</span></div>
                <div style="margin-top:5px;">📡 資料抓取時間：{{ data.update_time }}</div>
                {% if data.publish_time != 'N/A' %}
                <div style="margin-top:5px;">📊 環境部發布時間：<span data-publish-time>{{ data.publish_time }}</span></div>
                {% endif %}
                <div class="refresh-note">⏱️ 資料每5分鐘自動更新</div>
            </div>
            {% else %}
            <div class="error-message">
                <h2>⚠️ 尚未取得資料</h2>
                <p style="margin-top:10px;">請稍後重新整理頁面。</p>
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
    bg_exists = os.path.exists(BACKGROUND_IMAGE)
    page_load_time = get_taipei_time().strftime('%Y-%m-%d %H:%M:%S')
    return render_template_string(HTML_TEMPLATE, data=latest_data, forecast=forecast_data, page_load_time=page_load_time, bg_image=BACKGROUND_IMAGE if bg_exists else None)

@app.route('/api/data')
def api_data():
    if should_fetch_data():
        with fetch_lock:
            if should_fetch_data():
                fetch_air_quality_data()
                fetch_weather_forecast()
    return jsonify({'success': True, 'aqi_data': latest_data, 'forecast_data': forecast_data, 'page_load_time': get_taipei_time().strftime('%Y-%m-%d %H:%M:%S')})

@app.route('/background')
def background():
    if os.path.exists(BACKGROUND_IMAGE):
        directory = os.path.dirname(os.path.abspath(BACKGROUND_IMAGE)) or '.'
        filename = os.path.basename(BACKGROUND_IMAGE)
        return send_from_directory(directory, filename)
    return "", 404

fetch_air_quality_data()
fetch_weather_forecast()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
