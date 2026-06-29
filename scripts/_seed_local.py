# Local scratch seeder — UTF-8 safe (run with the venv python).
import time, urllib.parse, urllib.request, http.cookiejar

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

# wait for server
for _ in range(30):
    try:
        opener.open(BASE + "/login"); break
    except Exception:
        time.sleep(0.5)

post("/login", {"username": "timur", "password": "password", "next": "/weight"})

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
print("DONE")
