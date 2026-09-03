"""pytest 全局配置：保证从任意目录跑 `pytest agent-service/tests` 都能 import src/app。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
