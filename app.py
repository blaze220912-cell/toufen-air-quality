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

latest_data = {'aqi': 'N/A', 'pm25_avg': 'N/A', 'pm10_avg': 'N/A', 'pm10': 'N/A', 'pm25': 'N/A', 'o3': 'N/A', 'update_time': '尚未更新', 'site_name': '頭份', 'publish_time': 'N/A', 'has_data': False, 'last_fetch': None}
forecast_data = {'temp': 'N/A', 'feels_like': 'N/A', 'comfort_index': 'N/A', 'comfort_desc': '無資料', 'comfort_emoji': '❓', 'comfort_color': 'gray', 'humidity': 'N/A', 'wind_display': 'N/A', 'weather_desc': 'N/A', 'pop': 'N/A', 'forecast_time': 'N/A', 'has_data': False, 'last_fetch': None}
fetch_lock = Lock()

AQI_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_213?format=json&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&limit=2&sort=monitordate desc"
FORECAST_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-013?Authorization=CWA-BC6838CC-5D26-43CD-B524-8A522B534959&LocationName=頭份市"

def get_taipei_time():
    return datetime.now(TAIPEI_TZ)

def get_comfort_emoji_color(desc):
    if '舒適' in desc: return '😊', 'green'
    elif '悶熱' in desc: return '😓', 'orange'
    elif '易中暑' in desc or '炎熱' in desc: return '🥵', 'red'
    elif '寒冷' in desc or '冷' in desc: return '🥶', 'blue'
    else: return '😐', 'yellow'

def fetch_weather_forecast():
    global forecast_data
    try:
        response = requests.get(FORECAST_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('success') == 'true' and data.get('records'):
            location = data['records']['Locations'][0]['Location'][0]
            elements = location['WeatherElement']
            current_time = get_taipei_time()
            temp_element = next((e for e in elements if e['ElementName'] == '溫度'), None)
            temp_times = temp_element['Time'] if temp_element else []
            closest_index = 0
            min_diff = float('inf')
            for i, time_data in enumerate(temp_times):
                try:
                    forecast_dt = datetime.strptime(time_data.get('DataTime', ''), '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                    diff = (forecast_dt - current_time.replace(tzinfo=None)).total_seconds()
                    if diff >= 0 and diff < min_diff:
                        min_diff = diff
                        closest_index = i
                except: continue
            temp = feels_like = comfort_index = comfort_desc = humidity = wind_speed = wind_scale = wind_dir = weather_desc = pop = forecast_time = 'N/A'
            if temp_element and len(temp_element['Time']) > closest_index:
                first_time = temp_element['Time'][closest_index]
                try:
                    forecast_time = datetime.strptime(first_time.get('DataTime', ''), '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M')
                except: pass
                temp = first_time['ElementValue'][0].get('Temperature', 'N/A')
            for elem_name, key in [('體感溫度', 'feels_like'), ('舒適度指數', 'comfort'), ('相對濕度', 'humidity'), ('風速', 'wind'), ('風向', 'wind_dir'), ('天氣現象', 'weather'), ('3小時降雨機率', 'pop')]:
                element = next((e for e in elements if e['ElementName'] == elem_name), None)
                if element and len(element['Time']) > closest_index:
                    val = element['Time'][closest_index]['ElementValue'][0]
                    if key == 'feels_like': feels_like = val.get('ApparentTemperature', 'N/A')
                    elif key == 'comfort': comfort_index = val.get('ComfortIndex', 'N/A'); comfort_desc = val.get('ComfortIndexDescription', '無資料')
                    elif key == 'humidity': humidity = val.get('RelativeHumidity', 'N/A')
                    elif key == 'wind': wind_speed = val.get('WindSpeed', 'N/A'); wind_scale = val.get('BeaufortScale', 'N/A')
                    elif key == 'wind_dir': wind_dir = val.get('WindDirection', 'N/A')
                    elif key == 'weather': weather_desc = val.get('Weather', 'N/A')
                    elif key == 'pop': pop = val.get('ProbabilityOfPrecipitation', 'N/A')
            wind_display = f"{wind_dir} 平均風速{wind_scale}級(每秒{wind_speed}公尺)" if all(x != 'N/A' for x in [wind_dir, wind_speed, wind_scale]) else 'N/A'
            comfort_emoji, comfort_color = get_comfort_emoji_color(comfort_desc)
            forecast_data = {'temp': temp, 'feels_like': feels_like, 'comfort_index': comfort_index, 'comfort_desc': comfort_desc, 'comfort_emoji': comfort_emoji, 'comfort_color': comfort_color, 'humidity': humidity, 'wind_display': wind_display, 'weather_desc': weather_desc, 'pop': pop, 'forecast_time': forecast_time, 'has_data': True, 'last_fetch': get_taipei_time()}
            print("✓ 預報更新成功")
            return
        forecast_data['has_data'] = False
    except Exception as e:
        print(f"× 預報失敗: {e}")
        forecast_data['has_data'] = False

def fetch_air_quality_data():
    global latest_data
    try:
        response = requests.get(AQI_API_URL, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        if data.get('records') and len(data['records']) >= 2:
            records = sorted(data['records'], key=lambda x: x.get('monitordate', ''), reverse=True)
            current, previous = records[0], records[1] if len(records) > 1 else None
            def calc_change(curr, prev):
                if any(x in ['N/A', '', None] for x in [curr, prev]): return None
                try:
                    diff = float(curr) - float(prev)
                    return f"↑ +{diff:.1f}" if diff > 0 else (f"↓ {diff:.1f}" if diff < 0 else "─ 0")
                except: return None
            aqi, pm25, pm25_avg, pm10, pm10_avg, o3 = [current.get(k, 'N/A') for k in ['aqi', 'pm2.5', 'pm2.5_avg', 'pm10', 'pm10_avg', 'o3']]
            changes = {f'{k}_change': calc_change(current.get(k2, 'N/A'), previous.get(k2, 'N/A') if previous else None) for k, k2 in [('aqi', 'aqi'), ('pm25_avg', 'pm2.5_avg'), ('pm10_avg', 'pm10_avg'), ('pm10', 'pm10'), ('pm25', 'pm2.5'), ('o3', 'o3')]}
            def get_level(val, thresholds, labels):
                if val in ['N/A', '']: return 'gray', '無資料'
                try:
                    v = float(val)
                    for i, t in enumerate(thresholds):
                        if v <= t: return ['green', 'yellow', 'orange'][i], labels[i]
                    return 'red', labels[3]
                except: return 'gray', '無資料'
            levels = {f'{k}_color': get_level(v, t, l)[0], f'{k}_label': get_level(v, t, l)[1] for k, v, t, l in [('aqi', aqi, [50, 100, 150], ['良好', '普通', '對敏感族群不健康', '不健康']), ('pm25_avg', pm25_avg, [15.4, 35.4, 54.4], ['良好', '普通', '對敏感族群不健康', '不健康']), ('pm10_avg', pm10_avg, [54, 125, 254], ['良好', '普通', '對敏感族群不健康', '不健康']), ('pm10', pm10, [54, 125, 254], ['良好', '普通', '對敏感族群不健康', '不健康']), ('pm25', pm25, [15.4, 35.4, 54.4], ['良好', '普通', '對敏感族群不健康', '不健康']), ('o3', o3, [54, 70, 85], ['良好', '普通', '對敏感族群不健康', '不健康'])]}
            latest_data = {'aqi': aqi, 'pm25_avg': pm25_avg, 'pm10_avg': pm10_avg, 'pm10': pm10, 'pm25': pm25, 'o3': o3, **levels, **changes, 'update_time': get_taipei_time().strftime('%Y-%m-%d %H:%M:%S'), 'site_name': '頭份', 'publish_time': current.get('monitordate', 'N/A'), 'has_data': True, 'last_fetch': get_taipei_time()}
            print("✓ AQI更新成功")
        else:
            latest_data['has_data'] = False
    except Exception as e:
        print(f"× AQI失敗: {e}")
        latest_data['has_data'] = False

def should_fetch_data():
    t = get_taipei_time()
    if not latest_data['last_fetch'] or not forecast_data['last_fetch']: return True
    return (t - latest_data['last_fetch'] > timedelta(minutes=5)) or (t - forecast_data['last_fetch'] > timedelta(minutes=5))

HTML_TEMPLATE = '''<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>頭份環境監測</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Microsoft JhengHei',sans-serif;{% if bg_image %}background:url('/background') center/cover no-repeat fixed{% else %}background:linear-gradient(135deg,#667eea 0%,#764ba2 100%){% endif %};min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}.main-container{max-width:1400px;width:100%;display:grid;grid-template-columns:350px 1fr;gap:20px}.container{background:rgba(255,255,255,.95);border-radius:20px;padding:40px;box-shadow:0 20px 60px rgba(0,0,0,.3)}h1{text-align:center;color:#333;margin-bottom:10px;font-size:2.5em}h2{text-align:center;color:#333;margin-bottom:20px;font-size:1.8em}.site-info{text-align:center;color:#666;margin-bottom:30px;font-size:1.1em}.weather-container{background:rgba(255,255,255,.95);border-radius:20px;padding:30px;box-shadow:0 20px 60px rgba(0,0,0,.3)}.weather-grid{display:grid;gap:15px}.weather-item{background:linear-gradient(135deg,#4facfe 0%,#00f2fe 100%);color:white;padding:15px;border-radius:10px;display:flex;justify-content:space-between;align-items:center}.weather-item.temp{background:linear-gradient(135deg,#f093fb 0%,#f5576c 100%)}.weather-item.feels{background:linear-gradient(135deg,#fa709a 0%,#fee140 100%)}.weather-item.comfort.green{background:linear-gradient(135deg,#00d084 0%,#00a86b 100%)}.weather-item.comfort.yellow{background:linear-gradient(135deg,#ffd700 0%,#ffb900 100%)}.weather-item.comfort.orange{background:linear-gradient(135deg,#ff8c00 0%,#ff6b00 100%)}.weather-item.comfort.red{background:linear-gradient(135deg,#ff4757 0%,#e84118 100%)}.weather-item.comfort.blue{background:linear-gradient(135deg,#4facfe 0%,#00f2fe 100%)}.weather-item.comfort.gray{background:linear-gradient(135deg,#95a5a6 0%,#7f8c8d 100%)}.weather-item.humidity{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%)}.weather-item.wind{background:linear-gradient(135deg,#a8edea 0%,#fed6e3 100%);color:#333}.weather-item.pop{background:linear-gradient(135deg,#00c6ff 0%,#0072ff 100%)}.weather-label{font-size:.9em;opacity:.9}.weather-value{font-size:1.5em;font-weight:bold}.weather-value-large{font-size:2em;font-weight:bold}.comfort-emoji{font-size:2.5em}.weather-desc-box{background:linear-gradient(135deg,#a8edea 0%,#fed6e3 100%);color:#333;padding:15px;border-radius:10px;text-align:center;font-size:1.2em;font-weight:bold;margin-bottom:15px}.forecast-time{text-align:center;color:#666;font-size:.9em;margin-top:15px;padding:10px;background:#f8f9fa;border-radius:5px}.data-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px}.data-card{color:white;padding:25px;border-radius:15px;text-align:center;box-shadow:0 5px 15px rgba(0,0,0,.2);transition:transform .3s ease}.data-card.green{background:linear-gradient(135deg,#00d084 0%,#00a86b 100%)}.data-card.yellow{background:linear-gradient(135deg,#ffd700 0%,#ffb900 100%)}.data-card.orange{background:linear-gradient(135deg,#ff8c00 0%,#ff6b00 100%)}.data-card.red{background:linear-gradient(135deg,#ff4757 0%,#e84118 100%)}.data-card.gray{background:linear-gradient(135deg,#95a5a6 0%,#7f8c8d 100%)}.data-card:hover{transform:translateY(-5px)}.data-label{font-size:.9em;opacity:.9;margin-bottom:10px}.data-value{font-size:2.5em;font-weight:bold;margin-bottom:5px;display:flex;align-items:center;justify-content:center;gap:10px}.data-change{font-size:.35em;font-weight:normal;padding:3px 8px;border-radius:5px;white-space:nowrap}.data-change.up{color:#c0392b;background:rgba(192,57,43,.2)}.data-change.down{color:#27ae60;background:rgba(39,174,96,.2)}.data-change.same{color:#95a5a6;background:rgba(149,165,166,.2)}.data-unit{font-size:.8em;opacity:.8}.data-status{font-size:.85em;margin-top:8px;padding:5px 10px;background:rgba(255,255,255,.2);border-radius:15px;font-weight:500}.update-info{text-align:center;color:#666;padding:20px;background:#f8f9fa;border-radius:10px;margin-top:20px}.update-time{font-weight:bold;color:#667eea}.refresh-note{margin-top:10px;font-size:.9em;color:#888}.error-message{background:#fff3cd;color:#856404;padding:20px;border-radius:10px;text-align:center;margin:20px 0;border:2px solid #ffc107}@media(max-width:1024px){.main-container{grid-template-columns:1fr}}</style><script>function updateData(){fetch('/api/data').then(r=>r.json()).then(d=>{if(d.success){if(d.aqi_data.has_data){['aqi','pm25-avg','pm10-avg','pm25','pm10','o3'].forEach(k=>{let key=k.replace('-','_');updateElement(`[data-${k}]`,d.aqi_data[key]);updateChange(`[data-${k}-change]`,d.aqi_data[key+'_change'])});updateElement('[data-publish-time]',d.aqi_data.publish_time)}if(d.forecast_data.has_data){['temp','feels','comfort','comfort-desc','comfort-emoji','humidity','wind','weather','pop','time'].forEach(k=>{let key=k==='feels'?'feels_like':(k==='wind'?'wind_display':(k==='weather'?'weather_desc':(k==='time'?'forecast_time':k.replace('-','_'))));updateElement(`[data-forecast-${k}]`,d.forecast_data[key])})}updateElement('[data-page-time]',d.page_load_time)}}).catch(e=>console.error('更新失敗:',e))}function updateElement(s,v){const e=document.querySelector(s);if(e&&v!=null)e.textContent=v}function updateChange(s,v){const e=document.querySelector(s);if(e){if(v){e.textContent=v;e.style.display='';e.className='data-change';if(v.includes('↑'))e.className+=' up';else if(v.includes('↓'))e.className+=' down';else e.className+=' same'}else e.style.display='none'}}setInterval(updateData,300000);setTimeout(updateData,10000)</script></head><body><div class="main-container"><div class="weather-container"><h2>🌤️ 天氣預報</h2><div class="site-info">頭份市</div>{% if forecast.has_data %}<div class="weather-desc-box"><span data-forecast-weather>{{forecast.weather_desc}}</span></div><div class="weather-grid"><div class="weather-item temp"><span class="weather-label">🌡️ 溫度</span><span class="weather-value-large"><span data-forecast-temp>{{forecast.temp}}</span>°C</span></div><div class="weather-item feels"><span class="weather-label">🌡️ 體感溫度</span><span class="weather-value"><span data-forecast-feels>{{forecast.feels_like}}</span>°C</span></div><div class="weather-item comfort {{forecast.comfort_color}}"><div><div class="weather-label">😊 舒適度</div><div style="font-size:.8em;margin-top:5px"><span data-forecast-comfort-desc>{{forecast.comfort_desc}}</span> (指數 <span data-forecast-comfort>{{forecast.comfort_index}}</span>)</div></div><span class="comfort-emoji" data-forecast-comfort-emoji>{{forecast.comfort_emoji}}</span></div><div class="weather-item humidity"><span class="weather-label">💧 相對濕度</span><span class="weather-value"><span data-forecast-humidity>{{forecast.humidity}}</span>%</span></div><div class="weather-item pop"><span class="weather-label">☔ 降雨機率</span><span class="weather-value"><span data-forecast-pop>{{forecast.pop}}</span>%</span></div><div class="weather-item wind"><div style="width:100%"><div class="weather-label" style="margin-bottom:8px">🌬️ 風速與風向</div><div style="font-size:1em;font-weight:bold" data-forecast-wind>{{forecast.wind_display}}</div></div></div></div><div class="forecast-time">📅 預報時間：<span data-forecast-time>{{forecast.forecast_time}}</span></div>{%else%}<div class="error-message"><h3>⚠️ 預報資料載入中</h3></div>{%endif%}</div><div class="container"><h1>🌫️ 空氣品質監測</h1><div class="site-info">監測站點：{{data.site_name}}</div>{%if data.has_data%}<div class="data-grid">{%for item in[{'key':'aqi','label':'空氣品質指標 (AQI)','unit':'指數'},{'key':'pm25_avg','label':'PM2.5 平均','unit':'μg/m³'},{'key':'pm10_avg','label':'PM10 平均','unit':'μg/m³'},{'key':'pm25','label':'PM2.5','unit':'μg/m³'},{'key':'pm10','label':'PM10','unit':'μg/m³'},{'key':'o3','label':'臭氧 (O₃)','unit':'ppb'}]%}<div class="data-card {{data[item.key+'_color']}}"><div class="data-label">{{item.label}}</div><div class="data-value"><span data-{{item.key.replace('_','-')}}>{{data[item.key]}}</span>{%set change_key=item.key+'_change'%}{%if data[change_key]%}<span data-{{item.key.replace('_','-')}}-change class="data-change {{'up' if '↑' in data[change_key] else('down' if '↓' in data[change_key] else 'same')}}">{{data[change_key]}}</span>{%else%}<span data-{{item.key.replace('_','-')}}-change class="data-change" style="display:none"></span>{%endif%}</div><div class="data-unit">{{item.unit}}</div><div class="data-status">{{data[item.key+'_label']}}</div></div>{%endfor%}</div><div class="update-info"><div>🖥️ 頁面載入時間：<span class="update-time" data-page-time>{{page_load_time}}</span></div><div style="margin-top:5px">📡 資料抓取時間：{{data.update_time}}</div>{%if data.publish_time!='N/A'%}<div style="margin-top:5px">📊 環境部發布時間：<span data-publish-time>{{data.publish_time}}</span></div>{%endif%}<div class="refresh-note">⏱️ 資料每5分鐘自動更新</div></div>{%else%}<div class="error-message"><h2>⚠️ 尚未取得資料</h2><p style="margin-top:10px">請稍後重新整理頁面。</p></div>{%endif%}</div></div></body></html>'''

@app.route('/')
def index():
    if should_fetch_data():
        with fetch_lock:
            if should_fetch_data():
                fetch_air_quality_data()
                fetch_weather_forecast()
    return render_template_string(HTML_TEMPLATE, data=latest_data, forecast=forecast_data, page_load_time=get_taipei_time().strftime('%Y-%m-%d %H:%M:%S'), bg_image=BACKGROUND_IMAGE if os.path.exists(BACKGROUND_IMAGE) else None)

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
        return send_from_directory(os.path.dirname(os.path.abspath(BACKGROUND_IMAGE)) or '.', os.path.basename(BACKGROUND_IMAGE))
    return "", 404

fetch_air_quality_data()
fetch_weather_forecast()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
