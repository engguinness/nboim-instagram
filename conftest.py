# pytest 가 저장소 루트의 publish.py·sync_content.py 를 import 할 수 있게 한다.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
