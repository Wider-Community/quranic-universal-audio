# run_validate.ps1
# سكريبت لتشغيل validate_timestamps.py لكل reciters في مجلد Data
# يعرض أهم 50 خطأ/تحذير

# مسار البايثون
$pythonPath = "C:/Program Files/Python313/python.exe"

# مسار السكريبت validate_timestamps.py
$scriptPath = "C:/Users/User/Downloads/quranic-universal-audio/validators/validate_timestamps.py"

# مسار مجلد Data اللي فيه كل reciters
$dataDir = "C:/Users/User/Downloads/quranic-universal-audio/Data"

# عدد أعلى التحذيرات/الأخطاء اللي تظهر
$topN = 50

# تشغيل السكريبت
& $pythonPath $scriptPath $dataDir --top $topN