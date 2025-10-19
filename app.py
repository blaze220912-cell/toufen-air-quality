from flask import Flask, render_template_string, send_from_directory
import requests
from datetime import datetime
from threading import Thread
import time
import urllib3
import os
import pytz

# 關閉 SSL 警告訊息
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# 設定台北時區
TZ = pytz.timezone('Asia/Taipei')

# 設定背景圖片檔名（你可以修改這裡）
BACKGROUND_IMAGE = "background.jpg"  # 改成你的圖片檔名

# 全域變數儲存最新數據
latest_data = {
    'aqi': 'N/A',
    'pm25_avg': 'N/A',
    'pm10_avg': 'N/A',
    'pm10': 'N/A',
    'pm25': 'N/A',
    'o3': 'N/A',
    'update_time': '尚未更新',
    'site_name': '頭份',
    'publish_time': 'N/A',
    'has_data': False
}

# 用於確保背景執行緒只啟動一次
_background_thread = None
_background_lock = Thread.__module__  # 簡單的初始化標記

def ensure_background_thread():
    """確保背景執行緒已啟動"""
    global _background_thread
    if _background_thread is None:
        print("=== 初始化：立即抓取資料 ===")
        fetch_air_quality_data()
        print("=== 啟動背景定期更新執行緒 ===")
        _background_thread = Thread(target=update_data_periodically, daemon=True)
        _background_thread.start()
        print("=== 背景執行緒已啟動 ===")

API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_488?format=json&api_key=e0438a06-74df-4300-8ce5-edfcb08c82b8&filters=SiteName,EQ,頭份"

def fetch_air_quality_data():
    """抓取空汙數據"""
    global latest_data
    try:
        print(f"正在呼叫 API: {API_URL[:80]}...")
        response = requests.get(API_URL, timeout=10, verify=False)
        print(f"API 回應狀態碼: {response.status_code}")
        print(f"API 回應內容長度: {len(response.text)} 字元")
        
        response.raise_for_status()
        data = response.json()
        
        if data.get('records') and len(data['records']) > 0:
            # 按資料建立時間排序，取得最新的一筆
            records = data['records']
            print(f"API 返回 {len(records)} 筆資料")
            
            # 顯示前5筆資料的時間
            print("最近的資料建立時間:")
            for i, r in enumerate(records[:5]):
                print(f"  [{i}] {r.get('datacreationdate', 'N/A')}")
            
            # 篩選出有資料建立時間的資料並排序
            valid_records = [r for r in records if r.get('datacreationdate')]
            if valid_records:
                # 按資料建立時間降序排序
                valid_records.sort(key=lambda x: x.get('datacreationdate', ''), reverse=True)
                record = valid_records[0]
                print(f"✓ 選擇最新資料，建立時間: {record.get('datacreationdate', 'N/A')}")
            else:
                record = records[0]
                print(f"使用第一筆資料，資料建立時間: {record.get('datacreationdate', 'N/A')}")
            
            # 取得數值
            aqi = record.get('aqi', 'N/A')
            pm25 = record.get('pm2.5', 'N/A')
            pm25_avg = record.get('pm2.5_avg', 'N/A')
            pm10 = record.get('pm10', 'N/A')
            pm10_avg = record.get('pm10_avg', 'N/A')
            o3 = record.get('o3', 'N/A')
            
            # 計算顏色等級和文字標籤
            def get_level_info(value, thresholds, labels):
                """根據閾值返回顏色等級和文字標籤"""
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
            
            latest_data = {
                'aqi': aqi,
                'aqi_color': aqi_color,
                'aqi_label': aqi_label,
                'pm25_avg': pm25_avg,
                'pm25_avg_color': pm25_avg_color,
                'pm25_avg_label': pm25_avg_label,
                'pm10_avg': pm10_avg,
                'pm10_avg_color': pm10_avg_color,
                'pm10_avg_label': pm10_avg_label,
                'pm10': pm10,
                'pm10_color': pm10_color,
                'pm10_label': pm10_label,
                'pm25': pm25,
                'pm25_color': pm25_color,
                'pm25_label': pm25_label,
                'o3': o3,
                'o3_color': o3_color,
                'o3_label': o3_label,
                'update_time': datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S'),
                'site_name': record.get('sitename', '頭份'),
                'publish_time': record.get('datacreationdate', 'N/A'),
                'has_data': True
            }
            print(f"數據更新成功: {latest_data['update_time']}")
            print(f"PM2.5: {latest_data['pm25']}, PM10: {latest_data['pm10']}, O3: {latest_data['o3']}")
        else:
            print("API 回應中沒有找到數據記錄")
            latest_data['has_data'] = False
    except Exception as e:
        print(f"抓取數據失敗: {e}")
        latest_data['has_data'] = False

def update_data_periodically():
    """每5分鐘更新一次數據"""
    while True:
        fetch_air_quality_data()
        time.sleep(300)  # 300秒 = 5分鐘

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>頭份空氣品質監測</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
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
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 800px;
            width: 100%;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 10px;
            font-size: 2.5em;
        }
        .site-info {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
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
        .data-card.green {
            background: linear-gradient(135deg, #00d084 0%, #00a86b 100%);
        }
        .data-card.yellow {
            background: linear-gradient(135deg, #ffd700 0%, #ffb900 100%);
        }
        .data-card.orange {
            background: linear-gradient(135deg, #ff8c00 0%, #ff6b00 100%);
        }
        .data-card.red {
            background: linear-gradient(135deg, #ff4757 0%, #e84118 100%);
        }
        .data-card.gray {
            background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%);
        }
        .data-card:hover {
            transform: translateY(-5px);
        }
        .data-label {
            font-size: 0.9em;
            opacity: 0.9;
            margin-bottom: 10px;
        }
        .data-value {
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        .data-unit {
            font-size: 0.8em;
            opacity: 0.8;
        }
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
        .update-time {
            font-weight: bold;
            color: #667eea;
        }
        .refresh-note {
            margin-top: 10px;
            font-size: 0.9em;
            color: #888;
        }
        .error-message {
            background: #fff3cd;
            color: #856404;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            margin: 20px 0;
            border: 2px solid #ffc107;
        }
    </style>
    <script>
        // 每4分鐘(240秒)重新載入頁面以顯示最新數據
        setTimeout(function() {
            location.reload();
        }, 240000);
    </script>
</head>
<body>
    <div class="container">
        <h1>🌤️ 空氣品質監測</h1>
        <div class="site-info">監測站點：{{ data.site_name }}</div>
        
        {% if data.has_data %}
        <div class="data-grid">
            <div class="data-card {{ data.aqi_color }}">
                <div class="data-label">空氣品質指標 (AQI)</div>
                <div class="data-value">{{ data.aqi }}</div>
                <div class="data-unit">指數</div>
                <div class="data-status">{{ data.aqi_label }}</div>
            </div>
            
            <div class="data-card {{ data.pm25_avg_color }}">
                <div class="data-label">PM2.5 平均</div>
                <div class="data-value">{{ data.pm25_avg }}</div>
                <div class="data-unit">μg/m³</div>
                <div class="data-status">{{ data.pm25_avg_label }}</div>
            </div>
            
            <div class="data-card {{ data.pm10_avg_color }}">
                <div class="data-label">PM10 平均</div>
                <div class="data-value">{{ data.pm10_avg }}</div>
                <div class="data-unit">μg/m³</div>
                <div class="data-status">{{ data.pm10_avg_label }}</div>
            </div>
            
            <div class="data-card {{ data.pm25_color }}">
                <div class="data-label">PM2.5</div>
                <div class="data-value">{{ data.pm25 }}</div>
                <div class="data-unit">μg/m³</div>
                <div class="data-status">{{ data.pm25_label }}</div>
            </div>
            
            <div class="data-card {{ data.pm10_color }}">
                <div class="data-label">PM10</div>
                <div class="data-value">{{ data.pm10 }}</div>
                <div class="data-unit">μg/m³</div>
                <div class="data-status">{{ data.pm10_label }}</div>
            </div>
            
            <div class="data-card {{ data.o3_color }}">
                <div class="data-label">臭氧 (O₃)</div>
                <div class="data-value">{{ data.o3 }}</div>
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
            <div class="refresh-note">⏱️ 資料每5分鐘更新 | 頁面每4分鐘自動刷新</div>
        </div>
        {% else %}
        <div class="error-message">
            <h2>⚠️ 尚未取得資料</h2>
            <p style="margin-top: 10px;">請稍後重新整理頁面，或檢查網路連線。</p>
            <p style="margin-top: 5px; font-size: 0.9em;">最後嘗試時間：{{ data.update_time }}</p>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    """首頁路由"""
    # 確保背景執行緒已啟動
    ensure_background_thread()
    
    print(f"網頁請求 - has_data: {latest_data['has_data']}")
    print(f"當前數據: PM2.5={latest_data['pm25']}, PM10={latest_data['pm10']}")
    
    # 檢查背景圖片是否存在
    bg_exists = os.path.exists(BACKGROUND_IMAGE)
    
    # 加上當前頁面載入時間（使用台北時區）
    page_load_time = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template_string(
        HTML_TEMPLATE, 
        data=latest_data, 
        page_load_time=page_load_time,
        bg_image=BACKGROUND_IMAGE if bg_exists else None
    )

@app.route('/background')
def background():
    """提供背景圖片"""
    if os.path.exists(BACKGROUND_IMAGE):
        directory = os.path.dirname(os.path.abspath(BACKGROUND_IMAGE)) or '.'
        filename = os.path.basename(BACKGROUND_IMAGE)
        return send_from_directory(directory, filename)
    return "", 404

if __name__ == '__main__':
    # 本地開發時啟動
    ensure_background_thread()
    
    # 啟動 Flask 應用程式
    print("Flask 應用程式啟動中...")
    print("請在瀏覽器中開啟: http://127.0.0.1:5000")
    
    # 取得 PORT 環境變數（Render 會自動設定）
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)

# Gunicorn 啟動時自動執行
ensure_background_thread()
