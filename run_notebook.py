import papermill as pm
from datetime import datetime

try:
    print(f"▶️ Ejecutando notebook a las {datetime.now()}")
    pm.execute_notebook(
        'calendars_script.ipynb',
        'output_calendars.ipynb'
    )
    print(f"✅ Notebook ejecutado exitosamente a las {datetime.now()}")
except Exception as e:
    print(f"❌ Error ejecutando notebook: {e}")
