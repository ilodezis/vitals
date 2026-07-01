# Local scratch seeder — UTF-8 safe (run with the venv python).
import time, urllib.parse, urllib.request, http.cookiejar, json

BASE = "http://127.0.0.1:8000"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def post(path, data):
    body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return opener.open(req).getcode()
    except urllib.error.HTTPError as e:
        return e.code

def post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body,
        headers={"Content-Type": "application/json"})
    try:
        return opener.open(req).getcode()
    except urllib.error.HTTPError as e:
        return e.code

# wait for server
for _ in range(30):
    try:
        opener.open(BASE + "/login"); break
    except Exception:
        time.sleep(0.5)

print("login", post("/login", {"username": "timur", "password": "password", "next": "/weight"}))

# Enable body_comp module
print("enable_body_comp", post("/settings/modules", {"module": "body_comp", "enabled": "true"}))

S = [
    {"name": "Креатин моногидрат", "dose": "5 г", "timing": "Утро", "evidence": "A", "active": "true", "note": "ежедневно, можно с едой"},
    {"name": "Витамин D3", "dose": "5000 МЕ", "timing": "Утро", "evidence": "B", "active": "true", "contraindications": "осторожно при высоком кальции крови"},
    {"name": "Омега-3", "dose": "2 г", "timing": "День", "evidence": "A", "active": "true", "note": "с жирной пищей"},
    {"name": "Магний глицинат", "dose": "400 мг", "timing": "Ночь", "evidence": "B", "active": "true", "note": "за час до сна, помогает сну"},
    {"name": "Цинк пиколинат", "dose": "25 мг", "timing": "Вечер", "evidence": "B", "active": "true"},
    {"name": "Старый предтрен", "dose": "1 порция", "timing": "День", "active": "false", "note": "архив, больше не принимаю"},
]
for s in S:
    print("supp", post("/supplements/save", s))

P = [
    {"name": "Дифферин", "type": "Ретиноид", "active_ingredient": "Адапален 0.1%", "default_time": "evening",
     "active": "true", "schedule_days": ["1", "3", "5"], "description": "нормализует кератинизацию, против акне",
     "usage_instructions": "горошина на сухую кожу, через 20 мин крем"},
    {"name": "Азелик", "type": "Азелаиновая кислота", "active_ingredient": "Азелаин 15%", "default_time": "evening",
     "active": "true", "schedule_days": ["2", "4", "6"], "description": "против воспалений и пигментации"},
    {"name": "Сыворотка + SPF", "type": "Защита", "active_ingredient": "SPF 50", "default_time": "morning",
     "active": "true", "schedule_days": ["0", "1", "2", "3", "4", "5", "6"], "usage_instructions": "обязательно каждое утро"},
    {"name": "Увлажняющий крем", "type": "Увлажнение", "active_ingredient": "Церамиды", "default_time": "both",
     "active": "true", "schedule_days": ["0", "1", "2", "3", "4", "5", "6"]},
]
for p in P:
    print("prod", post("/skincare/product/save", p))

# weight + measurements: older has full neck+waist (=> body-fat), newest has neck only (=> no body-fat)
print("w1", post("/weight/log", {"date": "2026-06-18", "weight_kg": "111.3"}))
print("m1", post("/weight/measurement", {"date": "2026-06-18", "neck_cm": "42", "waist_cm": "106", "hips_cm": "110"}))
print("w2", post("/weight/log", {"date": "2026-06-20", "weight_kg": "110.8"}))
print("w3", post("/weight/log", {"date": "2026-06-23", "weight_kg": "110.6"}))
print("m2", post("/weight/measurement", {"date": "2026-06-23", "neck_cm": "42"}))  # no waist -> no BF

# a GLP-1 phase + injection for that page
print("phase", post("/glp1/phase", {"start_date": "2026-05-15", "drug": "semaglutide", "dose_mg": "0.5"}))
print("inj", post("/glp1/injection", {"date": "2026-06-22", "dose_mg": "0.5", "drug": "semaglutide", "site": "abdomen_left", "note": "без побочек"}))

# Seed body-scans (InBody / МедАсс)
scan1 = {
    "date": "2026-06-18",
    "device": "InBody 770",
    "override": True,
    "metrics": [
        {"label": "Вес", "value": 111.3, "unit": "кг"},
        {"label": "Процент жира", "value": 22.4, "unit": "%"},
        {"label": "Скелетно-мышечная масса", "value": 48.5, "unit": "кг"},
        {"label": "Безжировая масса", "value": 86.4, "unit": "кг"},
        {"label": "Общая жидкость организма", "value": 64.2, "unit": "л"},
        {"label": "Фазовый угол", "value": 6.8, "unit": "°"},
        {"label": "Балл InBody", "value": 78},
        {"label": "Площадь висцерального жира", "value": 124.0, "unit": "см²"}
    ]
}
print("scan1", post_json("/weight/body-scan/confirm", scan1))

scan2 = {
    "date": "2026-06-25",
    "device": "InBody 770",
    "override": True,
    "metrics": [
        {"label": "Вес", "value": 110.2, "unit": "кг"},
        {"label": "Процент жира", "value": 21.8, "unit": "%"},
        {"label": "Скелетно-мышечная масса", "value": 48.8, "unit": "кг"},
        {"label": "Безжировая масса", "value": 86.2, "unit": "кг"},
        {"label": "Общая жидкость организма", "value": 64.5, "unit": "л"},
        {"label": "Фазовый угол", "value": 7.0, "unit": "°"},
        {"label": "Балл InBody", "value": 80},
        {"label": "Площадь висцерального жира", "value": 120.0, "unit": "см²"}
    ]
}
print("scan2", post_json("/weight/body-scan/confirm", scan2))

print("DONE")
